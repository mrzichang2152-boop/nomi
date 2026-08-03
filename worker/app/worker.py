from __future__ import annotations

import json
import base64
import hashlib
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import parse_qs, unquote_plus, urlparse
from zoneinfo import ZoneInfo

import httpx
import psycopg
import redis
from cryptography.fernet import Fernet, InvalidToken

from app.event_batcher import MemoryBatcher
from app.vector import embedding_status, text_embedding_with_provider, vector_literal
from app.worker_concurrency import DedupeLockRegistry, process_entries_with_locks


DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
MODEL_MODE = os.getenv("MODEL_MODE", "standard")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://81.70.177.246:9151/v1").rstrip("/")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.6-27b")
MODEL_ROUTER_URL = os.getenv("MODEL_ROUTER_URL", "").rstrip("/")
REDIS_START_ID = os.getenv("REDIS_START_ID", "$")
REALTIME_CHANNEL = os.getenv("REALTIME_CHANNEL", "par:realtime")
WORKER_STREAM_KEY = os.getenv("WORKER_STREAM_KEY", "events:raw")
WORKER_CHECKPOINT_KEY = os.getenv("WORKER_CHECKPOINT_KEY", "events:raw:worker:last_id")
WORKER_DEADLETTER_STREAM = os.getenv("WORKER_DEADLETTER_STREAM", "events:deadletter")
WORKER_MEMORY_BATCH_SIZE = int(os.getenv("WORKER_MEMORY_BATCH_SIZE", "20"))
WORKER_MEMORY_BATCH_MAX_AGE_SECONDS = float(os.getenv("WORKER_MEMORY_BATCH_MAX_AGE_SECONDS", "30"))
WORKER_CONCURRENCY = int(os.getenv("WORKER_CONCURRENCY", "4"))
WORKER_STREAM_READ_COUNT = int(os.getenv("WORKER_STREAM_READ_COUNT", "100"))
WORKER_STREAM_PROCESS_COUNT = int(os.getenv("WORKER_STREAM_PROCESS_COUNT", "20"))
WORKER_REMINDER_SCAN_INTERVAL_SECONDS = float(os.getenv("WORKER_REMINDER_SCAN_INTERVAL_SECONDS", "30"))
USER_TIMEZONE_NAME = os.getenv("USER_TIMEZONE", "Asia/Shanghai")
try:
    USER_TIMEZONE = ZoneInfo(USER_TIMEZONE_NAME)
except Exception:
    USER_TIMEZONE = timezone(timedelta(hours=8))

_AGENDA_SCHEMA_LOCK = threading.Lock()
_AGENDA_SCHEMA_READY = False
_RAW_DATA_FERNET: Fernet | None = None


@dataclass(frozen=True)
class StreamProcessResult:
    success: bool
    checkpoint: bool

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<![\dA-Za-z-])(?:\+?\d[\d -]{7,}\d)(?![\dA-Za-z-])")
PRESERVED_DATE_TIME_RE = re.compile(
    r"(?<!\d)20\d{2}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}(?::\d{2})?)?(?!\d)"
)
URL_QUERY_RE = re.compile(r"([?&])([^=#&]+)=([^&#]+)")
LINKEDIN_JOB_URL_RE = re.compile(
    r"https?://(?:[\w-]+\.)?linkedin\.com/jobs/(?:view/\d{6,}/?|search/\?[^\\s\"'<>，。；、]*currentJobId=\d{6,}[^\\s\"'<>，。；、]*)",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(token|secret|cookie|session|password|passwd|auth|code|验证码|校验码|verification)", re.I)
INLINE_SECRET_RE = re.compile(r"\b(token|secret|sessionid|session|password|passwd|auth|code)=([^,\s&;]+)", re.I)
OAUTH_FRAGMENT_RE = re.compile(r"([#&])(access_token|id_token|refresh_token|state|token|code)=([^&#]+)", re.I)
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)
VERIFICATION_CODE_RE = re.compile(
    r"("
    r"(?:(?:验证码|校验码)[^\dA-Za-z]{0,8}|"
    r"(?:verification\s+code|login\s+code|security\s+code|code)\b[^\dA-Za-z]{1,8})"
    r")([A-Za-z0-9-]{4,12})",
    re.I,
)
ORDER_ID_RE = re.compile(r"((?:订单号|订单|order(?: id)?)[^\dA-Za-z]{0,8})([A-Za-z0-9-]{5,24})", re.I)
ID_CARD_RE = re.compile(r"((?:身份证号?|id card)[^\dA-Za-z]{0,8})(\d{17}[\dXx])", re.I)
PASSPORT_RE = re.compile(r"((?:护照|passport)[^\dA-Za-z]{0,8})([A-Z]{1,2}\d{6,9})", re.I)
BANK_CARD_RE = re.compile(r"((?:银行卡|卡号|bank card)[^\dA-Za-z]{0,8})(\d(?:[ -]?\d){12,18})", re.I)
AMOUNT_RE = re.compile(
    r"(?<![\dA-Za-z_:.-])(?:(?:¥|￥|\$|RMB\s*)\d{1,7}(?:\.\d{1,2})?\s*(?:元|CNY|USD|美元)?|\d{1,7}(?:\.\d{1,2})?\s*(?:元|CNY|USD|美元))(?![\dA-Za-z_:.-])",
    re.I,
)
CHINESE_ADDRESS_RE = re.compile(
    r"((?:收货地址|地址)[：:\s]*)([^，。；;\\n]{6,80}(?:号|室|楼|层|单元|弄|路|街|大道|巷|村|县|区|市))"
)
ENTITY_CLEAN_RE = re.compile(r"^[\s\W_]+|[\s\W_]+$")
EXACT_TIME_RE = re.compile(
    r"\d{1,2}[:：点](?:\d{0,2}|半)|[一二三四五六七八九十两]{1,3}点(?:半)?|上午|下午|晚上|中午|早上|\b(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*(?:am|pm)\b",
    re.I,
)
ONLINE_EVENT_RE = re.compile(
    r"(zoom|google\s*meet|meet\.google|teams|microsoft\s*teams|腾讯会议|飞书会议|视频会议|电话会议|线上|在线|会议链接|webinar|https?://)",
    re.I,
)
DEADLINE_EVENT_RE = re.compile(r"(截止|到期|前|之前|以前|deadline|due|before| by )", re.I)
LOW_VALUE_PRIVATE_SIGNAL_RE = re.compile(
    r"("
    r"取消订阅|隐私\s*[·・]\s*条款|privacy\s*[·・]\s*terms|"
    r"you have \d+ new messages?|view messages?:?\s*https?://|linkedin\.com/comm/messaging|"
    r"订单支付成功|支付成功|payment successful|invoice paid|"
    r"官方安全中心|账号验证|账户验证|安全中心提醒|"
    r"验证码|verification code|login code|security code"
    r")",
    re.I,
)
TIME_OF_DAY_RE = re.compile(r"(?<![A-Za-z0-9_/-])(上午|下午|晚上|中午|早上)?\s*([0-2]?\d|[一二三四五六七八九十两]{1,3})\s*(?:点|[:：])\s*([0-5]?\d|半)?")
EN_TIME_OF_DAY_RE = re.compile(r"\b([01]?\d|2[0-3])(?::([0-5]\d))?\s*(am|pm)\b", re.I)
EXPLICIT_DATE_RE = re.compile(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?")
WEEKDAY_RE = re.compile(r"(下周)?(?:周|星期|礼拜)([一二三四五六日天])")
EN_WEEKDAY_RE = re.compile(r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
CHINESE_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
ENGLISH_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
CHINESE_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
MEETING_VERB_RE = re.compile(r"(?:见面|见一下|见|碰面|碰头|面试|开会|会议|详聊|详细聊|聊一下|聊聊|面聊|interview|meet(?:ing)?)", re.I)
MEETING_TEXT_MARKERS = ["见面", "见一下", "见吧", "吃饭", "约", "会议", "开会", "碰面", "面试", "详聊", "详细聊", "聊一下", "聊聊", "面聊", "interview", "Zoom", "zoom"]
FUZZY_TIME_MARKERS = ["周末", "下周", "周日", "周六", "改天", "找时间", "有空", "明后天", "今天", "明天", "后天", "今晚", "明晚", "上午", "下午", "晚上", "早上"]
AGENDA_MODEL_DISABLED_VALUES = {"0", "false", "off", "no", "disabled"}
AGENDA_TYPES = {"appointment", "deadline", "todo", "payment", "travel", "shopping", "followup", "reminder"}
AGENDA_OPERATIONS = {
    "create",
    "update",
    "reschedule",
    "cancel",
    "merge",
    "complete",
    "lower_confidence",
    "request_clarification",
}
AGENDA_STATUSES = {"scheduled", "open", "pending", "canceled", "completed"}
AGENDA_CERTAINTIES = {"exact", "fuzzy"}
AGENDA_MODEL_MIN_CONFIDENCE = 0.45
EVENT_LABELS = {
    "ordinary_chat",
    "todo",
    "commitment",
    "appointment",
    "reschedule",
    "cancel",
    "deadline",
    "payment",
    "travel",
    "shopping",
    "relationship_signal",
    "important_fact",
    "user_instruction",
    "preference_update",
    "user_feedback",
    "low_value",
}
EVENT_LABEL_PRIORITY = [
    "cancel",
    "reschedule",
    "payment",
    "deadline",
    "appointment",
    "travel",
    "shopping",
    "todo",
    "commitment",
    "user_instruction",
    "preference_update",
    "user_feedback",
    "relationship_signal",
    "important_fact",
    "ordinary_chat",
    "low_value",
]
LOW_VALUE_EVENT_LABELS = {"ordinary_chat", "low_value"}
EVENT_IMPORTANCE_FLOORS = {
    "appointment": 0.72,
    "reschedule": 0.78,
    "cancel": 0.76,
    "deadline": 0.72,
    "payment": 0.72,
    "todo": 0.65,
    "travel": 0.64,
    "shopping": 0.6,
    "important_fact": 0.7,
    "user_instruction": 0.68,
}


def openai_compatible_chat_url(base_url: str) -> str:
    clean = str(base_url or "").rstrip("/")
    if clean.endswith("/v1"):
        return f"{clean}/chat/completions"
    return f"{clean}/v1/chat/completions"
RULES_FIRST_EVENT_LABELS = {
    "appointment",
    "reschedule",
    "cancel",
    "deadline",
    "payment",
    "travel",
    "shopping",
    "todo",
    "important_fact",
}
LOW_VALUE_TELEMETRY_EVENT_TYPES = {
    "browser_network_event",
    "browser_focus_event",
    "browser_snapshot",
    "whatsapp_snapshot",
    "whatsapp_open_chat_snapshot",
}
INTENT_ALIASES = {
    "约定": "social_plan",
    "日程": "schedule",
    "付款": "payment_reminder",
    "待办": "task_request",
    "截止日期": "task_request",
    "出行": "travel_plan",
    "购物": "shopping_intent",
    "用户指令": "user_instruction",
    "偏好更新": "preference_update",
    "用户反馈": "user_feedback",
    "陈述事实": "conversation_memory",
    "事实陈述": "conversation_memory",
    "重要事实": "conversation_memory",
}
FAMILY_RELATION_ALIASES = {
    "儿子": ("son", "儿子"),
    "孩子": ("child", "孩子"),
    "小孩": ("child", "孩子"),
    "女儿": ("daughter", "女儿"),
    "爸爸": ("father", "父亲"),
    "父亲": ("father", "父亲"),
    "妈妈": ("mother", "母亲"),
    "母亲": ("mother", "母亲"),
    "老婆": ("wife", "妻子"),
    "妻子": ("wife", "妻子"),
    "太太": ("wife", "妻子"),
    "丈夫": ("husband", "丈夫"),
    "老公": ("husband", "丈夫"),
    "哥哥": ("elder_brother", "哥哥"),
    "姐姐": ("elder_sister", "姐姐"),
    "弟弟": ("younger_brother", "弟弟"),
    "妹妹": ("younger_sister", "妹妹"),
}
FAMILY_RELATION_FACT_RE = re.compile(
    r"(?:我|我的)\s*"
    r"(儿子|女儿|孩子|小孩|爸爸|父亲|妈妈|母亲|老婆|妻子|太太|丈夫|老公|哥哥|姐姐|弟弟|妹妹)"
    r"\s*(?:叫|名字叫|名叫|是)\s*"
    r"([\u4e00-\u9fff]{2,4}|[A-Za-z][A-Za-z .'-]{1,60})"
)
THIRD_PERSON_FAMILY_RELATION_FACT_RE = re.compile(
    r"([\u4e00-\u9fff]{2,8}?|[A-Za-z][A-Za-z .'-]{1,60})\s*"
    r"(?:他的|她的|的|他|她)?\s*"
    r"(儿子|女儿|孩子|小孩|爸爸|父亲|妈妈|母亲|老婆|妻子|太太|丈夫|老公|哥哥|姐姐|弟弟|妹妹)"
    r"\s*(?:叫|名字叫|名叫|是)\s*"
    r"([\u4e00-\u9fff]{2,4}|[A-Za-z][A-Za-z .'-]{1,60})"
)
EXTERNAL_FIRST_PERSON_SOURCES = {"whatsapp", "telegram", "gmail", "linkedin"}
SELF_MESSAGE_DIRECTIONS = {"outgoing", "outbound", "sent", "self", "me", "from_user"}
SELF_SENDER_MARKERS = {"", "我", "自己", "我自己", "本人", "user", "me", "myself", "you"}


def mask_value(value: Any) -> Any:
    if isinstance(value, str):
        preserved: dict[str, str] = {}

        def preserve_date_time(match: re.Match[str]) -> str:
            token = f"__PRESERVE_DATE_TIME_{len(preserved)}__"
            preserved[token] = match.group(0)
            return token

        value = PRESERVED_DATE_TIME_RE.sub(preserve_date_time, value)
        value = LINKEDIN_JOB_URL_RE.sub(preserve_date_time, value)
        value = EMAIL_RE.sub("EMAIL_1", value)
        value = URL_QUERY_RE.sub(r"\1\2=REDACTED", value)
        value = OAUTH_FRAGMENT_RE.sub(r"\1\2=REDACTED", value)
        value = INLINE_SECRET_RE.sub(r"\1=REDACTED", value)
        value = BEARER_RE.sub("Bearer REDACTED", value)
        value = VERIFICATION_CODE_RE.sub(r"\1CODE_1", value)
        value = ORDER_ID_RE.sub(r"\1ORDER_1", value)
        value = ID_CARD_RE.sub(r"\1ID_CARD_1", value)
        value = PASSPORT_RE.sub(r"\1PASSPORT_1", value)
        value = BANK_CARD_RE.sub(r"\1BANK_CARD_1", value)
        value = CHINESE_ADDRESS_RE.sub(r"\1ADDRESS_1", value)
        value = PHONE_RE.sub("PHONE_1", value)
        value = AMOUNT_RE.sub("AMOUNT_1", value)
        for token, original in preserved.items():
            value = value.replace(token, original)
        return value
    if isinstance(value, dict):
        masked = {}
        for key, inner in value.items():
            if SENSITIVE_KEY_RE.search(str(key)) and not isinstance(inner, (dict, list)):
                masked[key] = "REDACTED"
            else:
                masked[key] = mask_value(inner)
        return masked
    if isinstance(value, list):
        return [mask_value(item) for item in value]
    return value


def normalize_entity_name(name: str) -> str:
    cleaned = ENTITY_CLEAN_RE.sub("", str(name).strip().lower())
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:180] or "unknown"


def agenda_semantic_text_hash(text: str) -> str:
    normalized = normalize_support_text(text)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def raw_data_fernet() -> Fernet:
    global _RAW_DATA_FERNET
    if _RAW_DATA_FERNET is None:
        secret = os.getenv("RAW_DATA_ENCRYPTION_KEY") or os.getenv("APP_PASSWORD") or "par-dev-local-raw-data"
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        _RAW_DATA_FERNET = Fernet(key)
    return _RAW_DATA_FERNET


def decrypt_private_raw_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    if value.get("format") != "fernet-json-v1" or not value.get("ciphertext"):
        return value
    try:
        plaintext = raw_data_fernet().decrypt(str(value["ciphertext"]).encode("utf-8"))
        decoded = json.loads(plaintext.decode("utf-8"))
    except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def compute_importance(source: str, event_type: str, raw_data: dict[str, Any], base: float = 0.2) -> float:
    score = base
    if source in {"gmail", "calendar", "whatsapp", "telegram"}:
        score += 0.15
    if event_type in {"calendar_event", "gmail_thread_snapshot", "whatsapp_message", "telegram_message_preview"}:
        score += 0.15
    focus_score = raw_data.get("focus_score")
    if isinstance(focus_score, (int, float)):
        score += min(max(float(focus_score), 0), 1) * 0.35
    signals = raw_data.get("signals") if isinstance(raw_data.get("signals"), dict) else {}
    user_action_points = min(int(signals.get("input") or 0), 3) * 0.05 + min(int(signals.get("copy") or 0), 2) * 0.05
    score += user_action_points
    relationship_weight = raw_data.get("relationship_weight")
    if isinstance(relationship_weight, (int, float)):
        score += min(max(float(relationship_weight), 0), 1) * 0.15
    repeat_frequency = raw_data.get("repeat_frequency")
    if isinstance(repeat_frequency, (int, float)):
        score += min(max(float(repeat_frequency), 0), 5) * 0.03
    return round(min(max(score, 0), 1), 3)


def dialogue_batch_turns(raw_data: dict[str, Any], max_turns: int = 30) -> list[dict[str, Any]]:
    turns = raw_data.get("turns")
    if not isinstance(turns, list):
        return []
    normalized: list[dict[str, Any]] = []
    for turn in turns[:max_turns]:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip() or "unknown"
        content = str(turn.get("content") or turn.get("message") or turn.get("text") or "").strip()
        if not content:
            continue
        normalized.append(
            {
                "role": role,
                "content": content[:500],
                "created_at": str(turn.get("created_at") or turn.get("timestamp") or "").strip(),
                "event_id": str(turn.get("event_id") or "").strip(),
                "turn_id": str(turn.get("turn_id") or "").strip(),
            }
        )
    return normalized


def dialogue_batch_text(raw_data: dict[str, Any], max_chars: int = 6000) -> str:
    lines = []
    for turn in dialogue_batch_turns(raw_data):
        prefix = turn["role"]
        created_at = f" ({turn['created_at']})" if turn.get("created_at") else ""
        lines.append(f"{prefix}: {turn['content']}{created_at}")
    return "\n".join(lines)[:max_chars]


def summarize_dialogue_batch(raw_data: dict[str, Any]) -> str:
    turns = dialogue_batch_turns(raw_data)
    user_contents = [turn["content"] for turn in turns if turn["role"] == "user"]
    assistant_contents = [turn["content"] for turn in turns if turn["role"] == "assistant"]
    if not turns:
        return "Nomi 对话批次为空。"
    first_user = user_contents[0] if user_contents else turns[0]["content"]
    last_user = user_contents[-1] if user_contents else turns[-1]["content"]
    last_assistant = assistant_contents[-1] if assistant_contents else ""
    if first_user == last_user:
        core = first_user
    else:
        core = f"{first_user}；后续用户又提到：{last_user}"
    if last_assistant:
        return f"Nomi 对话批次摘要：用户关注「{core}」；最后回复为「{last_assistant}」。"[:500]
    return f"Nomi 对话批次摘要：用户关注「{core}」。"[:500]


def rule_extract_nomi_chat_semantics(event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
    if event_type == "dialogue_batch":
        turns = dialogue_batch_turns(raw_data)
        text = dialogue_batch_text(raw_data)
        user_turns = [turn for turn in turns if turn["role"] == "user"]
        assistant_turns = [turn for turn in turns if turn["role"] == "assistant"]
        round_count = raw_data.get("round_count")
        if not isinstance(round_count, int):
            round_count = min(len(user_turns), len(assistant_turns))
        return {
            "intent": "dialogue_batch_summary",
            "entities": {
                "source": "nomi_chat",
                "event_type": event_type,
                "person": "conversation",
                "role": "batch",
                "text": text,
                "conversation_id": raw_data.get("conversation_id"),
                "turn_count": len(turns),
                "round_count": round_count,
                "user_turn_count": len(user_turns),
                "assistant_turn_count": len(assistant_turns),
                "batch_id": raw_data.get("batch_id"),
                "batch_reason": raw_data.get("batch_reason"),
            },
            "importance": 0.62 if turns else 0.25,
            "summary": summarize_dialogue_batch(raw_data),
            "model_version": f"{MODEL_MODE}:nomi-chat-dialogue-batch-rules-v0",
        }

    role = str(raw_data.get("role") or "user").strip()
    text = str(raw_data.get("content") or raw_data.get("message") or raw_data.get("text") or "").strip()
    lowered = text.lower()
    intent = "conversation_memory"
    importance = 0.5 if role == "user" else 0.34
    if role == "user" and any(marker in text for marker in ["别提醒", "不用提醒", "忽略", "不重要", "以后别"]):
        intent = "user_feedback"
        importance = 0.84
    elif role == "user" and any(marker in text for marker in ["以后", "喜欢", "偏好", "记住", "习惯"]):
        intent = "preference_update"
        importance = 0.78
    elif role == "user" and any(marker in text for marker in ["帮我", "提醒", "盯一下", "安排", "查", "找", "处理"]):
        intent = "user_instruction"
        importance = 0.76
    elif role == "assistant":
        intent = "assistant_response"
    return {
        "intent": intent,
        "entities": {
            "source": "nomi_chat",
            "event_type": event_type,
            "person": role,
            "role": role,
            "text": text,
            "conversation_id": raw_data.get("conversation_id"),
            "client_type": raw_data.get("client_type"),
            "contains_negative_feedback": any(marker in text or marker in lowered for marker in ["别提醒", "不用提醒", "ignore"]),
        },
        "importance": importance,
        "summary": f"{role} said to Nomi: {text}"[:500],
        "model_version": f"{MODEL_MODE}:nomi-chat-rules-v0",
    }


def first_person_subject_for_event(source: str, raw_data: dict[str, Any]) -> tuple[str, str]:
    direction = str(
        raw_data.get("message_direction")
        or raw_data.get("direction")
        or raw_data.get("messageDirection")
        or ""
    ).strip().lower()
    if direction in SELF_MESSAGE_DIRECTIONS:
        return "user", "user"
    sender = str(
        raw_data.get("sender")
        or raw_data.get("speaker")
        or raw_data.get("from_name")
        or raw_data.get("from")
        or raw_data.get("author")
        or ""
    ).strip()
    if source in EXTERNAL_FIRST_PERSON_SOURCES and sender and normalize_entity_name(sender) not in SELF_SENDER_MARKERS:
        return sender, sender
    return "user", "user"


def clean_family_relation_name(value: str) -> str:
    name = re.sub(r"[，。！？；;,.!?].*$", "", str(value or "").strip())
    return re.sub(r"\s+", " ", name).strip()


def extract_family_relation_fact(text: str, *, subject: str = "user", person: str = "user") -> dict[str, str] | None:
    content = str(text or "")
    match = FAMILY_RELATION_FACT_RE.search(content)
    if match:
        raw_relation = match.group(1)
        name = clean_family_relation_name(match.group(2))
        if not name:
            return None
        return {
            "subject": subject or "user",
            "person": person or subject or "user",
            "source_speaker": person or subject or "user",
            "relation": FAMILY_RELATION_ALIASES.get(raw_relation, (raw_relation, raw_relation))[0],
            "relation_label": FAMILY_RELATION_ALIASES.get(raw_relation, (raw_relation, raw_relation))[1],
            "predicate": f"{FAMILY_RELATION_ALIASES.get(raw_relation, (raw_relation, raw_relation))[0]}_name",
            "object": name,
            "reference_scope": "first_person",
        }

    match = THIRD_PERSON_FAMILY_RELATION_FACT_RE.search(content)
    if not match:
        return None
    owner = clean_family_relation_name(match.group(1))
    raw_relation = match.group(2)
    name = clean_family_relation_name(match.group(3))
    if not owner or not name:
        return None
    relation, relation_label = FAMILY_RELATION_ALIASES.get(raw_relation, (raw_relation, raw_relation))
    return {
        "subject": owner,
        "person": owner,
        "source_speaker": person or subject or "user",
        "relation": relation,
        "relation_label": relation_label,
        "predicate": f"{relation}_name",
        "object": name,
        "reference_scope": "third_person",
    }


def rule_extract_semantics(source: str, event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
    if source == "nomi_chat":
        return rule_extract_nomi_chat_semantics(event_type, raw_data)

    if source == "longmemeval_conversation" and event_type == "conversation_turn":
        speaker = str(raw_data.get("speaker") or raw_data.get("role") or "unknown").strip()
        text = str(raw_data.get("text") or raw_data.get("content") or "").strip()
        return {
            "intent": "conversation_memory",
            "entities": {
                "source": source,
                "event_type": event_type,
                "person": speaker,
                "text": text,
                "question_id": raw_data.get("question_id"),
                "session_id": raw_data.get("session_id"),
                "message_index": raw_data.get("message_index"),
            },
            "importance": 0.6 if speaker == "user" else 0.42,
            "summary": f"{speaker} said: {text}"[:500],
            "model_version": f"{MODEL_MODE}:longmemeval-rules-v0",
        }

    if source == "locomo_conversation" and event_type == "conversation_turn":
        speaker = str(raw_data.get("speaker") or "unknown").strip()
        text = str(raw_data.get("text") or "").strip()
        return {
            "intent": "conversation_memory",
            "entities": {
                "source": source,
                "event_type": event_type,
                "person": speaker,
                "text": text,
                "session": raw_data.get("session"),
                "sample_index": raw_data.get("sample_index"),
            },
            "importance": 0.58 if len(text) < 80 else 0.68,
            "summary": f"{speaker} said: {text}"[:500],
            "model_version": f"{MODEL_MODE}:conversation-rules-v0",
        }

    if source == "locomo_seed" and event_type == "long_term_memory_qa":
        question = str(raw_data.get("question") or "").strip()
        answer = str(raw_data.get("answer") or "").strip()
        category = raw_data.get("category")
        summary = f"长期记忆测试事实：问题「{question}」的答案是「{answer}」。"
        return {
            "intent": "long_term_memory_fact",
            "entities": {
                "source": source,
                "event_type": event_type,
                "question": question,
                "answer": answer,
                "category": category,
                "sample_index": raw_data.get("sample_index"),
                "evidence": raw_data.get("evidence", []),
            },
            "importance": 0.78,
            "summary": summary[:500],
            "model_version": f"{MODEL_MODE}:locomo-rules-v0",
        }

    text = json.dumps(raw_data, ensure_ascii=False)
    lowered = text.lower()
    intent = "generic_event"
    importance = 0.2

    if event_type == "search":
        intent = "research_interest"
        importance = compute_importance(source, event_type, raw_data, base=0.45)
    if source == "focus" and event_type == "deep_focus":
        intent = "focused_attention"
        importance = compute_importance(source, event_type, raw_data, base=0.35)
    if "吃饭" in text or "dinner" in lowered or "lunch" in lowered:
        intent = "social_plan"
        importance = max(importance, 0.75)
    if source in {"gmail", "calendar"}:
        importance = max(importance, compute_importance(source, event_type, raw_data, base=0.4))
    if event_type == "calendar_event":
        intent = "schedule"
        importance = max(importance, compute_importance(source, event_type, raw_data, base=0.6))

    entities = {
        "source": source,
        "event_type": event_type,
        "keywords": [word for word in ["Tokyo", "东京", "Alex", "hotel", "酒店"] if word in text],
    }
    if source == "gmail" and raw_data.get("body"):
        subject = str(raw_data.get("subject") or "").strip()
        body = str(raw_data.get("body") or "").strip()
        summary = f"{subject}：{body}" if subject else body
    else:
        summary = readable_raw_text(raw_data) or text[:180]
    first_person_subject, first_person_person = first_person_subject_for_event(source, raw_data)
    family_fact = extract_family_relation_fact(
        str(summary),
        subject=first_person_subject,
        person=first_person_person,
    )
    if family_fact:
        subject_label = "用户" if family_fact["subject"] == "user" else family_fact["subject"]
        source_speaker = family_fact.get("source_speaker") or first_person_person
        entities.update(
            {
                "subject": family_fact["subject"],
                "predicate": family_fact["predicate"],
                "object": family_fact["object"],
                "family_relation": family_fact["relation"],
                "family_relation_label": family_fact["relation_label"],
                "person": family_fact["person"],
                "speaker": source_speaker,
                "source_speaker": source_speaker,
                "related_person": family_fact["object"],
                "reference_scope": family_fact.get("reference_scope", "first_person"),
                "text": str(summary)[:500],
            }
        )
        return {
            "intent": "conversation_memory",
            "entities": entities,
            "importance": 0.82,
            "summary": f"{subject_label}的{family_fact['relation_label']}叫{family_fact['object']}。",
            "model_version": f"{MODEL_MODE}:family-relation-rules-v0",
        }
    return {
        "intent": intent,
        "entities": entities,
        "importance": importance,
        "summary": str(summary)[:500],
        "model_version": f"{MODEL_MODE}:rules-v0",
    }


def readable_raw_text(raw_data: dict[str, Any]) -> str:
    if isinstance(raw_data.get("turns"), list):
        return dialogue_batch_text(raw_data)
    for key in ("message", "text", "content", "body", "query", "subject", "title", "snippet", "description"):
        value = raw_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def event_label_text(raw_data: dict[str, Any], semantic: dict[str, Any]) -> str:
    pieces = [
        semantic.get("intent"),
        semantic.get("summary"),
        raw_data.get("message"),
        raw_data.get("body"),
        raw_data.get("text"),
        raw_data.get("content"),
        raw_data.get("subject"),
        raw_data.get("title"),
        raw_data.get("query"),
    ]
    return "\n".join(str(piece) for piece in pieces if piece)


def is_low_value_private_signal(source: str, event_type: str, raw_data: dict[str, Any], semantic: dict[str, Any]) -> bool:
    normalized_source = str(source or "").strip().lower()
    normalized_event_type = str(event_type or "").strip().lower()
    if normalized_source not in {"gmail", "telegram", "linkedin"}:
        return False
    text = event_label_text(raw_data, semantic)
    if normalized_source == "gmail":
        sender_text = " ".join(
            str(raw_data.get(key) or "")
            for key in ("from", "sender", "sender_name", "author", "subject")
        )
        entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
        sender_text = f"{sender_text} {entities.get('sender') or ''}"
        if "linkedin" in sender_text.lower() and re.search(r"\byou have \d+ new messages?\b", text, re.I):
            return True
    if normalized_event_type.endswith("snapshot") and LOW_VALUE_PRIVATE_SIGNAL_RE.search(text):
        return True
    return bool(LOW_VALUE_PRIVATE_SIGNAL_RE.search(text) and normalized_source in {"gmail", "linkedin"})


def has_exact_agenda_time(text: str) -> bool:
    return bool(TIME_OF_DAY_RE.search(text) or EN_TIME_OF_DAY_RE.search(text))


def has_calendar_time_reference(text: str) -> bool:
    return bool(
        has_exact_agenda_time(text)
        or EXPLICIT_DATE_RE.search(text)
        or WEEKDAY_RE.search(text)
        or EN_WEEKDAY_RE.search(text)
        or any(marker in text for marker in FUZZY_TIME_MARKERS)
    )


def has_fuzzy_agenda_time(text: str) -> bool:
    return not has_exact_agenda_time(text) and any(marker in text for marker in FUZZY_TIME_MARKERS)


def has_meeting_text_signal(text: str) -> bool:
    return bool(MEETING_VERB_RE.search(text) or any(marker in text for marker in MEETING_TEXT_MARKERS))


def rule_event_labels(source: str, event_type: str, raw_data: dict[str, Any], semantic: dict[str, Any]) -> list[str]:
    text = event_label_text(raw_data, semantic)
    lowered = text.lower()
    intent = str(semantic.get("intent") or "")
    semantic_entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    labels: list[str] = []

    def add(label: str) -> None:
        if label in EVENT_LABELS and label not in labels:
            labels.append(label)

    if event_type in LOW_VALUE_TELEMETRY_EVENT_TYPES:
        add("low_value")
        return labels
    if is_non_agenda_browser_observation(semantic, raw_data):
        add("low_value")
        return labels
    if is_low_value_private_signal(source, event_type, raw_data, semantic):
        add("low_value")
        return labels

    negates_meeting = any(marker in text for marker in ["不是开会", "不是会议", "不是见面", "不见面了", "不见面", "不用见面", "不用见", "别见面"])
    if any(marker in text for marker in ["取消", "不去了", "不用去了", "不见面了", "不见面", "不用见面", "不用见", "别见面"]) or any(marker in lowered for marker in ["cancel", "canceled", "cancelled"]):
        add("cancel")
    if any(marker in text for marker in ["改到", "改成", "换到", "推迟", "提前", "改电话聊", "电话聊"]) or "reschedule" in lowered:
        add("reschedule")
    has_calendar_time = has_calendar_time_reference(text)
    has_meeting_signal = has_meeting_text_signal(text)
    if (
        (intent in {"social_plan", "schedule"} and not negates_meeting)
        or (not negates_meeting and any(marker in text for marker in MEETING_TEXT_MARKERS))
        or (not negates_meeting and has_meeting_signal and has_calendar_time)
    ):
        add("appointment")
    if any(marker in text for marker in ["路线", "打车", "导航", "机场", "酒店", "高铁", "航班", "出发", "到达"]):
        add("travel")
    if intent in {"payment_reminder"} or any(marker in text for marker in ["付款", "支付", "账单", "发票", "还款", "报销"]):
        add("payment")
    deadline_before_phrase = bool(
        re.search(r"(?:今天|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])?.{0,8}(?:[0-2]?\d|[一二三四五六七八九十两]{1,3})(?:点|[:：])(?:[0-5]?\d|半)?\s*(?:前|之前|以前)", text)
    )
    if any(marker in text for marker in ["截止", "到期"]) or deadline_before_phrase or any(marker in lowered for marker in ["deadline", "due", "before ", " by "]):
        add("deadline")
    if intent in {"task_request", "user_instruction"} or any(marker in text for marker in ["待办", "帮我", "提醒", "处理", "盯一下", "记得", "别忘了", "发我", "核对", "确认"]):
        add("todo")
    if any(marker in text for marker in ["我会", "我来", "答应", "承诺", "promise"]):
        add("commitment")
    if any(marker in text for marker in ["买", "下单", "购物", "快递", "包裹", "订单", "退货"]):
        add("shopping")
    if intent == "preference_update":
        add("preference_update")
    if intent == "user_feedback":
        add("user_feedback")
    if intent == "user_instruction":
        add("user_instruction")
    if semantic_entities.get("family_relation"):
        add("relationship_signal")
        add("important_fact")
    if any(marker in text for marker in ["喜欢", "讨厌", "不信任", "关系", "生日", "家人", "朋友", "儿子", "女儿", "孩子", "父亲", "母亲", "爸爸", "妈妈", "老婆", "丈夫"]):
        add("relationship_signal")
    if any(marker in text for marker in ["请记住", "帮我记住", "记住：", "记住:", "暗号是", "测试暗号"]):
        add("important_fact")
    if intent in {"long_term_memory_fact", "conversation_memory", "research_interest", "focused_attention"}:
        add("important_fact")
    if not labels:
        add("ordinary_chat" if source in {"whatsapp", "telegram", "nomi_chat", "longmemeval_conversation", "locomo_conversation"} else "low_value")
    return labels


def primary_event_label(labels: list[str]) -> str:
    label_set = set(labels)
    for label in EVENT_LABEL_PRIORITY:
        if label in label_set:
            return label
    return labels[0] if labels else "low_value"


def intent_for_primary_label(primary_label: str, current_intent: str) -> str:
    normalized_intent = INTENT_ALIASES.get(str(current_intent or "").strip(), current_intent)
    if normalized_intent and normalized_intent != "generic_event":
        return normalized_intent
    return {
        "payment": "payment_reminder",
        "appointment": "social_plan",
        "deadline": "task_request",
        "todo": "task_request",
        "travel": "travel_plan",
        "shopping": "shopping_intent",
        "cancel": "schedule",
        "reschedule": "schedule",
        "important_fact": "conversation_memory",
    }.get(primary_label, normalized_intent or "generic_event")


def enrich_semantic_classification(
    source: str,
    event_type: str,
    raw_data: dict[str, Any],
    semantic: dict[str, Any],
    model_entities: Optional[dict[str, Any]] = None,
    parser_mode: str = "rules_only",
    validation_warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    entities = dict(semantic.get("entities") or {})
    rule_labels = rule_event_labels(source, event_type, raw_data, semantic)
    model_labels = normalize_string_list((model_entities or entities).get("labels"))
    model_labels = [label for label in model_labels if label in EVENT_LABELS]
    warnings = list(validation_warnings or [])

    substantive_rule_labels = [label for label in rule_labels if label not in LOW_VALUE_EVENT_LABELS]
    labels = list(rule_labels)
    if substantive_rule_labels:
        if set(model_labels).issubset(LOW_VALUE_EVENT_LABELS):
            warnings.append("rule_overrode_low_value_model_label")
        labels.extend(label for label in model_labels if label not in LOW_VALUE_EVENT_LABELS)
    else:
        labels = model_labels or rule_labels
    labels = list(dict.fromkeys(label for label in labels if label in EVENT_LABELS))
    if any(label not in LOW_VALUE_EVENT_LABELS for label in labels):
        labels = [label for label in labels if label not in LOW_VALUE_EVENT_LABELS]
    if entities.get("family_relation") and "important_fact" in labels:
        primary_label = "important_fact"
    else:
        primary_label = primary_event_label(labels)

    entities["labels"] = labels
    entities["primary_label"] = primary_label
    entities["classification_trace"] = {
        "parser_mode": parser_mode,
        "rule_labels": rule_labels,
        "model_labels": model_labels,
        "validation_warnings": list(dict.fromkeys(warnings)),
    }
    semantic["entities"] = entities
    semantic["intent"] = intent_for_primary_label(primary_label, str(semantic.get("intent") or ""))
    importance_floor = EVENT_IMPORTANCE_FLOORS.get(primary_label)
    if importance_floor is not None:
        try:
            current_importance = float(semantic.get("importance") or 0)
        except (TypeError, ValueError):
            current_importance = 0
        semantic["importance"] = round(max(current_importance, importance_floor), 3)
    return semantic


def call_model(messages: list[dict[str, str]]) -> str:
    router_url = os.getenv("MODEL_ROUTER_URL", MODEL_ROUTER_URL).rstrip("/")
    if router_url:
        response = httpx.post(
            f"{router_url}/model/route",
            json={
                "task": "semantic_extraction",
                "messages": messages,
                "temperature": 0.1,
                "stream": False,
                "reasoning_effort": "none",
                "enable_thinking": False,
            },
            timeout=worker_online_model_timeout_seconds(),
        )
        response.raise_for_status()
        data = response.json()
        if "content" in data:
            return str(data["content"])
        return str(data)

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.1,
        "reasoning_effort": "none",
        "enable_thinking": False,
        "stream": False,
    }
    response = httpx.post(
        openai_compatible_chat_url(MODEL_BASE_URL),
        json=payload,
        timeout=worker_online_model_timeout_seconds(),
    )
    response.raise_for_status()
    data = response.json()
    if "choices" in data:
        return str(data["choices"][0]["message"]["content"])
    if "response" in data:
        return str(data["response"])
    if "text" in data:
        return str(data["text"])
    return str(data)


def parse_model_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if "```" in text:
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start : end + 1]
    return json.loads(text)


def worker_online_model_timeout_seconds() -> float:
    raw = os.getenv("WORKER_ONLINE_MODEL_TIMEOUT_SECONDS", "8")
    try:
        value = float(raw)
    except ValueError:
        value = 8.0
    return min(max(value, 1.0), 15.0)


def worker_rules_first_enabled() -> bool:
    return os.getenv("WORKER_RULES_FIRST_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no", "disabled"}


def rules_first_confident(semantic: dict[str, Any], raw_data: dict[str, Any]) -> bool:
    if not worker_rules_first_enabled():
        return False
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    labels = entities.get("labels") if isinstance(entities.get("labels"), list) else []
    primary = str(entities.get("primary_label") or "")
    label_set = {str(label) for label in labels}
    if primary:
        label_set.add(primary)
    if not label_set.intersection(RULES_FIRST_EVENT_LABELS):
        return False
    text = " ".join(
        str(value or "")
        for value in [
            raw_data.get("text"),
            raw_data.get("content"),
            raw_data.get("subject"),
            raw_data.get("snippet"),
            semantic.get("summary"),
        ]
    )
    return bool(
        has_exact_agenda_time(text)
        or EXPLICIT_DATE_RE.search(text)
        or WEEKDAY_RE.search(text)
        or EN_WEEKDAY_RE.search(text)
        or any(marker in text for marker in ["今天", "明天", "后天", "截止", "取消", "改到", "付款", "支付", "打车", "导航", "购买", "下单", "记住", "暗号"])
    )


def extract_semantics(source: str, event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
    start_ms = time.perf_counter() * 1000.0
    rule_start_ms = time.perf_counter() * 1000.0
    fallback = rule_extract_semantics(source, event_type, raw_data)
    fallback["raw_data"] = raw_data
    fallback_parser_mode = "rules_only_telemetry" if event_type in LOW_VALUE_TELEMETRY_EVENT_TYPES else "rules_only"
    fallback = enrich_semantic_classification(source, event_type, raw_data, fallback, parser_mode=fallback_parser_mode)
    rule_ms = max(0, int(time.perf_counter() * 1000.0 - rule_start_ms))
    model_ms = 0

    def with_latency(semantic: dict[str, Any]) -> dict[str, Any]:
        entities = semantic.setdefault("entities", {})
        trace = entities.setdefault("classification_trace", {})
        trace["latency_trace"] = {
            "total_ms": max(0, int(time.perf_counter() * 1000.0 - start_ms)),
            "rule_ms": rule_ms,
            "model_ms": model_ms,
        }
        return semantic

    if event_type in LOW_VALUE_TELEMETRY_EVENT_TYPES:
        return with_latency(fallback)
    if is_non_agenda_browser_observation(fallback, raw_data):
        fallback = enrich_semantic_classification(
            source,
            event_type,
            raw_data,
            fallback,
            parser_mode="rules_only_browser_observation",
        )
        return with_latency(fallback)
    if is_low_value_private_signal(source, event_type, raw_data, fallback):
        fallback = enrich_semantic_classification(
            source,
            event_type,
            raw_data,
            fallback,
            parser_mode="rules_only_low_value_private_signal",
        )
        return with_latency(fallback)
    if source == "nomi_chat" and event_type == "dialogue_batch":
        return with_latency(fallback)
    if source in {"locomo_seed", "locomo_conversation", "longmemeval_conversation"}:
        return with_latency(fallback)
    if rules_first_confident(fallback, raw_data):
        fallback = enrich_semantic_classification(source, event_type, raw_data, fallback, parser_mode="rules_first")
        return with_latency(fallback)
    prompt = {
        "source": source,
        "event_type": event_type,
        "raw_data": raw_data,
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是个人语义事件抽取器。只输出 JSON，不要解释。"
                "字段必须包含 intent, entities, importance, summary。"
                "importance 是 0 到 1 的数字。entities 是对象。summary 用中文一句话概括。"
                "entities 可包含 labels 和 primary_label；labels 只能来自普通聊天、待办、约定、改期、取消、截止日期、付款、出行、购物、关系信号、重要事实、用户指令、偏好更新、用户反馈、低价值这些类别。"
                "不要把模糊时间或地点补成精确信息。"
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    try:
        model_start_ms = time.perf_counter() * 1000.0
        parsed = parse_model_json(call_model(messages))
        model_ms = max(0, int(time.perf_counter() * 1000.0 - model_start_ms))
        model_entities = parsed.get("entities") if isinstance(parsed.get("entities"), dict) else {}
        merged_entities = dict(fallback.get("entities") or {})
        merged_entities.update(model_entities)
        semantic = {
            "intent": str(parsed.get("intent") or fallback["intent"])[:120],
            "entities": merged_entities,
            "importance": float(parsed.get("importance", fallback["importance"])),
            "summary": str(parsed.get("summary") or fallback["summary"])[:500],
            "model_version": f"{MODEL_MODE}:{MODEL_NAME}",
            "raw_data": raw_data,
        }
        semantic = enrich_semantic_classification(
            source,
            event_type,
            raw_data,
            semantic,
            model_entities=model_entities,
            parser_mode="hybrid_model_rules",
        )
        warnings = semantic["entities"].get("classification_trace", {}).get("validation_warnings", [])
        if "rule_overrode_low_value_model_label" in warnings:
            semantic["summary"] = fallback["summary"]
            semantic["importance"] = max(float(semantic.get("importance") or 0), float(fallback.get("importance") or 0))
        return with_latency(semantic)
    except Exception:
        if "model_start_ms" in locals():
            model_ms = max(0, int(time.perf_counter() * 1000.0 - model_start_ms))
        return with_latency(enrich_semantic_classification(
            source,
            event_type,
            raw_data,
            fallback,
            parser_mode="rules_fallback",
            validation_warnings=["model_semantic_parse_failed"],
        ))


def summary_has_actionable_place(summary: str) -> bool:
    return bool(extract_place(str(summary or ""), {}) or re.search(r"(?:street|road|station|airport|hotel|plaza|square)\b", str(summary or ""), re.I))


def clarification_actions_for_fuzzy_plan() -> list[dict[str, Any]]:
    return [
        {
            "id": "clarify_time_place",
            "label": "补充时间地点",
            "kind": "clarification",
            "risk": "local_only",
            "requires_confirmation": False,
            "next_step": "ask_for_time_place",
        },
        {
            "id": "snooze",
            "label": "稍后提醒",
            "kind": "local",
            "risk": "local_only",
            "requires_confirmation": False,
            "next_step": "snooze_suggestion",
        },
        {
            "id": "open_source",
            "label": "查看原消息",
            "kind": "source_review",
            "risk": "read_only",
            "requires_confirmation": False,
            "next_step": "open_source_event",
        },
    ]


def suggestion_actions_for_event(intent: str, source: str, suggestion_type: str, summary: str) -> list[dict[str, Any]]:
    normalized_intent = INTENT_ALIASES.get(str(intent or "").strip(), intent)
    text = f"{normalized_intent} {intent} {source} {suggestion_type} {summary}".lower()
    if intent in {"cancel", "canceled", "cancelled", "取消"} or any(
        marker in text for marker in ["取消", "不去了", "不用去了", "cancel", "canceled", "cancelled"]
    ):
        return [
            {
                "id": "snooze",
                "label": "稍后提醒",
                "kind": "local",
                "risk": "local_only",
                "requires_confirmation": False,
                "next_step": "snooze_suggestion",
            },
            {
                "id": "open_source",
                "label": "查看原消息",
                "kind": "source_review",
                "risk": "read_only",
                "requires_confirmation": False,
                "next_step": "open_source_event",
            },
        ]
    if normalized_intent in {"social_plan", "schedule", "travel_plan"} or suggestion_type in {"social_followup", "calendar_reminder"} or any(
        marker in text for marker in ["见面", "路线", "street", "road"]
    ):
        if not summary_has_actionable_place(summary):
            return clarification_actions_for_fuzzy_plan()
        return [
            {
                "id": "route_lookup",
                "label": "查路线",
                "kind": "tool_intent",
                "risk": "read_only",
                "requires_confirmation": False,
                "next_step": "route_lookup",
            },
            {
                "id": "ride_prepare",
                "label": "帮我打车",
                "kind": "tool_intent",
                "risk": "external_execution",
                "requires_confirmation": True,
                "next_step": "prepare_ride_request",
            },
            {
                "id": "snooze",
                "label": "稍后提醒",
                "kind": "local",
                "risk": "local_only",
                "requires_confirmation": False,
                "next_step": "snooze_suggestion",
            },
        ]
    if source == "gmail" or normalized_intent in {"payment_reminder", "email_verification", "task_request"}:
        return [
            {
                "id": "add_reminder",
                "label": "稍后提醒",
                "kind": "local",
                "risk": "local_only",
                "requires_confirmation": False,
                "next_step": "create_local_reminder",
            },
            {
                "id": "open_source",
                "label": "查看原邮件",
                "kind": "source_review",
                "risk": "read_only",
                "requires_confirmation": False,
                "next_step": "open_source_event",
            },
        ]
    return [
        {
            "id": "snooze",
            "label": "稍后提醒",
            "kind": "local",
            "risk": "local_only",
            "requires_confirmation": False,
            "next_step": "snooze_suggestion",
        },
        {
            "id": "dismiss",
            "label": "忽略",
            "kind": "feedback",
            "risk": "local_only",
            "requires_confirmation": False,
            "next_step": "dismiss_suggestion",
        },
    ]


def suggestion_for_event(event_id: str, semantic: dict[str, Any]) -> Optional[dict[str, Any]]:
    summary = semantic_display_summary(semantic) or str(semantic["summary"]).strip()
    display_summary = summary.rstrip("。.!！?？")
    importance = float(semantic["importance"])
    raw_intent = str(semantic["intent"])
    intent = INTENT_ALIASES.get(raw_intent.strip(), raw_intent)
    entities = semantic.get("entities", {})
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    if is_non_agenda_browser_observation(semantic, raw_data):
        return None
    if is_low_value_telemetry_semantic(semantic, raw_data):
        return None
    source = str(entities.get("source") or "")
    event_type = str(entities.get("event_type") or raw_data.get("event_type") or "")
    normalized_source = source.strip().lower()
    normalized_event_type = event_type.strip().lower()
    if normalized_source == "nomi_chat":
        return None
    if normalized_source in {"whatsapp", "telegram"} and normalized_event_type.endswith("snapshot"):
        if re.fullmatch(r"\(\d+\)\s*(whatsapp|telegram)\s*", display_summary, re.I):
            return None
    labels = set(normalize_string_list(entities.get("labels")))
    primary_label = str(entities.get("primary_label") or "").strip()
    if primary_label:
        labels.add(primary_label)
    if "low_value" in labels:
        return None
    is_appointment_like = intent in {"social_plan", "schedule"} or "appointment" in labels or "travel" in labels
    is_cancel_like = intent in {"cancel", "canceled", "cancelled", "取消"} or "cancel" in labels
    if importance < 0.55 and intent not in {"social_plan", "schedule", "research_interest"} and not is_appointment_like:
        return None

    suggestion_type = "attention"
    confidence = min(max(importance, 0), 1)
    expires_in = timedelta(days=7)
    if is_cancel_like:
        suggestion_type = "calendar_cancellation"
        title = "确认取消安排"
        body = f"这条信息是在取消或停止安排：{display_summary}。"
        expires_in = timedelta(days=2)
    elif intent == "research_interest":
        suggestion_type = "research_followup"
        title = "继续整理搜索结果"
        body = f"你最近关注了：{display_summary}。可以让我帮你汇总资料、比较选项或列下一步。"
        expires_in = timedelta(days=14)
    elif source == "gmail" or intent in {"payment_reminder", "email_verification", "task_request"}:
        suggestion_type = "email_todo"
        title = "处理邮件待办"
        body = f"这封邮件可能需要处理：{display_summary}。"
        expires_in = timedelta(days=3)
    elif intent == "schedule" or source == "calendar":
        suggestion_type = "calendar_reminder"
        title = "跟进日程安排"
        body = f"这条信息可能需要跟进：{display_summary}。"
        expires_in = timedelta(days=2)
    elif intent == "social_plan" or is_appointment_like:
        suggestion_type = "social_followup"
        title = "跟进近期安排"
        body = f"这条信息可能需要跟进：{display_summary}。"
    else:
        title = "可能值得关注"
        body = summary
    dedupe_summary = re.sub(r"\s+", " ", summary)[:120]
    dedupe_key = f"{suggestion_type}:{source or 'unknown'}:{intent}:{dedupe_summary}"
    expires_at = (datetime.now(timezone.utc) + expires_in).isoformat()
    return {
        "source_event_id": event_id,
        "title": title[:120],
        "body": body[:500],
        "priority": min(max(importance, 0), 1),
        "metadata": {
            "intent": intent,
            "source": source or "unknown",
            "event_type": str(entities.get("event_type") or ""),
            "entities": entities,
            "suggestion_type": suggestion_type,
            "confidence": round(confidence, 3),
            "dedupe_key": dedupe_key,
            "expires_at": expires_at,
            "actions": suggestion_actions_for_event(intent, source, suggestion_type, summary),
        },
    }


def persist_vector(
    conn: psycopg.Connection,
    event_id: str,
    source: str,
    event_type: str,
    semantic: dict[str, Any],
) -> None:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    content = vector_content_for_event(source, event_type, semantic)
    embedding_vector, embedding_provider = text_embedding_with_provider(content)
    embedding = vector_literal(embedding_vector)
    configured_embedding = embedding_status()
    conn.execute(
        """
        INSERT INTO memory_vectors
          (id, event_id, source, event_type, content, embedding, metadata)
        VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
        ON CONFLICT (event_id) DO UPDATE SET
          content = EXCLUDED.content,
          embedding = EXCLUDED.embedding,
          metadata = EXCLUDED.metadata
        """,
        (
            uuid.uuid4(),
            event_id,
            source,
            event_type,
            content,
            embedding,
            json.dumps(
                {
                    "intent": semantic["intent"],
                    "importance": semantic["importance"],
                    "entities": semantic["entities"],
                    "embedding_provider": embedding_provider,
                    "embedding_model": configured_embedding.get("model"),
                    "memory_scope": memory_scope_for_event(source, event_type, raw_data, semantic),
                },
                ensure_ascii=False,
            ),
        ),
    )


def memory_scope_for_event(
    source: str,
    event_type: str,
    raw_data: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any]:
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    conversation_label = str(
        raw_data.get("chat_name")
        or raw_data.get("thread_title")
        or raw_data.get("subject")
        or raw_data.get("conversation_id")
        or ""
    ).strip()
    speaker = str(raw_data.get("sender") or raw_data.get("speaker") or raw_data.get("from") or "").strip()
    related_candidates = [
        conversation_label,
        speaker,
        entities.get("person"),
        entities.get("subject"),
        entities.get("object"),
    ]
    participants = raw_data.get("participants")
    if isinstance(participants, list):
        related_candidates.extend(str(item) for item in participants)
    related_entities = sorted(
        {
            normalize_entity_name(str(item))
            for item in related_candidates
            if item and normalize_entity_name(str(item)) != "unknown"
        }
    )

    predicate = normalize_entity_name(str(entities.get("predicate") or semantic.get("intent") or ""))
    text = " ".join(
        str(value)
        for value in [
            raw_data.get("message"),
            raw_data.get("body"),
            raw_data.get("text"),
            semantic.get("summary"),
        ]
        if value
    ).lower()
    negative_markers = [
        "negative_opinion",
        "dislike",
        "unreliable",
        "annoying",
        "do not trust",
        "don't trust",
        "badmouth",
        "坏话",
        "不靠谱",
        "讨厌",
        "不信任",
        "差劲",
    ]
    is_negative = any(marker in predicate or marker in text for marker in negative_markers)
    is_third_party = len(set(related_entities)) >= 2
    sensitivity = "normal"
    usable_contexts = ["private_analysis", "personal_search", "self_reminder"]
    not_usable_contexts: list[str] = []
    if is_negative and is_third_party:
        sensitivity = "third_party_private_negative"
        not_usable_contexts.extend(["reply_to_contact", "external_message", "email_draft"])

    return {
        "source": source,
        "event_type": event_type,
        "conversation_id": str(raw_data.get("conversation_id") or raw_data.get("chat_id") or ""),
        "conversation_label": conversation_label,
        "speaker": speaker,
        "related_entities": related_entities,
        "sensitivity": sensitivity,
        "usable_contexts": usable_contexts,
        "not_usable_contexts": not_usable_contexts,
    }


def vector_content_for_event(source: str, event_type: str, semantic: dict[str, Any]) -> str:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    pieces = [str(semantic.get("summary") or "")]
    if source == "gmail" and event_type == "gmail_thread_snapshot":
        pieces.extend(
            [
                str(raw_data.get("subject") or ""),
                str(raw_data.get("sender") or ""),
                str(raw_data.get("body") or ""),
                " ".join(raw_data.get("attachments") or []),
                " ".join(raw_data.get("labels") or []),
            ]
        )
    elif source in {"whatsapp", "telegram"}:
        pieces.extend(
            [
                str(raw_data.get("chat_name") or ""),
                str(raw_data.get("sender") or ""),
                str(raw_data.get("message") or ""),
            ]
        )
    elif source == "nomi_chat":
        pieces.extend(
            [
                str(raw_data.get("role") or ""),
                str(raw_data.get("content") or ""),
                dialogue_batch_text(raw_data),
                str(raw_data.get("conversation_id") or ""),
            ]
        )
    elif source == "bookmark":
        pieces.extend([str(raw_data.get("title") or ""), str(raw_data.get("url") or ""), str(raw_data.get("folder_path") or "")])
    elif source == "search":
        pieces.append(str(raw_data.get("query") or ""))
        for result in raw_data.get("results") or []:
            if isinstance(result, dict):
                pieces.extend([str(result.get("title") or ""), str(result.get("url") or ""), str(result.get("snippet") or "")])
    content = "\n".join(piece for piece in pieces if piece).strip()
    return content[:6000] or str(semantic.get("summary") or "")


def realtime_message_for_suggestion(suggestion: dict[str, Any]) -> dict[str, Any]:
    metadata = suggestion.get("metadata") if isinstance(suggestion.get("metadata"), dict) else {}
    actions = metadata.get("actions") if isinstance(metadata.get("actions"), list) else []
    return {
        "type": "proactive_message",
        "id": str(suggestion["id"]),
        "suggestion_id": str(suggestion["id"]),
        "source_event_id": str(suggestion.get("source_event_id") or ""),
        "title": suggestion["title"],
        "body": suggestion["body"],
        "priority": suggestion["priority"],
        "source": metadata.get("source") or metadata.get("collector") or "unknown",
        "metadata": metadata,
        "actions": actions,
        "open_view": "chat",
    }


def publish_realtime_message(redis_client: Any, message: dict[str, Any]) -> None:
    if redis_client is None:
        return
    redis_client.publish(REALTIME_CHANNEL, json.dumps(message, ensure_ascii=False))


def normalize_suggestion_display_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def suggestion_display_dedupe_key(title: str, body: str) -> str:
    normalized_title = normalize_suggestion_display_text(title)
    normalized_body = normalize_suggestion_display_text(body)
    digest = hashlib.sha256(f"{normalized_title}\n{normalized_body}".encode("utf-8")).hexdigest()[:24]
    return f"display:{digest}:{normalized_title[:48]}"


def existing_suggestion_id_for_dedupe(conn: psycopg.Connection, dedupe_key: str) -> Optional[str]:
    key = str(dedupe_key or "").strip()
    if not key:
        return None
    row = conn.execute(
        """
        SELECT id
        FROM proactive_suggestions
        WHERE metadata->>'dedupe_key' = %s
          AND status IN ('open', 'snoozed', 'dismissed', 'done')
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (key,),
    ).fetchone()
    if not row:
        return None
    return str(row[0])


def existing_suggestion_id_for_visible_content(
    conn: psycopg.Connection,
    title: str,
    body: str,
    display_dedupe_key: str,
) -> Optional[str]:
    normalized_title = str(title or "")[:120]
    normalized_body = str(body or "")[:500]
    key = str(display_dedupe_key or "").strip()
    if not key and not normalized_title and not normalized_body:
        return None
    row = conn.execute(
        """
        SELECT id
        FROM proactive_suggestions
        WHERE status IN ('open', 'snoozed', 'dismissed', 'done')
          AND (
            metadata->>'display_dedupe_key' = %s
            OR (title = %s AND body = %s)
          )
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (key, normalized_title, normalized_body),
    ).fetchone()
    if not row:
        return None
    return str(row[0])


def lock_suggestion_dedupe_key(conn: psycopg.Connection, dedupe_key: str) -> None:
    key = str(dedupe_key or "").strip()
    if not key:
        return
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


def persist_suggestion(conn: psycopg.Connection, event_id: str, semantic: dict[str, Any], redis_client: Any = None) -> None:
    suggestion = suggestion_for_event(event_id, semantic)
    if not suggestion:
        return
    metadata = suggestion.get("metadata") if isinstance(suggestion.get("metadata"), dict) else {}
    display_dedupe_key = suggestion_display_dedupe_key(suggestion["title"], suggestion["body"])
    metadata["display_dedupe_key"] = display_dedupe_key
    suggestion["metadata"] = metadata
    dedupe_key = str(metadata.get("dedupe_key") or "").strip()
    lock_suggestion_dedupe_key(conn, dedupe_key)
    lock_suggestion_dedupe_key(conn, display_dedupe_key)
    if existing_suggestion_id_for_dedupe(conn, dedupe_key):
        return
    if existing_suggestion_id_for_visible_content(conn, suggestion["title"], suggestion["body"], display_dedupe_key):
        return
    suggestion_id = uuid.uuid4()
    suggestion["id"] = str(suggestion_id)
    conn.execute(
        """
        INSERT INTO proactive_suggestions
          (id, source_event_id, title, body, priority, metadata, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (source_event_id) DO UPDATE SET
          title = EXCLUDED.title,
          body = EXCLUDED.body,
          priority = EXCLUDED.priority,
          metadata = EXCLUDED.metadata,
          updated_at = now()
        """,
        (
            suggestion_id,
            suggestion["source_event_id"],
            suggestion["title"],
            suggestion["body"],
            suggestion["priority"],
            json.dumps(suggestion["metadata"], ensure_ascii=False),
        ),
    )
    publish_realtime_message(redis_client, realtime_message_for_suggestion(suggestion))


JOB_REQUIREMENT_ALIASES: dict[str, list[str]] = {
    "Java": ["java"],
    "Go": [" go ", "golang", "go&", "go/", "熟悉 go", "go、", "go。"],
    "PHP": ["php"],
    "C++": ["c++", "cpp"],
    "Android": ["android"],
    "Linux": ["linux"],
    "JVM tuning": ["jvm", "gc", "fullgc", "垃圾回收", "调优"],
    "high concurrency": ["high concurrency", "高并发", "tps", "concurrency"],
    "high availability": ["high availability", "高可用", "availability"],
    "distributed systems": ["distributed systems", "分布式"],
    "microservices": ["microservices", "microservice", "微服务"],
    "Kafka": ["kafka"],
    "RocketMQ": ["rocketmq", "rocket mq"],
    "Redis": ["redis"],
    "Elasticsearch": ["elasticsearch", "elastic search", " es "],
    "MySQL": ["mysql"],
    "sharding": ["sharding", "分库分表"],
    "DDD": ["ddd", "领域驱动"],
    "SQL optimization": ["sql optimization", "sql tuning", "sql 调优", "sql优化"],
    "observability": ["observability", "otel", "prometheus", "grafana", "可观测"],
    "team leadership": ["team leadership", "leader", "technical owner", "技术 owner", "技术owner", "管理"],
    "AI Agent": ["ai agent", "agent", "智能体", "harness"],
    "LLM product": ["llm", "large language model", "大模型"],
    "workflow automation": ["automation", "workflow", "自动化"],
    "data analysis": ["analytics", "analysis", "数据"],
    "B2B SaaS": ["b2b", "saas", "tob"],
}


def openable_linkedin_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url or "REDACTED" in url:
        return ""
    if not re.match(r"^https://([a-z0-9-]+\.)?linkedin\.com/", url, flags=re.I):
        return ""
    return url


LINKEDIN_JOB_QUERY_REJECT_TERMS = [
    "基于我刚刚",
    "刚刚真实",
    "结合我的",
    "推荐理由",
    "可以打开",
    "工作机会",
    "帮我找找看",
    "请基于",
]
LINKEDIN_JOB_QUERY_ALLOW_TERMS = [
    "engineer",
    "developer",
    "java",
    "go",
    "golang",
    "python",
    "backend",
    "full-stack",
    "software",
    "ai",
    "agent",
    "infra",
    "架构",
    "后端",
    "工程师",
    "开发",
    "全栈",
    "云原生",
    "算法",
]


def linkedin_job_search_query_from_raw(raw_data: dict[str, Any], fallback_raw_data: dict[str, Any] | None = None) -> str:
    for source in [raw_data, fallback_raw_data or {}]:
        url = str(source.get("url") or "").strip()
        if url:
            query = parse_qs(urlparse(url).query).get("keywords", [""])[0]
            query = unquote_plus(str(query or "")).strip()
            if query and "REDACTED" not in query.upper():
                return query
        title = str(source.get("title") or "").strip()
        match = re.search(r"\)\s*(.*?)\s+Jobs(?:\s+in|\s+\|)", title)
        if match:
            query = match.group(1).strip()
            if query:
                return query
    return ""


def looks_like_action_request_query(query: str) -> bool:
    normalized = re.sub(r"\s+", "", query or "").lower()
    if not normalized:
        return False
    if any(term.lower().replace(" ", "") in normalized for term in LINKEDIN_JOB_QUERY_REJECT_TERMS):
        return True
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", normalized))
    return len(normalized) >= 42 and chinese_chars >= 18 and not any(
        term.lower().replace(" ", "") in normalized for term in LINKEDIN_JOB_QUERY_ALLOW_TERMS
    )


def is_valid_linkedin_job_search_context(raw_data: dict[str, Any], fallback_raw_data: dict[str, Any] | None = None) -> bool:
    query = linkedin_job_search_query_from_raw(raw_data, fallback_raw_data)
    if not query:
        return True
    return not looks_like_action_request_query(query)


def extract_job_requirements(text: str) -> list[str]:
    lowered = f" {str(text or '').lower()} "
    requirements: list[str] = []
    for requirement, terms in JOB_REQUIREMENT_ALIASES.items():
        if any(term.lower() in lowered for term in terms):
            requirements.append(requirement)
    return list(dict.fromkeys(requirements))


def latest_career_context_text(conn: psycopg.Connection) -> str:
    pieces: list[str] = []
    for sql in [
        """
        SELECT headline, target_roles, target_locations, skills, payload
        FROM career_profiles
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        """
        SELECT parsed_text, payload
        FROM career_resumes
        WHERE status <> 'deleted'
        ORDER BY CASE WHEN payload->>'is_default' = 'true' THEN 1 ELSE 0 END DESC,
                 updated_at DESC
        LIMIT 1
        """,
    ]:
        try:
            row = conn.execute(sql).fetchone()
        except Exception:
            row = None
        if not row:
            continue
        for item in row:
            if isinstance(item, (dict, list)):
                pieces.append(json.dumps(item, ensure_ascii=False, default=str))
            else:
                pieces.append(str(item or ""))
    return " ".join(pieces)


def score_linkedin_job_for_career(job: dict[str, Any], career_text: str) -> tuple[float, list[str], list[str]]:
    job_text = " ".join(
        str(job.get(key) or "")
        for key in ["title", "company", "location", "text", "jd_text", "description"]
    )
    requirements = extract_job_requirements(job_text)
    career_lower = career_text.lower()
    matched = [
        requirement
        for requirement in requirements
        if requirement.lower() in career_lower
        or any(alias.lower() in career_lower for alias in JOB_REQUIREMENT_ALIASES.get(requirement, []))
    ]
    gaps = [requirement for requirement in requirements if requirement not in matched]
    title_lower = str(job.get("title") or "").lower()
    role_bonus = 0.0
    if any(marker in title_lower for marker in ["backend", "golang", "java", "后端", "架构", "infra", "云原生"]):
        role_bonus = 0.22
    elif any(marker in title_lower for marker in ["ai", "llm", "agent", "大模型"]):
        role_bonus = 0.14
    if requirements:
        score = 0.38 + (len(matched) / max(len(requirements), 1)) * 0.4 + role_bonus
    else:
        score = 0.52 + role_bonus
    return min(round(score, 2), 0.95), matched, gaps


def clean_linkedin_job_title_and_company(title: str, company: str) -> tuple[str, str]:
    clean_title = str(title or "").strip()
    clean_company = str(company or "").strip()
    if "|" not in clean_title:
        return clean_title, clean_company
    parts = [part.strip() for part in clean_title.split("|") if part.strip()]
    if len(parts) < 2:
        return clean_title, clean_company
    if parts[-1].lower() == "linkedin":
        parts = parts[:-1]
    if len(parts) < 2:
        return parts[0], clean_company
    if clean_company and parts[-1].casefold() == clean_company.casefold():
        return parts[0], clean_company
    if not clean_company:
        return parts[0], parts[1]
    return clean_title, clean_company


def linkedin_job_rows_from_raw_data(
    event_id: str,
    raw_data: dict[str, Any],
    *,
    fallback_raw_data: dict[str, Any] | None = None,
    career_text: str = "",
) -> list[dict[str, Any]]:
    if not is_valid_linkedin_job_search_context(raw_data, fallback_raw_data):
        return []
    search_query = linkedin_job_search_query_from_raw(raw_data, fallback_raw_data)
    source_title = str(raw_data.get("title") or (fallback_raw_data or {}).get("title") or "").strip()
    source_jobs = raw_data.get("job_results") or raw_data.get("job_pages") or []
    fallback_jobs = (fallback_raw_data or {}).get("job_results") or (fallback_raw_data or {}).get("job_pages") or []
    if isinstance(source_jobs, dict):
        source_jobs = [source_jobs]
    if isinstance(fallback_jobs, dict):
        fallback_jobs = [fallback_jobs]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, job in enumerate(source_jobs):
        if not isinstance(job, dict):
            continue
        fallback_job = fallback_jobs[index] if index < len(fallback_jobs) and isinstance(fallback_jobs[index], dict) else {}
        title = str(job.get("title") or fallback_job.get("title") or "").strip()
        company = str(job.get("company") or fallback_job.get("company") or "").strip()
        title, company = clean_linkedin_job_title_and_company(title, company)
        location = str(job.get("location") or fallback_job.get("location") or "").strip()
        if not title or not company:
            continue
        job_id = str(job.get("job_id") or fallback_job.get("job_id") or "").strip()
        if not job_id:
            digest = hashlib.sha256(f"{title}|{company}|{location}".encode("utf-8")).hexdigest()[:12]
            job_id = f"linkedin_search_{digest}"
        if job_id in seen:
            continue
        seen.add(job_id)
        url = openable_linkedin_url(job.get("url")) or openable_linkedin_url(fallback_job.get("url")) or openable_linkedin_url(raw_data.get("url"))
        text = str(job.get("text") or fallback_job.get("text") or raw_data.get("text") or "")[:5000]
        requirements = extract_job_requirements(" ".join([title, company, location, text]))
        fit_score, matched, gaps = score_linkedin_job_for_career(
            {"title": title, "company": company, "location": location, "text": text},
            career_text,
        )
        status = "recommended" if fit_score >= 0.65 else "tracked"
        rows.append(
            {
                "id": job_id,
                "source": "linkedin_browser_observation",
                "title": title[:220],
                "company": company[:220],
                "location": location[:180],
                "url": url,
                "status": status,
                "fit_score": fit_score,
                "requirements": requirements,
                "source_event_ids": [event_id],
                "payload": {
                    "job_id": job_id,
                    "source": "linkedin_browser_observation",
                    "source_event_ids": [event_id],
                    "source_title": source_title,
                    "search_query": search_query,
                    "capture_scope": raw_data.get("capture_scope") or (fallback_raw_data or {}).get("capture_scope"),
                    "url_openable": bool(url),
                    "url_kind": "linkedin_job_or_search_url" if url else "not_available_in_protected_event",
                    "title": title[:220],
                    "company": company[:220],
                    "location": location[:180],
                    "summary": f"{company} 的 {title}，地点 {location}。匹配项：{'、'.join(matched) or '暂未解析'}。缺口：{'、'.join(gaps) or '暂未发现明显缺口'}。",
                    "matched_requirements": matched,
                    "gap_requirements": gaps,
                    "requirements": requirements,
                    "jd_text": text,
                    "observed_from": "linkedin_job_search_results",
                },
            }
        )
    return rows


def private_raw_data_for_event(conn: psycopg.Connection, event_id: str) -> dict[str, Any]:
    try:
        row = conn.execute("SELECT raw_data_private FROM events WHERE event_id = %s", (event_id,)).fetchone()
    except Exception:
        return {}
    if not row:
        return {}
    return decrypt_private_raw_data(row[0])


def persist_linkedin_job_search_opportunities(conn: psycopg.Connection, event_id: str, semantic: dict[str, Any]) -> int:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    if not raw_data.get("job_results") and not raw_data.get("job_pages"):
        return 0
    private_raw_data = private_raw_data_for_event(conn, event_id)
    source_raw_data = private_raw_data if private_raw_data else raw_data
    career_text = latest_career_context_text(conn)
    rows = linkedin_job_rows_from_raw_data(
        event_id,
        source_raw_data,
        fallback_raw_data=raw_data,
        career_text=career_text,
    )
    for row in rows:
        conn.execute(
            """
            INSERT INTO job_opportunities (
              id, source, title, company, location, url, status, fit_score,
              requirements, source_event_ids, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::TEXT[], %s::jsonb, now(), now())
            ON CONFLICT (id) DO UPDATE SET
              source = EXCLUDED.source,
              title = EXCLUDED.title,
              company = EXCLUDED.company,
              location = EXCLUDED.location,
              url = COALESCE(NULLIF(EXCLUDED.url, ''), job_opportunities.url),
              status = EXCLUDED.status,
              fit_score = EXCLUDED.fit_score,
              requirements = EXCLUDED.requirements,
              source_event_ids = ARRAY(SELECT DISTINCT unnest(job_opportunities.source_event_ids || EXCLUDED.source_event_ids)),
              payload = job_opportunities.payload || EXCLUDED.payload,
              updated_at = now()
            """,
            (
                row["id"],
                row["source"],
                row["title"],
                row["company"],
                row["location"],
                row["url"],
                row["status"],
                row["fit_score"],
                json.dumps(row["requirements"], ensure_ascii=False),
                row["source_event_ids"],
                json.dumps(row["payload"], ensure_ascii=False, default=str),
            ),
        )
    return len(rows)


def source_event_id_candidates(value: Any) -> list[str]:
    if isinstance(value, list):
        candidates: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                candidates.append(text)
        return candidates
    text = str(value or "").strip()
    if text:
        return [text]
    return []


def first_existing_source_event_id(conn: psycopg.Connection, value: Any) -> Optional[str]:
    for candidate in source_event_id_candidates(value):
        try:
            normalized = str(uuid.UUID(str(candidate)))
        except (TypeError, ValueError):
            continue
        row = conn.execute(
            "SELECT event_id FROM events WHERE event_id = %s LIMIT 1",
            (normalized,),
        ).fetchone()
        if row:
            return str(row[0])
    return None


def dispatch_due_agenda_reminders(conn: psycopg.Connection, redis_client: Any = None, *, limit: int = 20) -> int:
    ensure_agenda_schema(conn)
    rows = conn.execute(
        """
        SELECT r.id, r.agenda_item_id, r.dedupe_key, r.title, r.body, r.metadata, a.source_event_ids
        FROM agenda_reminders r
        JOIN agenda_items a ON a.id = r.agenda_item_id
        WHERE r.status = 'pending'
          AND r.remind_at <= now()
          AND a.status IN ('scheduled', 'pending')
        ORDER BY r.remind_at ASC
        LIMIT %s
        FOR UPDATE SKIP LOCKED
        """,
        (max(1, min(int(limit or 20), 100)),),
    ).fetchall()
    dispatched = 0
    for row in rows:
        reminder_id, agenda_id, dedupe_key, title, body, raw_metadata, source_event_ids = row
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        metadata = dict(metadata)
        metadata["dedupe_key"] = str(dedupe_key)
        metadata["suggestion_type"] = "agenda_time_reminder"
        metadata["source"] = metadata.get("source") or "agenda"
        metadata["display_dedupe_key"] = suggestion_display_dedupe_key(str(title or "日程提醒"), str(body or "你有一个即将开始的日程。"))
        source_event_id = first_existing_source_event_id(conn, metadata.get("source_event_ids") or source_event_ids)
        lock_suggestion_dedupe_key(conn, str(dedupe_key))
        lock_suggestion_dedupe_key(conn, str(metadata.get("display_dedupe_key") or ""))
        if existing_suggestion_id_for_dedupe(conn, str(dedupe_key)):
            conn.execute(
                """
                UPDATE agenda_reminders
                SET status = 'sent',
                    sent_at = now(),
                    metadata = metadata || %s::jsonb,
                    updated_at = now()
                WHERE id = %s
                """,
                (json.dumps({"delivery_status": "duplicate_suppressed"}, ensure_ascii=False), reminder_id),
            )
            continue
        if existing_suggestion_id_for_visible_content(conn, str(title or "日程提醒"), str(body or "你有一个即将开始的日程。"), str(metadata.get("display_dedupe_key") or "")):
            conn.execute(
                """
                UPDATE agenda_reminders
                SET status = 'sent',
                    sent_at = now(),
                    metadata = metadata || %s::jsonb,
                    updated_at = now()
                WHERE id = %s
                """,
                (json.dumps({"delivery_status": "visible_duplicate_suppressed"}, ensure_ascii=False), reminder_id),
            )
            continue
        suggestion_id = uuid.uuid4()
        suggestion = {
            "id": str(suggestion_id),
            "source_event_id": source_event_id,
            "title": str(title or "日程提醒"),
            "body": str(body or "你有一个即将开始的日程。"),
            "priority": 0.95,
            "metadata": metadata,
        }
        conn.execute(
            """
            INSERT INTO proactive_suggestions
              (id, source_event_id, title, body, priority, status, metadata, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, 'open', %s, now(), now())
            ON CONFLICT (source_event_id) DO UPDATE SET
              title = EXCLUDED.title,
              body = EXCLUDED.body,
              priority = EXCLUDED.priority,
              status = 'open',
              metadata = EXCLUDED.metadata,
              updated_at = now()
            """,
            (
                suggestion_id,
                source_event_id,
                suggestion["title"],
                suggestion["body"],
                suggestion["priority"],
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            UPDATE agenda_reminders
            SET status = 'sent', sent_at = now(), updated_at = now()
            WHERE id = %s
            """,
            (reminder_id,),
        )
        publish_realtime_message(redis_client, realtime_message_for_suggestion(suggestion))
        dispatched += 1
    return dispatched


def _dispatch_due_agenda_reminders_if_due(redis_client: Any, last_scan_at: float) -> float:
    started = time.monotonic()
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            dispatched = dispatch_due_agenda_reminders(conn, redis_client)
        if dispatched:
            print(f"worker agenda reminders dispatched count={dispatched}", flush=True)
    except Exception as exc:
        print(f"worker agenda reminder dispatch failed error={exc!r}", flush=True)
    return started


def maybe_dispatch_due_agenda_reminders(redis_client: Any, last_scan_at: float) -> float:
    if WORKER_REMINDER_SCAN_INTERVAL_SECONDS <= 0:
        return last_scan_at
    now = time.monotonic()
    if now - last_scan_at < WORKER_REMINDER_SCAN_INTERVAL_SECONDS:
        return last_scan_at
    return _dispatch_due_agenda_reminders_if_due(redis_client, last_scan_at)


ATTACHMENT_PROVENANCE_KEYS = {
    "attachment_id",
    "turn_id",
    "mime_type",
    "status",
    "processing_version",
    "locator",
    "content_hash",
    "chunk_ordinal",
}
ATTACHMENT_LOCATOR_KEYS = {
    "page",
    "slide",
    "sheet",
    "cell",
    "cell_range",
    "row",
    "row_start",
    "row_end",
    "paragraph",
    "paragraph_start",
    "paragraph_end",
    "section",
    "item",
    "ordinal",
}


def safe_attachment_locator(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in sorted(ATTACHMENT_LOCATOR_KEYS):
        item = value.get(key)
        if isinstance(item, bool):
            continue
        if isinstance(item, (int, float)) and item >= 0:
            result[key] = item
        elif isinstance(item, str):
            cleaned = re.sub(r"<[^>]*>", "", item).strip()[:120]
            if cleaned and ".." not in cleaned and not cleaned.startswith(("/", "\\")):
                result[key] = cleaned
    return result


def safe_attachment_provenance(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            continue
        item: dict[str, Any] = {}
        for key in sorted(ATTACHMENT_PROVENANCE_KEYS - {"locator", "chunk_ordinal"}):
            text = re.sub(r"[^A-Za-z0-9_.:+/@-]", "", str(raw.get(key) or ""))[:200]
            if text:
                item[key] = text
        ordinal = raw.get("chunk_ordinal")
        if isinstance(ordinal, int) and ordinal >= 0:
            item["chunk_ordinal"] = ordinal
        locator = safe_attachment_locator(raw.get("locator"))
        if locator:
            item["locator"] = locator
        required = {"attachment_id", "turn_id", "processing_version", "content_hash", "locator"}
        if not required.issubset(item):
            continue
        fingerprint = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(item)
    return result


def fact_from_semantic(event_id: str, semantic: dict[str, Any]) -> dict[str, Any]:
    entities = semantic.get("entities", {})
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    source = str(entities.get("source") or raw_data.get("source") or "")
    event_type = str(entities.get("event_type") or raw_data.get("event_type") or "")
    if entities.get("source") in {"longmemeval_conversation", "locomo_seed"} and entities.get("question") and entities.get("answer"):
        subject = entities.get("question")
        predicate = "benchmark_answer"
        obj = entities.get("answer")
    elif entities.get("subject") and entities.get("predicate") and entities.get("object"):
        subject = entities.get("subject")
        predicate = str(entities.get("predicate"))[:180]
        obj = entities.get("object")
    else:
        subject = (
            entities.get("person")
            or entities.get("source")
            or entities.get("question")
            or "user"
        )
        predicate = str(semantic.get("intent") or "observed")[:180]
        obj = (
            entities.get("answer")
            or semantic.get("summary")
            or entities.get("event_type")
            or semantic.get("intent")
        )
    metadata = {
        "summary": semantic.get("summary"),
        "entities": entities,
        "source_event_id": event_id,
        "memory_scope": memory_scope_for_event(source, event_type, raw_data, semantic),
    }
    attachment_provenance = safe_attachment_provenance(raw_data.get("attachment_provenance"))
    if attachment_provenance:
        metadata["attachment_provenance"] = attachment_provenance
    return {
        "subject": normalize_entity_name(str(subject)),
        "predicate": predicate,
        "object": normalize_entity_name(str(obj)) if len(str(obj)) < 180 else str(obj)[:500],
        "confidence": min(max(float(semantic.get("importance", 0.2)), 0), 1),
        "metadata": metadata,
    }


def state_category_for_predicate(predicate: str) -> str:
    normalized = normalize_entity_name(predicate)
    if normalized in {"identity", "profile", "role", "background"}:
        return "identity"
    if normalized in {"preference", "likes", "dislikes", "preferred"}:
        return "preference"
    if normalized in {"active_project", "project", "research_interest", "current_project"}:
        return "project"
    if normalized in {"long_term_goal", "goal", "objective", "plan"}:
        return "goal"
    if normalized == "conversation_memory":
        return "profile"
    return "state"


def state_key_for_fact(fact: dict[str, Any]) -> str:
    category = state_category_for_predicate(fact["predicate"])
    if category == "profile":
        return f"entity:{fact['subject']}:profile"
    if category in {"identity", "preference"}:
        return f"profile:{fact['subject']}:{category}"
    if category == "project":
        return f"project:{fact['subject']}"
    if category == "goal":
        return f"goal:{fact['subject']}"
    return f"state:{fact['predicate']}:{fact['subject']}"


def state_payload_for_fact(fact: dict[str, Any], semantic: dict[str, Any]) -> dict[str, Any]:
    summary = str(semantic.get("summary") or fact["object"])[:500]
    category = state_category_for_predicate(fact["predicate"])
    return {
        "subject": fact["subject"],
        "state_category": category,
        "current_value": fact["object"],
        "facts": [
            {
                "predicate": fact["predicate"],
                "object": fact["object"],
                "summary": summary,
                "confidence": fact["confidence"],
            }
        ],
    }


def entity_type_for_name(name: str, semantic: dict[str, Any]) -> str:
    entities = semantic.get("entities", {})
    normalized = normalize_entity_name(name)
    if normalized == normalize_entity_name(entities.get("company", "")):
        return "company"
    if normalized == normalize_entity_name(entities.get("role", "")):
        return "job_role"
    if normalized == normalize_entity_name(entities.get("recruiter", "")):
        return "person"
    if name == entities.get("person"):
        return "person"
    if name == entities.get("answer"):
        return "object"
    if name == entities.get("source"):
        return "source"
    return "concept"


def career_relationship_edges(semantic: dict[str, Any]) -> list[dict[str, Any]]:
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    text = "\n".join(
        str(item)
        for item in [
            semantic.get("summary"),
            raw_data.get("subject"),
            raw_data.get("body"),
            raw_data.get("message"),
            raw_data.get("text"),
        ]
        if item
    )
    recruiter = str(entities.get("recruiter") or raw_data.get("recruiter_name") or raw_data.get("sender") or "").strip()
    company = str(entities.get("company") or raw_data.get("company") or "").strip()
    role = str(entities.get("role") or raw_data.get("role") or raw_data.get("job_title") or raw_data.get("title") or "").strip()
    if not company:
        company_match = re.search(r"(?:at|for)\s+([A-Z][A-Za-z0-9 .&-]{2,50})", text)
        if company_match:
            company = company_match.group(1).strip(" .,-")
    if not role:
        role_match = re.search(r"([A-Za-z0-9 +/#-]{2,50}\s+(?:role|position|job))", text, re.I)
        if role_match:
            role = role_match.group(1).strip(" .,-")
    if not recruiter or recruiter.lower() in {"unknown", "user", "gmail"}:
        return []
    edges: list[dict[str, Any]] = []
    if company:
        edges.append({"from": recruiter, "to": company, "relation_type": "recruits_for_company"})
    if role:
        edges.append({"from": recruiter, "to": role, "relation_type": "recruits_for_role"})
    if company and role:
        edges.append({"from": company, "to": role, "relation_type": "company_hiring_role"})
    return edges


def persist_career_relationship_edges(
    conn: psycopg.Connection,
    event_id: str,
    timestamp: str,
    semantic: dict[str, Any],
) -> None:
    edges = career_relationship_edges(semantic)
    if not edges:
        return
    confidence = min(max(float(semantic.get("importance", 0.2)), 0), 1)
    aliases = semantic_alias_map(semantic)
    for edge in edges:
        from_name = str(edge["from"])
        to_name = str(edge["to"])
        from_id = upsert_entity(conn, from_name, entity_type_for_name(from_name, semantic), aliases=aliases)
        to_id = upsert_entity(conn, to_name, entity_type_for_name(to_name, semantic), aliases=aliases)
        relation_type = str(edge["relation_type"])
        conn.execute(
            """
            INSERT INTO relationships (id, from_entity, to_entity, relation_type, weight, metadata, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (from_entity, to_entity, relation_type) DO UPDATE SET
              weight = GREATEST(relationships.weight, EXCLUDED.weight),
              metadata = EXCLUDED.metadata,
              updated_at = now()
            """,
            (
                uuid.uuid4(),
                from_id,
                to_id,
                relation_type,
                confidence,
                json.dumps(
                    {
                        "confidence": confidence,
                        "source_event_id": event_id,
                        "summary": semantic.get("summary"),
                        "valid_from": timestamp,
                        "career_relationship": {
                            "from": from_name,
                            "to": to_name,
                            "relation_type": relation_type,
                        },
                        "memory_scope": memory_scope_for_event(
                            str((semantic.get("entities") or {}).get("source") or ""),
                            str((semantic.get("entities") or {}).get("event_type") or ""),
                            semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {},
                            semantic,
                        ),
                    },
                    ensure_ascii=False,
                ),
            ),
        )


def canonical_entity_name(name: str, aliases: Optional[dict[str, str]] = None) -> tuple[str, Optional[str]]:
    normalized = normalize_entity_name(name)
    aliases = aliases or {}
    for alias, canonical in aliases.items():
        if normalize_entity_name(alias) == normalized:
            canonical_normalized = normalize_entity_name(canonical)
            return canonical_normalized, normalized if normalized != canonical_normalized else None
    return normalized, None


def semantic_alias_map(semantic: dict[str, Any]) -> dict[str, str]:
    entities = semantic.get("entities", {})
    aliases = entities.get("aliases")
    return aliases if isinstance(aliases, dict) else {}


def upsert_entity(conn: psycopg.Connection, name: str, entity_type: str, aliases: Optional[dict[str, str]] = None) -> Any:
    canonical, alias = canonical_entity_name(name, aliases)
    alias_list = [alias] if alias else []
    cursor = conn.execute(
        """
        INSERT INTO entities (id, entity_type, name, aliases)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (entity_type, name) DO UPDATE SET
          aliases = (
            SELECT ARRAY(SELECT DISTINCT unnest(entities.aliases || EXCLUDED.aliases))
          )
        RETURNING id
        """,
        (uuid.uuid4(), entity_type, canonical, alias_list),
    )
    row = cursor.fetchone() if hasattr(cursor, "fetchone") else None
    return row[0] if row else uuid.uuid4()


def persist_fact_graph_and_state(
    conn: psycopg.Connection,
    event_id: str,
    timestamp: str,
    semantic: dict[str, Any],
) -> None:
    ensure_relationship_metadata_column(conn)
    fact = fact_from_semantic(event_id, semantic)
    fact_id = uuid.uuid4()
    fact_cursor = conn.execute(
        """
        INSERT INTO facts
          (id, subject, predicate, object, confidence, valid_from, source_event_ids, metadata, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, ARRAY[%s]::UUID[], %s, now())
        ON CONFLICT (subject, predicate, object) DO UPDATE SET
          confidence = GREATEST(facts.confidence, EXCLUDED.confidence),
          source_event_ids = (
            SELECT ARRAY(SELECT DISTINCT unnest(facts.source_event_ids || EXCLUDED.source_event_ids))
          ),
          metadata =
            (EXCLUDED.metadata - 'attachment_provenance') ||
            jsonb_build_object(
              'attachment_provenance',
              (
                SELECT COALESCE(jsonb_agg(item), '[]'::jsonb)
                FROM (
                  SELECT DISTINCT value AS item
                  FROM jsonb_array_elements(
                    COALESCE(facts.metadata->'attachment_provenance', '[]'::jsonb) ||
                    COALESCE(EXCLUDED.metadata->'attachment_provenance', '[]'::jsonb)
                  ) AS provenance(value)
                ) AS unique_provenance
              )
            ),
          updated_at = now()
        RETURNING id
        """,
        (
            fact_id,
            fact["subject"],
            fact["predicate"],
            fact["object"],
            fact["confidence"],
            datetime.fromisoformat(timestamp.replace("Z", "+00:00")),
            event_id,
            json.dumps(fact["metadata"], ensure_ascii=False),
        ),
    )
    returned = fact_cursor.fetchone() if hasattr(fact_cursor, "fetchone") else None
    persisted_fact_id = returned[0] if returned else fact_id

    aliases = semantic_alias_map(semantic)
    subject_id = upsert_entity(conn, fact["subject"], entity_type_for_name(fact["subject"], semantic), aliases=aliases)
    object_id = upsert_entity(conn, fact["object"], entity_type_for_name(fact["object"], semantic), aliases=aliases)
    conn.execute(
        """
        INSERT INTO relationships (id, from_entity, to_entity, relation_type, weight, metadata, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (from_entity, to_entity, relation_type) DO UPDATE SET
          weight = GREATEST(relationships.weight, EXCLUDED.weight),
          metadata = EXCLUDED.metadata,
          updated_at = now()
        """,
        (
            uuid.uuid4(),
            subject_id,
            object_id,
            fact["predicate"],
            fact["confidence"],
            json.dumps(
                {
                    "confidence": fact["confidence"],
                    "source_event_id": event_id,
                    "summary": semantic.get("summary"),
                    "valid_from": timestamp,
                    "memory_scope": fact["metadata"].get("memory_scope"),
                },
                ensure_ascii=False,
            ),
        ),
    )

    should_update_state = fact["confidence"] >= 0.7 or fact["predicate"] == "conversation_memory"
    if should_update_state:
        state_key = state_key_for_fact(fact)
        state_payload = state_payload_for_fact(fact, semantic)
        conn.execute(
            """
            INSERT INTO memory_states (key, value, confidence, source_fact_ids, updated_at)
            VALUES (%s, %s, %s, ARRAY[%s]::UUID[], now())
            ON CONFLICT (key) DO UPDATE SET
              value = jsonb_build_object(
                'subject', COALESCE(memory_states.value->>'subject', EXCLUDED.value->>'subject'),
                'state_category', COALESCE(EXCLUDED.value->>'state_category', memory_states.value->>'state_category'),
                'current_value', COALESCE(EXCLUDED.value->>'current_value', memory_states.value->>'current_value'),
                'facts', (
                  SELECT COALESCE(jsonb_agg(item), '[]'::jsonb)
                  FROM (
                    SELECT DISTINCT ON (
                      COALESCE(fact_item->>'predicate', ''),
                      COALESCE(fact_item->>'object', ''),
                      COALESCE(fact_item->>'summary', '')
                    ) fact_item AS item
                    FROM jsonb_array_elements(
                      COALESCE(memory_states.value->'facts', '[]'::jsonb) || COALESCE(EXCLUDED.value->'facts', '[]'::jsonb)
                    ) AS fact_item
                    ORDER BY
                      COALESCE(fact_item->>'predicate', ''),
                      COALESCE(fact_item->>'object', ''),
                      COALESCE(fact_item->>'summary', ''),
                      (fact_item->>'confidence')::float DESC
                    LIMIT 20
                  ) deduped
                )
              ),
              confidence = GREATEST(memory_states.confidence, EXCLUDED.confidence),
              source_fact_ids = (
                SELECT ARRAY(SELECT DISTINCT unnest(memory_states.source_fact_ids || EXCLUDED.source_fact_ids))
              ),
              updated_at = now()
            """,
            (
                state_key,
                json.dumps(state_payload, ensure_ascii=False),
                fact["confidence"],
                persisted_fact_id,
            ),
        )
    persist_career_relationship_edges(conn, event_id, timestamp, semantic)


def ensure_relationship_metadata_column(conn: psycopg.Connection) -> None:
    conn.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb")


def ensure_agenda_schema(conn: psycopg.Connection) -> None:
    global _AGENDA_SCHEMA_READY
    if _AGENDA_SCHEMA_READY:
        return
    with _AGENDA_SCHEMA_LOCK:
        if _AGENDA_SCHEMA_READY:
            return
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agenda_items (
              id UUID PRIMARY KEY,
              type TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'scheduled',
              certainty TEXT NOT NULL DEFAULT 'exact',
              time_window JSONB NOT NULL DEFAULT '{}'::jsonb,
              place TEXT,
              participants JSONB NOT NULL DEFAULT '[]'::jsonb,
              missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb,
              needs_clarification BOOLEAN NOT NULL DEFAULT FALSE,
              confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
              source_event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agenda_item_versions (
              id UUID PRIMARY KEY,
              agenda_item_id UUID REFERENCES agenda_items(id) ON DELETE CASCADE,
              operation TEXT NOT NULL,
              previous_value JSONB NOT NULL DEFAULT '{}'::jsonb,
              new_value JSONB NOT NULL DEFAULT '{}'::jsonb,
              reason TEXT NOT NULL DEFAULT '',
              source_event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
              confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agenda_reminders (
              id UUID PRIMARY KEY,
              agenda_item_id UUID REFERENCES agenda_items(id) ON DELETE CASCADE,
              starts_at TIMESTAMPTZ NOT NULL,
              remind_at TIMESTAMPTZ NOT NULL,
              lead_minutes INTEGER NOT NULL,
              dedupe_key TEXT NOT NULL,
              title TEXT NOT NULL,
              body TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              sent_at TIMESTAMPTZ
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS agenda_items_status_idx ON agenda_items(status, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS agenda_items_metadata_dedupe_idx ON agenda_items ((metadata->>'dedupe_key'))")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS agenda_reminders_dedupe_key_idx ON agenda_reminders(dedupe_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS agenda_reminders_due_idx ON agenda_reminders(status, remind_at)")
        _AGENDA_SCHEMA_READY = True


def semantic_text(semantic: dict[str, Any]) -> str:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    readable = readable_raw_text(raw_data)
    display_summary = semantic_display_summary(semantic)
    pieces = []
    for piece in [
        display_summary,
        readable,
        raw_data.get("message"),
        raw_data.get("body"),
        raw_data.get("text"),
        raw_data.get("content"),
        raw_data.get("subject"),
        raw_data.get("title"),
    ]:
        text = str(piece or "").strip()
        if text and text not in pieces:
            pieces.append(text)
    return "\n".join(pieces)


def semantic_display_summary(semantic: dict[str, Any]) -> str:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    readable = readable_raw_text(raw_data)
    summary = str(semantic.get("summary") or "").strip()
    if (not summary or summary.startswith("{")) and raw_data:
        summary = readable_raw_text(raw_data)
    return summary[:500]


def agenda_operation_for_text(text: str) -> str:
    if any(marker in text for marker in ["取消", "不去了", "不用去了", "不见面了", "不见面", "不用见面", "不用见", "别见面", "cancel", "canceled", "cancelled"]):
        return "cancel"
    if any(marker in text for marker in ["改到", "改成", "换到", "推迟", "提前", "改电话聊", "电话聊", "reschedule"]):
        return "reschedule"
    return "create"


def agenda_type_for_semantic(semantic: dict[str, Any], text: str) -> Optional[str]:
    intent = str(semantic.get("intent") or "")
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    labels = set(normalize_string_list(entities.get("labels")))
    primary_label = str(entities.get("primary_label") or "").strip()
    if primary_label:
        labels.add(primary_label)
    not_meeting_reminder = any(marker in text for marker in ["不是开会", "不是会议", "不是见面"]) and any(marker in text for marker in ["提醒", "别忘了"])
    explicit_todo_request = any(marker in text for marker in ["提醒我", "帮我提醒", "提醒你", "待办", "记得提醒", "设个提醒", "别忘了"])
    if "deadline" in labels or any(marker in text for marker in ["截止", "deadline", "due", "到期"]) or any(marker in text.lower() for marker in ["before ", " by "]):
        return "deadline"
    if not_meeting_reminder or explicit_todo_request or intent in {"task_request", "user_instruction", "待办"} and ("todo" in labels or "待办" in labels):
        return "todo"
    if intent in {"social_plan", "schedule", "约定", "日程"} or "appointment" in labels or has_meeting_text_signal(text):
        return "appointment"
    if intent in {"payment_reminder", "付款"} or "payment" in labels or any(marker in text for marker in ["付款", "支付", "账单", "发票", "还款"]):
        return "payment"
    if intent in {"task_request", "user_instruction", "待办"} or "todo" in labels or any(marker in text for marker in ["待办", "帮我", "提醒", "处理"]):
        return "todo"
    return None


def extract_agenda_participants(raw_data: dict[str, Any], semantic: dict[str, Any]) -> list[str]:
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    candidates = [
        raw_data.get("chat_name"),
        raw_data.get("sender"),
        raw_data.get("from"),
        entities.get("person"),
        entities.get("subject"),
    ]
    participants = raw_data.get("participants")
    if isinstance(participants, list):
        candidates.extend(participants)
    cleaned = []
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value and value.lower() not in {"user", "unknown", "nomi_chat", "gmail", "whatsapp"}:
            cleaned.append(value)
    return list(dict.fromkeys(cleaned))[:8]


def extract_place(text: str, raw_data: dict[str, Any]) -> str:
    explicit = str(raw_data.get("place") or raw_data.get("location") or "").strip()
    if explicit:
        return explicit
    suffixes = r"(?:路|街|店|站|机场|酒店|咖啡|餐厅|mall|plaza|广场|公园|中心|大厦|楼|园区)"
    location_marker_match = re.search(
        rf"(?:地点|位置|地址)\s*(?:还是|仍是|仍然是|在|是|为|:|：)?\s*([\u4e00-\u9fffA-Za-z0-9·.\- ]{{2,40}}{suffixes})",
        text,
        re.I,
    )
    if location_marker_match:
        return clean_place_text(location_marker_match.group(1))
    marker_match = re.search(rf"(?:在|去|到)([\u4e00-\u9fffA-Za-z0-9·.\- ]{{2,40}}{suffixes})", text, re.I)
    if marker_match:
        return clean_place_text(marker_match.group(1))
    trailing_match = re.search(
        rf"(?:"
        rf"(?:20\d{{2}}[-年/]\d{{1,2}}[-月/]\d{{1,2}}日?\s*)?"
        rf"(?:(?:今天|明天|后天|今晚|明晚|周[一二三四五六日天]|星期[一二三四五六日天])?\s*)?"
        rf"(?:(?:上午|下午|晚上|中午|早上)?\s*[0-2]?\d(?:点|[:：])(?:[0-5]?\d)?\s*)?"
        rf")([\u4e00-\u9fffA-Za-z0-9·.\- ]{{2,40}}{suffixes})\s*(?:见|见面|碰面|聊|开会|面试)",
        text,
        re.I,
    )
    if trailing_match:
        return clean_place_text(trailing_match.group(1))
    return ""


def clean_place_text(value: str) -> str:
    text = str(value or "").strip(" ，。；;,.!?！？")
    time_matches = list(TIME_OF_DAY_RE.finditer(text))
    if time_matches:
        after_time = text[time_matches[-1].end() :].strip(" ，。；;,.!?！？")
        if after_time:
            text = after_time
    text = re.sub(r"^(?:在|去|到)", "", text).strip()
    text = re.sub(r"^(?:今天|明天|后天|今晚|明晚|周[一二三四五六日天]|星期[一二三四五六日天])", "", text).strip()
    text = re.sub(r"^(?:上午|下午|晚上|中午|早上)?\s*[0-2]?\d(?:点|[:：])(?:[0-5]?\d)?", "", text).strip()
    return text[:180]


def agenda_source_for_semantic(semantic: dict[str, Any], raw_data: dict[str, Any]) -> str:
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    return str(entities.get("source") or raw_data.get("source") or "").strip()


def agenda_dedupe_key_for_semantic(
    agenda_type: str,
    source: str,
    raw_data: dict[str, Any],
    participants: list[str],
    *,
    operation: str = "create",
    time_window: Optional[dict[str, Any]] = None,
    place: str = "",
    text: str = "",
) -> str:
    conversation_key = normalize_entity_name(
        str(
            raw_data.get("conversation_id")
            or raw_data.get("chat_id")
            or raw_data.get("thread_id")
            or raw_data.get("chat_name")
            or raw_data.get("subject")
            or ",".join(participants)
            or source
            or agenda_type
        )
    )
    parts = [agenda_type, source or "unknown"]
    if operation not in {"update", "reschedule", "cancel"}:
        window = time_window if isinstance(time_window, dict) else {}
        exact_time_key = str(window.get("start") or window.get("start_at") or "").strip()
        time_key = str(exact_time_key or window.get("date") or window.get("display") or "").strip()
        place_key = normalize_entity_name(str(place or ""))
        if place_key in {"unknown", "未知", "待定", "none", "null"}:
            place_key = ""
        text_hash = agenda_semantic_text_hash(text or readable_raw_text(raw_data))
        if exact_time_key and text_hash:
            parts.append(normalize_entity_name(exact_time_key))
            parts.append(f"text-{text_hash}")
            if place_key:
                parts.append(place_key)
        else:
            parts.append(conversation_key)
        if time_key and place_key and not exact_time_key:
            parts.append(normalize_entity_name(time_key))
            parts.append(place_key)
    else:
        parts.append(conversation_key)
    dedupe_seed = ":".join(parts)
    return f"agenda:{dedupe_seed}"


LOW_VALUE_TELEMETRY_SOURCES = {
    "focus",
    "browser",
    "browser_focus",
    "browser_network",
    "browser_runtime",
    "chromium_runtime",
}

LOW_VALUE_TELEMETRY_EVENT_TYPES = {
    "deep_focus",
    "browser_focus_event",
    "browser_network_event",
    "runtime_network_hook",
    "page_title",
    "tab_focus",
    "browser_snapshot",
    "whatsapp_snapshot",
    "whatsapp_open_chat_snapshot",
}


NON_AGENDA_BROWSER_EVENT_TYPES = {
    "linkedin_job_description_snapshot",
    "linkedin_job_search_results",
    "linkedin_contact_snapshot",
    "linkedin_profile_snapshot",
    "linkedin_visible_snapshot",
    "linkedin_login_snapshot",
}


def is_non_agenda_browser_observation(semantic: dict[str, Any], raw_data: Optional[dict[str, Any]] = None) -> bool:
    raw = raw_data if isinstance(raw_data, dict) else semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    source = str(entities.get("source") or raw.get("source") or "").strip().lower()
    event_type = str(entities.get("event_type") or raw.get("event_type") or "").strip().lower()
    if event_type in NON_AGENDA_BROWSER_EVENT_TYPES:
        return True
    if source in {"linkedin", "linkedin_browser", "linkedin_browser_observation"} and any(
        key in raw for key in ("job_pages", "job_results", "profile_pages", "profile_results", "contact_results")
    ):
        return True
    return False


def is_low_value_telemetry_semantic(semantic: dict[str, Any], raw_data: Optional[dict[str, Any]] = None) -> bool:
    raw = raw_data if isinstance(raw_data, dict) else semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    source = str(entities.get("source") or raw.get("source") or "").strip().lower()
    event_type = str(entities.get("event_type") or raw.get("event_type") or "").strip().lower()
    summary = str(semantic.get("summary") or raw.get("title") or raw.get("url") or "").strip()
    has_user_message = any(str(raw.get(key) or "").strip() for key in ("message", "body", "text", "content", "subject"))
    if has_user_message:
        return False
    if source in LOW_VALUE_TELEMETRY_SOURCES or event_type in LOW_VALUE_TELEMETRY_EVENT_TYPES:
        return True
    if summary and re.search(r"\s[|｜-]\s|\bhttps?://|\b[A-Z][A-Za-z]+:", summary):
        return source in {"", "focus"} and not any(marker in summary for marker in ["见", "约", "提醒", "付款", "截止", "面试"])
    return False


def should_skip_generic_fact_graph_for_semantic(semantic: dict[str, Any], raw_data: Optional[dict[str, Any]] = None) -> bool:
    return is_non_agenda_browser_observation(semantic, raw_data)


def should_skip_agenda_candidate(semantic: dict[str, Any], raw_data: dict[str, Any]) -> bool:
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    source = agenda_source_for_semantic(semantic, raw_data)
    role = str(raw_data.get("role") or entities.get("role") or entities.get("person") or "").strip().lower()
    intent = str(semantic.get("intent") or "").strip()
    labels = set(normalize_string_list(entities.get("labels")))
    primary_label = str(entities.get("primary_label") or "").strip()
    if primary_label:
        labels.add(primary_label)
    actionable_labels = {
        "appointment",
        "deadline",
        "todo",
        "payment",
        "travel",
        "shopping",
        "followup",
        "reminder",
        "cancel",
        "reschedule",
        "约定",
        "待办",
        "截止日期",
        "付款",
        "出行",
        "购物",
        "取消",
        "改期",
    }
    if is_non_agenda_browser_observation(semantic, raw_data):
        return True
    if is_low_value_telemetry_semantic(semantic, raw_data):
        return True
    if source == "nomi_chat" and role == "assistant":
        return True
    if source == "nomi_chat" and role != "assistant":
        text = semantic_text(semantic)
        explicit_schedule_request = any(
            marker in text
            for marker in [
                "提醒我",
                "帮我提醒",
                "安排到日历",
                "创建日程",
                "加入日程",
                "建个日程",
                "设个提醒",
                "记得提醒",
            ]
        )
        if not explicit_schedule_request:
            return True
    if intent in {"普通聊天", "casual_chat", "small_talk"} and not labels.intersection(actionable_labels):
        return True
    return intent == "assistant_response"


def agenda_model_enabled() -> bool:
    return os.getenv("AGENDA_MODEL_ENABLED", "1").strip().lower() not in AGENDA_MODEL_DISABLED_VALUES


def normalize_support_text(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[，。！？、,.!?;；:：\"'“”‘’（）()【】\[\]{}<>《》-]", "", normalized)
    return normalized


def text_supports_model_value(value: Any, text: str) -> bool:
    normalized_value = normalize_support_text(value)
    if not normalized_value:
        return True
    return normalized_value in normalize_support_text(text)


def normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif value:
        raw_items = [value]
    else:
        raw_items = []
    cleaned = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text.lower() not in {"unknown", "none", "null"}:
            cleaned.append(text[:120])
    return list(dict.fromkeys(cleaned))


def bounded_float(value: Any, default: float = 0.0) -> float:
    try:
        return min(max(float(value), 0), 1)
    except (TypeError, ValueError):
        return default


def agenda_candidate_copy(candidate: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if candidate is None:
        return None
    return json.loads(json.dumps(candidate, ensure_ascii=False))


def parse_event_local_datetime(timestamp: str) -> datetime:
    try:
        value = str(timestamp or "").replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(USER_TIMEZONE)


def chinese_hour_to_int(value: str) -> Optional[int]:
    value = str(value or "").strip()
    if not value:
        return None
    if value.isdigit():
        hour = int(value)
        return hour if 0 <= hour <= 23 else None
    if value == "十":
        return 10
    if "十" in value:
        before, after = value.split("十", 1)
        tens = CHINESE_DIGITS.get(before, 1 if before == "" else 0)
        ones = CHINESE_DIGITS.get(after, 0) if after else 0
        hour = tens * 10 + ones
        return hour if 0 <= hour <= 23 else None
    hour = CHINESE_DIGITS.get(value)
    return hour if hour is not None and 0 <= hour <= 23 else None


def extract_time_of_day(text: str) -> Optional[tuple[int, int]]:
    match = TIME_OF_DAY_RE.search(text)
    if not match:
        english_match = EN_TIME_OF_DAY_RE.search(text)
        if english_match:
            raw_hour, raw_minute, meridiem = english_match.groups()
            hour = int(raw_hour)
            minute = int(raw_minute or "0")
            marker = meridiem.lower()
            if marker == "pm" and 1 <= hour < 12:
                hour += 12
            if marker == "am" and hour == 12:
                hour = 0
            return (hour, minute)
        if "中午" in text:
            return (12, 0)
        return None
    period, raw_hour, raw_minute = match.groups()
    hour = chinese_hour_to_int(raw_hour)
    if hour is None:
        return None
    minute = 30 if raw_minute == "半" else int(raw_minute or "0")
    implicit_evening = period is None and any(marker in text for marker in ["今晚", "明晚", "晚上"])
    if (period in {"下午", "晚上"} or implicit_evening) and 1 <= hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    return (hour, minute)


def resolve_agenda_date(text: str, event_dt: datetime) -> Optional[date]:
    explicit = EXPLICIT_DATE_RE.search(text)
    if explicit:
        year, month, day = (int(part) for part in explicit.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None
    if "后天" in text:
        return (event_dt + timedelta(days=2)).date()
    if "明天" in text:
        return (event_dt + timedelta(days=1)).date()
    if "今天" in text or "今晚" in text:
        return event_dt.date()
    weekday_match = WEEKDAY_RE.search(text)
    english_weekday_match = EN_WEEKDAY_RE.search(text) if not weekday_match else None
    if not weekday_match and not english_weekday_match:
        return None
    if weekday_match:
        next_week, raw_weekday = weekday_match.groups()
        target_weekday = CHINESE_WEEKDAYS.get(raw_weekday)
    else:
        next_week, raw_weekday = english_weekday_match.groups()  # type: ignore[union-attr]
        target_weekday = ENGLISH_WEEKDAYS.get(str(raw_weekday).lower())
    if target_weekday is None:
        return None
    days_until = (target_weekday - event_dt.weekday()) % 7
    if next_week:
        days_until += 7
    return (event_dt + timedelta(days=days_until)).date()


def resolved_agenda_time_window(text: str, timestamp: str) -> dict[str, Any]:
    event_dt = parse_event_local_datetime(timestamp)
    target_date = resolve_agenda_date(text, event_dt)
    time_of_day = extract_time_of_day(text)
    if target_date is None:
        return {"source_event_timestamp": event_dt.isoformat()}

    resolved: dict[str, Any] = {
        "date": target_date.isoformat(),
        "weekday": WEEKDAY_LABELS[target_date.weekday()],
        "source_event_timestamp": event_dt.isoformat(),
    }
    if time_of_day:
        hour, minute = time_of_day
        start = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=USER_TIMEZONE,
        )
        resolved["start"] = start.isoformat(timespec="seconds")
        resolved["display"] = f"{target_date.isoformat()} {resolved['weekday']} {hour:02d}:{minute:02d}"
    else:
        resolved["display"] = f"{target_date.isoformat()} {resolved['weekday']}"
    return resolved


def agenda_certainty_and_missing(text: str, place: str, agenda_type: str, operation: str, timestamp: str = "") -> tuple[str, list[str], dict[str, Any]]:
    has_exact_time = has_exact_agenda_time(text)
    has_fuzzy_time = has_fuzzy_agenda_time(text)
    missing_fields: list[str] = []
    if operation == "cancel":
        missing_fields = []
    elif not has_exact_time:
        missing_fields.append("exact_time")
    if agenda_type == "appointment" and operation != "cancel" and not place:
        missing_fields.append("exact_place")
    certainty = "fuzzy" if has_fuzzy_time or missing_fields else "exact"
    time_window = {
        "raw_text": text[:240],
        "has_exact_time": has_exact_time,
        "has_fuzzy_time": has_fuzzy_time,
    }
    time_window.update(resolved_agenda_time_window(text, timestamp))
    return certainty, missing_fields, time_window


def pending_artifacts_for_agenda_text(text: str) -> list[str]:
    pending_artifacts: list[str] = []
    if re.search(r"zoom", text, re.I) and any(marker in text for marker in ["稍后", "待发", "之后发", "晚点发"]):
        pending_artifacts.append("zoom_link")
    return pending_artifacts


def apply_pending_artifact_missing_fields(missing_fields: list[str], pending_artifacts: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(missing_fields))
    if "zoom_link" in pending_artifacts:
        normalized = [field for field in normalized if field != "exact_place"]
        if "exact_link" not in normalized:
            normalized.append("exact_link")
    return normalized


def agenda_candidate_from_semantic(event_id: str, timestamp: str, semantic: dict[str, Any]) -> Optional[dict[str, Any]]:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    if should_skip_agenda_candidate(semantic, raw_data):
        return None
    text = semantic_text(semantic)
    agenda_type = agenda_type_for_semantic(semantic, text)
    if not agenda_type:
        return None
    place = extract_place(text, raw_data)
    participants = extract_agenda_participants(raw_data, semantic)
    operation = agenda_operation_for_text(text)
    certainty, missing_fields, time_window = agenda_certainty_and_missing(text, place, agenda_type, operation, timestamp)
    status = "canceled" if operation == "cancel" else "scheduled"
    title = str(semantic_display_summary(semantic) or text or agenda_type).strip()[:180]
    source = agenda_source_for_semantic(semantic, raw_data)
    metadata = {
        "source": source,
        "dedupe_key": agenda_dedupe_key_for_semantic(
            agenda_type,
            source,
            raw_data,
            participants,
            operation=operation,
            time_window=time_window,
            place=place,
            text=text,
        ),
        "created_from": "semantic_event",
        "event_timestamp": timestamp,
    }
    pending_artifacts = pending_artifacts_for_agenda_text(text)
    missing_fields = apply_pending_artifact_missing_fields(missing_fields, pending_artifacts)
    if pending_artifacts and certainty == "exact":
        certainty = "fuzzy"
    if pending_artifacts:
        metadata["pending_artifacts"] = pending_artifacts
    return {
        "type": agenda_type,
        "title": title,
        "status": status,
        "certainty": certainty,
        "time_window": time_window,
        "place": place,
        "participants": participants,
        "missing_fields": missing_fields,
        "needs_clarification": bool(missing_fields),
        "confidence": min(max(float(semantic.get("importance") or 0.2), 0), 1),
        "source_event_ids": [event_id],
        "operation": operation,
        "metadata": metadata,
    }


def model_agenda_candidate_from_semantic(
    event_id: str,
    timestamp: str,
    semantic: dict[str, Any],
    rule_candidate: Optional[dict[str, Any]],
) -> tuple[Optional[dict[str, Any]], list[str]]:
    if not agenda_model_enabled():
        return None, ["agenda_model_disabled"]

    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    prompt = {
        "event_id": event_id,
        "event_timestamp": timestamp,
        "semantic": mask_value(
            {
                "intent": semantic.get("intent"),
                "importance": semantic.get("importance"),
                "summary": semantic.get("summary"),
                "entities": semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {},
            }
        ),
        "raw_data": mask_value(raw_data),
        "rule_candidate": mask_value(rule_candidate or {}),
        "output_schema": {
            "is_agenda": "boolean",
            "type": sorted(AGENDA_TYPES),
            "operation": sorted(AGENDA_OPERATIONS),
            "title": "short Chinese title grounded in evidence",
            "status": sorted(AGENDA_STATUSES),
            "certainty": sorted(AGENDA_CERTAINTIES),
            "time_window": "object with raw_text and optional exact fields only when source evidence is exact",
            "place": "place string only when supported by source evidence",
            "participants": "array",
            "missing_fields": "array, e.g. exact_time/exact_place",
            "needs_clarification": "boolean",
            "confidence": "0..1",
            "reason": "short evidence-based explanation",
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "你是 Nomi 的私有事件日程候选解析器。只输出 JSON。"
                "你的任务是提出候选，不是最终决策。"
                "严禁根据常识补全原文没有的精确时间、地点、金额或人名。"
                "如果只有周末、下周、找时间这类信息，certainty 必须是 fuzzy，并把 exact_time 放入 missing_fields。"
                "如果不是日程、待办、付款、出行、购物或截止日期，is_agenda=false。"
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    try:
        parsed = parse_model_json(call_model(messages))
    except Exception as exc:
        return None, [f"model_parse_failed:{exc.__class__.__name__}"]
    if not isinstance(parsed, dict):
        return None, ["model_candidate_not_object"]
    return parsed, []


def rules_fallback_agenda_candidate(
    rule_candidate: Optional[dict[str, Any]],
    model_candidate: Optional[dict[str, Any]],
    warnings: list[str],
) -> Optional[dict[str, Any]]:
    candidate = agenda_candidate_copy(rule_candidate)
    if not candidate:
        return None
    metadata = dict(candidate.get("metadata") or {})
    metadata["parser_mode"] = "rules_fallback"
    metadata["rule_candidate"] = agenda_candidate_copy(rule_candidate)
    metadata["validation_warnings"] = warnings or ["model_candidate_rejected"]
    if model_candidate is not None:
        metadata["model_candidate"] = model_candidate
    candidate["metadata"] = metadata
    return candidate


def rules_first_agenda_candidate(rule_candidate: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    candidate = agenda_candidate_copy(rule_candidate)
    if not candidate:
        return None
    metadata = dict(candidate.get("metadata") or {})
    metadata["parser_mode"] = "rules_first_exact"
    metadata["rule_candidate"] = agenda_candidate_copy(rule_candidate)
    metadata["validation_warnings"] = []
    candidate["metadata"] = metadata
    return candidate


def should_use_rules_first_agenda_candidate(rule_candidate: Optional[dict[str, Any]]) -> bool:
    if not rule_candidate:
        return False
    if rule_candidate.get("operation") not in {"create", "update", "reschedule"}:
        return False
    if str(rule_candidate.get("certainty") or "") != "exact":
        return False
    if rule_candidate.get("missing_fields"):
        return False
    if rule_candidate.get("needs_clarification"):
        return False
    if bounded_float(rule_candidate.get("confidence")) < 0.5:
        return False
    if rule_candidate.get("type") == "appointment" and not str(rule_candidate.get("place") or "").strip():
        return False
    time_window = rule_candidate.get("time_window") if isinstance(rule_candidate.get("time_window"), dict) else {}
    if not time_window.get("has_exact_time") or not time_window.get("start"):
        return False
    return True


def validated_model_fields_for_agenda(
    rule_candidate: Optional[dict[str, Any]],
    model_candidate: dict[str, Any],
    semantic: dict[str, Any],
    timestamp: str,
) -> tuple[Optional[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    text = semantic_text(semantic)
    source = agenda_source_for_semantic(semantic, raw_data)

    if model_candidate.get("is_agenda") is False:
        return None, ["model_said_not_agenda"]

    model_type = str(model_candidate.get("type") or "").strip()
    rule_type = rule_candidate.get("type") if rule_candidate else ""
    agenda_type = model_type if model_type in AGENDA_TYPES else str(rule_type or "")
    if not agenda_type:
        return None, ["missing_or_invalid_agenda_type"]
    if model_type and model_type not in AGENDA_TYPES:
        warnings.append("invalid_model_type")

    model_operation = str(model_candidate.get("operation") or "").strip()
    rule_operation = str(rule_candidate.get("operation") or "create") if rule_candidate else "create"
    if rule_operation in {"cancel", "reschedule"}:
        operation = rule_operation
        if model_operation and model_operation != rule_operation:
            warnings.append("rule_operation_overrode_model")
    elif model_operation in AGENDA_OPERATIONS:
        operation = model_operation
    else:
        operation = rule_operation if rule_operation in AGENDA_OPERATIONS else "create"
        if model_operation:
            warnings.append("invalid_model_operation")

    confidence = bounded_float(model_candidate.get("confidence"))
    if confidence < AGENDA_MODEL_MIN_CONFIDENCE and rule_candidate:
        return None, ["model_confidence_too_low"]

    rule_place = str(rule_candidate.get("place") or "") if rule_candidate else extract_place(text, raw_data)
    model_place = str(model_candidate.get("place") or "").strip()
    if model_place:
        if text_supports_model_value(model_place, text) or (
            rule_place and normalize_support_text(model_place) == normalize_support_text(rule_place)
        ):
            place = model_place[:180]
        else:
            warnings.append("unsupported_place")
            place = rule_place
    else:
        place = rule_place

    rule_certainty, rule_missing_fields, rule_time_window = agenda_certainty_and_missing(text, place, agenda_type, operation, timestamp)
    model_certainty = str(model_candidate.get("certainty") or "").strip()
    if model_certainty not in AGENDA_CERTAINTIES:
        model_certainty = rule_certainty
        warnings.append("invalid_model_certainty")

    model_time_window = model_candidate.get("time_window") if isinstance(model_candidate.get("time_window"), dict) else {}
    model_has_exact_time = model_certainty == "exact" or any(key in model_time_window for key in ["start", "end", "start_at", "end_at"])
    if model_has_exact_time and not rule_time_window.get("has_exact_time"):
        warnings.append("unsupported_exact_time")
        model_time_window = {}
        model_certainty = "fuzzy"

    certainty = "fuzzy" if rule_certainty == "fuzzy" or model_certainty == "fuzzy" else "exact"
    missing_fields = normalize_string_list(model_candidate.get("missing_fields"))
    for field in rule_missing_fields:
        if field not in missing_fields:
            missing_fields.append(field)
    rule_pending_artifacts = []
    if rule_candidate:
        rule_metadata = rule_candidate.get("metadata") if isinstance(rule_candidate.get("metadata"), dict) else {}
        rule_pending_artifacts = normalize_string_list(rule_metadata.get("pending_artifacts"))
    pending_artifacts = list(dict.fromkeys(rule_pending_artifacts + pending_artifacts_for_agenda_text(text)))
    missing_fields = apply_pending_artifact_missing_fields(missing_fields, pending_artifacts)
    if operation == "cancel":
        missing_fields = []
        certainty = model_certainty if model_certainty in AGENDA_CERTAINTIES else "exact"
    if model_has_exact_time and "unsupported_exact_time" in warnings and "exact_time" not in missing_fields:
        missing_fields.append("exact_time")
    if agenda_type == "appointment" and operation != "cancel" and not place and "exact_place" not in missing_fields:
        missing_fields.append("exact_place")

    participants = normalize_string_list(model_candidate.get("participants"))
    if not participants:
        participants = list(rule_candidate.get("participants") or []) if rule_candidate else extract_agenda_participants(raw_data, semantic)
    else:
        rule_participants = list(rule_candidate.get("participants") or []) if rule_candidate else extract_agenda_participants(raw_data, semantic)
        participants = list(dict.fromkeys(participants + rule_participants))[:8]

    title = str(model_candidate.get("title") or "").strip()[:180]
    if not title:
        title = str(rule_candidate.get("title") if rule_candidate else semantic.get("summary") or agenda_type).strip()[:180]
    elif "unsupported_exact_time" in warnings and EXACT_TIME_RE.search(title):
        warnings.append("unsupported_title_detail")
        title = str(rule_candidate.get("title") if rule_candidate else semantic.get("summary") or agenda_type).strip()[:180]

    status = str(model_candidate.get("status") or "").strip()
    if operation == "cancel":
        status = "canceled"
    elif status not in AGENDA_STATUSES:
        status = str(rule_candidate.get("status") or "scheduled") if rule_candidate else "scheduled"

    time_window = dict(rule_time_window)
    if model_time_window:
        time_window.update({str(key): value for key, value in model_time_window.items() if str(key) not in {"start", "end", "start_at", "end_at"}})
    time_window["rule_has_exact_time"] = bool(rule_time_window.get("has_exact_time"))

    metadata = dict(rule_candidate.get("metadata") or {}) if rule_candidate else {}
    if pending_artifacts:
        metadata["pending_artifacts"] = pending_artifacts
    metadata.update(
        {
            "source": source,
            "dedupe_key": metadata.get("dedupe_key")
            or agenda_dedupe_key_for_semantic(
                agenda_type,
                source,
                raw_data,
                participants,
                operation=operation,
                time_window=time_window,
                place=place,
                text=text,
            ),
            "created_from": "semantic_event",
            "event_timestamp": metadata.get("event_timestamp") or timestamp,
            "parser_mode": "hybrid_model_rules",
            "model_candidate": model_candidate,
            "rule_candidate": agenda_candidate_copy(rule_candidate),
            "validation_warnings": warnings,
            "model_reason": str(model_candidate.get("reason") or "")[:500],
        }
    )

    return {
        "type": agenda_type,
        "title": title,
        "status": status,
        "certainty": certainty,
        "time_window": time_window,
        "place": place,
        "participants": participants[:8],
        "missing_fields": missing_fields,
        "needs_clarification": bool(missing_fields) or bool(model_candidate.get("needs_clarification")),
        "confidence": (
            max(confidence, bounded_float(rule_candidate.get("confidence")) if rule_candidate else 0)
            if not warnings
            else bounded_float(rule_candidate.get("confidence"), confidence) if rule_candidate else confidence
        ),
        "source_event_ids": list(rule_candidate.get("source_event_ids") or []) if rule_candidate else [],
        "operation": operation,
        "metadata": metadata,
    }, warnings


def hybrid_agenda_candidate_from_semantic(event_id: str, timestamp: str, semantic: dict[str, Any]) -> Optional[dict[str, Any]]:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    if should_skip_agenda_candidate(semantic, raw_data):
        return None
    rule_candidate = agenda_candidate_from_semantic(event_id, timestamp, semantic)
    if should_use_rules_first_agenda_candidate(rule_candidate):
        return rules_first_agenda_candidate(rule_candidate)
    model_candidate, model_warnings = model_agenda_candidate_from_semantic(event_id, timestamp, semantic, rule_candidate)
    if model_warnings and model_candidate is None:
        return rules_fallback_agenda_candidate(rule_candidate, model_candidate, model_warnings)
    if model_candidate is None:
        return rules_fallback_agenda_candidate(rule_candidate, model_candidate, ["model_candidate_missing"])

    validated, validation_warnings = validated_model_fields_for_agenda(rule_candidate, model_candidate, semantic, timestamp)
    warnings = model_warnings + validation_warnings
    if not validated:
        if "model_said_not_agenda" in warnings:
            return None
        return rules_fallback_agenda_candidate(rule_candidate, model_candidate, warnings)
    if event_id not in validated["source_event_ids"]:
        validated["source_event_ids"].append(event_id)
    validated["metadata"]["validation_warnings"] = warnings
    return validated


def normalize_agenda_stored_value(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, list):
        return [str(item) if isinstance(item, uuid.UUID) else item for item in value]
    return value


def agenda_previous_value_from_row(row: Any) -> dict[str, Any]:
    if not row or len(row) < 13:
        return {}
    return {
        "type": row[1],
        "title": row[2],
        "status": row[3],
        "certainty": row[4],
        "time_window": normalize_agenda_stored_value(row[5]),
        "place": row[6] or "",
        "participants": normalize_agenda_stored_value(row[7]) or [],
        "missing_fields": normalize_agenda_stored_value(row[8]) or [],
        "needs_clarification": bool(row[9]),
        "confidence": bounded_float(row[10]),
        "source_event_ids": [str(item) for item in (normalize_agenda_stored_value(row[11]) or [])],
        "metadata": normalize_agenda_stored_value(row[12]) or {},
    }


def parse_agenda_start_datetime(time_window: Any) -> Optional[datetime]:
    if not isinstance(time_window, dict):
        return None
    raw_start = str(time_window.get("start") or time_window.get("start_at") or "").strip()
    if not raw_start:
        return None
    try:
        parsed = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=USER_TIMEZONE)
    return parsed.astimezone(USER_TIMEZONE)


def agenda_candidate_text(candidate: dict[str, Any]) -> str:
    time_window = candidate.get("time_window") if isinstance(candidate.get("time_window"), dict) else {}
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    return "\n".join(
        str(piece or "")
        for piece in [
            candidate.get("title"),
            candidate.get("place"),
            time_window.get("raw_text"),
            metadata.get("model_reason"),
        ]
        if piece
    )


def agenda_reminder_policy_for_candidate(candidate: dict[str, Any]) -> Optional[dict[str, Any]]:
    if str(candidate.get("status") or "").strip().lower() in {"canceled", "cancelled", "completed", "done", "dismissed"}:
        return None
    time_window = candidate.get("time_window") if isinstance(candidate.get("time_window"), dict) else {}
    if not time_window.get("has_exact_time") and not time_window.get("rule_has_exact_time"):
        return None
    if not parse_agenda_start_datetime(time_window):
        return None
    text = agenda_candidate_text(candidate)
    place = str(candidate.get("place") or "").strip()
    candidate_type = str(candidate.get("type") or "").strip().lower()
    if candidate_type == "deadline" or DEADLINE_EVENT_RE.search(text):
        return {
            "event_modality": "deadline",
            "lead_minutes": 60,
            "reason": "detected_deadline",
            "confidence": 0.82,
        }
    if place:
        return {
            "event_modality": "offline",
            "lead_minutes": 40,
            "reason": "detected_physical_location",
            "confidence": 0.86,
        }
    if ONLINE_EVENT_RE.search(text):
        return {
            "event_modality": "online",
            "lead_minutes": 10,
            "reason": "detected_online_meeting",
            "confidence": 0.84,
        }
    return {
        "event_modality": "online_or_no_travel_required",
        "lead_minutes": 10,
        "reason": "no_physical_location_detected",
        "confidence": 0.58,
    }


def agenda_reminder_actions(policy: dict[str, Any]) -> list[dict[str, Any]]:
    modality = str(policy.get("event_modality") or "")
    if modality == "offline":
        return [
            {
                "id": "route_lookup",
                "label": "查路线",
                "kind": "tool_intent",
                "risk": "read_only",
                "requires_confirmation": False,
                "next_step": "route_lookup",
            },
            {
                "id": "ride_prepare",
                "label": "帮我打车",
                "kind": "tool_intent",
                "risk": "external_execution",
                "requires_confirmation": True,
                "next_step": "prepare_ride_request",
            },
            {
                "id": "snooze",
                "label": "稍后提醒",
                "kind": "local",
                "risk": "local_only",
                "requires_confirmation": False,
                "next_step": "snooze_suggestion",
            },
        ]
    if modality == "deadline":
        return [
            {
                "id": "review_task",
                "label": "查看待办",
                "kind": "local",
                "risk": "local_only",
                "requires_confirmation": False,
                "next_step": "open_task_context",
            },
            {
                "id": "snooze",
                "label": "稍后提醒",
                "kind": "local",
                "risk": "local_only",
                "requires_confirmation": False,
                "next_step": "snooze_suggestion",
            },
        ]
    return [
        {
            "id": "open_meeting",
            "label": "打开会议",
            "kind": "tool_intent",
            "risk": "read_only",
            "requires_confirmation": False,
            "next_step": "open_meeting_link",
        },
        {
            "id": "snooze",
            "label": "稍后提醒",
            "kind": "local",
            "risk": "local_only",
            "requires_confirmation": False,
            "next_step": "snooze_suggestion",
        },
    ]


def display_agenda_start(starts_at: datetime, time_window: dict[str, Any]) -> str:
    display = str(time_window.get("display") or "").strip()
    if display:
        return display
    weekday = WEEKDAY_LABELS[starts_at.weekday()]
    return f"{starts_at.date().isoformat()} {weekday} {starts_at.hour:02d}:{starts_at.minute:02d}"


def agenda_reminder_title_and_body(candidate: dict[str, Any], starts_at: datetime, policy: dict[str, Any]) -> tuple[str, str]:
    time_window = candidate.get("time_window") if isinstance(candidate.get("time_window"), dict) else {}
    place = str(candidate.get("place") or "").strip()
    title_text = str(candidate.get("title") or "").strip(" 。.!！?？")[:80]
    display_time = display_agenda_start(starts_at, time_window)
    if policy.get("event_modality") == "offline":
        short = f"{place}见面" if place else title_text or "线下日程"
        title = f"即将出发：{short}"[:120]
        body = f"提醒：你 {display_time} 要去{place}见面。"
        if "带合同" in title_text:
            body = body.rstrip("。") + "，记得带合同。"
        return title, body
    if policy.get("event_modality") == "deadline":
        title = f"截止提醒：{title_text or '待办事项'}"[:120]
        body = f"提醒：你需要在 {display_time} 前完成：{title_text or '这项待办'}。"
        return title, body
    title = f"即将开始：{title_text or '线上日程'}"[:120]
    body = f"提醒：你 {display_time} 有线上日程，可以提前打开会议链接。"
    return title, body


def upsert_agenda_reminder_for_candidate(conn: psycopg.Connection, agenda_id: Any, candidate: dict[str, Any]) -> None:
    policy = agenda_reminder_policy_for_candidate(candidate)
    if not policy:
        conn.execute(
            """
            UPDATE agenda_reminders
            SET status = 'canceled', updated_at = now()
            WHERE agenda_item_id = %s AND status = 'pending'
            """,
            (agenda_id,),
        )
        return
    time_window = candidate.get("time_window") if isinstance(candidate.get("time_window"), dict) else {}
    starts_at = parse_agenda_start_datetime(time_window)
    if starts_at is None:
        return
    lead_minutes = int(policy["lead_minutes"])
    remind_at = starts_at - timedelta(minutes=lead_minutes)
    dedupe_key = f"agenda_reminder:{agenda_id}:{starts_at.isoformat(timespec='seconds')}:{lead_minutes}m"
    title, body = agenda_reminder_title_and_body(candidate, starts_at, policy)
    metadata = {
        "source": (candidate.get("metadata") or {}).get("source") if isinstance(candidate.get("metadata"), dict) else "",
        "agenda_item_id": str(agenda_id),
        "agenda_title": candidate.get("title"),
        "starts_at": starts_at.isoformat(timespec="seconds"),
        "remind_at": remind_at.isoformat(timespec="seconds"),
        "lead_minutes": lead_minutes,
        "reminder_policy": policy,
        "time_window": time_window,
        "place": candidate.get("place") or "",
        "participants": candidate.get("participants") or [],
        "source_event_ids": [str(item) for item in candidate.get("source_event_ids") or []],
        "dedupe_key": dedupe_key,
        "actions": agenda_reminder_actions(policy),
    }
    conn.execute(
        """
        UPDATE agenda_reminders
        SET status = 'canceled', updated_at = now()
        WHERE agenda_item_id = %s AND status = 'pending' AND dedupe_key <> %s
        """,
        (agenda_id, dedupe_key),
    )
    conn.execute(
        """
        INSERT INTO agenda_reminders
          (id, agenda_item_id, starts_at, remind_at, lead_minutes, dedupe_key, title, body, metadata, status, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', now())
        ON CONFLICT (dedupe_key) DO UPDATE SET
          starts_at = EXCLUDED.starts_at,
          remind_at = EXCLUDED.remind_at,
          lead_minutes = EXCLUDED.lead_minutes,
          title = EXCLUDED.title,
          body = EXCLUDED.body,
          metadata = EXCLUDED.metadata,
          status = 'pending',
          sent_at = NULL,
          updated_at = now()
        """,
        (
            uuid.uuid4(),
            agenda_id,
            starts_at,
            remind_at,
            lead_minutes,
            dedupe_key,
            title,
            body,
            json.dumps(metadata, ensure_ascii=False),
        ),
    )


def persist_agenda(conn: psycopg.Connection, event_id: str, timestamp: str, semantic: dict[str, Any]) -> None:
    ensure_agenda_schema(conn)
    candidate = hybrid_agenda_candidate_from_semantic(event_id, timestamp, semantic)
    if not candidate:
        return
    dedupe_key = candidate["metadata"]["dedupe_key"]
    existing_cursor = conn.execute(
        """
        SELECT id, type, title, status, certainty, time_window, place, participants, missing_fields,
               needs_clarification, confidence, source_event_ids, metadata
        FROM agenda_items
        WHERE metadata->>'dedupe_key' = %s
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (dedupe_key,),
    )
    existing = existing_cursor.fetchone() if hasattr(existing_cursor, "fetchone") else None
    agenda_id = existing[0] if existing else uuid.uuid4()
    previous_value = agenda_previous_value_from_row(existing)
    new_value = {
        key: candidate[key]
        for key in [
            "type",
            "title",
            "status",
            "certainty",
            "time_window",
            "place",
            "participants",
            "missing_fields",
            "needs_clarification",
            "confidence",
        ]
    }
    new_value["source_event_ids"] = [str(item) for item in candidate["source_event_ids"]]
    new_value["metadata"] = candidate["metadata"]
    if existing:
        conn.execute(
            """
            UPDATE agenda_items
            SET title = %s,
                status = %s,
                certainty = %s,
                time_window = %s,
                place = %s,
                participants = %s,
                missing_fields = %s,
                needs_clarification = %s,
                confidence = GREATEST(confidence, %s),
                source_event_ids = (
                  SELECT ARRAY(SELECT DISTINCT unnest(agenda_items.source_event_ids || ARRAY[%s]::UUID[]))
                ),
                metadata = %s,
                updated_at = now()
            WHERE id = %s
            """,
            (
                candidate["title"],
                candidate["status"],
                candidate["certainty"],
                json.dumps(candidate["time_window"], ensure_ascii=False),
                candidate["place"] or None,
                json.dumps(candidate["participants"], ensure_ascii=False),
                json.dumps(candidate["missing_fields"], ensure_ascii=False),
                candidate["needs_clarification"],
                candidate["confidence"],
                event_id,
                json.dumps(candidate["metadata"], ensure_ascii=False),
                agenda_id,
            ),
        )
    else:
        cursor = conn.execute(
            """
            INSERT INTO agenda_items
              (id, title, type, status, certainty, time_window, participants, missing_fields,
               needs_clarification, confidence, source_event_ids, metadata, place, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ARRAY[%s]::UUID[], %s, %s, now())
            RETURNING id
            """,
            (
                agenda_id,
                candidate["title"],
                candidate["type"],
                candidate["status"],
                candidate["certainty"],
                json.dumps(candidate["time_window"], ensure_ascii=False),
                json.dumps(candidate["participants"], ensure_ascii=False),
                json.dumps(candidate["missing_fields"], ensure_ascii=False),
                candidate["needs_clarification"],
                candidate["confidence"],
                event_id,
                json.dumps(candidate["metadata"], ensure_ascii=False),
                candidate["place"] or None,
            ),
        )
        returned = cursor.fetchone() if hasattr(cursor, "fetchone") else None
        agenda_id = returned[0] if returned else agenda_id
    conn.execute(
        """
        INSERT INTO agenda_item_versions
          (id, agenda_item_id, operation, previous_value, new_value, reason, source_event_ids, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, ARRAY[%s]::UUID[], %s)
        """,
        (
            uuid.uuid4(),
            agenda_id,
            candidate["operation"] if existing else "create",
            json.dumps(previous_value, ensure_ascii=False),
            json.dumps(new_value, ensure_ascii=False),
            f"{candidate['operation']} agenda from semantic event: {candidate['title']}",
            event_id,
            candidate["confidence"],
        ),
    )
    upsert_agenda_reminder_for_candidate(conn, agenda_id, candidate)


def persist_memory_enrichment(
    conn: psycopg.Connection,
    event_id: str,
    timestamp: str,
    semantic: dict[str, Any],
    source: str,
    event_type: str,
) -> None:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    if not should_skip_generic_fact_graph_for_semantic(semantic, raw_data):
        persist_fact_graph_and_state(conn, event_id, timestamp, semantic)
    persist_vector(conn, event_id, source, event_type, semantic)


def persist_memory_enrichment_batch(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    start_ms = time.perf_counter() * 1000.0
    with psycopg.connect(DATABASE_URL) as conn:
        for item in items:
            persist_memory_enrichment(
                conn,
                str(item["event_id"]),
                str(item["timestamp"]),
                item["semantic"],
                str(item["source"]),
                str(item["event_type"]),
            )
    elapsed = max(0, int(time.perf_counter() * 1000.0 - start_ms))
    print(f"worker memory batch enriched count={len(items)} latency_ms={elapsed}", flush=True)


def create_memory_batcher() -> MemoryBatcher:
    return MemoryBatcher(
        max_items=WORKER_MEMORY_BATCH_SIZE,
        max_age_seconds=WORKER_MEMORY_BATCH_MAX_AGE_SECONDS,
        flush_fn=persist_memory_enrichment_batch,
    )


def persist_semantics(
    conn: psycopg.Connection,
    event_id: str,
    timestamp: str,
    semantic: dict[str, Any],
    redis_client: Any = None,
    memory_batcher: MemoryBatcher | None = None,
) -> None:
    semantic_id = uuid.uuid4()
    cursor = conn.execute(
        """
        INSERT INTO semantic_events
          (id, event_id, intent, entities, importance, summary, model_version)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (event_id) DO NOTHING
        """,
        (
            semantic_id,
            event_id,
            semantic["intent"],
            json.dumps(semantic["entities"], ensure_ascii=False),
            semantic["importance"],
            semantic["summary"],
            semantic["model_version"],
        ),
    )
    if not cursor.rowcount:
        try:
            persist_linkedin_job_search_opportunities(conn, event_id, semantic)
        except Exception as exc:
            print(f"worker linkedin opportunity backfill failed event_id={event_id} error={exc!r}", flush=True)
        return
    if is_low_value_telemetry_semantic(semantic):
        return
    source_cursor = conn.execute(
        "SELECT source, event_type FROM events WHERE event_id = %s",
        (event_id,),
    )
    source_row = source_cursor.fetchone() if hasattr(source_cursor, "fetchone") else None
    source = source_row[0] if source_row else "unknown"
    event_type = source_row[1] if source_row else "unknown"
    if memory_batcher is None:
        persist_memory_enrichment(conn, event_id, timestamp, semantic, source, event_type)
    else:
        memory_batcher.add(
            {
                "event_id": event_id,
                "timestamp": timestamp,
                "semantic": semantic,
                "source": source,
                "event_type": event_type,
            }
        )
    try:
        written_jobs = persist_linkedin_job_search_opportunities(conn, event_id, semantic)
        if written_jobs:
            print(f"worker linkedin opportunities persisted event_id={event_id} count={written_jobs}", flush=True)
    except Exception as exc:
        print(f"worker linkedin opportunity persistence failed event_id={event_id} error={exc!r}", flush=True)
    persist_agenda(conn, event_id, timestamp, semantic)
    persist_suggestion(conn, event_id, semantic, redis_client=redis_client)
    if semantic["importance"] >= 0.7:
        conn.execute(
            """
            INSERT INTO working_memory (key, value, expires_at, updated_at)
            VALUES (%s, %s, now() + interval '72 hours', now())
            ON CONFLICT (key) DO UPDATE SET
              value = EXCLUDED.value,
              expires_at = EXCLUDED.expires_at,
              updated_at = now()
            """,
            (
                f"active:{semantic['intent']}",
                json.dumps({"summary": semantic["summary"], "event_id": event_id}, ensure_ascii=False),
            ),
        )
    day = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date()
    conn.execute(
        """
        INSERT INTO timeline (id, date, summary, source_event_ids)
        VALUES (%s, %s, %s, ARRAY[%s]::UUID[])
        """,
        (uuid.uuid4(), day, semantic["summary"], event_id),
    )


def _decode_redis_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def resolve_start_id(redis_client: Any) -> str:
    checkpoint = ""
    try:
        checkpoint = _decode_redis_value(redis_client.get(WORKER_CHECKPOINT_KEY)).strip()
    except Exception:
        checkpoint = ""
    if checkpoint:
        return checkpoint
    configured = str(REDIS_START_ID or "").strip()
    if not configured or configured == "$":
        return "0-0"
    return configured


def record_worker_checkpoint(redis_client: Any, message_id: str) -> None:
    try:
        redis_client.set(WORKER_CHECKPOINT_KEY, message_id)
    except Exception as exc:
        print(f"worker checkpoint write failed message_id={message_id} error={exc!r}", flush=True)


def deadletter_stream_entry(redis_client: Any, message_id: str, fields: dict[str, Any], error: Exception) -> None:
    try:
        redis_client.xadd(
            WORKER_DEADLETTER_STREAM,
            {
                "message_id": message_id,
                "event_id": str(fields.get("event_id") or ""),
                "source": str(fields.get("source") or ""),
                "event_type": str(fields.get("event_type") or ""),
                "timestamp": str(fields.get("timestamp") or ""),
                "error": repr(error)[:1000],
                "raw_data": str(fields.get("raw_data") or "")[:10000],
            },
        )
    except Exception as exc:
        print(f"worker deadletter write failed message_id={message_id} error={exc!r}", flush=True)


def is_retryable_worker_error(error: Exception) -> bool:
    retryable_types = tuple(
        error_type
        for error_type in (
            getattr(psycopg, "OperationalError", None),
            getattr(psycopg, "InterfaceError", None),
        )
        if isinstance(error_type, type)
    )
    if retryable_types and isinstance(error, retryable_types):
        return True
    text = repr(error).lower()
    return any(marker in text for marker in ["connection failed", "server closed the connection", "timeout expired"])


def process_stream_entry_result(
    redis_client: Any,
    message_id: str,
    fields: dict[str, Any],
    memory_batcher: MemoryBatcher | None = None,
    record_checkpoint: bool = True,
) -> StreamProcessResult:
    try:
        raw_data = json.loads(fields["raw_data"])
        masked = mask_value(raw_data)
        semantic = extract_semantics(fields["source"], fields["event_type"], masked)
        semantic["raw_data"] = masked
        with psycopg.connect(DATABASE_URL) as conn:
            if memory_batcher is None:
                persist_semantics(conn, fields["event_id"], fields["timestamp"], semantic, redis_client=redis_client)
            else:
                persist_semantics(
                    conn,
                    fields["event_id"],
                    fields["timestamp"],
                    semantic,
                    redis_client=redis_client,
                    memory_batcher=memory_batcher,
                )
        if record_checkpoint:
            record_worker_checkpoint(redis_client, message_id)
        print(
            "worker processed "
            f"message_id={message_id} event_id={fields.get('event_id')} "
            f"source={fields.get('source')} event_type={fields.get('event_type')} "
            f"intent={semantic.get('intent')}",
            flush=True,
        )
        return StreamProcessResult(success=True, checkpoint=True)
    except Exception as exc:
        deadletter_stream_entry(redis_client, message_id, fields, exc)
        retryable = is_retryable_worker_error(exc)
        if record_checkpoint and not retryable:
            record_worker_checkpoint(redis_client, message_id)
        print(
            "worker failed "
            f"message_id={message_id} event_id={fields.get('event_id')} "
            f"source={fields.get('source')} event_type={fields.get('event_type')} "
            f"retryable={retryable} error={exc!r}",
            flush=True,
        )
        return StreamProcessResult(success=False, checkpoint=not retryable)


def process_stream_entry(
    redis_client: Any,
    message_id: str,
    fields: dict[str, Any],
    memory_batcher: MemoryBatcher | None = None,
    record_checkpoint: bool = True,
) -> bool:
    return process_stream_entry_result(
        redis_client,
        message_id,
        fields,
        memory_batcher=memory_batcher,
        record_checkpoint=record_checkpoint,
    ).success


def stream_entry_priority(entry: tuple[str, dict[str, Any]]) -> tuple[int, str]:
    message_id, fields = entry
    source = str(fields.get("source") or "").strip().lower()
    event_type = str(fields.get("event_type") or "").strip().lower()
    if source in {"whatsapp", "gmail", "telegram", "calendar"} and event_type not in LOW_VALUE_TELEMETRY_EVENT_TYPES:
        return (0, message_id)
    if source in LOW_VALUE_TELEMETRY_SOURCES or event_type in LOW_VALUE_TELEMETRY_EVENT_TYPES:
        return (2, message_id)
    return (1, message_id)


def stream_batch_checkpoint_id(entries: list[tuple[str, dict[str, Any]]]) -> str:
    return entries[-1][0] if entries else "0-0"


def select_stream_entries_for_processing(
    entries: list[tuple[str, dict[str, Any]]],
    max_items: int = WORKER_STREAM_PROCESS_COUNT,
) -> list[tuple[str, dict[str, Any]]]:
    if not entries:
        return []
    return sorted(entries, key=stream_entry_priority)[: max(1, int(max_items))]


def stream_entry_lock_key(entry: tuple[str, dict[str, Any]]) -> str:
    message_id, fields = entry
    source = str(fields.get("source") or "unknown").strip().lower()
    raw_data: dict[str, Any] = {}
    try:
        parsed = json.loads(str(fields.get("raw_data") or "{}"))
        if isinstance(parsed, dict):
            raw_data = parsed
    except json.JSONDecodeError:
        raw_data = {}
    for key in (
        "conversation_id",
        "chat_id",
        "thread_id",
        "message_thread_id",
        "counterparty_id",
        "from",
        "sender",
    ):
        value = raw_data.get(key) or fields.get(key)
        if value:
            return f"{source}:{key}:{value}"
    return f"{source}:event:{fields.get('event_id') or message_id}"


def process_stream_entries_batch(
    redis_client: Any,
    entries: list[tuple[str, dict[str, Any]]],
    *,
    memory_batcher: MemoryBatcher,
    lock_registry: DedupeLockRegistry,
    max_workers: int = WORKER_CONCURRENCY,
) -> list[bool]:
    pending = list(entries)
    results: list[bool] = []
    results_by_message_id: dict[str, StreamProcessResult] = {}
    while pending:
        selected_entries = select_stream_entries_for_processing(pending, max_items=WORKER_STREAM_PROCESS_COUNT)
        selected_ids = {entry[0] for entry in selected_entries}
        selected_results = process_entries_with_locks(
            selected_entries,
            process_fn=lambda entry: process_stream_entry_result(
                redis_client,
                entry[0],
                entry[1],
                memory_batcher=memory_batcher,
                record_checkpoint=False,
            ),
            key_fn=stream_entry_lock_key,
            lock_registry=lock_registry,
            max_workers=max_workers,
        )
        for entry, result in zip(selected_entries, selected_results):
            results_by_message_id[entry[0]] = result
            results.append(result.success)
        pending = [entry for entry in pending if entry[0] not in selected_ids]
    checkpoint_id = ""
    for message_id, _ in entries:
        result = results_by_message_id.get(message_id)
        if result is None:
            break
        if result.success or result.checkpoint:
            checkpoint_id = message_id
            continue
        break
    if checkpoint_id:
        record_worker_checkpoint(redis_client, checkpoint_id)
    return results


def main() -> None:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    last_id = resolve_start_id(client)
    memory_batcher = create_memory_batcher()
    lock_registry = DedupeLockRegistry()
    last_reminder_scan_at = 0.0
    print(f"worker starting stream={WORKER_STREAM_KEY} start_id={last_id}", flush=True)
    while True:
        last_reminder_scan_at = maybe_dispatch_due_agenda_reminders(client, last_reminder_scan_at)
        messages = client.xread({WORKER_STREAM_KEY: last_id}, count=max(WORKER_STREAM_READ_COUNT, WORKER_STREAM_PROCESS_COUNT), block=5000)
        if not messages:
            memory_batcher.flush_due()
            last_reminder_scan_at = maybe_dispatch_due_agenda_reminders(client, last_reminder_scan_at)
            continue
        for _, entries in messages:
            process_stream_entries_batch(
                client,
                entries,
                memory_batcher=memory_batcher,
                lock_registry=lock_registry,
                max_workers=WORKER_CONCURRENCY,
            )
            last_id = resolve_start_id(client)
        memory_batcher.flush_due()
        last_reminder_scan_at = maybe_dispatch_due_agenda_reminders(client, last_reminder_scan_at)
        time.sleep(0.1)


if __name__ == "__main__":
    main()
