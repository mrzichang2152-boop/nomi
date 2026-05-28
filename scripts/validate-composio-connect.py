#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime_api"))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")
os.environ.setdefault("APP_PASSWORD", "secret")

from fastapi import HTTPException
from app import main


def report(stage: str, output: dict[str, Any], checks: dict[str, bool]) -> dict[str, Any]:
    return {"stage": stage, "reasonable": all(checks.values()), "output": output, "checks": checks}


class Cursor:
    rowcount = 1

    def __init__(self, rows: list[Any] | None = None):
        self.rows = rows or []

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, executed: list[tuple[str, tuple[Any, ...]]], existing_session: bool = False):
        self.executed = executed
        self.existing_session = existing_session

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))
        if "FROM composio_sessions" in normalized and self.existing_session:
            return Cursor([("sess_readonly", "https://mcp.composio.test/session", {"authorization": "Bearer secret"})])
        if "FROM composio_sessions" in normalized:
            return Cursor()
        return Cursor()


class FakeMcp:
    url = "https://mcp.composio.test/session"
    headers = {"authorization": "Bearer sdk-secret", "x-session": "session-secret"}


class FakeConnectRequest:
    id = "link_req_1"
    redirect_url = "https://connect.composio.dev/link/ln_test"
    connected_account_id = "ca_pending"
    expires_at = "2026-05-28T12:00:00Z"


class FakeConnection:
    is_active = True

    class connected_account:
        id = "ca_gmail"


class FakeToolkit:
    slug = "gmail"
    name = "Gmail"
    logo = "https://logo.test/gmail.png"
    connection = FakeConnection()


class FakeToolkitResult:
    items = [FakeToolkit()]
    next_cursor = None


class FakeSession:
    session_id = "sess_readonly"
    mcp = FakeMcp()

    def __init__(self, captured: dict[str, Any]):
        self.captured = captured

    def authorize(self, toolkit_slug: str, callback_url: str | None = None):
        self.captured["authorize"] = {"toolkit_slug": toolkit_slug, "callback_url": callback_url}
        return FakeConnectRequest()

    def toolkits(self, **kwargs):
        self.captured["toolkits_kwargs"] = kwargs
        return FakeToolkitResult()


class FakeComposio:
    def __init__(self, captured: dict[str, Any]):
        self.captured = captured

    def create(self, **kwargs):
        self.captured["create"] = kwargs
        return FakeSession(self.captured)

    def use(self, session_id: str):
        self.captured["use"] = session_id
        return FakeSession(self.captured)


def main_script() -> int:
    reports: list[dict[str, Any]] = []
    original_db = main.db
    original_factory = main.create_composio_sdk_client
    original_key = os.environ.get("COMPOSIO_API_KEY")
    original_user = os.environ.get("COMPOSIO_USER_ID")
    try:
        os.environ.pop("COMPOSIO_API_KEY", None)
        try:
            main.create_composio_connect_link("gmail")
            missing_key_output = {"raised": False}
        except HTTPException as exc:
            missing_key_output = {"raised": True, "status_code": exc.status_code, "detail": exc.detail}
        reports.append(
            report(
                "missing_api_key_blocks_connect_without_sdk",
                missing_key_output,
                {
                    "raises_503": missing_key_output.get("status_code") == 503,
                    "clear_error_code": missing_key_output.get("detail", {}).get("code") == "composio_api_key_missing",
                },
            )
        )

        captured: dict[str, Any] = {}
        executed: list[tuple[str, tuple[Any, ...]]] = []
        os.environ["COMPOSIO_API_KEY"] = "test-key"
        os.environ["COMPOSIO_USER_ID"] = "nomi_owner"
        main.db = lambda: FakeConn(executed, existing_session=False)
        main.create_composio_sdk_client = lambda api_key: FakeComposio(captured)
        link = main.create_composio_connect_link("gmail")
        link_text = json.dumps(link, ensure_ascii=False)
        reports.append(
            report(
                "connect_link_output_is_safe_and_actionable",
                {
                    "link": link,
                    "create_args": captured.get("create"),
                    "authorize_args": captured.get("authorize"),
                    "write_tables": [sql.split(" ")[2] for sql, _ in executed if sql.startswith("INSERT INTO ")],
                },
                {
                    "redirect_is_connect_link": link["redirect_url"].startswith("https://connect.composio.dev/link/"),
                    "manual_connections_disabled": captured.get("create", {}).get("manage_connections") is False,
                    "gmail_authorized": captured.get("authorize", {}).get("toolkit_slug") == "gmail",
                    "destructive_disabled": captured.get("create", {}).get("tags", {}).get("disable") == ["destructiveHint"],
                    "secrets_redacted": "sdk-secret" not in link_text and "test-key" not in link_text,
                    "local_audit_written": any("INSERT INTO composio_connect_requests" in sql for sql, _ in executed)
                    and any("INSERT INTO account_connections" in sql for sql, _ in executed),
                },
            )
        )

        captured = {}
        executed = []
        main.db = lambda: FakeConn(executed, existing_session=True)
        main.create_composio_sdk_client = lambda api_key: FakeComposio(captured)
        sync = main.sync_composio_toolkits("readonly")
        sync_text = json.dumps(sync, ensure_ascii=False)
        reports.append(
            report(
                "toolkit_sync_reports_connected_account_without_secrets",
                sync,
                {
                    "existing_session_reused": captured.get("use") == "sess_readonly",
                    "gmail_connected": sync["toolkits"] == [
                        {
                            "slug": "gmail",
                            "name": "Gmail",
                            "logo": "https://logo.test/gmail.png",
                            "connected": True,
                            "connected_account_id": "ca_gmail",
                        }
                    ],
                    "headers_redacted": "secret" not in sync_text,
                    "toolkit_row_written": any("INSERT INTO composio_toolkits" in sql for sql, _ in executed),
                },
            )
        )
    finally:
        main.db = original_db
        main.create_composio_sdk_client = original_factory
        if original_key is None:
            os.environ.pop("COMPOSIO_API_KEY", None)
        else:
            os.environ["COMPOSIO_API_KEY"] = original_key
        if original_user is None:
            os.environ.pop("COMPOSIO_USER_ID", None)
        else:
            os.environ["COMPOSIO_USER_ID"] = original_user

    print(json.dumps({"reports": reports}, ensure_ascii=False, indent=2))
    return 0 if all(item["reasonable"] for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main_script())

