from __future__ import annotations

from typing import Any


VALID_COLLECTOR_STATES = {
    "unknown",
    "logged_out",
    "login_required",
    "logged_in",
    "collecting",
    "degraded",
    "blocked",
}


def normalize_collector_state(
    *,
    source: str,
    account_id: str,
    login_state: str,
    last_success_event_at: str | None = None,
    last_error_code: str | None = None,
    last_error_message: str | None = None,
    reconnect_attempts: int = 0,
) -> dict[str, Any]:
    state = str(login_state or "unknown").strip().lower()
    if state not in VALID_COLLECTOR_STATES:
        state = "unknown"
    return {
        "source": str(source or "").strip().lower(),
        "account_id": str(account_id or "").strip(),
        "login_state": state,
        "last_success_event_at": str(last_success_event_at or "").strip(),
        "last_error_code": str(last_error_code or "").strip(),
        "last_error_message": str(last_error_message or "").strip(),
        "reconnect_attempts": max(0, int(reconnect_attempts or 0)),
    }


def explain_collector_gap(state: dict[str, Any], question: str) -> dict[str, Any]:
    source = str(state.get("source") or "unknown")
    login_state = str(state.get("login_state") or "unknown")
    last_success = str(state.get("last_success_event_at") or "").strip()
    error_message = str(state.get("last_error_message") or "").strip()
    question_text = str(question or "").strip()

    if login_state == "collecting":
        return {
            "source": source,
            "severity": "ok",
            "can_claim_no_records": True,
            "message": f"{source} 正在采集，可按现有记忆回答：{question_text}",
        }

    if login_state == "logged_in":
        return {
            "source": source,
            "severity": "warn",
            "can_claim_no_records": False,
            "message": f"{source} 已登录但实时采集未确认，最近成功同步时间：{last_success or '未知'}。",
        }

    reason_map = {
        "unknown": "采集状态未知",
        "logged_out": "账号未登录",
        "login_required": "需要重新登录",
        "degraded": "采集链路部分异常",
        "blocked": "平台阻断或页面异常",
    }
    reason = error_message or reason_map.get(login_state, "采集状态异常")
    suffix = f"最近成功同步时间：{last_success}。" if last_success else "还没有成功同步时间。"
    return {
        "source": source,
        "severity": "blocked" if login_state in {"blocked", "logged_out", "login_required"} else "warn",
        "can_claim_no_records": False,
        "message": f"{source} 当前{reason}，不能据此断言没有记录。{suffix}",
    }
