import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_ppt_request_routes_to_artifact_creation_task():
    from app.artifact_tasks import route_artifact_task

    route = route_artifact_task("帮我依据刚刚王总给的资料，写一份 PPT")

    assert route["message_kind"] == "task_request"
    assert route["task_type"] == "artifact_creation"
    assert route["artifact_type"] == "pptx"
    assert route["confidence"] >= 0.8
    assert route["requires_task_run"] is True
    assert route["requires_user_confirmation_before_external_effect"] is False
    assert route["risk_level"] == "medium"
    assert "PPT" in route["reason"]


def test_ppt_request_with_make_one_routes_to_artifact_creation_task():
    from app.artifact_tasks import route_artifact_task

    route = route_artifact_task("做一个 PPT，让普通人可以理解 LLM 的工作原理")

    assert route["message_kind"] == "task_request"
    assert route["task_type"] == "artifact_creation"
    assert route["artifact_type"] == "pptx"
    assert route["confidence"] >= 0.8
    assert route["requires_task_run"] is True


def test_english_ppt_request_routes_to_artifact_creation_task():
    from app.artifact_tasks import route_artifact_task

    route = route_artifact_task("Make a PPT for ordinary people explaining how LLM works")

    assert route["message_kind"] == "task_request"
    assert route["task_type"] == "artifact_creation"
    assert route["artifact_type"] == "pptx"
    assert route["confidence"] >= 0.8
    assert route["requires_task_run"] is True


def test_url_encoded_ppt_request_routes_to_artifact_creation_task():
    from app.artifact_tasks import route_artifact_task

    route = route_artifact_task("Make%20a%20PPT%20for%20ordinary%20people%20explaining%20how%20LLM%20works")

    assert route["message_kind"] == "task_request"
    assert route["task_type"] == "artifact_creation"
    assert route["artifact_type"] == "pptx"
    assert route["confidence"] >= 0.8


def test_plain_question_stays_chat_answer():
    from app.artifact_tasks import route_artifact_task

    route = route_artifact_task("王总刚刚说了什么？")

    assert route["message_kind"] == "chat_answer"
    assert route["task_type"] == "none"
    assert route["artifact_type"] == "none"
    assert route["requires_task_run"] is False


def test_image_request_routes_to_image_capability_pack():
    from app.artifact_tasks import build_opencode_artifact_route_decision, route_artifact_task

    route = route_artifact_task("帮我生成一张解释 RAG 工作原理的信息图")
    decision = build_opencode_artifact_route_decision(
        "帮我生成一张解释 RAG 工作原理的信息图",
        {"route": route, "evidence_pack": {"items": []}},
    )

    assert route["message_kind"] == "task_request"
    assert route["artifact_type"] == "image"
    assert decision["capability_pack_id"] == "image"
    assert decision["capability_pack_version"] == "1.0.0"


def test_opencode_artifact_route_carries_automatic_delivery_contract():
    from app.artifact_tasks import build_opencode_artifact_route_decision, route_artifact_task

    message = "生成一份两页的项目汇报 PPT"
    decision = build_opencode_artifact_route_decision(
        message,
        {
            "route": route_artifact_task(message),
            "conversation_id": "conv-auto-delivery",
            "evidence_pack": {"items": []},
        },
    )

    assert decision["conversation_id"] == "conv-auto-delivery"
    assert decision["artifact_delivery_mode"] == "automatic_v1"


def test_draw_image_request_routes_to_image_capability_pack():
    from app.artifact_tasks import route_artifact_task

    for message in ("画一张 RAG 流程图", "绘制一张项目进度信息图"):
        route = route_artifact_task(message)
        assert route["message_kind"] == "task_request"
        assert route["artifact_type"] == "image"
        assert route["confidence"] >= 0.8


def test_context_missing_inputs_are_specific_to_requested_artifact():
    from app.artifact_tasks import build_context_requirement_plan

    spreadsheet = build_context_requirement_plan("做一个成本利润 Excel 表格")
    document = build_context_requirement_plan("写一份项目复盘 Word 文档")
    image = build_context_requirement_plan("生成一张 RAG 流程信息图")

    assert spreadsheet["missing_user_inputs"] == ["数据来源", "字段定义", "计算目标"]
    assert document["missing_user_inputs"] == ["文档用途", "目标读者", "章节要求"]
    assert image["missing_user_inputs"] == ["图片用途", "目标受众", "画布尺寸"]


def test_spreadsheet_inline_data_introduced_as_data_only_is_not_reported_missing():
    from app.artifact_tasks import build_context_requirement_plan

    plan = build_context_requirement_plan(
        "生成XLSX用于项目利润分析。数据仅限：Alpha收入128000成本83000；"
        "字段包括项目、收入、成本、利润；利润用收入减成本的公式。"
    )

    assert "数据来源" not in plan["missing_user_inputs"]


def test_wang_zong_recent_material_plan_has_scoped_sources_and_missing_inputs():
    from app.artifact_tasks import build_context_requirement_plan

    plan = build_context_requirement_plan("帮我依据刚刚王总给的资料，写一份 PPT")

    assert plan["needed_context"][0]["type"] == "recent_messages"
    assert plan["needed_context"][0]["entity_hint"] == "王总"
    assert plan["needed_context"][0]["time_window"] == "recent"
    assert "whatsapp" in plan["needed_context"][0]["source"]
    assert "telegram" in plan["needed_context"][0]["source"]
    assert plan["needed_context"][1]["type"] == "attachments"
    assert "PPT用途" in plan["missing_user_inputs"]
    assert "目标听众" in plan["missing_user_inputs"]
    assert "期望页数" in plan["missing_user_inputs"]
    assert plan["can_start_without_missing_inputs"] is True


def test_self_contained_artifact_request_does_not_fetch_private_context():
    from app.artifact_tasks import build_context_requirement_plan

    plan = build_context_requirement_plan(
        "生成2页PPTX。第1页标题Auto Delivery Verification；"
        "第2页说明Server-side unified delivery和Android real-device received。"
    )

    assert plan["needed_context"] == []
    assert plan["requires_private_context"] is False


def test_english_self_contained_presentation_contract_is_not_reported_missing():
    from app.artifact_tasks import build_context_requirement_plan

    plan = build_context_requirement_plan(
        "Create a 2-slide PPTX for software engineers. "
        "Slide 1 explains context routing and slide 2 reports the acceptance result."
    )

    assert plan["missing_user_inputs"] == []
    assert plan["requires_private_context"] is False


def test_evidence_pack_marks_missing_topic_when_no_evidence_is_found():
    from app.artifact_tasks import build_evidence_pack

    pack = build_evidence_pack(
        "帮我依据刚刚王总给的资料，写一份 PPT",
        context_plan={"needed_context": [], "missing_user_inputs": ["PPT用途"]},
        source_context=[],
        memory_context=[],
    )

    assert pack["items"] == []
    assert pack["coverage"]["has_topic"] is False
    assert pack["coverage"]["has_data_points"] is False
    assert "未找到王总最近资料" in pack["missing_evidence"]


def test_evidence_pack_uses_real_source_items_and_explains_relevance():
    from app.artifact_tasks import build_evidence_pack

    source_item = {
        "event_id": "evt_whatsapp_1",
        "source": "whatsapp",
        "actor": "王总",
        "timestamp": "2026-07-06T10:30:00+08:00",
        "content": "王总：本次客户汇报重点是上线计划、预算和风险。",
    }

    pack = build_evidence_pack(
        "帮我依据刚刚王总给的资料，写一份 PPT",
        context_plan={"needed_context": [], "missing_user_inputs": []},
        source_context=[source_item],
        memory_context=[],
    )

    assert pack["items"][0]["evidence_id"] == "evt_whatsapp_1"
    assert pack["items"][0]["source"] == "whatsapp"
    assert pack["items"][0]["actor"] == "王总"
    assert "客户汇报重点" in pack["items"][0]["excerpt"]
    assert pack["items"][0]["confidence"] >= 0.8
    assert "王总" in pack["items"][0]["reason"]
    assert pack["coverage"]["has_topic"] is True
    assert pack["coverage"]["has_data_points"] is True


def test_evidence_pack_preserves_real_attachments_for_artifact_tasks():
    from app.artifact_tasks import build_evidence_pack

    source_item = {
        "event_id": "evt_gmail_attachment_1",
        "source": "gmail",
        "actor": "王总",
        "timestamp": "2026-07-06T11:00:00+08:00",
        "attachments": [
            {
                "attachment_id": "att_1",
                "filename": "客户汇报材料.pdf",
                "mime_type": "application/pdf",
                "local_path": "/app/uploads/客户汇报材料.pdf",
            }
        ],
    }

    pack = build_evidence_pack(
        "帮我依据刚刚王总给的资料，写一份 PPT",
        context_plan={"needed_context": [], "missing_user_inputs": []},
        source_context=[source_item],
        memory_context=[],
    )

    assert pack["items"][0]["evidence_id"] == "evt_gmail_attachment_1"
    assert pack["items"][0]["source_type"] == "file"
    assert "客户汇报材料.pdf" in pack["items"][0]["excerpt"]
    assert pack["items"][0]["attachments"] == [
        {
            "attachment_id": "att_1",
            "filename": "客户汇报材料.pdf",
            "mime_type": "application/pdf",
            "local_path": "/app/uploads/客户汇报材料.pdf",
        }
    ]
    assert pack["coverage"]["has_file_attachments"] is True


def test_get_task_returns_artifact_task_state_and_evidence(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    created_at = datetime(2026, 7, 6, 10, 30, tzinfo=timezone.utc)
    executed = []

    class Cursor:
        def __init__(self, rows=None, row=None):
            self.rows = rows or []
            self.row = row

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(sql.split())
            executed.append((compact, params))
            if "FROM task_runs" in compact:
                return Cursor(
                    row=(
                        "task_artifact_1",
                        "artifact_creation",
                        ["evt_whatsapp_wang_1"],
                        "ppt_creation_pipeline",
                        "artifact_task",
                        "queued",
                        "local_artifact_only",
                        False,
                        "依据王总资料生成 PPT",
                        {"route": {"artifact_type": "pptx"}},
                        created_at,
                        created_at,
                    )
                )
            if "FROM task_steps" in compact:
                return Cursor(
                    rows=[
                        ("step_1", "interpret_request", 0, "succeeded", {"message": "写 PPT"}, {}, "", 1, created_at),
                        ("step_2", "gather_evidence", 1, "queued", {}, {}, "", 0, created_at),
                    ]
                )
            if "FROM task_evidence_links" in compact:
                return Cursor(
                    rows=[
                        (
                            "link_1",
                            "evt_whatsapp_wang_1",
                            "event",
                            "whatsapp",
                            "王总",
                            "artifact_evidence",
                            0.9,
                            created_at,
                        )
                    ]
                )
            raise AssertionError(f"unexpected query: {compact}")

    monkeypatch.setattr(main, "db", lambda: Conn())

    response = TestClient(main.app).get("/api/tasks/task_artifact_1", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["task_run_id"] == "task_artifact_1"
    assert body["task"]["task_type"] == "artifact_creation"
    assert body["task"]["artifact_type"] == "pptx"
    assert body["task"]["status"] == "queued"
    assert body["steps"][0]["step_name"] == "interpret_request"
    assert body["steps"][0]["status"] == "succeeded"
    assert body["steps"][1]["step_name"] == "gather_evidence"
    assert body["evidence_links"][0]["evidence_id"] == "evt_whatsapp_wang_1"
    assert body["evidence_links"][0]["source"] == "whatsapp"
    assert any("FROM task_runs" in sql for sql, _ in executed)


def test_get_task_artifacts_returns_empty_list_for_planning_task(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    class Cursor:
        def fetchall(self):
            return []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(sql.split())
            assert "FROM task_artifacts" in compact
            assert params == ("task_artifact_1",)
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    response = TestClient(main.app).get("/api/tasks/task_artifact_1/artifacts", headers={"x-par-password": "secret"})

    assert response.status_code == 200
    assert response.json() == {"task_run_id": "task_artifact_1", "artifacts": []}


def test_download_artifact_returns_file_from_storage_root(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    artifact_dir = tmp_path / "task_1"
    artifact_dir.mkdir()
    artifact_path = artifact_dir / "demo.pptx"
    artifact_path.write_bytes(b"pptx-bytes")
    monkeypatch.setattr(main, "ARTIFACT_STORAGE_DIR", str(tmp_path), raising=False)

    class Cursor:
        def fetchone(self):
            return (
                "demo.pptx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                str(artifact_path),
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(sql.split())
            assert "FROM task_artifacts" in compact
            assert params == ("artifact_demo",)
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    response = TestClient(main.app).get(
        "/api/artifacts/artifact_demo/download",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    assert response.content == b"pptx-bytes"
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )


def test_download_artifact_accepts_query_password_for_external_browser(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    artifact_dir = tmp_path / "task_1"
    artifact_dir.mkdir()
    artifact_path = artifact_dir / "demo.pptx"
    artifact_path.write_bytes(b"pptx-bytes")
    monkeypatch.setattr(main, "ARTIFACT_STORAGE_DIR", str(tmp_path), raising=False)

    class Cursor:
        def fetchone(self):
            return (
                "demo.pptx",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                str(artifact_path),
            )

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            compact = " ".join(sql.split())
            assert "FROM task_artifacts" in compact
            assert params == ("artifact_demo",)
            return Cursor()

    monkeypatch.setattr(main, "db", lambda: Conn())

    response = TestClient(main.app).get("/api/artifacts/artifact_demo/download?password=secret")

    assert response.status_code == 200
    assert response.content == b"pptx-bytes"


def test_opencode_artifact_plan_is_a_generic_open_task_not_a_ppt_chain():
    from app.artifact_tasks import (
        build_artifact_task_payload,
        build_opencode_artifact_plan,
        build_opencode_artifact_route_decision,
    )

    payload = build_artifact_task_payload(
        "那你帮我做一个ppt 让普通人可以理解llm的工作原理",
        source_context=[],
        memory_context=[],
    )

    plan = build_opencode_artifact_plan(
        "那你帮我做一个ppt 让普通人可以理解llm的工作原理",
        payload=payload,
    )

    assert plan["task_type"] == "artifact_creation"
    assert plan["artifact_type"] == "pptx"
    assert plan["executor_adapter"] == "opencode"
    assert [step["step_id"] for step in plan["steps"]] == [
        "gather_artifact_context",
        "opencode_execute_artifact",
        "verify_artifact_delivery",
    ]
    assert "opencode.run_task_packet" in plan["steps"][1]["allowed_actions"]
    assert "filesystem.write_artifact" in plan["steps"][1]["allowed_actions"]
    assert "browser.submit" not in plan["steps"][1]["allowed_actions"]
    assert "message.send" not in plan["steps"][1]["allowed_actions"]
    assert "基于证据" in " ".join(plan["steps"][1]["verification_criteria"])
    decision = build_opencode_artifact_route_decision(
        "那你帮我做一个ppt 让普通人可以理解llm的工作原理",
        payload,
    )
    assert decision["route_type"] == "long_tail_agent"
    assert decision["executor_adapter"] == "opencode"
    assert decision["capability_id"] == "artifact.creation.opencode"
    assert decision["capability_pack_id"] == "presentation"
    assert decision["capability_pack_version"] == "1.0.0"
    assert decision["capability_pack_agent"] == "presentation-producer"


def test_page_count_is_not_misread_as_a_contact_entity():
    from app.artifact_tasks import build_context_requirement_plan

    plan = build_context_requirement_plan(
        "请生成一份4页PPTX《Q2客户支持复盘汇报》，受众是管理层。"
        "第1页标题摘要；第2页关键指标；第3页总结现状与证据；第4页待评估行动。"
    )

    assert all(item["entity_hint"] == "" for item in plan["needed_context"])


def test_artifact_task_title_does_not_misread_page_summary_as_a_contact(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    title = main.artifact_task_title(
        "生成4页PPTX，第3页总结现状与证据",
        "pptx",
    )

    assert title == "生成PPT产物"


def test_artifact_task_title_does_not_misread_page_only_summarizes_as_a_contact(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    title = main.artifact_task_title(
        "生成4页PPTX，第3页只总结上述现状与证据，不添加信息缺口或评价",
        "pptx",
    )

    assert title == "生成PPT产物"


def test_opencode_artifact_payload_carries_audited_web_evidence_and_tool_contract():
    from app.artifact_tasks import build_artifact_task_payload, build_opencode_artifact_plan

    payload = build_artifact_task_payload(
        "帮我做一份面向普通人的 LLM 原理 PPT",
        source_context=[],
        memory_context=[],
        web_context=[
            {
                "source_id": "websrc_transformer_paper",
                "layer": "web_evidence",
                "title": "Attention Is All You Need",
                "url": "https://arxiv.org/abs/1706.03762",
                "snippet": "The Transformer architecture is based solely on attention mechanisms.",
                "provider": "exa",
                "trust_tier": "primary",
            }
        ],
    )
    plan = build_opencode_artifact_plan("帮我做一份面向普通人的 LLM 原理 PPT", payload=payload)

    evidence = payload["evidence_pack"]["items"][0]
    assert evidence["evidence_id"] == "websrc_transformer_paper"
    assert evidence["source_type"] == "web"
    assert evidence["url"] == "https://arxiv.org/abs/1706.03762"
    assert "Transformer architecture" in evidence["excerpt"]
    assert "nomi.web.search" in plan["steps"][0]["allowed_actions"]
    assert "nomi.web.fetch" in plan["steps"][0]["allowed_actions"]
    assert any("不可信" in constraint for constraint in plan["constraints"])


def test_artifact_payload_treats_the_persisted_current_request_as_traceable_evidence():
    from app.artifact_tasks import (
        build_artifact_task_payload,
        build_opencode_artifact_route_decision,
        opencode_artifact_task_answer,
    )

    event_id = "31ee9e14-1d72-43a3-a463-66be32a870b5"
    message = (
        "生成4页Q2客户支持复盘PPTX。首次响应中位数12分钟，"
        "平均解决时间4.2小时，升级率0.9%。"
    )
    payload = build_artifact_task_payload(
        message,
        source_context=[],
        memory_context=[],
        current_request_evidence_id=event_id,
    )

    evidence = payload["evidence_pack"]["items"]
    assert len(evidence) == 1
    assert evidence[0]["evidence_id"] == event_id
    assert evidence[0]["source_type"] == "user_request"
    assert "首次响应中位数12分钟" in evidence[0]["excerpt"]
    assert "未找到最近资料" not in payload["evidence_pack"]["missing_evidence"]

    decision = build_opencode_artifact_route_decision(message, payload)
    assert decision["source_event_ids"] == [event_id]
    answer = opencode_artifact_task_answer({"artifact_type": "pptx"}, payload)
    assert "任务要求已完整记录" in answer
    assert "已找到 1 条可追溯资料" not in answer


def test_self_contained_artifact_request_excludes_unrelated_private_candidates():
    from app.artifact_tasks import build_artifact_task_payload

    event_id = "request_self_contained_1"
    message = "生成2页PPTX，解释服务端统一交付与Android真机接收。"
    payload = build_artifact_task_payload(
        message,
        current_request_evidence_id=event_id,
        source_context=[
            {
                "event_id": "old_whatsapp_1",
                "source": "whatsapp",
                "actor": "大刚",
                "content": "明天下午三点半人民广场见，带合同。",
            },
            {
                "event_id": "old_gmail_1",
                "source": "gmail",
                "actor": "newsletter@example.com",
                "content": "本周营销活动和隐私政策更新。",
            },
        ],
        memory_context=[
            {
                "memory_id": "old_memory_1",
                "source": "memory",
                "content": "用户最近在寻找后端工程师岗位。",
            }
        ],
    )

    evidence = payload["evidence_pack"]["items"]
    assert [item["evidence_id"] for item in evidence] == [event_id]
    assert payload["context_plan"]["needed_context"] == []


def test_private_material_request_keeps_matching_entity_and_rejects_other_people():
    from app.artifact_tasks import build_artifact_task_payload

    payload = build_artifact_task_payload(
        "帮我依据刚刚王总给的资料，写一份PPT",
        source_context=[
            {
                "event_id": "wang_material",
                "source": "whatsapp",
                "actor": "王总",
                "content": "王总：客户汇报要覆盖上线计划、预算和风险。",
            },
            {
                "event_id": "li_material",
                "source": "telegram",
                "actor": "李总",
                "content": "李总：周五聚餐地点改到静安寺。",
            },
        ],
        memory_context=[],
    )

    evidence = payload["evidence_pack"]["items"]
    assert [item["evidence_id"] for item in evidence] == ["wang_material"]
    assert payload["context_plan"]["requires_private_context"] is True


def test_opencode_artifact_plan_carries_requirements_contract_without_generic_missing_material():
    from app.artifact_tasks import (
        build_artifact_task_payload,
        build_opencode_artifact_plan,
        opencode_artifact_task_answer,
    )
    from app.open_task_clarification import analyze_open_task_clarity

    original = "帮我做一个 AI 生成视频原理的 PPT 可以用来讲解"
    payload = build_artifact_task_payload(original, source_context=[], memory_context=[])
    pending = analyze_open_task_clarity(original, artifact_payload=payload)
    executable = analyze_open_task_clarity(
        "普通人，10页，偏科普，可以多用类比",
        artifact_payload=payload,
        pending_task_state=pending,
    )
    payload["open_task_clarification"] = executable
    payload["requirements_contract"] = executable["requirements_contract"]

    plan = build_opencode_artifact_plan(original, payload=payload)

    assert plan["input"]["requirements_contract"]["audience"] == "普通人"
    assert plan["input"]["requirements_contract"]["page_count"] == 10
    assert plan["input"]["requirements_contract"]["source_policy"] == "may_use_general_knowledge"
    assert "未找到最近资料" not in plan["metadata"]["missing_evidence"]
    assert "目标听众" not in plan["metadata"]["missing_evidence"]
    assert "期望页数" not in plan["metadata"]["missing_evidence"]
    assert plan["metadata"]["requirements_contract"]["final_goal"].startswith("生成一份")

    answer = opencode_artifact_task_answer(
        {"artifact_type": "pptx"},
        payload,
    )
    assert "目标听众" not in answer
    assert "期望页数" not in answer
    assert "未找到最近资料" not in answer
