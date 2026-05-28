import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import psycopg
import redis

from app.vector import embedding_status, text_embedding_with_provider, vector_literal


DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
MODEL_MODE = os.getenv("MODEL_MODE", "standard")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:9161").rstrip("/")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.6")
MODEL_ROUTER_URL = os.getenv("MODEL_ROUTER_URL", "").rstrip("/")
REDIS_START_ID = os.getenv("REDIS_START_ID", "$")
REALTIME_CHANNEL = os.getenv("REALTIME_CHANNEL", "par:realtime")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d -]{7,}\d)(?!\d)")
URL_QUERY_RE = re.compile(r"([?&])([^=#&]+)=([^&#]+)")
SENSITIVE_KEY_RE = re.compile(r"(token|secret|cookie|session|password|passwd|auth|code|验证码|校验码|verification)", re.I)
INLINE_SECRET_RE = re.compile(r"\b(token|secret|sessionid|session|password|passwd|auth|code)=([^,\s&;]+)", re.I)
OAUTH_FRAGMENT_RE = re.compile(r"([#&])(access_token|id_token|refresh_token|state|token|code)=([^&#]+)", re.I)
BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)
VERIFICATION_CODE_RE = re.compile(r"((?:验证码|校验码|verification code|code)[^\dA-Za-z]{0,8})([A-Za-z0-9-]{4,12})", re.I)
ORDER_ID_RE = re.compile(r"((?:订单号|订单|order(?: id)?)[^\dA-Za-z]{0,8})([A-Za-z0-9-]{5,24})", re.I)
ID_CARD_RE = re.compile(r"((?:身份证号?|id card)[^\dA-Za-z]{0,8})(\d{17}[\dXx])", re.I)
PASSPORT_RE = re.compile(r"((?:护照|passport)[^\dA-Za-z]{0,8})([A-Z]{1,2}\d{6,9})", re.I)
BANK_CARD_RE = re.compile(r"((?:银行卡|卡号|bank card)[^\dA-Za-z]{0,8})(\d(?:[ -]?\d){12,18})", re.I)
AMOUNT_RE = re.compile(r"(?<![\dA-Za-z_:])(?:¥|￥|RMB\s*)?\d{1,7}(?:\.\d{2})?\s*(?:元|CNY|USD|美元)?(?![\dA-Za-z_:])", re.I)
CHINESE_ADDRESS_RE = re.compile(
    r"((?:收货地址|地址)[：:\s]*)([^，。；;\\n]{6,80}(?:号|室|楼|层|单元|弄|路|街|大道|巷|村|县|区|市))"
)
ENTITY_CLEAN_RE = re.compile(r"^[\s\W_]+|[\s\W_]+$")
EXACT_TIME_RE = re.compile(r"\d{1,2}[:：点]\d{0,2}|[一二三四五六七八九十两]{1,3}点|上午|下午|晚上|中午|早上")
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


def mask_value(value: Any) -> Any:
    if isinstance(value, str):
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


def rule_extract_nomi_chat_semantics(event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
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
        summary = raw_data.get("message") or raw_data.get("query") or raw_data.get("subject") or raw_data.get("title") or text[:180]
    return {
        "intent": intent,
        "entities": entities,
        "importance": importance,
        "summary": str(summary)[:500],
        "model_version": f"{MODEL_MODE}:rules-v0",
    }


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


def rule_event_labels(source: str, event_type: str, raw_data: dict[str, Any], semantic: dict[str, Any]) -> list[str]:
    text = event_label_text(raw_data, semantic)
    lowered = text.lower()
    intent = str(semantic.get("intent") or "")
    labels: list[str] = []

    def add(label: str) -> None:
        if label in EVENT_LABELS and label not in labels:
            labels.append(label)

    if any(marker in text for marker in ["取消", "不去了", "不用去了"]) or any(marker in lowered for marker in ["cancel", "canceled", "cancelled"]):
        add("cancel")
    if any(marker in text for marker in ["改到", "改成", "换到", "推迟", "提前"]) or "reschedule" in lowered:
        add("reschedule")
    if intent in {"social_plan", "schedule"} or any(marker in text for marker in ["见面", "见吧", "吃饭", "约", "会议", "开会", "碰面"]):
        add("appointment")
    if any(marker in text for marker in ["路线", "打车", "导航", "机场", "酒店", "高铁", "航班", "出发", "到达"]):
        add("travel")
    if intent in {"payment_reminder"} or any(marker in text for marker in ["付款", "支付", "账单", "发票", "还款", "报销"]):
        add("payment")
    if any(marker in text for marker in ["截止", "到期"]) or any(marker in lowered for marker in ["deadline", "due"]):
        add("deadline")
    if intent in {"task_request", "user_instruction"} or any(marker in text for marker in ["待办", "帮我", "提醒", "处理", "盯一下"]):
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
    if any(marker in text for marker in ["喜欢", "讨厌", "不信任", "关系", "生日", "家人", "朋友"]):
        add("relationship_signal")
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
    if current_intent and current_intent != "generic_event":
        return current_intent
    return {
        "payment": "payment_reminder",
        "appointment": "social_plan",
        "deadline": "task_request",
        "todo": "task_request",
        "travel": "travel_plan",
        "shopping": "shopping_intent",
        "cancel": "schedule",
        "reschedule": "schedule",
    }.get(primary_label, current_intent or "generic_event")


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
            },
            timeout=60,
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
        "stream": False,
    }
    response = httpx.post(f"{MODEL_BASE_URL}/v1/chat/completions", json=payload, timeout=60)
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


def extract_semantics(source: str, event_type: str, raw_data: dict[str, Any]) -> dict[str, Any]:
    fallback = rule_extract_semantics(source, event_type, raw_data)
    fallback["raw_data"] = raw_data
    fallback = enrich_semantic_classification(source, event_type, raw_data, fallback, parser_mode="rules_only")
    if source in {"locomo_seed", "locomo_conversation", "longmemeval_conversation"}:
        return fallback
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
        parsed = parse_model_json(call_model(messages))
        semantic = {
            "intent": str(parsed.get("intent") or fallback["intent"])[:120],
            "entities": parsed.get("entities") if isinstance(parsed.get("entities"), dict) else fallback["entities"],
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
            model_entities=parsed.get("entities") if isinstance(parsed.get("entities"), dict) else {},
            parser_mode="hybrid_model_rules",
        )
        warnings = semantic["entities"].get("classification_trace", {}).get("validation_warnings", [])
        if "rule_overrode_low_value_model_label" in warnings:
            semantic["summary"] = fallback["summary"]
            semantic["importance"] = max(float(semantic.get("importance") or 0), float(fallback.get("importance") or 0))
        return semantic
    except Exception:
        return enrich_semantic_classification(
            source,
            event_type,
            raw_data,
            fallback,
            parser_mode="rules_fallback",
            validation_warnings=["model_semantic_parse_failed"],
        )


def suggestion_actions_for_event(intent: str, source: str, suggestion_type: str, summary: str) -> list[dict[str, Any]]:
    text = f"{intent} {source} {suggestion_type} {summary}".lower()
    if intent in {"social_plan", "schedule"} or any(marker in text for marker in ["见面", "路线", "street", "road"]):
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
    if source == "gmail" or intent in {"payment_reminder", "email_verification", "task_request"}:
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
    summary = semantic["summary"].strip()
    display_summary = summary.rstrip("。.!！?？")
    importance = float(semantic["importance"])
    intent = semantic["intent"]
    entities = semantic.get("entities", {})
    source = str(entities.get("source") or "")
    if importance < 0.55 and intent not in {"social_plan", "schedule", "research_interest"}:
        return None

    suggestion_type = "attention"
    confidence = min(max(importance, 0), 1)
    expires_in = timedelta(days=7)
    if intent == "research_interest":
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
    elif intent == "social_plan":
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
        "source_event_id": str(suggestion["source_event_id"]),
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


def persist_suggestion(conn: psycopg.Connection, event_id: str, semantic: dict[str, Any], redis_client: Any = None) -> None:
    suggestion = suggestion_for_event(event_id, semantic)
    if not suggestion:
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
    return {
        "subject": normalize_entity_name(str(subject)),
        "predicate": predicate,
        "object": normalize_entity_name(str(obj)) if len(str(obj)) < 180 else str(obj)[:500],
        "confidence": min(max(float(semantic.get("importance", 0.2)), 0), 1),
        "metadata": {
            "summary": semantic.get("summary"),
            "entities": entities,
            "source_event_id": event_id,
            "memory_scope": memory_scope_for_event(source, event_type, raw_data, semantic),
        },
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
    if name == entities.get("person"):
        return "person"
    if name == entities.get("answer"):
        return "object"
    if name == entities.get("source"):
        return "source"
    return "concept"


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
          metadata = EXCLUDED.metadata,
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


def ensure_relationship_metadata_column(conn: psycopg.Connection) -> None:
    conn.execute("ALTER TABLE relationships ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb")


def ensure_agenda_schema(conn: psycopg.Connection) -> None:
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
    conn.execute("CREATE INDEX IF NOT EXISTS agenda_items_status_idx ON agenda_items(status, updated_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS agenda_items_metadata_dedupe_idx ON agenda_items ((metadata->>'dedupe_key'))")


def semantic_text(semantic: dict[str, Any]) -> str:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    pieces = [
        semantic.get("summary"),
        raw_data.get("message"),
        raw_data.get("body"),
        raw_data.get("text"),
        raw_data.get("content"),
        raw_data.get("subject"),
        raw_data.get("title"),
    ]
    return "\n".join(str(piece) for piece in pieces if piece)


def agenda_operation_for_text(text: str) -> str:
    if any(marker in text for marker in ["取消", "不去了", "不用去了", "cancel", "canceled", "cancelled"]):
        return "cancel"
    if any(marker in text for marker in ["改到", "改成", "换到", "推迟", "提前", "reschedule"]):
        return "reschedule"
    return "create"


def agenda_type_for_semantic(semantic: dict[str, Any], text: str) -> Optional[str]:
    intent = str(semantic.get("intent") or "")
    if intent in {"social_plan", "schedule"} or any(marker in text for marker in ["见面", "吃饭", "约", "会议", "开会", "碰面"]):
        return "appointment"
    if intent in {"payment_reminder"} or any(marker in text for marker in ["付款", "支付", "账单", "发票", "还款"]):
        return "payment"
    if intent in {"task_request", "user_instruction"} or any(marker in text for marker in ["待办", "帮我", "提醒", "处理"]):
        return "todo"
    if any(marker in text for marker in ["截止", "deadline", "due", "到期"]):
        return "deadline"
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
    match = re.search(r"(?:在|去)([\u4e00-\u9fffA-Za-z0-9·.\- ]{2,40}(?:路|街|店|站|机场|酒店|咖啡|餐厅|mall|plaza))", text, re.I)
    return match.group(1).strip() if match else ""


def agenda_source_for_semantic(semantic: dict[str, Any], raw_data: dict[str, Any]) -> str:
    entities = semantic.get("entities") if isinstance(semantic.get("entities"), dict) else {}
    return str(entities.get("source") or raw_data.get("source") or "").strip()


def agenda_dedupe_key_for_semantic(
    agenda_type: str,
    source: str,
    raw_data: dict[str, Any],
    participants: list[str],
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
    dedupe_seed = ":".join([agenda_type, source or "unknown", conversation_key])
    return f"agenda:{dedupe_seed}"


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


def agenda_certainty_and_missing(text: str, place: str, agenda_type: str, operation: str) -> tuple[str, list[str], dict[str, Any]]:
    has_exact_time = bool(EXACT_TIME_RE.search(text))
    has_fuzzy_time = any(marker in text for marker in ["周末", "下周", "周日", "周六", "改天", "找时间", "有空", "明后天"])
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
    return certainty, missing_fields, time_window


def agenda_candidate_from_semantic(event_id: str, timestamp: str, semantic: dict[str, Any]) -> Optional[dict[str, Any]]:
    raw_data = semantic.get("raw_data") if isinstance(semantic.get("raw_data"), dict) else {}
    text = semantic_text(semantic)
    agenda_type = agenda_type_for_semantic(semantic, text)
    if not agenda_type:
        return None
    place = extract_place(text, raw_data)
    participants = extract_agenda_participants(raw_data, semantic)
    operation = agenda_operation_for_text(text)
    certainty, missing_fields, time_window = agenda_certainty_and_missing(text, place, agenda_type, operation)
    status = "canceled" if operation == "cancel" else "scheduled"
    title = str(semantic.get("summary") or text or agenda_type).strip()[:180]
    source = agenda_source_for_semantic(semantic, raw_data)
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
        "metadata": {
            "source": source,
            "dedupe_key": agenda_dedupe_key_for_semantic(agenda_type, source, raw_data, participants),
            "created_from": "semantic_event",
            "event_timestamp": timestamp,
        },
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

    rule_certainty, rule_missing_fields, rule_time_window = agenda_certainty_and_missing(text, place, agenda_type, operation)
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
    metadata.update(
        {
            "source": source,
            "dedupe_key": metadata.get("dedupe_key")
            or agenda_dedupe_key_for_semantic(agenda_type, source, raw_data, participants),
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
    rule_candidate = agenda_candidate_from_semantic(event_id, timestamp, semantic)
    model_candidate, model_warnings = model_agenda_candidate_from_semantic(event_id, timestamp, semantic, rule_candidate)
    if model_warnings and model_candidate is None:
        return rules_fallback_agenda_candidate(rule_candidate, model_candidate, model_warnings)
    if model_candidate is None:
        return rules_fallback_agenda_candidate(rule_candidate, model_candidate, ["model_candidate_missing"])

    validated, validation_warnings = validated_model_fields_for_agenda(rule_candidate, model_candidate, semantic, timestamp)
    warnings = model_warnings + validation_warnings
    if not validated:
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


def persist_semantics(conn: psycopg.Connection, event_id: str, timestamp: str, semantic: dict[str, Any], redis_client: Any = None) -> None:
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
        return
    source_cursor = conn.execute(
        "SELECT source, event_type FROM events WHERE event_id = %s",
        (event_id,),
    )
    source_row = source_cursor.fetchone() if hasattr(source_cursor, "fetchone") else None
    source = source_row[0] if source_row else "unknown"
    event_type = source_row[1] if source_row else "unknown"
    persist_fact_graph_and_state(conn, event_id, timestamp, semantic)
    persist_vector(conn, event_id, source, event_type, semantic)
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


def main() -> None:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    last_id = REDIS_START_ID
    while True:
        messages = client.xread({"events:raw": last_id}, count=10, block=5000)
        if not messages:
            continue
        for _, entries in messages:
            for message_id, fields in entries:
                last_id = message_id
                raw_data = json.loads(fields["raw_data"])
                masked = mask_value(raw_data)
                semantic = extract_semantics(fields["source"], fields["event_type"], masked)
                semantic["raw_data"] = masked
                with psycopg.connect(DATABASE_URL) as conn:
                    persist_semantics(conn, fields["event_id"], fields["timestamp"], semantic, redis_client=client)
        time.sleep(0.1)


if __name__ == "__main__":
    main()
