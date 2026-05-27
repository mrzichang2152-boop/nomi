from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, Optional

import psycopg
import redis
import redis.asyncio as aioredis
import httpx
from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field

from app.auth import is_authorized
from app.model_client import QwenClient
from app.vector import embedding_status, text_embedding, text_embedding_with_provider, vector_literal


DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:9161")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.6")
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "").strip()
COMPOSIO_API_BASE_URL = os.getenv("COMPOSIO_API_BASE_URL", "https://backend.composio.dev").rstrip("/")
REALTIME_CHANNEL = os.getenv("REALTIME_CHANNEL", "par:realtime")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
ENABLE_DAILY_MAINTENANCE = os.getenv("ENABLE_DAILY_MAINTENANCE", "true").lower() == "true"
DAILY_MAINTENANCE_HOUR_UTC = int(os.getenv("DAILY_MAINTENANCE_HOUR_UTC", "19"))
RAW_RETENTION_DAYS = int(os.getenv("RAW_RETENTION_DAYS", "30"))
LOW_VALUE_RAW_RETENTION_DAYS = int(os.getenv("LOW_VALUE_RAW_RETENTION_DAYS", "7"))

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_collector_settings_schema()
    ensure_event_private_storage_schema()
    ensure_memory_governance_schema()
    text_embedding_with_provider("startup embedding warmup")
    task = None
    if ENABLE_DAILY_MAINTENANCE:
        task = asyncio.create_task(daily_maintenance_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="Personal AI Runtime", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class EventIn(BaseModel):
    source: str
    event_type: str
    raw_data: dict[str, Any]
    timestamp: Optional[datetime] = None


class CollectorHealthIn(BaseModel):
    collector: str
    status: str = Field(pattern="^(healthy|degraded|failed)$")
    last_event_at: Optional[datetime] = None
    last_injection_at: Optional[datetime] = None
    error_count: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class SearchIn(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)


class ReasonIn(BaseModel):
    query: str
    limit: int = Field(default=10, ge=1, le=50)


class LoginIn(BaseModel):
    password: str


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=12, ge=1, le=30)


class ToolRouteIn(BaseModel):
    request: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


class MemoryDeleteIn(BaseModel):
    memory_id: Optional[str] = None
    source: Optional[str] = None


class MemoryCorrectionIn(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    reason: str = ""


class SuggestionStatusIn(BaseModel):
    status: str = Field(pattern="^(open|done|dismissed)$")


class ConsolidateIn(BaseModel):
    date: str


class CollectorSettingsUpdateIn(BaseModel):
    enabled: Optional[bool] = None
    paused_until: Optional[datetime] = None
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MaintenanceIn(BaseModel):
    date: Optional[str] = None
    raw_retention_days: int = Field(default=30, ge=7, le=365)
    low_value_retention_days: int = Field(default=7, ge=1, le=90)


@dataclass(frozen=True)
class RetrievalPlan:
    state_limit: int
    timeline_limit: int
    semantic_limit: int
    graph_limit: int
    bm25_limit: int
    vector_limit: int
    supernode_degree_limit: int = 80


def db() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def raw_data_fernet() -> Fernet:
    secret = os.getenv("RAW_DATA_ENCRYPTION_KEY") or os.getenv("APP_PASSWORD") or "par-dev-local-raw-data"
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_private_raw_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    plaintext = json.dumps(raw_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ciphertext = raw_data_fernet().encrypt(plaintext).decode("utf-8")
    return {
        "format": "fernet-json-v1",
        "ciphertext": ciphertext,
        "encrypted_at": datetime.now(timezone.utc).isoformat(),
    }


def decrypt_private_raw_data(envelope: dict[str, Any]) -> dict[str, Any]:
    if envelope.get("format") != "fernet-json-v1" or not envelope.get("ciphertext"):
        raise ValueError("unsupported private raw data envelope")
    try:
        plaintext = raw_data_fernet().decrypt(str(envelope["ciphertext"]).encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("invalid private raw data key") from exc
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("private raw data is not an object")
    return decoded


def protect_private_value(value: Any) -> Any:
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
        protected = {}
        for key, inner in value.items():
            if SENSITIVE_KEY_RE.search(str(key)) and not isinstance(inner, (dict, list)):
                protected[key] = "REDACTED"
            else:
                protected[key] = protect_private_value(inner)
        return protected
    if isinstance(value, list):
        return [protect_private_value(item) for item in value]
    return value


def collect_sensitive_reasons(value: Any) -> list[str]:
    reasons: set[str] = set()

    def visit(item: Any, key_hint: str = "") -> None:
        if key_hint and SENSITIVE_KEY_RE.search(key_hint):
            reasons.add(f"key:{key_hint}")
        if isinstance(item, str):
            checks = [
                ("email", EMAIL_RE),
                ("url_secret", URL_QUERY_RE),
                ("oauth_fragment", OAUTH_FRAGMENT_RE),
                ("inline_secret", INLINE_SECRET_RE),
                ("bearer_token", BEARER_RE),
                ("verification_code", VERIFICATION_CODE_RE),
                ("order_id", ORDER_ID_RE),
                ("id_card", ID_CARD_RE),
                ("passport", PASSPORT_RE),
                ("bank_card", BANK_CARD_RE),
                ("address", CHINESE_ADDRESS_RE),
                ("phone", PHONE_RE),
                ("amount", AMOUNT_RE),
            ]
            for name, pattern in checks:
                if pattern.search(item):
                    reasons.add(name)
        elif isinstance(item, dict):
            for key, inner in item.items():
                visit(inner, str(key))
        elif isinstance(item, list):
            for inner in item:
                visit(inner, key_hint)

    visit(value)
    return sorted(reasons)


def protect_private_payload(value: dict[str, Any]) -> dict[str, Any]:
    protected = protect_private_value(value)
    if not isinstance(protected, dict):
        protected = {"value": protected}
    reasons = collect_sensitive_reasons(value)
    protected["sensitive"] = bool(reasons)
    protected["sensitive_reasons"] = reasons
    return protected


def require_password(x_par_password: Optional[str]) -> None:
    if not is_authorized(x_par_password):
        raise HTTPException(status_code=401, detail="invalid password")


def tool_permission_policy() -> dict[str, str]:
    return {
        "read_only": "allowed_after_login",
        "draft": "allowed_after_login",
        "write": "requires_confirmation",
        "external_message": "requires_explicit_confirmation",
        "external_execution": "requires_explicit_confirmation",
        "payment_or_purchase": "requires_final_user_confirmation",
    }


def default_tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": "gmail",
            "name": "Gmail",
            "category": "communication",
            "phase": "core",
            "recommended_adapter": "google_workspace_mcp",
            "permission_levels": ["read_only", "draft", "external_message"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["查邮件", "总结邮件", "提取待办", "起草回复"],
        },
        {
            "id": "google_calendar",
            "name": "Google Calendar",
            "category": "schedule",
            "phase": "core",
            "recommended_adapter": "google_workspace_mcp",
            "permission_levels": ["read_only", "write"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["查日程", "创建日程", "发现冲突", "提醒约定"],
        },
        {
            "id": "google_drive_docs",
            "name": "Google Drive / Docs",
            "category": "files",
            "phase": "core",
            "recommended_adapter": "google_workspace_mcp",
            "permission_levels": ["read_only", "draft", "write"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["找文件", "总结文档", "生成文档", "修改文档"],
        },
        {
            "id": "google_sheets",
            "name": "Google Sheets",
            "category": "files",
            "phase": "core",
            "recommended_adapter": "google_workspace_mcp",
            "permission_levels": ["read_only", "draft", "write"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["读表", "整理账单", "做统计", "更新表格"],
        },
        {
            "id": "slack",
            "name": "Slack",
            "category": "communication",
            "phase": "core",
            "recommended_adapter": "slack_mcp",
            "permission_levels": ["read_only", "draft", "external_message"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["搜消息", "总结频道", "提取行动项", "发消息"],
        },
        {
            "id": "whatsapp",
            "name": "WhatsApp",
            "category": "communication",
            "phase": "core",
            "recommended_adapter": "managed_browser_first",
            "permission_levels": ["read_only", "draft", "external_message"],
            "risk_level": "high",
            "confirmation_required": True,
            "user_jobs": ["搜聊天", "总结对话", "识别约定", "起草回复"],
        },
        {
            "id": "outlook_graph",
            "name": "Outlook / Microsoft Graph",
            "category": "communication",
            "phase": "recommended",
            "recommended_adapter": "microsoft_graph_mcp",
            "permission_levels": ["read_only", "draft", "write", "external_message"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["处理邮件", "同步日历", "查联系人", "读取 OneDrive"],
        },
        {
            "id": "notion",
            "name": "Notion",
            "category": "knowledge",
            "phase": "recommended",
            "recommended_adapter": "notion_mcp_or_composio",
            "permission_levels": ["read_only", "draft", "write"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["查笔记", "写页面", "整理知识库", "更新项目记录"],
        },
        {
            "id": "tasks",
            "name": "Todoist / Google Tasks",
            "category": "task",
            "phase": "core",
            "recommended_adapter": "todoist_mcp_or_google_tasks",
            "permission_levels": ["read_only", "write"],
            "risk_level": "low",
            "confirmation_required": True,
            "user_jobs": ["创建待办", "同步提醒", "任务复盘", "跟进承诺"],
        },
        {
            "id": "apple_reminders_calendar",
            "name": "Apple Reminders / Calendar",
            "category": "task",
            "phase": "recommended",
            "recommended_adapter": "apple_shortcuts_or_local_bridge",
            "permission_levels": ["read_only", "write"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["同步提醒事项", "创建日历", "读取本机任务"],
        },
        {
            "id": "github",
            "name": "GitHub",
            "category": "developer",
            "phase": "recommended",
            "recommended_adapter": "github_mcp",
            "permission_levels": ["read_only", "draft", "write"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["查 issue", "总结 PR", "创建 issue", "查看代码变更"],
        },
        {
            "id": "linear",
            "name": "Linear",
            "category": "project",
            "phase": "recommended",
            "recommended_adapter": "linear_mcp_or_composio",
            "permission_levels": ["read_only", "write"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["查任务", "更新状态", "创建 issue", "整理 sprint"],
        },
        {
            "id": "jira_confluence",
            "name": "Jira / Confluence",
            "category": "project",
            "phase": "recommended",
            "recommended_adapter": "atlassian_mcp_or_zapier",
            "permission_levels": ["read_only", "draft", "write"],
            "risk_level": "medium",
            "confirmation_required": True,
            "user_jobs": ["查需求", "更新任务", "总结知识库", "生成文档"],
        },
        {
            "id": "crm",
            "name": "HubSpot / Salesforce",
            "category": "sales",
            "phase": "recommended",
            "recommended_adapter": "composio_or_zapier_mcp",
            "permission_levels": ["read_only", "draft", "write", "external_message"],
            "risk_level": "high",
            "confirmation_required": True,
            "user_jobs": ["客户跟进", "记录沟通", "更新商机", "生成销售邮件"],
        },
        {
            "id": "stripe",
            "name": "Stripe",
            "category": "finance",
            "phase": "recommended",
            "recommended_adapter": "stripe_mcp",
            "permission_levels": ["read_only", "draft", "write"],
            "risk_level": "high",
            "confirmation_required": True,
            "user_jobs": ["查付款", "查订阅", "生成发票", "收入摘要"],
        },
        {
            "id": "shopify",
            "name": "Shopify",
            "category": "commerce",
            "phase": "recommended",
            "recommended_adapter": "shopify_mcp_or_composio",
            "permission_levels": ["read_only", "draft", "write"],
            "risk_level": "high",
            "confirmation_required": True,
            "user_jobs": ["查订单", "查库存", "处理售后", "客户摘要"],
        },
        {
            "id": "amazon_shopping",
            "name": "Amazon Shopping",
            "category": "commerce",
            "phase": "experimental",
            "recommended_adapter": "managed_browser_or_unofficial_mcp",
            "permission_levels": ["read_only", "draft", "payment_or_purchase"],
            "risk_level": "high",
            "confirmation_required": True,
            "user_jobs": ["搜商品", "比价", "加入购物车", "准备下单"],
        },
        {
            "id": "uber",
            "name": "Uber",
            "category": "local_service",
            "phase": "experimental",
            "recommended_adapter": "managed_browser_or_unofficial_mcp",
            "permission_levels": ["read_only", "external_execution", "payment_or_purchase"],
            "risk_level": "high",
            "confirmation_required": True,
            "user_jobs": ["查车型", "查价格", "查 ETA", "确认后叫车"],
        },
        {
            "id": "google_maps",
            "name": "Google Maps",
            "category": "local_service",
            "phase": "core",
            "recommended_adapter": "google_maps_mcp_or_api",
            "permission_levels": ["read_only"],
            "risk_level": "low",
            "confirmation_required": False,
            "user_jobs": ["查地点", "查路线", "估算通勤", "附近服务"],
        },
        {
            "id": "browser_automation",
            "name": "Browser / Playwright / Puppeteer",
            "category": "automation",
            "phase": "core",
            "recommended_adapter": "playwright_mcp",
            "permission_levels": ["read_only", "draft", "write", "external_message", "external_execution"],
            "risk_level": "high",
            "confirmation_required": True,
            "user_jobs": ["操作没有 MCP 的网站", "读取页面", "填写表单", "确认后执行"],
        },
    ]


def capability_taxonomy() -> list[dict[str, Any]]:
    return [
        {
            "id": "communication.message.draft_reply",
            "domain": "communication",
            "category": "messaging",
            "action": "draft_reply",
            "risk_permission": "external_message",
            "tool_ids": ["whatsapp", "slack", "gmail", "outlook_graph"],
            "keywords": ["回复", "回消息", "reply", "respond", "whatsapp", "slack", "邮件回复"],
        },
        {
            "id": "communication.email.process",
            "domain": "communication",
            "category": "email",
            "action": "process",
            "risk_permission": "external_message",
            "tool_ids": ["gmail", "outlook_graph"],
            "keywords": ["邮件", "email", "gmail", "outlook", "收件箱", "发邮件", "起草邮件"],
        },
        {
            "id": "schedule.calendar.create_event",
            "domain": "schedule",
            "category": "calendar",
            "action": "create_event",
            "risk_permission": "write",
            "tool_ids": ["google_calendar", "outlook_graph", "apple_reminders_calendar"],
            "keywords": ["日程", "会议", "约", "calendar", "开会", "提醒", "明天", "下午"],
        },
        {
            "id": "memory.personal_search",
            "domain": "memory",
            "category": "search",
            "action": "answer_with_memory",
            "risk_permission": "read_only",
            "tool_ids": [],
            "keywords": ["找", "搜索", "之前", "谁说", "记得", "什么时间", "地址"],
        },
        {
            "id": "suggestion.proactive",
            "domain": "assistant",
            "category": "suggestion",
            "action": "create_suggestion",
            "risk_permission": "draft",
            "tool_ids": [],
            "keywords": ["提醒我", "主动", "建议", "别忘", "跟进"],
        },
        {
            "id": "commerce.product.compare",
            "domain": "commerce",
            "category": "product",
            "action": "compare",
            "risk_permission": "payment_or_purchase",
            "tool_ids": ["amazon_shopping", "shopify", "browser_automation"],
            "keywords": ["买", "商品", "比价", "amazon", "购物", "下单", "优惠"],
        },
        {
            "id": "local_service.ride.estimate_or_book",
            "domain": "local_service",
            "category": "ride",
            "action": "estimate_or_book",
            "risk_permission": "payment_or_purchase",
            "tool_ids": ["uber", "google_maps", "browser_automation"],
            "keywords": ["打车", "uber", "叫车", "去机场", "路线", "eta"],
        },
        {
            "id": "business.crm.contact.upsert",
            "domain": "business",
            "category": "crm",
            "action": "contact_upsert",
            "risk_permission": "write",
            "tool_ids": ["crm"],
            "keywords": ["hubspot", "salesforce", "客户", "线索", "crm", "商机", "联系人"],
        },
        {
            "id": "knowledge.note.write",
            "domain": "knowledge",
            "category": "notes",
            "action": "write",
            "risk_permission": "write",
            "tool_ids": ["notion", "google_drive_docs"],
            "keywords": ["notion", "笔记", "知识库", "写进", "记录到"],
        },
        {
            "id": "project.issue.create_or_update",
            "domain": "project",
            "category": "issue",
            "action": "create_or_update",
            "risk_permission": "write",
            "tool_ids": ["linear", "jira_confluence", "github"],
            "keywords": ["linear", "jira", "issue", "任务", "bug", "需求"],
        },
        {
            "id": "automation.browser.operate",
            "domain": "automation",
            "category": "browser",
            "action": "operate",
            "risk_permission": "external_execution",
            "tool_ids": ["browser_automation"],
            "keywords": ["网站", "网页", "填写", "报名表", "不支持 mcp", "浏览器", "表单"],
        },
    ]


def core_pipeline_registry() -> list[dict[str, Any]]:
    return [
        {
            "id": "reply_pipeline",
            "name": "回复消息 Pipeline",
            "capability_id": "communication.message.draft_reply",
            "steps": ["识别对象", "拉当前会话", "拉允许使用的记忆", "生成草稿", "防泄露检查", "用户确认"],
            "permission": "external_message",
        },
        {
            "id": "email_pipeline",
            "name": "邮件处理 Pipeline",
            "capability_id": "communication.email.process",
            "steps": ["搜索邮件", "总结重点", "提取待办", "起草回复", "用户确认"],
            "permission": "external_message",
        },
        {
            "id": "calendar_pipeline",
            "name": "日程提醒 Pipeline",
            "capability_id": "schedule.calendar.create_event",
            "steps": ["识别时间地点人物", "检查冲突", "生成日程建议", "用户确认", "创建事件"],
            "permission": "write",
        },
        {
            "id": "personal_search_pipeline",
            "name": "个人搜索 Pipeline",
            "capability_id": "memory.personal_search",
            "steps": ["分层召回", "作用域过滤", "证据组装", "回答"],
            "permission": "read_only",
        },
        {
            "id": "suggestion_pipeline",
            "name": "主动建议 Pipeline",
            "capability_id": "suggestion.proactive",
            "steps": ["事件进入", "语义抽取", "重要性评分", "写入记忆", "触发建议"],
            "permission": "draft",
        },
        {
            "id": "shopping_pipeline",
            "name": "购物比价 Pipeline",
            "capability_id": "commerce.product.compare",
            "steps": ["识别商品", "读取偏好", "搜索候选", "比较", "确认后加购或跳转"],
            "permission": "payment_or_purchase",
        },
        {
            "id": "ride_pipeline",
            "name": "出行 Pipeline",
            "capability_id": "local_service.ride.estimate_or_book",
            "steps": ["识别目的地", "查路线", "查车型价格", "展示建议", "确认后叫车"],
            "permission": "payment_or_purchase",
        },
    ]


def execution_guard_for_permission(permission: str) -> dict[str, Any]:
    policy = tool_permission_policy()
    guard = policy.get(permission, "requires_confirmation")
    return {
        "permission": permission,
        "policy": guard,
        "requires_confirmation": guard not in {"allowed_after_login"},
        "final_user_confirmation": permission == "payment_or_purchase",
    }


def match_capability(request: str) -> dict[str, Any]:
    lowered = request.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for capability in capability_taxonomy():
        score = sum(1 for keyword in capability["keywords"] if str(keyword).lower() in lowered)
        if score:
            scored.append((score, capability))
    if scored:
        return sorted(scored, key=lambda item: item[0], reverse=True)[0][1]
    return next(item for item in capability_taxonomy() if item["id"] == "automation.browser.operate")


def pipeline_for_capability(capability_id: str) -> Optional[dict[str, Any]]:
    for pipeline in core_pipeline_registry():
        if pipeline["capability_id"] == capability_id:
            return pipeline
    return None


def tools_for_capability(capability: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = {tool["id"]: tool for tool in default_tool_catalog()}
    candidates = [catalog[tool_id] for tool_id in capability.get("tool_ids", []) if tool_id in catalog]
    if not candidates and "browser_automation" in catalog:
        candidates = [catalog["browser_automation"]]
    return candidates


def route_tool_request(request: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    capability = match_capability(request)
    pipeline = pipeline_for_capability(capability["id"])
    candidate_tools = tools_for_capability(capability)
    route_type = "core_pipeline" if pipeline else "long_tail_tool"
    permission = str((pipeline or {}).get("permission") or capability.get("risk_permission") or "read_only")
    return {
        "request": request,
        "route_type": route_type,
        "capability": {key: capability[key] for key in ["id", "domain", "category", "action", "risk_permission"]},
        "pipeline": pipeline,
        "candidate_tools": candidate_tools,
        "execution_guard": execution_guard_for_permission(permission),
        "routing_reason": (
            "命中核心高频任务，使用确定性 Pipeline。"
            if pipeline
            else "未命中核心 Pipeline，进入长尾工具目录候选召回。"
        ),
        "context": context or {},
    }


def current_composio_api_key() -> str:
    return os.getenv("COMPOSIO_API_KEY", COMPOSIO_API_KEY).strip()


def current_composio_base_url() -> str:
    return os.getenv("COMPOSIO_API_BASE_URL", COMPOSIO_API_BASE_URL).strip().rstrip("/")


def composio_status_payload() -> dict[str, Any]:
    api_key = current_composio_api_key()
    base_url = current_composio_base_url()
    if not api_key:
        return {
            "configured": False,
            "reachable": False,
            "api_base_url": base_url,
            "mcp_server_count": 0,
            "error": "COMPOSIO_API_KEY is not configured",
        }
    try:
        response = httpx.get(
            f"{base_url}/api/v3/mcp/servers",
            headers={"x-api-key": api_key},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("items") if isinstance(data, dict) else []
        if not isinstance(items, list):
            items = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), list) else []
        return {
            "configured": True,
            "reachable": True,
            "api_base_url": base_url,
            "mcp_server_count": len(items),
            "error": "",
        }
    except Exception as exc:
        return {
            "configured": True,
            "reachable": False,
            "api_base_url": base_url,
            "mcp_server_count": 0,
            "error": str(exc)[:300],
        }


def ensure_collector_settings_schema() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collector_settings (
              source TEXT PRIMARY KEY,
              enabled BOOLEAN NOT NULL DEFAULT TRUE,
              paused_until TIMESTAMPTZ,
              reason TEXT NOT NULL DEFAULT '',
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS collector_settings_enabled_idx
            ON collector_settings(enabled, paused_until)
            """
        )


def ensure_event_private_storage_schema() -> None:
    with db() as conn:
        conn.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS raw_data_private JSONB")


def ensure_memory_governance_schema() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_audit_log (
              id UUID PRIMARY KEY,
              action TEXT NOT NULL,
              target_type TEXT NOT NULL,
              target_id TEXT NOT NULL,
              reason TEXT NOT NULL DEFAULT '',
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS memory_audit_log_target_idx
            ON memory_audit_log(target_type, target_id, created_at DESC)
            """
        )


def default_collector_settings() -> list[str]:
    return ["bookmark", "calendar", "focus", "gmail", "search", "telegram", "whatsapp"]


def row_to_collector_setting(row: Any) -> dict[str, Any]:
    paused_until = row[2]
    now = datetime.now(timezone.utc)
    is_paused = bool(paused_until and paused_until > now)
    return {
        "source": row[0],
        "enabled": row[1],
        "paused_until": paused_until.isoformat() if hasattr(paused_until, "isoformat") else paused_until,
        "paused": is_paused,
        "reason": row[3] or "",
        "metadata": row[4] or {},
        "updated_at": row[5].isoformat() if hasattr(row[5], "isoformat") else row[5],
    }


def row_to_collector_health(row: Any) -> dict[str, Any]:
    return {
        "collector": row[0],
        "health_status": row[1],
        "last_event_at": row[2].isoformat() if hasattr(row[2], "isoformat") else row[2],
        "last_injection_at": row[3].isoformat() if hasattr(row[3], "isoformat") else row[3],
        "error_count": row[4],
        "details": row[5] or {},
        "health_updated_at": row[6].isoformat() if hasattr(row[6], "isoformat") else row[6],
    }


def merge_collector_status(settings: list[dict[str, Any]], health_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    health_by_source = {row["collector"]: row for row in health_rows}
    merged = []
    for setting in settings:
        health = health_by_source.get(setting["source"], {})
        merged.append(
            {
                **setting,
                "health_status": health.get("health_status", "unknown"),
                "last_event_at": health.get("last_event_at"),
                "last_injection_at": health.get("last_injection_at"),
                "error_count": health.get("error_count", 0),
                "details": health.get("details", {}),
                "health_updated_at": health.get("health_updated_at"),
            }
        )
    return sorted(merged, key=lambda item: item["source"])


def collector_status_for_source(conn: psycopg.Connection, source: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT enabled, paused_until, reason
        FROM collector_settings
        WHERE source = %s
        """,
        (source,),
    ).fetchone()
    if not row:
        return {"source": source, "enabled": True, "paused": False, "paused_until": None, "reason": ""}

    enabled, paused_until, reason = row
    now = datetime.now(timezone.utc)
    paused = bool(paused_until and paused_until > now)
    return {
        "source": source,
        "enabled": enabled,
        "paused": paused,
        "paused_until": paused_until.isoformat() if hasattr(paused_until, "isoformat") else paused_until,
        "reason": reason or "",
    }


def ensure_collector_event_allowed(conn: psycopg.Connection, source: str) -> None:
    status = collector_status_for_source(conn, source)
    if not status["enabled"] or status["paused"]:
        raise HTTPException(status_code=409, detail=status)


def default_maintenance_date(today: Optional[date] = None) -> str:
    current = today or datetime.now(timezone.utc).date()
    return (current - timedelta(days=1)).isoformat()


async def daily_maintenance_loop() -> None:
    last_run_date: Optional[str] = None
    while True:
        now = datetime.now(timezone.utc)
        target_date = default_maintenance_date(now.date())
        if now.hour == DAILY_MAINTENANCE_HOUR_UTC and last_run_date != target_date:
            try:
                with db() as conn:
                    run_daily_memory_maintenance(
                        conn,
                        date_text=target_date,
                        raw_retention_days=RAW_RETENTION_DAYS,
                        low_value_retention_days=LOW_VALUE_RAW_RETENTION_DAYS,
                    )
                last_run_date = target_date
            except Exception:
                pass
        await asyncio.sleep(1800)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/memory/status")
def memory_status(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    return {"embedding": embedding_status()}


@app.get("/api/memory/embedding/probe")
def memory_embedding_probe(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    vector, actual_provider = text_embedding_with_provider("personal memory embedding probe")
    norm = sum(value * value for value in vector) ** 0.5
    return {
        "configured": embedding_status(),
        "actual_provider": actual_provider,
        "dimensions": len(vector),
        "norm": round(norm, 6),
    }


@app.get("/api/tools/catalog")
def tool_catalog(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    tools = default_tool_catalog()
    phases = {
        "core": [tool["id"] for tool in tools if tool["phase"] == "core"],
        "recommended": [tool["id"] for tool in tools if tool["phase"] == "recommended"],
        "experimental": [tool["id"] for tool in tools if tool["phase"] == "experimental"],
    }
    return {
        "tools": tools,
        "phases": phases,
        "permission_policy": tool_permission_policy(),
    }


@app.post("/api/tools/route")
def tool_route(body: ToolRouteIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    return route_tool_request(body.request, body.context)


@app.get("/api/tools/composio/status")
def composio_status(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    return composio_status_payload()


@app.get("/api/memory/debug")
def memory_debug(
    x_par_password: Optional[str] = Header(default=None),
    query: str = "Caroline",
) -> dict[str, Any]:
    require_password(x_par_password)
    pattern = f"%{query}%"
    patterns = token_patterns(query)
    with db() as conn:
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM events),
              (SELECT count(*) FROM semantic_events),
              (SELECT count(*) FROM facts),
              (SELECT count(*) FROM entities),
              (SELECT count(*) FROM relationships),
              (SELECT count(*) FROM memory_states),
              (SELECT count(*) FROM memory_vectors),
              (SELECT count(*) FROM proactive_suggestions)
            """
        ).fetchone()
        event_samples = conn.execute(
            """
            SELECT source, event_type, raw_data, timestamp
            FROM events
            WHERE raw_data::text ILIKE %s
            ORDER BY timestamp DESC
            LIMIT 3
            """,
            (pattern,),
        ).fetchall()
        fact_samples = conn.execute(
            """
            SELECT subject, predicate, object, confidence
            FROM facts
            WHERE subject ILIKE %s OR predicate ILIKE %s OR object ILIKE %s
            ORDER BY confidence DESC, updated_at DESC
            LIMIT 5
            """,
            (pattern, pattern, pattern),
        ).fetchall()
        if patterns:
            state_conditions = " OR ".join(["key ILIKE %s OR value::text ILIKE %s" for _ in patterns])
            state_params: list[Any] = []
            for token_pattern in patterns:
                state_params.extend([token_pattern, token_pattern])
            state_samples = conn.execute(
                f"""
                SELECT key, value, confidence
                FROM memory_states
                WHERE {state_conditions}
                ORDER BY updated_at DESC
                LIMIT 5
                """,
                tuple(state_params),
            ).fetchall()
        else:
            state_samples = []
        context = retrieve_context(query, 12)
    return {
        "embedding": embedding_status(),
        "counts": {
            "events": counts[0],
            "semantic_events": counts[1],
            "facts": counts[2],
            "entities": counts[3],
            "relationships": counts[4],
            "memory_states": counts[5],
            "memory_vectors": counts[6],
            "suggestions": counts[7],
        },
        "event_samples": [
            {
                "source": row[0],
                "event_type": row[1],
                "raw_data": row[2],
                "timestamp": row[3].isoformat(),
            }
            for row in event_samples
        ],
        "fact_samples": [
            {"subject": row[0], "predicate": row[1], "object": row[2], "confidence": row[3]}
            for row in fact_samples
        ],
        "state_samples": [
            {"key": row[0], "value": row[1], "confidence": row[2]}
            for row in state_samples
        ],
        "retrieval_layers": [item["layer"] for item in context],
        "retrieval_sample": context[:5],
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/login")
def login(body: LoginIn) -> dict[str, bool]:
    if not is_authorized(body.password):
        raise HTTPException(status_code=401, detail="invalid password")
    return {"ok": True}


@app.post("/event")
def create_event(event: EventIn) -> dict[str, str]:
    event_id = uuid.uuid4()
    ts = event.timestamp or datetime.now(timezone.utc)
    protected_raw_data = protect_private_payload(event.raw_data)
    private_raw_data = encrypt_private_raw_data(event.raw_data)

    with db() as conn:
        ensure_collector_event_allowed(conn, event.source)
        conn.execute(
            """
            INSERT INTO events (event_id, timestamp, source, event_type, raw_data, raw_data_private)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (event_id, ts, event.source, event.event_type, json.dumps(protected_raw_data), json.dumps(private_raw_data)),
        )

    redis_client().xadd(
        "events:raw",
        {
            "event_id": str(event_id),
            "timestamp": ts.isoformat(),
            "source": event.source,
            "event_type": event.event_type,
            "raw_data": json.dumps(protected_raw_data, ensure_ascii=False),
        },
    )
    return {"event_id": str(event_id), "status": "queued"}


@app.get("/api/events/{event_id}/private-raw")
def private_raw_event(event_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        row = conn.execute(
            """
            SELECT raw_data_private
            FROM events
            WHERE event_id = %s
            """,
            (event_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="event not found")
    if not row[0]:
        raise HTTPException(status_code=404, detail="private raw data not available")
    try:
        raw_data = decrypt_private_raw_data(row[0])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"event_id": event_id, "raw_data": raw_data}


@app.get("/api/collectors/settings")
def collector_settings(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT source, enabled, paused_until, reason, metadata, updated_at
            FROM collector_settings
            ORDER BY source
            """
        ).fetchall()
    existing = {row[0] for row in rows}
    settings = [row_to_collector_setting(row) for row in rows]
    for source in default_collector_settings():
        if source not in existing:
            settings.append(
                {
                    "source": source,
                    "enabled": True,
                    "paused_until": None,
                    "paused": False,
                    "reason": "",
                    "metadata": {},
                    "updated_at": None,
                }
            )
    settings.sort(key=lambda item: item["source"])
    return {"collectors": settings}


@app.get("/api/collectors/status")
def collector_status(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    settings = collector_settings(x_par_password)["collectors"]
    with db() as conn:
        rows = conn.execute(
            """
            SELECT collector, status, last_event_at, last_injection_at, error_count, details, updated_at
            FROM collector_health
            ORDER BY collector
            """
        ).fetchall()
    health = [row_to_collector_health(row) for row in rows]
    return {"collectors": merge_collector_status(settings, health)}


@app.patch("/api/collectors/settings/{source}")
def update_collector_setting(
    source: str,
    body: CollectorSettingsUpdateIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    enabled = True if body.enabled is None else body.enabled
    with db() as conn:
        conn.execute(
            """
            INSERT INTO collector_settings
              (source, enabled, paused_until, reason, metadata, updated_at)
            VALUES (%s, %s, %s, %s, %s, now())
            ON CONFLICT (source) DO UPDATE SET
              enabled = EXCLUDED.enabled,
              paused_until = EXCLUDED.paused_until,
              reason = EXCLUDED.reason,
              metadata = EXCLUDED.metadata,
              updated_at = now()
            """,
            (source, enabled, body.paused_until, body.reason, json.dumps(body.metadata)),
        )
        row = conn.execute(
            """
            SELECT source, enabled, paused_until, reason, metadata, updated_at
            FROM collector_settings
            WHERE source = %s
            """,
            (source,),
        ).fetchone()
    return row_to_collector_setting(row)


@app.get("/timeline")
def get_timeline(limit: int = 30) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, date, summary, source_event_ids, created_at
            FROM timeline
            ORDER BY date DESC, created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "date": row[1].isoformat(),
            "summary": row[2],
            "source_event_ids": [str(x) for x in row[3]],
            "created_at": row[4].isoformat(),
        }
        for row in rows
    ]


@app.post("/search")
def search(body: SearchIn) -> dict[str, Any]:
    context = retrieve_context(body.query, body.limit)
    return build_personal_search_response(body.query, context)


@app.post("/reason")
def reason(body: ReasonIn) -> dict[str, Any]:
    result = search(SearchIn(query=body.query, limit=body.limit))
    return {
        "answer": result["answer"],
        "confidence": result["confidence"],
        "evidence": result["sources"],
    }


def search_layer_explanation(layer: str) -> str:
    explanations = {
        "working_memory": "状态记忆：当前偏好、近期状态或活跃上下文",
        "timeline": "时间线：按日期整理的长期事件摘要",
        "semantic_memory": "语义记忆：稳定的长期语义摘要",
        "entity_graph": "知识图谱：实体、关系或事实匹配",
        "bm25_recall": "关键词召回：字面关键词匹配的历史内容",
        "vector_recall": "向量召回：语义相近的历史内容",
    }
    return explanations.get(layer, "个人记忆：相关历史上下文")


def build_personal_search_response(query: str, context: list[dict[str, Any]]) -> dict[str, Any]:
    layers = list(dict.fromkeys(str(item.get("layer") or "unknown") for item in context))
    sources = []
    for index, item in enumerate(context, start=1):
        layer = str(item.get("layer") or "unknown")
        sources.append(
            {
                "rank": index,
                "layer": layer,
                "explanation": search_layer_explanation(layer),
                "content": item,
            }
        )
    confidence = 0 if not sources else min(0.55 + len(layers) * 0.08 + min(len(sources), 5) * 0.03, 0.92)
    return {
        "query": query,
        "answer": f"找到 {len(sources)} 条相关个人记忆。" if sources else "没有找到相关个人记忆。",
        "confidence": round(confidence, 2),
        "layers": layers,
        "retrieval_plan": explain_retrieval_plan(query, plan_retrieval(query, max(len(context), 1))),
        "sources": sources,
    }


def decorate_context_sources(context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decorated = []
    for item in context:
        layer = str(item.get("layer") or "unknown")
        decorated.append({**item, "explanation": search_layer_explanation(layer)})
    return decorated


def build_reasoning_context(
    state_rows: list[Any],
    timeline_rows: list[Any],
    semantic_rows: list[Any],
    fact_rows: list[Any],
    bm25_rows: list[Any],
    vector_rows: list[Any],
) -> list[dict[str, Any]]:
    context: list[dict[str, Any]] = []
    for row in state_rows:
        context.append(
            {
                "layer": "working_memory",
                "key": row[0],
                "value": row[1],
                "updated_at": row[2].isoformat() if hasattr(row[2], "isoformat") else row[2],
            }
        )
    for row in timeline_rows:
        context.append(
            {
                "layer": "timeline",
                "date": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
                "summary": row[1],
                "source_event_ids": [str(x) for x in row[2]],
            }
        )
    for row in semantic_rows:
        context.append(
            {
                "layer": "semantic_memory",
                "memory_type": row[0],
                "content": row[1],
                "confidence": row[2],
                "source_event_ids": [str(x) for x in row[3]],
            }
        )
    for row in fact_rows:
        context.append(
            {
                "layer": "entity_graph",
                "subject": row[0],
                "predicate": row[1],
                "object": row[2],
                "confidence": row[3],
                "source_event_ids": [str(x) for x in row[4]],
                "metadata": row[5] if len(row) > 5 else {},
            }
        )
    for row in bm25_rows:
        context.append(
            {
                "layer": "bm25_recall",
                "time": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
                "source": row[1],
                "event_type": row[2],
                "raw_data": row[3],
                "summary": row[4],
                "intent": row[5],
                "importance": row[6],
                "rank": row[7],
                "metadata": row[8] if len(row) > 8 else {},
            }
        )
    for row in vector_rows:
        context.append(
            {
                "layer": "vector_recall",
                "time": row[0].isoformat() if hasattr(row[0], "isoformat") else row[0],
                "source": row[1],
                "event_type": row[2],
                "raw_data": row[3],
                "summary": row[4],
                "intent": row[5],
                "importance": row[6],
                "metadata": row[7] if len(row) > 7 else {},
            }
        )
    return context


def normalize_policy_entity(value: Any) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", str(value or "").strip().lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def infer_memory_access_policy(query: str, explicit_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    explicit_context = explicit_context or {}
    lowered = query.lower()
    output_context = str(explicit_context.get("output_context") or "personal_search")
    if any(marker in lowered for marker in ["回复", "回 ", "reply", "respond", "写封邮件", "起草邮件"]):
        output_context = "reply_to_contact"
    if any(marker in lowered for marker in ["分析", "关系", "怎么看", "评价", "relationship", "analyze"]):
        output_context = "private_analysis"

    target_entities: list[str] = []
    explicit_target = explicit_context.get("target_contact") or explicit_context.get("conversation_label")
    if explicit_target:
        target_entities.append(normalize_policy_entity(explicit_target))
    target_patterns = [
        r"(?:回复|回|reply(?: to)?|respond(?: to)?)\s*([A-Za-z][\w .'-]{1,60}|[\u4e00-\u9fff]{2,12})",
        r"(?:给|to)\s*([A-Za-z][\w .'-]{1,60}|[\u4e00-\u9fff]{2,12})(?:写|发|send|reply)",
    ]
    for pattern in target_patterns:
        match = re.search(pattern, query, flags=re.I)
        if match:
            target = re.split(r"[,，。.!！?？；;]|语气|关于|说|写|发", match.group(1).strip(), 1)[0]
            normalized = normalize_policy_entity(target)
            if normalized:
                target_entities.append(normalized)
    target_entities = list(dict.fromkeys(item for item in target_entities if item))
    return {
        "output_context": output_context,
        "target_entities": target_entities,
        "explicit_context": explicit_context,
    }


def memory_scope_from_context_item(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    scope = metadata.get("memory_scope") if isinstance(metadata.get("memory_scope"), dict) else {}
    if scope:
        return scope
    raw_data = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
    conversation_label = str(raw_data.get("chat_name") or raw_data.get("subject") or "").strip()
    speaker = str(raw_data.get("sender") or raw_data.get("speaker") or "").strip()
    related = [conversation_label, speaker, item.get("subject"), item.get("object")]
    return {
        "conversation_label": conversation_label,
        "speaker": speaker,
        "related_entities": [normalize_policy_entity(value) for value in related if normalize_policy_entity(value)],
        "sensitivity": "normal",
        "not_usable_contexts": [],
        "usable_contexts": ["private_analysis", "personal_search", "self_reminder"],
    }


def filter_context_by_memory_access_policy(context: list[dict[str, Any]], policy: dict[str, Any]) -> list[dict[str, Any]]:
    output_context = str(policy.get("output_context") or "personal_search")
    target_entities = [normalize_policy_entity(value) for value in policy.get("target_entities", []) if normalize_policy_entity(value)]
    if output_context == "private_analysis":
        return context

    filtered: list[dict[str, Any]] = []
    for item in context:
        scope = memory_scope_from_context_item(item)
        not_usable = set(scope.get("not_usable_contexts") or [])
        sensitivity = str(scope.get("sensitivity") or "normal")
        related_entities = [normalize_policy_entity(value) for value in scope.get("related_entities", []) if normalize_policy_entity(value)]
        conversation_label = normalize_policy_entity(scope.get("conversation_label"))
        is_target_conversation = bool(target_entities) and conversation_label in target_entities
        mentions_target = bool(target_entities) and any(entity in target_entities for entity in related_entities)

        if output_context in not_usable:
            continue
        if output_context == "reply_to_contact" and sensitivity.startswith("third_party_private"):
            continue
        if output_context == "reply_to_contact" and mentions_target and conversation_label and not is_target_conversation:
            continue
        filtered.append(item)
    return filtered


def context_text(item: dict[str, Any]) -> str:
    text = json.dumps(item, ensure_ascii=False, default=str).lower()
    return re.sub(r"[^\w\s]", " ", text)


def query_tokens(query: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s]", " ", query.lower())
    return [token for token in re.split(r"\s+", cleaned) if len(token) >= 4]


def rerank_context(query: str, context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens = query_tokens(query)
    layer_bonus = {
        "entity_graph": 1.0,
        "working_memory": 0.4,
        "timeline": 0.3,
        "semantic_memory": 0.25,
        "bm25_recall": 0.2,
        "vector_recall": 0.1,
    }

    def score(item: dict[str, Any]) -> float:
        text = context_text(item)
        overlap = sum(1 for token in tokens if token in text)
        confidence = float(item.get("confidence") or item.get("importance") or item.get("rank") or 0)
        return overlap + confidence + layer_bonus.get(item.get("layer"), 0)

    return sorted(context, key=score, reverse=True)


def normalize_retrieval_pattern(query: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", query.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return f"%{cleaned}%" if cleaned else "%"


def token_patterns(query: str, max_tokens: int = 6) -> list[str]:
    return [f"%{token}%" for token in query_tokens(query)[:max_tokens]]


def plan_retrieval(query: str, limit: int = 12) -> RetrievalPlan:
    lowered = query.lower()
    graph_markers = ["关系", "谁", "谁和", "谁约", "什么关系", "related", "relationship", "who"]
    state_markers = ["现在", "当前", "最近", "偏好", "状态", "current", "preference", "recent"]
    recall_markers = ["之前", "看过", "提过", "大概", "那个", "similar", "before", "previous", "remember"]
    timeline_markers = ["什么时候", "哪天", "今天", "昨天", "when", "date", "time"]

    graph_score = 2 if any(marker in lowered for marker in graph_markers) else 1
    state_score = 2 if any(marker in lowered for marker in state_markers) else 1
    vector_score = 2 if any(marker in lowered for marker in recall_markers) else 1
    bm25_score = vector_score
    timeline_score = 2 if any(marker in lowered for marker in timeline_markers) else 1
    semantic_score = 1

    total = graph_score + state_score + vector_score + bm25_score + timeline_score + semantic_score

    def weighted(score: int, minimum: int = 1) -> int:
        return max(minimum, round(limit * score / total))

    return RetrievalPlan(
        state_limit=weighted(state_score),
        timeline_limit=weighted(timeline_score),
        semantic_limit=weighted(semantic_score),
        graph_limit=weighted(graph_score),
        bm25_limit=weighted(bm25_score),
        vector_limit=weighted(vector_score),
    )


def explain_retrieval_plan(query: str, plan: RetrievalPlan) -> dict[str, Any]:
    lowered = query.lower()
    reasons: list[str] = []
    priority_layers: list[str] = []
    if any(marker in lowered for marker in ["关系", "谁", "什么关系", "related", "relationship", "who"]):
        reasons.append("问题包含关系/人物线索，优先使用知识图谱。")
        priority_layers.append("entity_graph")
    if any(marker in lowered for marker in ["现在", "当前", "最近", "偏好", "状态", "current", "preference", "recent"]):
        reasons.append("问题询问当前状态、偏好或近期上下文，优先使用 KV/状态记忆。")
        priority_layers.append("working_memory")
    if any(marker in lowered for marker in ["之前", "看过", "提过", "大概", "那个", "similar", "before", "previous", "remember"]):
        reasons.append("问题是模糊回忆或语义相似查找，增加 RAG/BM25 召回。")
        priority_layers.extend(["vector_recall", "bm25_recall"])
    if any(marker in lowered for marker in ["什么时候", "哪天", "今天", "昨天", "when", "date", "time"]):
        reasons.append("问题包含时间线索，增加 timeline 召回。")
        priority_layers.append("timeline")
    if not reasons:
        reasons.append("未命中特定路由线索，均衡检索状态、时间线、语义记忆、知识图谱和 RAG。")
    priority_layers = list(dict.fromkeys(priority_layers)) or ["working_memory", "semantic_memory", "entity_graph", "vector_recall"]
    return {
        "query": query,
        "priority_layers": priority_layers,
        "reasons": reasons,
        "limits": {
            "state_limit": plan.state_limit,
            "timeline_limit": plan.timeline_limit,
            "semantic_limit": plan.semantic_limit,
            "graph_limit": plan.graph_limit,
            "bm25_limit": plan.bm25_limit,
            "vector_limit": plan.vector_limit,
            "supernode_degree_limit": plan.supernode_degree_limit,
        },
    }


def graph_fact_sql() -> str:
    return """
    WITH matched_facts AS (
      SELECT f.subject, f.predicate, f.object, f.confidence, f.source_event_ids, f.metadata, f.updated_at
      FROM facts f
      WHERE f.subject ILIKE %s OR f.predicate ILIKE %s OR f.object ILIKE %s
    ),
    entity_degree AS (
      SELECT name, count(*) AS degree
      FROM (
        SELECT e.name
        FROM relationships r
        JOIN entities e ON e.id = r.from_entity
        UNION ALL
        SELECT e.name
        FROM relationships r
        JOIN entities e ON e.id = r.to_entity
      ) nodes
      GROUP BY name
    )
    SELECT mf.subject, mf.predicate, mf.object, mf.confidence, mf.source_event_ids, mf.metadata
    FROM matched_facts mf
    LEFT JOIN entity_degree subject_degree ON subject_degree.name = mf.subject
    LEFT JOIN entity_degree object_degree ON object_degree.name = mf.object
    WHERE COALESCE(subject_degree.degree, 0) <= %s
      AND COALESCE(object_degree.degree, 0) <= %s
    ORDER BY mf.confidence DESC, mf.updated_at DESC
    LIMIT %s
    """


def bm25_sql() -> str:
    return """
    SELECT e.timestamp, e.source, e.event_type, e.raw_data, s.summary, s.intent, s.importance,
           ts_rank_cd(
             to_tsvector('simple', e.raw_data::text || ' ' || COALESCE(s.summary, '')),
             plainto_tsquery('simple', %s)
           ) AS rank,
           COALESCE(v.metadata, '{}'::jsonb) AS metadata
    FROM events e
    LEFT JOIN semantic_events s ON s.event_id = e.event_id
    LEFT JOIN memory_vectors v ON v.event_id = e.event_id
    WHERE to_tsvector('simple', e.raw_data::text || ' ' || COALESCE(s.summary, ''))
          @@ plainto_tsquery('simple', %s)
    ORDER BY rank DESC, e.timestamp DESC
    LIMIT %s
    """


def summarize_daily_facts(fact_rows: list[Any], max_items: int = 8) -> str:
    if not fact_rows:
        return "当天没有足够的高价值事实可合并。"
    grouped: dict[str, list[str]] = {}
    followups: list[str] = []
    stable_memory: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    def fact_priority(item: Any) -> tuple[int, float]:
        predicate = str(item[1])
        benchmark_penalty = 1 if predicate == "benchmark_answer" else 0
        return (benchmark_penalty, -float(item[3] or 0))

    for row in sorted(fact_rows, key=fact_priority):
        subject = str(row[0])
        predicate = str(row[1])
        obj = str(row[2])
        key = (subject.lower(), predicate.lower(), obj.lower())
        if key in seen:
            continue
        seen.add(key)
        cleaned_object = obj
        if cleaned_object.lower().startswith(subject.lower()):
            cleaned_object = cleaned_object[len(subject) :].strip(" :,-")
        if predicate == "benchmark_answer":
            phrase = f"answer: {cleaned_object}".strip()
        elif predicate == "conversation_memory":
            phrase = cleaned_object.strip()
        else:
            phrase = f"{predicate} {cleaned_object}".strip()
        if predicate in {"payment_reminder", "schedule", "task_request", "social_plan"}:
            followups.append(f"{subject}: {phrase[:180]}")
        if predicate in {"identity", "preference", "active_project", "long_term_goal", "conversation_memory"}:
            stable_memory.append(f"{subject}: {phrase[:180]}")
        grouped.setdefault(subject, []).append(phrase[:220])

    highlight_lines = []
    for subject, phrases in grouped.items():
        highlight_lines.append(f"{subject}: {'; '.join(phrases[:3])}")
        if len(highlight_lines) >= max_items:
            break
    sections = [f"今日重点：{'；'.join(highlight_lines[:max_items])}"]
    sections.append(f"待跟进：{'；'.join(followups[:5]) if followups else '暂无明确待办。'}")
    sections.append(f"稳定记忆：{'；'.join(stable_memory[:5]) if stable_memory else '暂无新增稳定偏好、身份或目标。'}")
    return "\n".join(sections)


def stable_semantic_memory_content(date_text: str, summary: str, fact_count: int) -> dict[str, Any]:
    return {
        "date": date_text,
        "summary": summary,
        "fact_count": fact_count,
        "source": "consolidated_daily",
    }


def consolidation_fact_sql() -> str:
    return """
        SELECT subject, predicate, object, confidence, source_event_ids
        FROM facts
        WHERE (valid_from::date = %s::date OR created_at::date = %s::date)
          AND COALESCE(metadata#>>'{entities,source}', metadata->>'source', '') NOT IN (
            'longmemeval_conversation',
            'longmemeval_backfill',
            'locomo_conversation',
            'locomo_seed',
            'locomo_seed_backfill'
          )
        ORDER BY CASE WHEN predicate = 'benchmark_answer' THEN 1 ELSE 0 END, updated_at DESC, confidence DESC
        LIMIT 50
        """


def consolidate_day(conn: psycopg.Connection, date_text: str) -> dict[str, Any]:
    rows = conn.execute(
        consolidation_fact_sql(),
        (date_text, date_text),
    ).fetchall()
    summary = summarize_daily_facts(rows)
    source_ids: list[Any] = []
    for row in rows:
        source_ids.extend(row[4])
    deduped_source_ids = list(dict.fromkeys(source_ids))
    if deduped_source_ids:
        conn.execute(
            """
            INSERT INTO timeline (id, date, summary, source_event_ids)
            VALUES (%s, %s::date, %s, %s::UUID[])
            """,
            (uuid.uuid4(), date_text, summary, deduped_source_ids),
        )
    conn.execute(
        """
        INSERT INTO memory_states (key, value, confidence, source_fact_ids, updated_at)
        VALUES (%s, %s, %s, ARRAY[]::UUID[], now())
        ON CONFLICT (key) DO UPDATE SET
          value = EXCLUDED.value,
          confidence = EXCLUDED.confidence,
          updated_at = now()
        """,
        (
            f"daily_summary:{date_text}",
            json.dumps({"date": date_text, "summary": summary}, ensure_ascii=False),
            0.7 if rows else 0.2,
        ),
    )
    if rows:
        conn.execute(
            """
            INSERT INTO semantic_memory (id, memory_type, content, confidence, source_event_ids, updated_at)
            VALUES (%s, %s, %s, %s, %s::UUID[], now())
            """,
            (
                uuid.uuid4(),
                "daily_consolidation",
                json.dumps(stable_semantic_memory_content(date_text, summary, len(rows)), ensure_ascii=False),
                0.78,
                deduped_source_ids,
            ),
        )
    return {"date": date_text, "fact_count": len(rows), "summary": summary}


def build_pruned_raw_data(source: str, event_type: str, summary: Optional[str], reason: str) -> dict[str, Any]:
    return {
        "pruned": True,
        "source": source,
        "event_type": event_type,
        "reason": reason,
        "semantic_summary": (summary or "No semantic summary was available.")[:500],
    }


def prune_raw_events(
    conn: psycopg.Connection,
    raw_retention_days: int,
    low_value_retention_days: int,
) -> dict[str, Any]:
    low_value = conn.execute(
        """
        UPDATE events e
        SET raw_data = jsonb_build_object(
          'pruned', true,
          'source', e.source,
          'event_type', e.event_type,
          'reason', 'low_value_retention_expired',
          'semantic_summary', COALESCE(s.summary, 'No semantic summary was available.')
        )
        FROM semantic_events s
        WHERE s.event_id = e.event_id
          AND s.importance < 0.35
          AND e.created_at < now() - (%s || ' days')::interval
          AND COALESCE((e.raw_data->>'pruned')::boolean, false) = false
        """,
        (low_value_retention_days,),
    )
    expired = conn.execute(
        """
        UPDATE events e
        SET raw_data = jsonb_build_object(
          'pruned', true,
          'source', e.source,
          'event_type', e.event_type,
          'reason', 'older_than_raw_retention',
          'semantic_summary', COALESCE(s.summary, 'No semantic summary was available.')
        )
        FROM semantic_events s
        WHERE s.event_id = e.event_id
          AND e.created_at < now() - (%s || ' days')::interval
          AND COALESCE((e.raw_data->>'pruned')::boolean, false) = false
        """,
        (raw_retention_days,),
    )
    return {
        "low_value_pruned": low_value.rowcount or 0,
        "expired_pruned": expired.rowcount or 0,
        "raw_retention_days": raw_retention_days,
        "low_value_retention_days": low_value_retention_days,
    }


def run_daily_memory_maintenance(
    conn: psycopg.Connection,
    date_text: str,
    raw_retention_days: int,
    low_value_retention_days: int,
) -> dict[str, Any]:
    consolidation = consolidate_day(conn, date_text)
    raw_cleanup = prune_raw_events(conn, raw_retention_days, low_value_retention_days)
    return {
        "date": date_text,
        "consolidation": consolidation,
        "raw_cleanup": raw_cleanup,
    }


def retrieve_context(query: str, limit: int) -> list[dict[str, Any]]:
    pattern = f"%{query}%"
    graph_pattern = normalize_retrieval_pattern(query)
    patterns = token_patterns(query)
    query_vector = vector_literal(text_embedding(query))
    plan = plan_retrieval(query, limit)
    with db() as conn:
        if patterns:
            state_conditions = " OR ".join(["key ILIKE %s OR value::text ILIKE %s" for _ in patterns])
            state_params: list[Any] = []
            for token_pattern in patterns:
                state_params.extend([token_pattern, token_pattern])
            state_rows = conn.execute(
                f"""
                SELECT key, value, updated_at
                FROM memory_states
                WHERE {state_conditions}
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (*state_params, plan.state_limit),
            ).fetchall()
        else:
            state_rows = []
        timeline_rows = conn.execute(
            """
            SELECT date, summary, source_event_ids
            FROM timeline
            WHERE summary ILIKE %s
            ORDER BY date DESC, created_at DESC
            LIMIT %s
            """,
            (pattern, plan.timeline_limit),
        ).fetchall()
        semantic_rows = conn.execute(
            """
            SELECT memory_type, content, confidence, source_event_ids
            FROM semantic_memory
            WHERE memory_type ILIKE %s OR content::text ILIKE %s
            ORDER BY confidence DESC, updated_at DESC
            LIMIT %s
            """,
            (pattern, pattern, plan.semantic_limit),
        ).fetchall()
        fact_rows = conn.execute(
            graph_fact_sql(),
            (
                graph_pattern,
                graph_pattern,
                graph_pattern,
                plan.supernode_degree_limit,
                plan.supernode_degree_limit,
                plan.graph_limit,
            ),
        ).fetchall()
        bm25_rows = conn.execute(
            bm25_sql(),
            (query, query, plan.bm25_limit),
        ).fetchall()
        vector_rows = conn.execute(
            """
            SELECT e.timestamp, e.source, e.event_type, e.raw_data, s.summary, s.intent, s.importance,
                   COALESCE(v.metadata, '{}'::jsonb) AS metadata
            FROM events e
            LEFT JOIN semantic_events s ON s.event_id = e.event_id
            LEFT JOIN memory_vectors v ON v.event_id = e.event_id
            WHERE e.raw_data::text ILIKE %s OR COALESCE(s.summary, '') ILIKE %s
            ORDER BY
              CASE WHEN v.embedding IS NULL THEN 1 ELSE 0 END,
              v.embedding <=> %s::vector,
              e.timestamp DESC
            LIMIT %s
            """,
            (pattern, pattern, query_vector, plan.vector_limit),
        ).fetchall()
        if not vector_rows:
            vector_rows = conn.execute(
                """
                SELECT e.timestamp, e.source, e.event_type, e.raw_data, s.summary, s.intent, s.importance,
                       COALESCE(v.metadata, '{}'::jsonb) AS metadata
                FROM events e
                LEFT JOIN semantic_events s ON s.event_id = e.event_id
                LEFT JOIN memory_vectors v ON v.event_id = e.event_id
                ORDER BY
                  CASE WHEN v.embedding IS NULL THEN 1 ELSE 0 END,
                  v.embedding <=> %s::vector,
                  e.timestamp DESC
                LIMIT %s
                """,
                (query_vector, plan.vector_limit),
            ).fetchall()
    context = build_reasoning_context(state_rows, timeline_rows, semantic_rows, fact_rows, bm25_rows, vector_rows)
    policy = infer_memory_access_policy(query)
    scoped_context = filter_context_by_memory_access_policy(context, policy)
    return rerank_context(query, scoped_context)[: max(limit, 1)]


@app.post("/api/chat")
async def chat(body: ChatIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    context = retrieve_context(body.message, body.limit)
    messages = build_chat_messages(body.message, context)
    answer = await QwenClient(MODEL_BASE_URL, MODEL_NAME).chat(messages)
    return {"answer": answer, "sources": decorate_context_sources(context)}


def build_chat_messages(message: str, context: list[dict[str, Any]]) -> list[dict[str, str]]:
    context_text = json.dumps(context, ensure_ascii=False, default=str)
    return [
        {
            "role": "system",
            "content": (
                "你是用户的私有个人助理。你只能基于给定的个人上下文和用户消息回答。"
                "如果证据不足，明确说明不确定。不要编造私人事实。回答要简洁、可执行。"
                "当用户要回复某个联系人、发消息或写邮件时，不能泄露第三方私下评价、抱怨、负面观点或敏感信息。"
                "如果某条上下文只适合用户私下分析，不要把它写进对外回复草稿。"
            ),
        },
        {
            "role": "user",
            "content": f"个人上下文 JSON:\n{context_text}\n\n用户问题:\n{message}",
        },
    ]


@app.websocket("/ws")
async def websocket_realtime(websocket: WebSocket, password: Optional[str] = None):
    if not is_authorized(password):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    redis_task = asyncio.create_task(redis_realtime_listener(websocket))
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "chat_message":
                await stream_chat_to_websocket(websocket, str(data.get("message") or ""), int(data.get("limit") or 12))
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "error", "message": "unsupported realtime message type"})
    except WebSocketDisconnect:
        return
    finally:
        redis_task.cancel()


async def redis_realtime_listener(websocket: WebSocket) -> None:
    client = aioredis.Redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(REALTIME_CHANNEL)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            payload = message.get("data")
            try:
                data = json.loads(payload)
            except (TypeError, json.JSONDecodeError):
                data = {"type": "error", "message": "invalid realtime payload"}
            await websocket.send_json(data)
    except asyncio.CancelledError:
        raise
    finally:
        await pubsub.close()
        await client.close()


async def stream_chat_to_websocket(websocket: WebSocket, message: str, limit: int) -> None:
    if not message.strip():
        await websocket.send_json({"type": "error", "message": "message is required"})
        return
    context = retrieve_context(message, max(1, min(limit, 30)))
    messages = build_chat_messages(message, context)
    answer_parts: list[str] = []
    async for delta in QwenClient(MODEL_BASE_URL, MODEL_NAME).stream_chat(messages):
        if not delta:
            continue
        answer_parts.append(delta)
        await websocket.send_json({"type": "chat_delta", "delta": delta})
    await websocket.send_json(
        {
            "type": "chat_done",
            "answer": "".join(answer_parts),
            "sources": decorate_context_sources(context),
        }
    )


@app.get("/api/memory")
def memory(x_par_password: Optional[str] = Header(default=None), limit: int = 30) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        semantic_rows = conn.execute(
            """
            SELECT id, memory_type, content, confidence, source_event_ids, updated_at
            FROM semantic_memory
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
        timeline_rows = conn.execute(
            """
            SELECT id, date, summary, source_event_ids, created_at
            FROM timeline
            ORDER BY date DESC, created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return {
        "semantic_memory": [
            {
                "id": str(row[0]),
                "memory_type": row[1],
                "content": row[2],
                "confidence": row[3],
                "source_event_ids": [str(x) for x in row[4]],
                "updated_at": row[5].isoformat(),
            }
            for row in semantic_rows
        ],
        "timeline": [
            {
                "id": str(row[0]),
                "date": row[1].isoformat(),
                "summary": row[2],
                "source_event_ids": [str(x) for x in row[3]],
                "created_at": row[4].isoformat(),
            }
            for row in timeline_rows
        ],
    }


@app.get("/api/memory/governance")
def memory_governance(
    x_par_password: Optional[str] = Header(default=None),
    source: Optional[str] = None,
    sensitive: Optional[bool] = None,
    q: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    require_password(x_par_password)
    limit = max(1, min(limit, 100))
    event_conditions = []
    event_params: list[Any] = []
    if source:
        event_conditions.append("e.source = %s")
        event_params.append(source)
    if sensitive is not None:
        event_conditions.append("COALESCE((e.raw_data->>'sensitive')::boolean, false) = %s")
        event_params.append(sensitive)
    if q:
        event_conditions.append("(e.raw_data::text ILIKE %s OR COALESCE(s.summary, '') ILIKE %s)")
        pattern = f"%{q}%"
        event_params.extend([pattern, pattern])
    event_where = f"WHERE {' AND '.join(event_conditions)}" if event_conditions else ""

    memory_pattern = f"%{q}%" if q else "%"
    with db() as conn:
        event_rows = conn.execute(
            f"""
            SELECT e.event_id, e.source, e.event_type, e.raw_data, e.timestamp,
                   s.summary, s.intent, s.importance
            FROM events e
            LEFT JOIN semantic_events s ON s.event_id = e.event_id
            {event_where}
            ORDER BY e.timestamp DESC
            LIMIT %s
            """,
            (*event_params, limit),
        ).fetchall()
        semantic_rows = conn.execute(
            """
            SELECT id, memory_type, content, confidence, source_event_ids, updated_at
            FROM semantic_memory
            WHERE content::text ILIKE %s OR memory_type ILIKE %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (memory_pattern, memory_pattern, limit),
        ).fetchall()
        state_rows = conn.execute(
            """
            SELECT key, value, confidence, source_fact_ids, updated_at
            FROM memory_states
            WHERE key ILIKE %s OR value::text ILIKE %s
            ORDER BY updated_at DESC
            LIMIT %s
            """,
            (memory_pattern, memory_pattern, limit),
        ).fetchall()

    return {
        "filters": {"source": source, "sensitive": sensitive, "q": q},
        "events": [
            {
                "event_id": str(row[0]),
                "source": row[1],
                "event_type": row[2],
                "raw_data": row[3],
                "timestamp": row[4].isoformat() if hasattr(row[4], "isoformat") else row[4],
                "summary": row[5],
                "intent": row[6],
                "importance": row[7],
                "sensitive": bool((row[3] or {}).get("sensitive")),
                "sensitive_reasons": (row[3] or {}).get("sensitive_reasons", []),
            }
            for row in event_rows
        ],
        "semantic_memory": [
            {
                "id": str(row[0]),
                "memory_type": row[1],
                "content": row[2],
                "confidence": row[3],
                "source_event_ids": [str(item) for item in row[4]],
                "updated_at": row[5].isoformat() if hasattr(row[5], "isoformat") else row[5],
            }
            for row in semantic_rows
        ],
        "states": [
            {
                "key": row[0],
                "value": row[1],
                "confidence": row[2],
                "source_fact_ids": [str(item) for item in row[3]],
                "updated_at": row[4].isoformat() if hasattr(row[4], "isoformat") else row[4],
            }
            for row in state_rows
        ],
    }


@app.patch("/api/memory/semantic/{memory_id}")
def correct_semantic_memory(
    memory_id: str,
    body: MemoryCorrectionIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    content = {"summary": body.summary, "source": "user_correction"}
    with db() as conn:
        cur = conn.execute(
            """
            UPDATE semantic_memory
            SET content = %s, confidence = 1, updated_at = now()
            WHERE id = %s
            """,
            (json.dumps(content, ensure_ascii=False), memory_id),
        )
        conn.execute(
            """
            INSERT INTO memory_audit_log (id, action, target_type, target_id, reason, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            """,
            (
                uuid.uuid4(),
                "correct",
                "semantic_memory",
                memory_id,
                body.reason,
                json.dumps({"summary": body.summary}, ensure_ascii=False),
            ),
        )
    return {"updated": cur.rowcount or 0}


@app.get("/api/suggestions")
def suggestions(x_par_password: Optional[str] = Header(default=None), limit: int = 20) -> list[dict[str, Any]]:
    require_password(x_par_password)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id, source_event_id, title, body, priority, status, metadata, created_at, updated_at
            FROM proactive_suggestions
            WHERE status = 'open'
            ORDER BY priority DESC, created_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    rows_as_dicts = [
        {
            "id": str(row[0]),
            "source_event_id": str(row[1]),
            "title": row[2],
            "body": row[3],
            "priority": row[4],
            "status": row[5],
            "metadata": row[6],
            "created_at": row[7].isoformat(),
            "updated_at": row[8].isoformat(),
        }
        for row in rows
    ]
    return filter_open_suggestions(rows_as_dicts)[:limit]


def parse_metadata_datetime(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def filter_open_suggestions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    filtered: list[dict[str, Any]] = []
    seen: set[str] = set()
    sorted_rows = sorted(rows, key=lambda item: (float(item.get("priority") or 0), item.get("created_at") or ""), reverse=True)
    for item in sorted_rows:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        expires_at = parse_metadata_datetime(metadata.get("expires_at"))
        if expires_at and expires_at <= now:
            continue
        dedupe_key = str(metadata.get("dedupe_key") or item.get("id"))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        filtered.append(item)
    return filtered


def suggestion_to_realtime_message(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "type": "proactive_message",
        "id": str(item.get("id", "")),
        "suggestion_id": str(item.get("id", "")),
        "source_event_id": str(item.get("source_event_id", "")),
        "title": item.get("title", ""),
        "body": item.get("body", ""),
        "priority": item.get("priority", 0),
        "source": metadata.get("source") or metadata.get("collector") or "unknown",
        "metadata": metadata,
        "created_at": item.get("created_at"),
        "open_view": "chat",
    }


@app.patch("/api/suggestions/{suggestion_id}")
def update_suggestion(
    suggestion_id: str,
    body: SuggestionStatusIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        cur = conn.execute(
            """
            UPDATE proactive_suggestions
            SET status = %s, updated_at = now()
            WHERE id = %s
            """,
            (body.status, suggestion_id),
        )
    return {"updated": cur.rowcount or 0}


@app.post("/api/consolidate")
def consolidate(
    body: ConsolidateIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        return consolidate_day(conn, body.date)


@app.post("/api/maintenance/daily")
def daily_memory_maintenance(
    body: MaintenanceIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    date_text = body.date or default_maintenance_date()
    with db() as conn:
        return run_daily_memory_maintenance(
            conn,
            date_text=date_text,
            raw_retention_days=body.raw_retention_days,
            low_value_retention_days=body.low_value_retention_days,
        )


@app.get("/collectors/health")
def collectors_health() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT collector, status, last_event_at, last_injection_at, error_count, details, updated_at
            FROM collector_health
            ORDER BY collector
            """
        ).fetchall()
    return [
        {
            "collector": row[0],
            "status": row[1],
            "last_event_at": row[2].isoformat() if row[2] else None,
            "last_injection_at": row[3].isoformat() if row[3] else None,
            "error_count": row[4],
            "details": row[5],
            "updated_at": row[6].isoformat(),
        }
        for row in rows
    ]


@app.post("/collectors/health")
def update_collector_health(body: CollectorHealthIn) -> dict[str, str]:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO collector_health
              (collector, status, last_event_at, last_injection_at, error_count, details, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (collector) DO UPDATE SET
              status = EXCLUDED.status,
              last_event_at = EXCLUDED.last_event_at,
              last_injection_at = EXCLUDED.last_injection_at,
              error_count = EXCLUDED.error_count,
              details = EXCLUDED.details,
              updated_at = now()
            """,
            (
                body.collector,
                body.status,
                body.last_event_at,
                body.last_injection_at,
                body.error_count,
                json.dumps(body.details),
            ),
        )
    return {"status": "ok"}


@app.post("/memory/delete")
def delete_memory(
    body: MemoryDeleteIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    if not body.memory_id and not body.source:
        raise HTTPException(status_code=400, detail="memory_id or source is required")
    deleted = 0
    with db() as conn:
        if body.memory_id:
            cur = conn.execute("DELETE FROM semantic_memory WHERE id = %s", (body.memory_id,))
            deleted += cur.rowcount or 0
        if body.source:
            cur = conn.execute("DELETE FROM events WHERE source = %s", (body.source,))
            deleted += cur.rowcount or 0
    return {"deleted": deleted}


@app.post("/model/route")
def model_route(task: str = "semantic_extraction") -> dict[str, str]:
    return {"mode": os.getenv("MODEL_MODE", "standard"), "task": task}
