from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


from app.attachments.citations import (
    CitationValidationError,
    citation_label,
    coverage_statement,
    validate_attachment_answer_citations,
    validate_cited_evidence_ids,
)
from app.attachments.retrieval import (
    AttachmentChunk,
    AttachmentEvidence,
    EvidenceMode,
    build_full_inspection_task,
    load_attachment_evidence,
    load_recent_attachment_ids,
    plan_attachment_evidence,
    process_full_inspection_batch,
    persist_full_inspection_task,
    terminal_full_inspection_summary,
    should_retrieve_attachment_evidence,
)
from app.chat_router import ChatContextRoute
from app.context_parallel import retrieve_chat_context_parallel
from app.attachments.worker_entrypoint import run_worker_cycle
from app.attachments.worker import (
    AttachmentFullInspectionWorker,
    ClaimedFullInspectionBatch,
    DatabaseAttachmentLocatorInspector,
    PostgresFullInspectionRepository,
)


PDF_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PPTX_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
SMALL_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def chunk(
    attachment_id: uuid.UUID,
    ordinal: int,
    text: str,
    *,
    tokens: int = 100,
    locator: dict[str, object] | None = None,
    content_hash: str | None = None,
    vector_score: float = 0.0,
    low_text_density: bool = False,
    contains_visual: bool = False,
    text_insufficient: bool = False,
) -> AttachmentChunk:
    return AttachmentChunk(
        attachment_id=attachment_id,
        ordinal=ordinal,
        text=text,
        token_count=tokens,
        locator=locator or {"page": ordinal + 1},
        content_hash=content_hash or f"hash-{attachment_id}-{ordinal}",
        vector_score=vector_score,
        low_text_density=low_text_density,
        contains_visual=contains_visual,
        text_insufficient=text_insufficient,
    )


def attachment(
    attachment_id: uuid.UUID,
    filename: str,
    kind: str,
    chunks: list[AttachmentChunk],
    *,
    page_count: int | None = None,
    slide_count: int | None = None,
) -> AttachmentEvidence:
    return AttachmentEvidence(
        attachment_id=attachment_id,
        filename=filename,
        kind=kind,
        chunks=tuple(chunks),
        page_count=page_count,
        slide_count=slide_count,
    )


def test_small_attachment_uses_full_text_at_or_below_24k_tokens():
    source = attachment(
        PDF_ID,
        "方案.pdf",
        "pdf",
        [
            chunk(PDF_ID, 0, "项目目标", tokens=8_000, locator={"page": 1}),
            chunk(PDF_ID, 1, "验收标准", tokens=8_000, locator={"page": 2}),
            chunk(PDF_ID, 2, "风险清单", tokens=8_000, locator={"page": 3}),
        ],
        page_count=3,
    )

    plan = plan_attachment_evidence("请总结", [source])

    assert plan.mode == EvidenceMode.FULL_TEXT
    assert [item.locator for item in plan.text_items] == [
        {"page": 1},
        {"page": 2},
        {"page": 3},
    ]
    assert plan.total_tokens == 24_000
    assert plan.coverage.complete is True
    assert plan.exclusions == ()


def test_large_attachment_cannot_starve_smaller_attachment():
    large = attachment(
        PDF_ID,
        "年度预算.pdf",
        "pdf",
        [
            chunk(
                PDF_ID,
                index,
                f"预算章节 {index}，现金流风险" if index in {8, 19} else f"普通预算章节 {index}",
                tokens=4_000,
                locator={"page": index + 1},
                vector_score=0.95 if index in {8, 19} else 0.05,
            )
            for index in range(25)
        ],
        page_count=25,
    )
    small = attachment(
        SMALL_ID,
        "补充说明.txt",
        "text",
        [chunk(SMALL_ID, 0, "现金流风险上限是 20 万元", tokens=600, locator={"line_start": 1, "line_end": 2})],
    )

    plan = plan_attachment_evidence(
        "比较两份预算的现金流风险",
        [large, small],
        total_attachment_budget=16_000,
    )

    assert plan.mode == EvidenceMode.HYBRID
    assert {item.attachment_id for item in plan.text_items} == {PDF_ID, SMALL_ID}
    assert plan.tokens_by_attachment[str(SMALL_ID)] == 600
    assert {item.locator.get("page") for item in plan.text_items if item.attachment_id == PDF_ID} >= {9, 20}
    assert plan.total_tokens <= 16_000


def test_hybrid_selection_deduplicates_content_and_diversifies_locators():
    source = attachment(
        PDF_ID,
        "报告.pdf",
        "pdf",
        [
            chunk(PDF_ID, 0, "收入增长 20%", locator={"page": 1}, content_hash="same", vector_score=0.9),
            chunk(PDF_ID, 1, "收入增长 20%", locator={"page": 2}, content_hash="same", vector_score=0.89),
            chunk(PDF_ID, 2, "成本风险", locator={"page": 2}, vector_score=0.88),
            chunk(PDF_ID, 3, "利润率风险", locator={"page": 3}, vector_score=0.87),
        ],
        page_count=40,
    )

    plan = plan_attachment_evidence("收入、成本和利润率风险", [source], total_attachment_budget=300)

    selected_hashes = [item.content_hash for item in plan.text_items]
    selected_pages = [item.locator["page"] for item in plan.text_items]
    assert selected_hashes.count("same") == 1
    assert len(set(selected_pages)) == len(selected_pages)
    assert any(item.reason == "duplicate_content" for item in plan.exclusions)


def test_visual_escalation_is_relevant_bounded_and_not_a_large_document_sweep():
    visual_chunks = [
        chunk(
            PDF_ID,
            index,
            f"流程图节点 {index}",
            tokens=80,
            locator={"page": index + 1},
            vector_score=1.0 - (index * 0.01),
            low_text_density=index % 2 == 0,
            contains_visual=index % 2 == 1,
            text_insufficient=True,
        )
        for index in range(10)
    ]
    source = attachment(PDF_ID, "流程.pdf", "pdf", visual_chunks, page_count=35)

    plan = plan_attachment_evidence("比较流程图的布局、颜色和节点关系", [source])

    assert plan.mode == EvidenceMode.HYBRID
    assert len(plan.visual_items) == 6
    assert [item.locator["page"] for item in plan.visual_items] == [1, 2, 3, 4, 5, 6]
    assert all(item.reason in {"low_text_density", "contains_visual", "visual_question", "text_insufficient"} for item in plan.visual_items)
    assert any(item.reason == "visual_limit" for item in plan.exclusions)


def test_large_presentation_uses_relevant_slides_without_default_visual_sweep():
    source = attachment(
        PPTX_ID,
        "路演.pptx",
        "pptx",
        [
            chunk(
                PPTX_ID,
                index,
                "核心商业模式" if index == 11 else f"第 {index + 1} 张普通内容",
                tokens=500,
                locator={"slide": index + 1},
                vector_score=0.99 if index == 11 else 0.01,
            )
            for index in range(31)
        ],
        slide_count=31,
    )

    plan = plan_attachment_evidence("商业模式是什么", [source], total_attachment_budget=2_000)

    assert plan.mode == EvidenceMode.HYBRID
    assert any(item.locator == {"slide": 12} for item in plan.text_items)
    assert plan.visual_items == ()
    assert plan.requires_async_full_inspection is False


def test_64k_attachment_budget_is_reduced_by_remaining_256k_context_budget():
    source = attachment(
        PDF_ID,
        "长报告.pdf",
        "pdf",
        [chunk(PDF_ID, index, f"风险 {index}", tokens=4_000, vector_score=1.0 - index / 100) for index in range(30)],
        page_count=30,
    )

    plan = plan_attachment_evidence(
        "风险",
        [source],
        total_attachment_budget=64_000,
        total_context_budget=256_000,
        already_reserved_context_tokens=220_000,
        reserved_output_tokens=20_000,
    )

    assert plan.effective_attachment_budget == 16_000
    assert plan.total_tokens <= 16_000
    assert any(item.reason == "budget_exceeded" for item in plan.exclusions)


def test_explicit_every_page_request_creates_bounded_durable_task_contract():
    source = attachment(
        PDF_ID,
        "审计.pdf",
        "pdf",
        [chunk(PDF_ID, index, f"第 {index + 1} 页", tokens=100, locator={"page": index + 1}) for index in range(12)],
        page_count=12,
    )

    plan = plan_attachment_evidence("请逐页完整检查每一页", [source])
    task = build_full_inspection_task(
        plan,
        user_turn_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        batch_size=5,
    )

    assert plan.mode == EvidenceMode.FULL_INSPECTION
    assert plan.requires_async_full_inspection is True
    assert task["task_type"] == "attachment_full_inspection"
    assert task["status"] == "pending"
    assert task["user_turn_id"] == "44444444-4444-4444-4444-444444444444"
    assert task["total_locators"] == 12
    assert [len(batch) for batch in task["batches"]] == [5, 5, 2]
    assert task["completed_locators"] == []
    assert task["failed_locators"] == []


def test_attachment_retrieval_route_only_runs_for_current_prior_or_required_file_evidence():
    assert should_retrieve_attachment_evidence(current_attachment_ids=[PDF_ID]) is True
    assert should_retrieve_attachment_evidence(message="继续比较刚才上传的 PDF", prior_attachment_ids=[PDF_ID]) is True
    assert should_retrieve_attachment_evidence(route_requires_file_evidence=True) is True
    assert should_retrieve_attachment_evidence(message="今天天气怎么样") is False


@pytest.mark.parametrize(
    ("filename", "kind", "locator", "expected"),
    [
        ("方案.pdf", "pdf", {"page": 7}, "[方案.pdf，第 7 页]"),
        ("介绍.pptx", "pptx", {"slide": 12}, "[介绍.pptx，第 12 张]"),
        ("需求.docx", "docx", {"heading": "验收标准"}, "[需求.docx，“验收标准”章节]"),
        ("预算.xlsx", "xlsx", {"sheet": "Sheet1", "range": "A2:D18"}, "[预算.xlsx，Sheet1!A2:D18]"),
        ("architecture.png", "image", {"frame": 1}, "[architecture.png]"),
    ],
)
def test_citation_labels_are_stable(filename, kind, locator, expected):
    assert citation_label(filename, kind, locator) == expected


def test_unselected_evidence_id_is_rejected_and_partial_coverage_is_explicit():
    source = attachment(
        PDF_ID,
        "方案.pdf",
        "pdf",
        [
            chunk(PDF_ID, 0, "已检查", tokens=100, locator={"page": 1}, vector_score=1.0),
            chunk(PDF_ID, 1, "未检查", tokens=100, locator={"page": 2}, vector_score=0.0),
        ],
        page_count=40,
    )
    plan = plan_attachment_evidence("已检查", [source], total_attachment_budget=100)
    selected = {item.evidence_id for item in plan.text_items}

    validate_cited_evidence_ids(selected, selected)
    with pytest.raises(CitationValidationError, match="unselected_evidence_id"):
        validate_cited_evidence_ids({"evidence-not-selected"}, selected)
    statement = coverage_statement(plan)
    assert "仅检查" in statement
    assert "第 1 页" in statement
    assert "未覆盖" in statement


def test_attachment_answer_rejects_unselected_page_citations_without_rejecting_web_sources():
    selected_context = [
        {
            "evidence_id": "att-evidence-page-1",
            "filename": "方案.pdf",
            "kind": "pdf",
            "locator": {"page": 1},
            "citation_label": "[方案.pdf，第 1 页]",
        }
    ]

    valid = validate_attachment_answer_citations(
        "第一页定义了目标。[方案.pdf，第 1 页] 公开资料另见 [web-source-1]。",
        selected_context,
    )
    invalid = validate_attachment_answer_citations(
        "第二页已经确认预算。[方案.pdf，第 2 页]",
        selected_context,
    )

    assert valid == {
        "valid": True,
        "selected_labels": ["[方案.pdf，第 1 页]"],
        "cited_labels": ["[方案.pdf，第 1 页]"],
        "unknown_labels": [],
    }
    assert invalid["valid"] is False
    assert invalid["unknown_labels"] == ["[方案.pdf，第 2 页]"]


def test_full_inspection_processes_bounded_batches_and_finishes_partial_with_failed_locators():
    plan = plan_attachment_evidence(
        "逐页检查",
        [
            attachment(
                PDF_ID,
                "审计.pdf",
                "pdf",
                [
                    chunk(PDF_ID, 0, "第一页", locator={"page": 1}),
                    chunk(PDF_ID, 1, "第二页", locator={"page": 2}),
                    chunk(PDF_ID, 2, "第三页", locator={"page": 3}),
                ],
                page_count=3,
            )
        ],
    )
    contract = build_full_inspection_task(plan, user_turn_id=uuid.uuid4(), batch_size=2)

    def inspect(locator):
        page = locator["locator"]["page"]
        if page == 2:
            raise RuntimeError("render_failed")
        return {"summary": f"第 {page} 页已核对", "citation_label": f"[审计.pdf，第 {page} 页]"}

    first = process_full_inspection_batch(contract, inspect)
    second = process_full_inspection_batch(first, inspect)

    assert first["status"] == "running"
    assert first["progress"] == {"processed": 2, "total": 3, "succeeded": 1, "failed": 1}
    assert second["status"] == "completed"
    assert second["coverage_status"] == "partial"
    assert [item["locator"] for item in second["completed_locators"]] == [{"page": 1}, {"page": 3}]
    assert second["failed_locators"][0]["locator"] == {"page": 2}
    assert second["failed_locators"][0]["error"] == "render_failed"
    assert second["unprocessed_locators"] == []
    assert "第 2 页" in terminal_full_inspection_summary(second)
    assert "部分完成" in terminal_full_inspection_summary(second)


def test_full_inspection_batch_resume_is_idempotent_and_forced_terminal_lists_unprocessed():
    contract = {
        "task_type": "attachment_full_inspection",
        "status": "pending",
        "total_locators": 2,
        "batches": [
            [
                {"attachment_id": str(PDF_ID), "filename": "方案.pdf", "kind": "pdf", "locator": {"page": 1}},
            ],
            [
                {"attachment_id": str(PDF_ID), "filename": "方案.pdf", "kind": "pdf", "locator": {"page": 2}},
            ],
        ],
        "completed_locators": [],
        "failed_locators": [],
        "coverage_status": "pending",
    }
    calls = []

    first = process_full_inspection_batch(
        contract,
        lambda locator: calls.append(locator["locator"]["page"]) or {"summary": "ok"},
    )
    replay = process_full_inspection_batch(
        first,
        lambda locator: calls.append(locator["locator"]["page"]) or {"summary": "ok"},
        batch_index=0,
    )
    forced = process_full_inspection_batch(replay, lambda locator: {"summary": "unused"}, force_terminal=True)

    assert calls == [1]
    assert replay["progress"]["processed"] == 1
    assert forced["status"] == "completed"
    assert forced["coverage_status"] == "partial"
    assert forced["unprocessed_locators"][0]["locator"] == {"page": 2}
    assert "第 2 页" in terminal_full_inspection_summary(forced)


def test_full_inspection_worker_claims_one_batch_and_persists_terminal_progress():
    payload = {
        "task_type": "attachment_full_inspection",
        "status": "pending",
        "total_locators": 1,
        "batches": [
            [
                {"attachment_id": str(PDF_ID), "filename": "方案.pdf", "kind": "pdf", "locator": {"page": 1}},
            ]
        ],
        "completed_locators": [],
        "failed_locators": [],
        "coverage_status": "pending",
    }

    class Repository:
        def __init__(self):
            self.claimed = False
            self.saved = []

        def claim_next(self, worker_id, lease_seconds):
            if self.claimed:
                return None
            self.claimed = True
            return ClaimedFullInspectionBatch(
                task_run_id="task-full-worker-1",
                task_step_id="step-full-worker-1",
                batch_index=0,
                payload=payload,
            )

        def persist_progress(self, claim, updated_payload):
            self.saved.append((claim, updated_payload))

    repository = Repository()
    worker = AttachmentFullInspectionWorker(
        repository=repository,
        inspector=lambda locator: {
            "summary": "第一页要求逐项验收",
            "citation_label": "[方案.pdf，第 1 页]",
        },
        worker_id="worker-test",
    )

    result = worker.run_next()

    assert result.task_run_id == "task-full-worker-1"
    assert result.status == "completed"
    assert result.coverage_status == "complete"
    assert repository.saved[0][1]["progress"] == {
        "processed": 1,
        "total": 1,
        "succeeded": 1,
        "failed": 0,
    }
    assert "覆盖完整" in repository.saved[0][1]["final_summary"]
    assert worker.run_next() is None


def test_postgres_full_inspection_repository_claims_with_lease_and_persists_step_and_task():
    payload = {
        "task_type": "attachment_full_inspection",
        "status": "pending",
        "batches": [[{"attachment_id": str(PDF_ID), "filename": "方案.pdf", "kind": "pdf", "locator": {"page": 1}}]],
        "completed_locators": [],
        "failed_locators": [],
    }

    class Result:
        def __init__(self, row=None):
            self.row = row

        def fetchone(self):
            return self.row

    class Conn:
        def __init__(self, claim_row=None):
            self.claim_row = claim_row
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(str(sql).split())
            self.calls.append((compact, params))
            if "FOR UPDATE OF step SKIP LOCKED" in compact:
                return Result(self.claim_row)
            return Result()

    claim_conn = Conn(("task-db-1", payload, "step-db-1", 0))
    persist_conn = Conn()
    connections = iter([claim_conn, persist_conn])
    repository = PostgresFullInspectionRepository(lambda: next(connections))

    claim = repository.claim_next("worker-db", 90)
    updated = process_full_inspection_batch(claim.payload, lambda locator: {"summary": "ok"}, batch_index=0)
    repository.persist_progress(claim, updated)

    assert claim.task_run_id == "task-db-1"
    assert claim.batch_index == 0
    assert any("lease_owner = %s" in sql and params[0] == "worker-db" for sql, params in claim_conn.calls)
    assert any("UPDATE task_runs" in sql and "status = 'running'" in sql for sql, _ in claim_conn.calls)
    assert any("UPDATE task_steps" in sql and "output_json" in sql for sql, _ in persist_conn.calls)
    assert any("UPDATE task_runs" in sql and params[0] == "completed" for sql, params in persist_conn.calls)


def test_database_attachment_locator_inspector_returns_traceable_chunk_content():
    class Result:
        def fetchone(self):
            return ("逐项核对验收标准", {"page": 7}, "pdf", "方案.pdf")

    class Conn:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            self.calls.append((" ".join(str(sql).split()), params))
            return Result()

    conn = Conn()
    inspector = DatabaseAttachmentLocatorInspector(lambda: conn)

    result = inspector(
        {
            "attachment_id": str(PDF_ID),
            "filename": "方案.pdf",
            "kind": "pdf",
            "locator": {"page": 7},
        }
    )

    assert result["content"] == "逐项核对验收标准"
    assert result["citation_label"] == "[方案.pdf，第 7 页]"
    assert conn.calls[0][1][0] == PDF_ID


def test_attachment_worker_cycle_advances_parse_and_full_inspection_queues_independently():
    calls = []

    class Worker:
        def __init__(self, name, result):
            self.name = name
            self.result = result

        def run_next(self):
            calls.append(self.name)
            return self.result

    parsed, inspected = run_worker_cycle(
        Worker("parse", None),
        Worker("full_inspection", {"status": "running"}),
    )

    assert calls == ["parse", "full_inspection"]
    assert parsed is None
    assert inspected == {"status": "running"}


class FakeResult:
    def __init__(self, *, rows=None, row=None, rowcount=1):
        self.rows = list(rows or [])
        self.row = row
        self.rowcount = rowcount

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.row


class RecordingConnection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((" ".join(str(sql).split()), params))
        if not self.responses:
            raise AssertionError(f"unexpected SQL: {sql}")
        return self.responses.pop(0)


def test_load_attachment_evidence_batches_manifest_chunks_and_vector_scores():
    rows = [
        (
            PDF_ID,
            "方案.pdf",
            "pdf",
            0,
            "项目目标",
            120,
            {"page": 1},
            "hash-1",
            0.91,
            {"manifest": {"page_count": 22}},
            True,
            True,
        ),
        (
            PDF_ID,
            "方案.pdf",
            "pdf",
            1,
            "验收标准",
            180,
            {"page": 2},
            "hash-2",
            0.82,
            {"manifest": {"page_count": 22}},
            False,
            False,
        ),
    ]
    conn = RecordingConnection([FakeResult(rows=rows)])

    loaded = load_attachment_evidence(conn, [PDF_ID], query_embedding=[0.1, 0.2])

    assert len(conn.calls) == 1
    assert "FROM chat_attachments attachment" in conn.calls[0][0]
    assert "chat_attachment_chunks" in conn.calls[0][0]
    assert loaded[0].page_count == 22
    assert [item.vector_score for item in loaded[0].chunks] == [0.91, 0.82]
    assert loaded[0].chunks[0].low_text_density is True
    assert loaded[0].chunks[0].contains_visual is True


def test_recent_attachment_ids_are_scoped_ordered_and_bounded_to_recent_turns():
    conn = RecordingConnection(
        [
            FakeResult(
                rows=[
                    (PDF_ID,),
                    (PPTX_ID,),
                    (PDF_ID,),
                ]
            )
        ]
    )
    conversation_id = uuid.UUID("55555555-5555-5555-5555-555555555555")

    result = load_recent_attachment_ids(conn, conversation_id, exclude_turn_id=SMALL_ID, round_limit=15)

    assert result == [PDF_ID, PPTX_ID]
    sql, params = conn.calls[0]
    assert "LIMIT %s" in sql
    assert params[-1] == 30


def test_attachment_retrieval_runs_in_parallel_context_without_disabling_existing_layers():
    route = ChatContextRoute(
        intent="task_request",
        needs_dialogue=True,
        needs_memory=True,
        needs_agenda=True,
        needs_tasks=True,
        needs_attachments=True,
    )
    fetchers = {
        "dialogue": lambda: ["turn"],
        "memory": lambda: ["memory"],
        "agenda": lambda: ["agenda"],
        "tasks": lambda: ["task"],
        "attachments": lambda: ["attachment-evidence"],
    }

    result = retrieve_chat_context_parallel(route, fetchers)

    assert result["dialogue"] == ["turn"]
    assert result["memory"] == ["memory"]
    assert result["agenda"] == ["agenda"]
    assert result["tasks"] == ["task"]
    assert result["attachments"] == ["attachment-evidence"]
    assert result["latency_trace"]["attachments_ms"] >= 0
    assert route.to_decision()["needs"]["attachments"] is True


def test_full_inspection_task_is_persisted_idempotently_with_batch_steps_and_evidence_links():
    task_contract = {
        "task_type": "attachment_full_inspection",
        "status": "pending",
        "user_turn_id": str(SMALL_ID),
        "total_locators": 3,
        "batches": [
            [
                {"attachment_id": str(PDF_ID), "filename": "审计.pdf", "kind": "pdf", "locator": {"page": 1}},
                {"attachment_id": str(PDF_ID), "filename": "审计.pdf", "kind": "pdf", "locator": {"page": 2}},
            ],
            [
                {"attachment_id": str(PDF_ID), "filename": "审计.pdf", "kind": "pdf", "locator": {"page": 3}},
            ],
        ],
        "completed_locators": [],
        "failed_locators": [],
        "coverage_status": "pending",
    }
    stored_row = (
        "task_attachment_inspection",
        "attachment_full_inspection",
        "queued",
        task_contract,
    )
    conn = RecordingConnection(
        [
            FakeResult(rowcount=1),
            FakeResult(row=stored_row),
            FakeResult(),
            FakeResult(),
            FakeResult(),
            FakeResult(),
            FakeResult(),
        ]
    )

    task = persist_full_inspection_task(conn, task_contract)

    assert task["task_run_id"] == "task_attachment_inspection"
    assert task["task_type"] == "attachment_full_inspection"
    assert task["status"] == "queued"
    inserts = [sql for sql, _ in conn.calls]
    assert sum("INSERT INTO task_steps" in sql for sql in inserts) == 2
    assert sum("INSERT INTO task_evidence_links" in sql for sql in inserts) == 3
    assert all("inspect_locator_batch" in str(params) for sql, params in conn.calls if "INSERT INTO task_steps" in sql)
