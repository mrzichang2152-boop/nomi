from __future__ import annotations

from uuid import UUID

from app.attachments.repository import load_public_attachments_for_turns


MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000101")
FIRST_ID = UUID("00000000-0000-0000-0000-000000000201")
SECOND_ID = UUID("00000000-0000-0000-0000-000000000202")


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


def test_public_history_contract_has_explicit_order_and_no_private_storage_fields():
    rows = [
        (MESSAGE_ID, 1, SECOND_ID, "同名.pdf", "application/pdf", None, 20, "ready", "attached", "pdf"),
        (MESSAGE_ID, 0, FIRST_ID, "同名.pdf", "application/pdf", None, 10, "ready", "attached", "pdf"),
    ]

    class Conn:
        def execute(self, sql, params=()):
            assert "order by ata.turn_id, ata.ordinal" in " ".join(sql.lower().split())
            assert params == ([MESSAGE_ID],)
            return Cursor(sorted(rows, key=lambda row: row[1]))

    payload = load_public_attachments_for_turns(Conn(), [MESSAGE_ID])[str(MESSAGE_ID)]

    assert [item["attachment_id"] for item in payload] == [str(FIRST_ID), str(SECOND_ID)]
    assert [item["ordinal"] for item in payload] == [0, 1]
    assert set(payload[0]) == {
        "attachment_id",
        "filename",
        "mime_type",
        "byte_size",
        "status",
        "kind",
        "preview_url",
        "content_url",
        "ordinal",
    }
    rendered = repr(payload).lower()
    assert "base64" not in rendered
    assert "storage_relative_path" not in rendered
    assert "sha256" not in rendered
    assert "original_bytes" not in rendered
