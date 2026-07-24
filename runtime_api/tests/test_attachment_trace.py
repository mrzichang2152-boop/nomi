from __future__ import annotations

import json
import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_attachment_trace_has_required_stage_and_stream_timings_without_private_data():
    from app.attachments.trace import build_attachment_trace

    trace = build_attachment_trace(
        request_id="req-123",
        client_request_id="client-456",
        turn_id="turn-789",
        retry_count=2,
        attachment_records=[
            {
                "attachment_id": "attachment-1",
                "mime_type": "application/pdf",
                "status": "ready",
                "processing_version": "attachment-v1",
                "content": "private quarterly revenue",
                "storage_relative_path": "private/attachment-1.pdf",
            }
        ],
        selected=[
            {
                "attachment_id": "attachment-1",
                "evidence_id": "evidence-1",
                "locator": {"page": 4},
                "content_hash": "chunk-4",
            }
        ],
        excluded=[
            {
                "attachment_id": "attachment-1",
                "evidence_id": "evidence-2",
                "locator": {"page": 5},
                "reason": "token_budget",
            }
        ],
        visual_count=1,
        timings={
            "upload_ms": 11,
            "hash_ms": 2,
            "store_ms": 7,
            "parse_ms": 23,
            "chunk_ms": 4,
            "embed_ms": 9,
            "retrieve_ms": 5,
            "render_ms": 3,
            "upstream_first_chunk_ms": 101,
            "formal_first_character_ms": 127,
            "total_ms": 222,
        },
    )

    assert trace["request_id"] == "req-123"
    assert trace["client_request_id"] == "client-456"
    assert trace["turn_id"] == "turn-789"
    assert trace["retry_count"] == 2
    assert trace["attachment_count"] == 1
    assert trace["visual_count"] == 1
    assert trace["selected_locators"] == [
        {
            "attachment_id": "attachment-1",
            "evidence_id": "evidence-1",
            "locator": {"page": 4},
            "content_hash": "chunk-4",
        }
    ]
    assert trace["excluded_locators"][0]["reason"] == "token_budget"
    assert trace["timings"] == {
        "upload_ms": 11,
        "hash_ms": 2,
        "store_ms": 7,
        "parse_ms": 23,
        "chunk_ms": 4,
        "embed_ms": 9,
        "retrieve_ms": 5,
        "render_ms": 3,
        "upstream_first_chunk_ms": 101,
        "formal_first_character_ms": 127,
        "total_ms": 222,
    }
    serialized = json.dumps(trace, ensure_ascii=False).lower()
    assert "private quarterly revenue" not in serialized
    assert "storage_relative_path" not in serialized
    assert "private/attachment-1.pdf" not in serialized


def test_trace_is_deterministic_and_deduplicates_selected_evidence():
    from app.attachments.trace import build_attachment_trace

    selected = [
        {
            "attachment_id": "a-1",
            "evidence_id": "e-1",
            "locator": {"slide": 2},
            "content_hash": "h-1",
        },
        {
            "attachment_id": "a-1",
            "evidence_id": "e-1",
            "locator": {"slide": 2},
            "content_hash": "h-1",
        },
    ]
    first = build_attachment_trace(
        request_id="r",
        client_request_id="c",
        turn_id="t",
        attachment_records=[],
        selected=selected,
        excluded=[],
        timings={},
    )
    second = build_attachment_trace(
        request_id="r",
        client_request_id="c",
        turn_id="t",
        attachment_records=[],
        selected=selected,
        excluded=[],
        timings={},
    )

    assert first == second
    assert len(first["selected_locators"]) == 1


def test_completed_chat_enriches_attachment_trace_with_stream_and_total_latency():
    from app.attachments.trace import enrich_attachment_traces

    context_pack = {
        "attachment_context": [
            {
                "layer": "attachment_evidence_plan",
                "trace": {
                    "request_id": "request-1",
                    "timings": {"retrieve_ms": 8, "formal_first_character_ms": None},
                },
            }
        ]
    }

    enriched = enrich_attachment_traces(
        context_pack,
        {
            "upstream_first_chunk_ms": 91,
            "formal_first_character_ms": 116,
            "total_ms": 240,
        },
    )

    assert enriched == 1
    assert context_pack["attachment_context"][0]["trace"]["timings"] == {
        "retrieve_ms": 8,
        "formal_first_character_ms": 116,
        "upstream_first_chunk_ms": 91,
        "total_ms": 240,
    }
