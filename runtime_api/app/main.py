from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import uuid
import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import psycopg
import redis
import redis.asyncio as aioredis
import httpx
from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from app.assistant_identity.api import router as assistant_identity_router
from app.assistant_identity.contact_resolver import ContactResolver
from app.assistant_identity.inbox_gateway import AssistantInboxGateway
from app.assistant_identity.outbound import OutboundMessagePipeline
from app.assistant_identity.phone_adapter import PhoneCallInstructionBuilder, PhoneWebhookVerifier
from app.assistant_identity.registry import AssistantIdentityRegistry
from app.assistant_identity.schema import assistant_identity_schema_sql
from app.assistant_memory import assistant_memory_schema_sql, build_session_search_context
from app.auth import is_authorized
from app.delegated_automation.models import (
    AutomationDecision,
    DelegationGrant,
    TargetManifest,
    parse_datetime,
)
from app.delegated_automation.policy import build_execution_trace, evaluate_delegated_action
from app.delegated_automation.schema import delegated_automation_schema_sql
from app.delegated_automation.store import InMemoryDelegatedAutomationStore
from app.model_gateway import ModelGatewayError, default_model_gateway
from app.model_client import QwenClient
from app.long_tail_agent import (
    ExecutorAdapterRegistry,
    ExternalEffectController,
    LongTailEventStore,
    LongTailGraphRunner,
    PostgresLongTailLeaseManager,
    PostgresLongTailEventStore,
    PostgresLongTailRecoveryScanner,
    PolicyGate,
    StepVerifier,
    long_tail_agent_schema_sql,
)
from app.pipelines import run_registered_pipeline
from app.private_events import private_event_gateway_schema_sql
from app.task_orchestrator import task_orchestrator_schema_sql
from app.tool_registry import default_tool_registry, tool_registry_schema_sql
from app.vector import embedding_status, text_embedding, text_embedding_with_provider, vector_literal
from app.voice import handle_voice_websocket
from app.workflow_distillation import workflow_distillation_schema_sql


DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "http://localhost:9161")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.6")
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY", "").strip()
COMPOSIO_API_BASE_URL = os.getenv("COMPOSIO_API_BASE_URL", "https://backend.composio.dev").rstrip("/")
COMPOSIO_USER_ID = os.getenv("COMPOSIO_USER_ID", "nomi_owner").strip() or "nomi_owner"
COMPOSIO_CALLBACK_URL = os.getenv("COMPOSIO_CALLBACK_URL", "").strip()
REALTIME_CHANNEL = os.getenv("REALTIME_CHANNEL", "par:realtime")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
ENABLE_DAILY_MAINTENANCE = os.getenv("ENABLE_DAILY_MAINTENANCE", "true").lower() == "true"
DAILY_MAINTENANCE_HOUR_UTC = int(os.getenv("DAILY_MAINTENANCE_HOUR_UTC", "19"))
RAW_RETENTION_DAYS = int(os.getenv("RAW_RETENTION_DAYS", "30"))
LOW_VALUE_RAW_RETENTION_DAYS = int(os.getenv("LOW_VALUE_RAW_RETENTION_DAYS", "7"))
ENABLE_OPENCLAW_JOB_RUNNER = os.getenv("ENABLE_OPENCLAW_JOB_RUNNER", "true").lower() == "true"
OPENCLAW_JOB_RUNNER_INTERVAL_SECONDS = float(os.getenv("OPENCLAW_JOB_RUNNER_INTERVAL_SECONDS", "5"))
OPENCLAW_JOB_RUNNER_BATCH_SIZE = int(os.getenv("OPENCLAW_JOB_RUNNER_BATCH_SIZE", "2"))
ENABLE_LONG_TAIL_RECOVERY_RUNNER = os.getenv("ENABLE_LONG_TAIL_RECOVERY_RUNNER", "true").lower() == "true"
LONG_TAIL_RECOVERY_INTERVAL_SECONDS = float(os.getenv("LONG_TAIL_RECOVERY_INTERVAL_SECONDS", "10"))
LONG_TAIL_RECOVERY_BATCH_SIZE = int(os.getenv("LONG_TAIL_RECOVERY_BATCH_SIZE", "10"))
LONG_TAIL_RECOVERY_LEASE_SECONDS = int(os.getenv("LONG_TAIL_RECOVERY_LEASE_SECONDS", "30"))
CONTEXT_MODEL_WINDOW_TOKENS = int(os.getenv("CONTEXT_MODEL_WINDOW_TOKENS", "256000"))
CONTEXT_OUTPUT_RESERVED_TOKENS = int(os.getenv("CONTEXT_OUTPUT_RESERVED_TOKENS", "32000"))
CONTEXT_SAFETY_RESERVED_TOKENS = int(os.getenv("CONTEXT_SAFETY_RESERVED_TOKENS", "12000"))
CONTEXT_INPUT_TARGET_TOKENS = int(os.getenv("CONTEXT_INPUT_TARGET_TOKENS", "208000"))
CONTEXT_HARD_INPUT_CEILING_TOKENS = int(os.getenv("CONTEXT_HARD_INPUT_CEILING_TOKENS", "224000"))
CONTEXT_SINGLE_ITEM_TOKEN_LIMIT = int(os.getenv("CONTEXT_SINGLE_ITEM_TOKEN_LIMIT", "8000"))
CONTEXT_TOKENIZER_MODEL = os.getenv("CONTEXT_TOKENIZER_MODEL", "").strip()
CONTEXT_TOKENIZER_BACKEND = os.getenv("CONTEXT_TOKENIZER_BACKEND", "auto").strip().lower()
_CONTEXT_TOKENIZER: Any = None
_CONTEXT_TOKENIZER_BACKEND = "conservative_char_estimator"
_CONTEXT_TOKENIZER_LOAD_ATTEMPTED = False

DEFAULT_COMPOSIO_READONLY_TOOLKITS = [
    "gmail",
    "googlecalendar",
    "googledrive",
    "googledocs",
    "googlesheets",
    "googletasks",
    "google_maps",
    "github",
    "slack",
    "notion",
]
DEFAULT_COMPOSIO_WRITE_TOOLKITS = [
    "gmail",
    "googlecalendar",
    "googledrive",
    "googledocs",
    "googlesheets",
    "googletasks",
    "github",
    "slack",
    "notion",
    "todoist",
    "linear",
    "jira",
]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<![\dA-Za-z-])(?:\+?\d[\d -]{7,}\d)(?![\dA-Za-z-])")
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
AMOUNT_RE = re.compile(
    r"(?<![\dA-Za-z_:.-])(?:(?:¥|￥|\$|RMB\s*)\d{1,7}(?:\.\d{1,2})?\s*(?:元|CNY|USD|美元)?|\d{1,7}(?:\.\d{1,2})?\s*(?:元|CNY|USD|美元))(?![\dA-Za-z_:.-])",
    re.I,
)
BILL_ID_RE = re.compile(r"\b(?:INV|INVOICE|BILL)[-_A-Z0-9]+\b", re.I)
CHINESE_ADDRESS_RE = re.compile(
    r"((?:收货地址|地址)[：:\s]*)([^，。；;\\n]{6,80}(?:号|室|楼|层|单元|弄|路|街|大道|巷|村|县|区|市))"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_collector_settings_schema()
    ensure_event_private_storage_schema()
    ensure_private_event_gateway_schema()
    ensure_assistant_identity_schema()
    ensure_memory_governance_schema()
    ensure_assistant_context_schema()
    ensure_curated_assistant_memory_schema()
    ensure_proactive_feedback_schema()
    ensure_task_routing_schema()
    ensure_task_orchestrator_schema()
    ensure_long_tail_agent_schema()
    ensure_tool_registry_schema()
    ensure_workflow_distillation_schema()
    ensure_openclaw_execution_schema()
    ensure_delegated_automation_schema()
    ensure_model_gateway_schema()
    text_embedding_with_provider("startup embedding warmup")
    tasks: list[asyncio.Task] = []
    if ENABLE_DAILY_MAINTENANCE:
        tasks.append(asyncio.create_task(daily_maintenance_loop()))
    if ENABLE_OPENCLAW_JOB_RUNNER:
        tasks.append(asyncio.create_task(openclaw_execution_job_runner_loop()))
    if ENABLE_LONG_TAIL_RECOVERY_RUNNER and DATABASE_URL != "postgresql://test":
        tasks.append(asyncio.create_task(long_tail_recovery_runner_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Nomi Personal Assistant Runtime", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(assistant_identity_router)


def build_long_tail_event_store() -> LongTailEventStore:
    store_mode = os.getenv("LONG_TAIL_EVENT_STORE", "auto").strip().lower()
    if store_mode == "memory" or DATABASE_URL == "postgresql://test":
        return LongTailEventStore()
    return PostgresLongTailEventStore(
        connection_factory=lambda: psycopg.connect(DATABASE_URL),
        materialize_events=True,
    )


_MODEL_GATEWAY: Any = None
_LONG_TAIL_EVENT_STORE = build_long_tail_event_store()
_LONG_TAIL_RUNNER = LongTailGraphRunner(event_store=_LONG_TAIL_EVENT_STORE, verifier=StepVerifier())
_LONG_TAIL_EFFECT_CONTROLLER = ExternalEffectController(event_store=_LONG_TAIL_EVENT_STORE)
_DELEGATED_AUTOMATION_STORE = InMemoryDelegatedAutomationStore()
_ASSISTANT_OUTBOUND_PIPELINE = OutboundMessagePipeline()
_ASSISTANT_IDENTITY_REGISTRY = AssistantIdentityRegistry()
_ASSISTANT_INBOX_EVENTS: list[dict[str, Any]] = []
_ASSISTANT_OUTBOUND_MESSAGES: list[dict[str, Any]] = []


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
    message: str = Field(min_length=1, max_length=50000)
    limit: int = Field(default=12, ge=1, le=50)
    conversation_id: Optional[str] = None
    client_type: str = Field(default="web", max_length=40)
    client_context: list[dict[str, Any]] = Field(default_factory=list)
    client_context_delta: list[dict[str, Any]] = Field(default_factory=list)
    ui_state: dict[str, Any] = Field(default_factory=dict)


class ToolRouteIn(BaseModel):
    request: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


class PipelineRunIn(BaseModel):
    request: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)


class DelegatedAutomationEvaluateIn(BaseModel):
    grant_id: str = Field(min_length=1, max_length=160)
    manifest_id: str = Field(min_length=1, max_length=160)
    target_id: str = Field(min_length=1, max_length=240)
    content_evidence_ids: list[str] = Field(default_factory=list)
    page_state: dict[str, Any] = Field(default_factory=dict)
    user_paused: bool = False
    now: Optional[str] = None


class DelegatedAutomationTraceIn(BaseModel):
    decision: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=40)
    result_summary: str = Field(default="", max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list)
    now: Optional[str] = None


class DelegatedAutomationPauseIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class ComposioToolExecuteIn(BaseModel):
    toolkit_slug: str = Field(min_length=1, max_length=120)
    tool_slug: str = Field(min_length=1, max_length=160)
    arguments: dict[str, Any] = Field(default_factory=dict)
    session_kind: str = Field(default="readonly", max_length=40)
    task_id: Optional[str] = None
    step_id: Optional[str] = None


class AssistantGmailSyncIn(BaseModel):
    identity_id: str = Field(default="nomi_gmail_primary", max_length=120)
    message: dict[str, Any] = Field(default_factory=dict)
    user_keys: list[str] = Field(default_factory=list)
    known_contacts: dict[str, str] = Field(default_factory=dict)


class AssistantIdentityPatchIn(BaseModel):
    display_name: Optional[str] = Field(default=None, max_length=120)
    status: Optional[str] = Field(default=None, max_length=80)


class AssistantWhatsAppWebhookIn(BaseModel):
    entry: list[dict[str, Any]] = Field(default_factory=list)
    known_contacts: dict[str, str] = Field(default_factory=dict)


class AssistantGmailPubSubIn(BaseModel):
    message: dict[str, Any] = Field(default_factory=dict)


class AssistantPhoneSmsWebhookIn(BaseModel):
    identity_id: str = Field(default="nomi_phone_primary", max_length=120)
    provider_message_id: Optional[str] = Field(default=None, max_length=200)
    from_number: str = Field(default="", max_length=80)
    to_number: str = Field(default="", max_length=80)
    body: str = Field(default="", max_length=10000)
    timestamp: Optional[str] = Field(default=None, max_length=120)
    known_contacts: dict[str, str] = Field(default_factory=dict)
    user_keys: list[str] = Field(default_factory=list)


class AssistantPhoneCallWebhookIn(BaseModel):
    identity_id: str = Field(default="nomi_phone_primary", max_length=120)
    provider_call_id: Optional[str] = Field(default=None, max_length=200)
    from_number: str = Field(default="", max_length=80)
    to_number: str = Field(default="", max_length=80)
    direction: str = Field(default="inbound", max_length=40)
    status: str = Field(default="received", max_length=80)
    timestamp: Optional[str] = Field(default=None, max_length=120)
    known_contacts: dict[str, str] = Field(default_factory=dict)
    user_keys: list[str] = Field(default_factory=list)


class AssistantOutboundDraftIn(BaseModel):
    identity_id: str = Field(min_length=1, max_length=120)
    channel: str = Field(min_length=1, max_length=40)
    recipient: str = Field(min_length=1, max_length=300)
    subject: str = Field(default="", max_length=500)
    body_text: str = Field(min_length=1, max_length=10000)
    source_evidence_ids: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


class AssistantOutboundDraftPatchIn(BaseModel):
    subject: Optional[str] = Field(default=None, max_length=500)
    body_text: Optional[str] = Field(default=None, max_length=10000)
    risk_notes: Optional[list[str]] = None


class AssistantOutboundSendIn(BaseModel):
    confirmation_token: str = Field(default="", max_length=500)


class GmailComposioFetchIn(BaseModel):
    query: str = Field(default="newer_than:1d", max_length=1000)
    limit: int = Field(default=20, ge=1, le=50)


class AgentTaskCreateIn(BaseModel):
    original_goal: str = Field(min_length=1, max_length=5000)
    route_decision: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any]


class AgentTaskCompleteStepIn(BaseModel):
    executor_result: dict[str, Any]


class AgentTaskCancelIn(BaseModel):
    reason: str = Field(default="", max_length=1000)


class AgentTaskHumanInputIn(BaseModel):
    step_id: Optional[str] = None
    input_type: str = Field(default="user_response", max_length=80)
    response: dict[str, Any] = Field(default_factory=dict)


class AgentTaskConfirmIn(BaseModel):
    step_id: Optional[str] = None
    confirmation: dict[str, Any] = Field(default_factory=dict)


class AgentTaskExternalEffectIn(BaseModel):
    step_id: str = Field(min_length=1, max_length=200)
    action_request_id: str = Field(min_length=1, max_length=200)
    effect_type: str = Field(min_length=1, max_length=120)
    proposal: dict[str, Any] = Field(default_factory=dict)


class AgentTaskExternalEffectConfirmIn(BaseModel):
    confirmation: dict[str, Any] = Field(default_factory=dict)


class AgentTaskExternalEffectExecuteIn(BaseModel):
    execution_payload: dict[str, Any] = Field(default_factory=dict)


class AgentTaskExternalEffectCompensationIn(BaseModel):
    proposal: dict[str, Any] = Field(default_factory=dict)


class BrowserOpenIn(BaseModel):
    source: str = Field(min_length=1, max_length=80)


class OpenClawExecuteIn(BaseModel):
    packet: dict[str, Any]
    execution_guard: dict[str, Any] = Field(default_factory=dict)


class OpenClawJobIn(BaseModel):
    packet: dict[str, Any]
    execution_guard: dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None
    max_attempts: int = Field(default=3, ge=1, le=5)


class SensitiveFieldReleaseIn(BaseModel):
    field: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=2000)
    purpose: str = Field(min_length=1, max_length=500)
    task_id: Optional[str] = None


class MemoryDeleteIn(BaseModel):
    memory_id: Optional[str] = None
    source: Optional[str] = None
    state_key: Optional[str] = None


class MemoryCorrectionIn(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    reason: str = ""


class SuggestionStatusIn(BaseModel):
    status: str = Field(pattern="^(open|done|dismissed)$")


class AgendaPatchIn(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    certainty: Optional[str] = None
    time_window: Optional[dict[str, Any]] = None
    place: Optional[str] = None
    participants: Optional[list[str]] = None
    missing_fields: Optional[list[str]] = None
    needs_clarification: Optional[bool] = None
    confidence: Optional[float] = None
    metadata: Optional[dict[str, Any]] = None
    reason: str = ""


class AgendaSnoozeIn(BaseModel):
    snoozed_until: str = Field(min_length=1, max_length=80)
    reason: str = ""


class SuggestionActionIn(BaseModel):
    action_id: str = Field(min_length=1, max_length=80)
    reason: str = ""
    rating: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    snoozed_until: Optional[str] = None


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


def model_gateway():
    global _MODEL_GATEWAY
    if _MODEL_GATEWAY is None:
        _MODEL_GATEWAY = default_model_gateway()
    return _MODEL_GATEWAY


def jsonb_param(value: Any) -> Jsonb | None:
    if value is None:
        return None
    return Jsonb(value)


def persist_model_request_trace(
    conn: psycopg.Connection,
    *,
    task_class: str,
    selected_provider_id: str,
    status: str,
    fallback_provider_ids: Optional[list[str]] = None,
    error_type: str = "",
    user_visible_message: str = "",
    context_snapshot_id: Optional[str] = None,
    input_token_estimate: Optional[int] = None,
    output_token_estimate: Optional[int] = None,
    stream_first_token_ms: Optional[int] = None,
    latency_ms: Optional[int] = None,
    payload: Optional[dict[str, Any]] = None,
) -> str:
    trace_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO model_request_traces (
          id, task_class, selected_provider_id, fallback_provider_ids, status,
          error_type, user_visible_message, context_snapshot_id,
          input_token_estimate, output_token_estimate, stream_first_token_ms,
          latency_ms, payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            trace_id,
            task_class,
            selected_provider_id,
            fallback_provider_ids or [],
            status,
            error_type,
            user_visible_message,
            context_snapshot_id,
            input_token_estimate,
            output_token_estimate,
            stream_first_token_ms,
            latency_ms,
            jsonb_param(payload or {}),
        ),
    )
    return trace_id


def model_trace_fallbacks(trace: dict[str, Any]) -> list[str]:
    raw = trace.get("fallback_from") if isinstance(trace, dict) else []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item)]


def safe_persist_model_request_trace(conn: psycopg.Connection, **kwargs: Any) -> Optional[str]:
    try:
        return persist_model_request_trace(conn, **kwargs)
    except Exception:
        return None


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
            key_is_timestamp = bool(re.search(r"(?:^|_)(?:created|updated|approved|timestamp|time|date)_?at$|timestamp|date", key_hint, re.I))
            value_is_timestamp = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T\s].*)?", item.strip()))
            is_timestamp_like = key_is_timestamp or value_is_timestamp
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
            phone_spans = [match.span() for match in PHONE_RE.finditer(item)]
            for name, pattern in checks:
                if is_timestamp_like and name in {"phone", "amount"}:
                    continue
                if name == "amount":
                    for amount_match in AMOUNT_RE.finditer(item):
                        amount_span = amount_match.span()
                        inside_phone = any(
                            amount_span[0] >= phone_span[0] and amount_span[1] <= phone_span[1]
                            for phone_span in phone_spans
                        )
                        has_currency_marker = bool(re.search(r"(¥|￥|RMB|CNY|USD|美元|元)", amount_match.group(0), re.I))
                        if inside_phone and not has_currency_marker:
                            continue
                        reasons.add(name)
                        break
                    continue
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


def long_tail_runner() -> LongTailGraphRunner:
    return _LONG_TAIL_RUNNER


def long_tail_event_store() -> LongTailEventStore:
    return _LONG_TAIL_EVENT_STORE


def long_tail_effect_controller() -> ExternalEffectController:
    global _LONG_TAIL_EFFECT_CONTROLLER
    if _LONG_TAIL_EFFECT_CONTROLLER.event_store is not _LONG_TAIL_EVENT_STORE:
        _LONG_TAIL_EFFECT_CONTROLLER = ExternalEffectController(event_store=_LONG_TAIL_EVENT_STORE)
    return _LONG_TAIL_EFFECT_CONTROLLER


def require_long_tail_task(task_id: str) -> dict[str, Any]:
    try:
        return long_tail_runner().get_task_state(task_id)
    except KeyError as exc:
        if long_tail_event_store().task_events(task_id):
            return long_tail_runner().recover_task(task_id)
        raise HTTPException(status_code=404, detail="task not found") from exc


BROWSER_COMMAND_QUEUE_KEY = "browser:commands"
BROWSER_OPEN_TARGETS: dict[str, dict[str, str]] = {
    "whatsapp": {
        "host_fragment": "web.whatsapp.com",
        "url": "https://web.whatsapp.com/",
    },
    "telegram": {
        "host_fragment": "web.telegram.org",
        "url": "https://web.telegram.org/",
    },
    "search": {
        "host_fragment": "google.",
        "url": "https://www.google.com/",
    },
    "shopping": {
        "host_fragment": "amazon.",
        "url": "https://www.amazon.com/",
    },
}


def browser_open_target(source: str) -> dict[str, str]:
    normalized = (source or "").strip().lower()
    target = BROWSER_OPEN_TARGETS.get(normalized)
    if not target:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_browser_source",
                "message": f"{source} is not a supported managed browser login source.",
                "supported_sources": sorted(BROWSER_OPEN_TARGETS),
            },
        )
    return {"source": normalized, **target}


def normalize_browser_command_payload(value: Any) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None
    action = str(value.get("action") or "")
    source = str(value.get("source") or "")
    target = BROWSER_OPEN_TARGETS.get(source)
    if action != "open_url" or not target:
        return None
    return {
        "command_id": str(value.get("command_id") or ""),
        "action": "open_url",
        "source": source,
        "url": target["url"],
        "host_fragment": target["host_fragment"],
        "created_at": str(value.get("created_at") or ""),
    }


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
            "id": "task.todo.manage",
            "domain": "task",
            "category": "todo",
            "action": "manage",
            "risk_permission": "write",
            "tool_ids": ["tasks", "google_calendar"],
            "keywords": ["待办", "todo", "任务", "跟进", "commitment", "截止", "deadline"],
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
            "id": "local_service.route.lookup",
            "domain": "local_service",
            "category": "route",
            "action": "lookup",
            "risk_permission": "read_only",
            "tool_ids": ["google_maps"],
            "keywords": ["查路线", "怎么去", "导航", "多久到", "要多久", "通勤", "地图"],
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
            "id": "finance.payment_bill.manage",
            "domain": "finance",
            "category": "payment",
            "action": "manage",
            "risk_permission": "payment_or_purchase",
            "tool_ids": ["stripe", "browser_automation"],
            "keywords": ["付款", "支付", "账单", "发票", "报销", "转账", "还款", "欠款"],
        },
        {
            "id": "contacts.relationship.update",
            "domain": "contacts",
            "category": "relationship",
            "action": "update",
            "risk_permission": "read_only",
            "tool_ids": [],
            "keywords": ["联系人", "关系", "偏好", "生日", "称呼", "他喜欢", "她喜欢"],
        },
        {
            "id": "files.document.process",
            "domain": "files",
            "category": "document",
            "action": "process",
            "risk_permission": "write",
            "tool_ids": ["google_drive_docs", "google_sheets"],
            "keywords": ["文档", "文件", "表格", "sheet", "docs", "drive", "总结这个文档"],
        },
        {
            "id": "account.login.manage",
            "domain": "account",
            "category": "login",
            "action": "manage",
            "risk_permission": "external_execution",
            "tool_ids": ["browser_automation"],
            "keywords": ["登录账号", "连接账号", "授权", "登录gmail", "登录 whatsapp", "登录 amazon"],
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


def pipeline_definition(
    *,
    pipeline_id: str,
    name: str,
    capability_id: str,
    steps: list[str],
    permission: str,
    required_slots: Optional[list[str]] = None,
    allowed_tools: Optional[list[str]] = None,
    forbidden_tools: Optional[list[str]] = None,
    writeback_targets: Optional[list[str]] = None,
    external_effects: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "id": pipeline_id,
        "version": "2026-05-28",
        "name": name,
        "capability_id": capability_id,
        "steps": steps,
        "permission": permission,
        "required_slots": required_slots or [],
        "allowed_tools": allowed_tools or [],
        "forbidden_tools": forbidden_tools or [],
        "writeback_targets": writeback_targets or ["task_trace"],
        "external_effects": external_effects or [],
    }


def core_pipeline_registry() -> list[dict[str, Any]]:
    return [
        pipeline_definition(
            pipeline_id="event_ingestion_pipeline",
            name="私有事件入库 Pipeline",
            capability_id="event.ingest",
            steps=["normalize", "dedupe", "append_event_ledger", "emit_processing_jobs"],
            permission="read_only",
            required_slots=["source", "event_type", "timestamp"],
            writeback_targets=["events", "collector_health", "task_trace"],
        ),
        pipeline_definition(
            pipeline_id="memory_write_pipeline",
            name="长期记忆写入 Pipeline",
            capability_id="memory.write",
            steps=["classify_scope", "write_kv", "write_graph", "write_rag_chunk", "index_embedding"],
            permission="read_only",
            required_slots=["event_id", "source_scope"],
            writeback_targets=["memory_items", "knowledge_entities", "knowledge_edges", "memory_vectors"],
        ),
        pipeline_definition(
            pipeline_id="context_pack_pipeline",
            name="上下文包 Pipeline",
            capability_id="context.pack",
            steps=["retrieve_scoped_memory", "retrieve_active_agenda", "retrieve_recent_turns", "assemble_context_pack"],
            permission="read_only",
            required_slots=["request_or_event_id"],
            writeback_targets=["context_snapshots"],
        ),
        pipeline_definition(
            pipeline_id="personal_search_pipeline",
            name="个人搜索 Pipeline",
            capability_id="memory.personal_search",
            steps=["分层召回", "作用域过滤", "证据组装", "回答"],
            permission="read_only",
            required_slots=["query"],
            writeback_targets=["assistant_turns", "task_trace"],
        ),
        pipeline_definition(
            pipeline_id="chat_response_pipeline",
            name="Nomi 对话 Pipeline",
            capability_id="assistant.chat.respond",
            steps=["store_user_turn", "build_context_pack", "stream_model_response", "store_assistant_turn"],
            permission="read_only",
            required_slots=["conversation_id", "message"],
            allowed_tools=["model_api"],
            writeback_targets=["assistant_turns", "events", "task_trace"],
        ),
        pipeline_definition(
            pipeline_id="reply_pipeline",
            name="回复消息 Pipeline",
            capability_id="communication.message.draft_reply",
            steps=["识别对象", "拉当前会话", "拉允许使用的记忆", "生成草稿", "防泄露检查", "用户确认"],
            permission="external_message",
            required_slots=["recipient", "channel", "message_intent"],
            allowed_tools=["whatsapp", "slack", "gmail", "outlook_graph"],
            forbidden_tools=["payment_gateway", "purchase_tool"],
            writeback_targets=["assistant_turns", "task_trace", "memory_items"],
            external_effects=["send_message"],
        ),
        pipeline_definition(
            pipeline_id="email_pipeline",
            name="邮件处理 Pipeline",
            capability_id="communication.email.process",
            steps=["搜索邮件", "总结重点", "提取待办", "起草回复", "用户确认"],
            permission="external_message",
            required_slots=["mailbox", "email_intent"],
            allowed_tools=["gmail", "outlook_graph"],
            forbidden_tools=["payment_gateway"],
            writeback_targets=["assistant_turns", "agenda_items", "task_trace", "memory_items"],
            external_effects=["send_email", "archive_email", "label_email"],
        ),
        pipeline_definition(
            pipeline_id="agenda_pipeline",
            name="日程管理 Pipeline",
            capability_id="schedule.calendar.create_event",
            steps=["识别时间地点人物", "检查冲突", "生成日程建议", "写入内部日程", "外部日历确认"],
            permission="write",
            required_slots=["time_window", "title"],
            allowed_tools=["google_calendar", "outlook_graph", "apple_reminders_calendar"],
            writeback_targets=["agenda_items", "agenda_item_versions", "task_trace"],
            external_effects=["write_calendar"],
        ),
        pipeline_definition(
            pipeline_id="task_todo_pipeline",
            name="待办跟进 Pipeline",
            capability_id="task.todo.manage",
            steps=["识别承诺", "解析截止时间", "写入内部待办", "计划提醒", "外部任务确认"],
            permission="write",
            required_slots=["task_title"],
            allowed_tools=["tasks", "google_calendar"],
            writeback_targets=["agenda_items", "agenda_item_versions", "task_trace"],
            external_effects=["write_task"],
        ),
        pipeline_definition(
            pipeline_id="proactive_suggestion_pipeline",
            name="主动建议 Pipeline",
            capability_id="suggestion.proactive",
            steps=["事件进入", "语义抽取", "重要性评分", "冷却检查", "触发建议"],
            permission="draft",
            required_slots=["candidate_type", "source_event_ids"],
            writeback_targets=["proactive_candidates", "proactive_suggestions", "task_trace"],
        ),
        pipeline_definition(
            pipeline_id="route_pipeline",
            name="路线查询 Pipeline",
            capability_id="local_service.route.lookup",
            steps=["识别出发地", "识别目的地", "查路线", "展示 ETA 和备选方案"],
            permission="read_only",
            required_slots=["destination"],
            allowed_tools=["google_maps"],
            writeback_targets=["route_cache", "assistant_turns", "task_trace"],
        ),
        pipeline_definition(
            pipeline_id="ride_pipeline",
            name="打车 Pipeline",
            capability_id="local_service.ride.estimate_or_book",
            steps=["识别目的地", "查路线", "查车型价格", "展示建议", "确认后叫车"],
            permission="payment_or_purchase",
            required_slots=["pickup", "destination"],
            allowed_tools=["uber", "google_maps", "browser_automation"],
            forbidden_tools=["unapproved_payment_gateway"],
            writeback_targets=["assistant_turns", "agenda_items", "task_trace", "memory_items"],
            external_effects=["book_ride", "payment"],
        ),
        pipeline_definition(
            pipeline_id="shopping_pipeline",
            name="购物比价 Pipeline",
            capability_id="commerce.product.compare",
            steps=["识别商品", "读取偏好", "搜索候选", "比较", "确认后加购或跳转"],
            permission="payment_or_purchase",
            required_slots=["product_intent"],
            allowed_tools=["amazon_shopping", "shopify", "browser_automation"],
            forbidden_tools=["unapproved_payment_gateway"],
            writeback_targets=["assistant_turns", "task_trace", "memory_items"],
            external_effects=["add_to_cart", "purchase", "payment"],
        ),
        pipeline_definition(
            pipeline_id="payment_bill_pipeline",
            name="账单付款 Pipeline",
            capability_id="finance.payment_bill.manage",
            steps=["识别账单", "核对金额", "核对收款方", "展示风险", "确认后付款或记录"],
            permission="payment_or_purchase",
            required_slots=["counterparty", "amount_or_bill"],
            allowed_tools=["stripe", "browser_automation"],
            forbidden_tools=["unapproved_bank_transfer"],
            writeback_targets=["agenda_items", "memory_items", "task_trace"],
            external_effects=["payment", "transfer"],
        ),
        pipeline_definition(
            pipeline_id="contact_relationship_pipeline",
            name="联系人关系 Pipeline",
            capability_id="contacts.relationship.update",
            steps=["抽取联系人事实", "判断关系作用域", "更新图谱", "记录证据"],
            permission="read_only",
            required_slots=["contact_or_actor"],
            writeback_targets=["knowledge_entities", "knowledge_edges", "memory_items", "task_trace"],
        ),
        pipeline_definition(
            pipeline_id="document_file_pipeline",
            name="文档文件 Pipeline",
            capability_id="files.document.process",
            steps=["定位文件", "读取内容", "总结或生成草稿", "写入前确认"],
            permission="write",
            required_slots=["file_or_query", "document_intent"],
            allowed_tools=["google_drive_docs", "google_sheets"],
            writeback_targets=["assistant_turns", "task_trace", "memory_items"],
            external_effects=["write_document", "share_file"],
        ),
        pipeline_definition(
            pipeline_id="account_login_pipeline",
            name="账号登录 Pipeline",
            capability_id="account.login.manage",
            steps=["选择渠道", "打开受控浏览器", "用户手动输入凭证", "记录连接状态"],
            permission="external_execution",
            required_slots=["account_provider"],
            allowed_tools=["browser_automation"],
            forbidden_tools=["credential_generator"],
            writeback_targets=["account_connections", "collector_settings", "task_trace"],
        ),
        pipeline_definition(
            pipeline_id="governance_audit_pipeline",
            name="治理审计 Pipeline",
            capability_id="governance.audit.trace",
            steps=["记录路由", "记录风险", "记录确认", "记录输出", "记录反馈"],
            permission="read_only",
            required_slots=["task_id"],
            writeback_targets=["memory_audit_log", "task_trace"],
        ),
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


def build_task_route_decision(
    *,
    route_type: str,
    capability: dict[str, Any],
    pipeline: Optional[dict[str, Any]],
    guard: dict[str, Any],
) -> dict[str, Any]:
    pipeline_id = pipeline["id"] if pipeline else None
    if route_type == "core_pipeline":
        reason = f"命中核心高频任务，使用确定性 Pipeline：{pipeline_id}。"
        confidence = 0.9
    elif route_type == "openclaw_tool":
        reason = "未命中确定性核心 Pipeline，交给 OpenClaw 长尾执行工具，并由 Nomi 保留确认和结果验收。"
        confidence = 0.72
    else:
        reason = "任务信息不足或外部影响不明确，需要先确认关键字段后再执行。"
        confidence = 0.64
    return {
        "route_type": route_type,
        "pipeline_id": pipeline_id,
        "capability_id": capability["id"],
        "confidence": confidence,
        "reason": reason,
        "risk_permission": guard["permission"],
        "confirmation_required": guard["requires_confirmation"],
        "final_user_confirmation": guard["final_user_confirmation"],
    }


def openclaw_allowed_actions(capability: dict[str, Any]) -> list[str]:
    if capability["id"] == "automation.browser.operate":
        return ["open_page", "read_page", "fill_form", "download_file"]
    if capability["risk_permission"] == "read_only":
        return ["open_page", "read_page", "extract_data"]
    if capability["risk_permission"] in {"write", "external_message"}:
        return ["open_page", "read_page", "fill_form", "draft_change"]
    return ["open_page", "read_page", "fill_form", "draft_change"]


def openclaw_forbidden_actions(permission: str) -> list[str]:
    forbidden = {"delete", "change_account_settings", "submit", "send_message", "pay", "purchase", "book", "transfer"}
    if permission == "read_only":
        forbidden.update({"fill_form", "draft_change"})
    if permission == "external_message":
        forbidden.update({"send_email", "post_message"})
    if permission == "payment_or_purchase":
        forbidden.update({"confirm_order", "add_payment_method"})
    return sorted(forbidden)


OPENCLAW_CONTEXT_ALLOWLIST = {
    "active_source_scope",
    "agenda_item_ids",
    "agenda_item_id",
    "conversation_id",
    "current_url",
    "event_summary",
    "form_fields",
    "page_title",
    "selected_text",
    "suggestion_id",
    "source_event_ids",
    "user_approved_fields",
}


def protected_context_preview(context: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    preview = {}
    protected = protect_private_value(context)
    for key, decision in decisions.items():
        if decision.get("include"):
            preview[key] = protected.get(key)
    return preview


def model_context_necessity_delta(
    request: str,
    capability: dict[str, Any],
    context: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if os.getenv("OPENCLAW_CONTEXT_MODEL_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        return {}
    preview = protected_context_preview(context, decisions)
    prompt = {
        "task": request,
        "capability": capability["id"],
        "candidate_context": preview,
        "instruction": (
            "Return JSON with include_keys and exclude_keys. You may only exclude keys. "
            "Do not include keys that are absent from candidate_context."
        ),
    }
    try:
        response = httpx.post(
            f"{MODEL_BASE_URL.rstrip('/')}/v1/chat/completions",
            json={
                "model": MODEL_NAME,
                "messages": [
                    {"role": "system", "content": "You classify minimum necessary context for a delegated browser agent."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, sort_keys=True)},
                ],
                "temperature": 0,
                "stream": False,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        content = ""
        if isinstance(data, dict) and data.get("choices"):
            content = str(data["choices"][0].get("message", {}).get("content", ""))
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def build_sensitive_field_release(
    *,
    field: str,
    value: str,
    purpose: str,
    task_id: Optional[str] = None,
) -> dict[str, Any]:
    normalized_field = re.sub(r"[^A-Za-z0-9_.:-]+", "_", field.strip()).strip("_") or "field"
    approval_material = json.dumps(
        {
            "field": normalized_field,
            "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "purpose": purpose,
            "task_id": task_id,
            "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    approval_id = f"sfr_{hashlib.sha1(approval_material.encode('utf-8')).hexdigest()[:16]}"
    return {
        "approved_sensitive_fields": {
            normalized_field: {
                "value": value,
                "approved": True,
                "approval_id": approval_id,
                "purpose": purpose,
                "task_id": task_id,
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
        }
    }


def extract_approved_sensitive_fields(value: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(value, dict):
        return {}, []
    approved: dict[str, Any] = {}
    summaries: list[dict[str, Any]] = []
    for field, release in value.items():
        if not isinstance(release, dict):
            continue
        if release.get("approved") is not True:
            continue
        raw_value = release.get("value")
        approval_id = str(release.get("approval_id") or "")
        purpose = str(release.get("purpose") or "")
        if raw_value in (None, "") or not approval_id.startswith("sfr_") or not purpose.strip():
            continue
        field_name = str(field)
        approved[field_name] = {
            "value": raw_value,
            "approved": True,
            "approval_id": approval_id,
            "purpose": purpose,
            "task_id": release.get("task_id"),
            "approved_at": release.get("approved_at"),
        }
        summaries.append(
            {
                "field": field_name,
                "approval_id": approval_id,
                "purpose": purpose,
                "task_id": release.get("task_id"),
            }
        )
    return approved, summaries


def assess_openclaw_context_necessity(
    request: str,
    capability: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    protected_context = protect_private_value(context)
    sensitive_reasons = collect_sensitive_reasons(context)
    decisions: dict[str, dict[str, Any]] = {}
    approved_sensitive_fields: dict[str, Any] = {}
    approved_sensitive_releases: list[dict[str, Any]] = []
    for key, value in context.items():
        if key == "approved_sensitive_fields":
            approved_sensitive_fields, approved_sensitive_releases = extract_approved_sensitive_fields(value)
            include = bool(approved_sensitive_fields)
            decisions[key] = {
                "include": include,
                "reason": "raw_value_released_after_user_approval" if include else "missing_valid_sensitive_field_release",
                "sensitive": True,
            }
            continue
        include = key in OPENCLAW_CONTEXT_ALLOWLIST
        decisions[key] = {
            "include": include,
            "reason": "allowlisted_minimum_context" if include else "not_in_openclaw_allowlist",
            "sensitive": bool(collect_sensitive_reasons({key: value})),
        }

    mode = "rules"
    model_delta = model_context_necessity_delta(request, capability, context, decisions)
    model_excludes = set(model_delta.get("exclude_keys") or [])
    if model_delta:
        mode = "rules+model"
        for key in model_excludes:
            if key in decisions and decisions[key]["include"]:
                decisions[key]["include"] = False
                decisions[key]["reason"] = "model_excluded"

    minimal_context = {
        key: protected_context[key]
        for key, decision in decisions.items()
        if decision["include"] and key in protected_context
    }
    if approved_sensitive_fields and decisions.get("approved_sensitive_fields", {}).get("include"):
        minimal_context["approved_sensitive_fields"] = approved_sensitive_fields
    return {
        "mode": mode,
        "sensitive": bool(sensitive_reasons),
        "sensitive_reasons": sensitive_reasons,
        "decisions": decisions,
        "model_delta": model_delta,
        "minimal_context": minimal_context,
        "approved_sensitive_releases": approved_sensitive_releases,
    }


def minimize_openclaw_context(context: dict[str, Any]) -> dict[str, Any]:
    capability = {"id": "automation.browser.operate"}
    return assess_openclaw_context_necessity("", capability, context)["minimal_context"]


def build_openclaw_task_packet(
    *,
    request: str,
    capability: dict[str, Any],
    context: dict[str, Any],
    guard: dict[str, Any],
) -> dict[str, Any]:
    context_assessment = assess_openclaw_context_necessity(request, capability, context)
    packet_hash = hashlib.sha1(
        json.dumps(
            {"request": request, "capability_id": capability["id"], "context": context_assessment["minimal_context"]},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return {
        "task_id": f"openclaw_{packet_hash}",
        "goal": request,
        "minimal_context": context_assessment["minimal_context"],
        "context_necessity": {
            "mode": context_assessment["mode"],
            "sensitive": context_assessment["sensitive"],
            "sensitive_reasons": context_assessment["sensitive_reasons"],
            "decisions": context_assessment["decisions"],
            "approved_sensitive_releases": context_assessment["approved_sensitive_releases"],
        },
        "allowed_actions": openclaw_allowed_actions(capability),
        "forbidden_actions": openclaw_forbidden_actions(guard["permission"]),
        "max_steps": 20,
        "requires_stop_before": ["submission", "payment", "external_message", "external_write"],
        "return_schema": {
            "status": "draft_ready | completed_read_only | blocked | needs_user_input | failed",
            "summary": "string",
            "evidence": ["string"],
            "proposed_next_action": "string",
            "needs_confirmation": True,
        },
    }


def openclaw_base_url() -> str:
    return os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/")


def openclaw_enabled() -> bool:
    return os.getenv("OPENCLAW_ENABLED", "false").lower() in {"1", "true", "yes"}


def openclaw_prompt_from_packet(packet: dict[str, Any], guard: dict[str, Any]) -> str:
    return "\n".join(
        [
            "你是 Nomi 委托的长尾执行工具，只能完成受限任务包里的目标。",
            f"目标：{packet.get('goal', '')}",
            f"最小上下文：{json.dumps(packet.get('minimal_context') or {}, ensure_ascii=False)}",
            f"允许动作：{', '.join(packet.get('allowed_actions') or [])}",
            f"禁止动作：{', '.join(packet.get('forbidden_actions') or [])}",
            f"停止前置条件：{', '.join(packet.get('requires_stop_before') or [])}",
            f"权限：{guard.get('permission', 'read_only')}",
            "如果需要提交、付款、发消息、删除、预订、写入外部系统或改变账号设置，必须停止并返回 needs_confirmation=true。",
            "请按任务包 return_schema 返回简短结果，不要泄露未提供的上下文。",
        ]
    )


def output_text_from_openclaw_response(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    output = data.get("output")
    if isinstance(output, list):
        texts: list[str] = []
        for item in output:
            if isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            texts.append(part["text"])
                elif isinstance(content, str):
                    texts.append(content)
        return "\n".join(texts)
    return ""


def publish_realtime_message_safely(message: dict[str, Any], redis_obj: Any = None) -> bool:
    if redis_obj is None and REDIS_URL == "redis://test":
        return False
    try:
        client = redis_obj or redis_client()
        if not hasattr(client, "publish"):
            return False
        client.publish(REALTIME_CHANNEL, json.dumps(message, ensure_ascii=False))
        return True
    except Exception:
        return False


def normalize_openclaw_gateway_events(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    raw_events = data.get("events")
    if not isinstance(raw_events, list):
        return []
    normalized: list[dict[str, Any]] = []
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or event.get("type") or "gateway_event")
        tool_name = str(event.get("tool_name") or event.get("name") or "")
        message = str(event.get("message") or event.get("summary") or event_type)
        payload = {
            key: value
            for key, value in event.items()
            if key not in {"event_type", "type", "tool_name", "name", "message", "summary"}
        }
        normalized.append(
            {
                "event_type": event_type,
                "tool_name": tool_name,
                "message": message,
                "payload": protect_private_value(payload),
            }
        )
    return normalized


def execute_openclaw_task_packet(packet: dict[str, Any], guard: dict[str, Any]) -> dict[str, Any]:
    task_id = str(packet.get("task_id") or f"openclaw_{uuid.uuid4().hex}")
    step_id = str(packet.get("step_id") or "openclaw_task_packet")
    executor_trace = {
        "provider": "openclaw",
        "executor_trace_id": f"openclaw_exec_{uuid.uuid4().hex}",
        "adapter_mode": "live" if openclaw_enabled() else "dry_run",
        "permission": guard.get("permission", "read_only"),
    }
    registry = ExecutorAdapterRegistry(event_store=long_tail_event_store(), policy_gate=PolicyGate())
    proposed = registry.propose_action(
        task_id=task_id,
        step_id=step_id,
        adapter="openclaw",
        action_type="openclaw.run_task_packet",
        target={
            "kind": "openclaw_task_packet",
            "task_id": task_id,
            "goal_hash": hashlib.sha256(str(packet.get("goal") or "").encode("utf-8")).hexdigest(),
        },
        input_summary={
            "permission": guard.get("permission", "read_only"),
            "allowed_actions": list(packet.get("allowed_actions") or []),
            "forbidden_actions": list(packet.get("forbidden_actions") or []),
            "requires_stop_before": list(packet.get("requires_stop_before") or []),
            "minimal_context_keys": sorted((packet.get("minimal_context") or {}).keys()),
        },
        risk_level=str(guard.get("permission") or "read_only"),
        expected_effect="Run an OpenClaw step executor under Nomi stop-before-effect rules.",
        allowed_actions={"openclaw.run_task_packet"},
        executor_trace=executor_trace,
    )
    if not proposed["policy_report"].get("may_execute"):
        return {
            "mode": "policy",
            "status": "blocked",
            "needs_confirmation": True,
            "reason": proposed["policy_report"].get("reason", "OpenClaw execution blocked by policy."),
            "policy_report": proposed["policy_report"],
        }

    if not openclaw_enabled():
        dry_run_result = {
            "mode": "dry_run",
            "status": "blocked",
            "external_side_effect": False,
            "reason": "OPENCLAW_ENABLED is not true; live OpenClaw execution is disabled.",
        }
        long_tail_event_store().append_event(
            task_id=task_id,
            event_type="executor.dry_run_completed",
            step_id=step_id,
            payload={
                "action_request_id": proposed["action_request"]["action_id"],
                "policy_status": proposed["policy_report"]["status"],
                "dry_run_result": dry_run_result,
                "executor_trace": executor_trace,
            },
            idempotency_key=f"{proposed['action_request']['idempotency_key']}:dry_run_completed",
        )
        return {
            "mode": "dry_run",
            "status": "blocked",
            "needs_confirmation": True,
            "reason": "OPENCLAW_ENABLED is not true; live OpenClaw execution is disabled.",
            "packet": packet,
        }

    headers = {"Content-Type": "application/json"}
    token = os.getenv("OPENCLAW_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "model": os.getenv("OPENCLAW_MODEL", "openclaw-agent"),
        "input": openclaw_prompt_from_packet(packet, guard),
        "metadata": {
            "nomi_task_id": packet.get("task_id"),
            "nomi_permission": guard.get("permission", "read_only"),
            "nomi_requires_confirmation": guard.get("requires_confirmation", True),
        },
    }
    try:
        response = httpx.post(
            f"{openclaw_base_url()}/v1/responses",
            headers=headers,
            json=payload,
            timeout=float(os.getenv("OPENCLAW_TIMEOUT_SECONDS", "30")),
        )
        response.raise_for_status()
        data = response.json()
        summary = output_text_from_openclaw_response(data) or json.dumps(data, ensure_ascii=False)[:1000]
        provider_trace_id = data.get("id") if isinstance(data, dict) else None
        executor_trace["provider_trace_id"] = provider_trace_id
        result = {
            "mode": "live",
            "status": "completed_read_only",
            "needs_confirmation": bool(guard.get("requires_confirmation", True)),
            "summary": summary,
            "raw_response_id": provider_trace_id,
            "events": normalize_openclaw_gateway_events(data),
            "external_side_effect": False,
        }
        long_tail_event_store().append_event(
            task_id=task_id,
            event_type="executor.live_completed",
            step_id=step_id,
            payload={
                "action_request_id": proposed["action_request"]["action_id"],
                "policy_status": proposed["policy_report"]["status"],
                "live_result": {
                    "mode": result["mode"],
                    "status": result["status"],
                    "provider_trace_id": provider_trace_id,
                    "external_side_effect": False,
                },
                "executor_trace": executor_trace,
            },
            idempotency_key=f"{proposed['action_request']['idempotency_key']}:live_completed",
        )
        return result
    except Exception as exc:
        result = {
            "mode": "live",
            "status": "failed",
            "needs_confirmation": True,
            "summary": "",
            "error": str(exc)[:300],
            "external_side_effect": False,
        }
        long_tail_event_store().append_event(
            task_id=task_id,
            event_type="executor.live_completed",
            step_id=step_id,
            payload={
                "action_request_id": proposed["action_request"]["action_id"],
                "policy_status": proposed["policy_report"]["status"],
                "live_result": {
                    "mode": result["mode"],
                    "status": result["status"],
                    "error": result["error"],
                    "external_side_effect": False,
                },
                "executor_trace": executor_trace,
            },
            idempotency_key=f"{proposed['action_request']['idempotency_key']}:live_completed",
        )
        return result


def classify_openclaw_job_result(
    result: dict[str, Any],
    *,
    attempt_count: int,
    max_attempts: int,
) -> dict[str, Any]:
    status = str(result.get("status") or "failed")
    error_text = str(result.get("error") or result.get("reason") or "").lower()
    retryable_error = any(term in error_text for term in ["timeout", "temporarily", "rate limit", "connection", "503", "502", "504"])
    if status in {"completed", "completed_read_only", "draft_ready"}:
        return {"status": "completed", "retryable": False, "next_attempt_delay_seconds": None}
    if status in {"blocked", "needs_user_input"}:
        return {"status": status, "retryable": False, "next_attempt_delay_seconds": None}
    if retryable_error and attempt_count < max_attempts:
        delay = min(30 * (2 ** max(0, attempt_count - 1)), 300)
        return {"status": "retry_scheduled", "retryable": True, "next_attempt_delay_seconds": delay}
    return {"status": "failed", "retryable": False, "next_attempt_delay_seconds": None}


def record_openclaw_execution_event(
    conn: psycopg.Connection,
    *,
    job_id: str,
    event_type: str,
    message: str = "",
    payload: Optional[dict[str, Any]] = None,
    redis_obj: Any = None,
) -> str:
    event_id = str(uuid.uuid4())
    safe_payload = protect_private_value(payload or {})
    conn.execute(
        """
        INSERT INTO openclaw_execution_events (
          id, job_id, event_type, message, payload, created_at
        )
        VALUES (%s, %s, %s, %s, %s, now())
        """,
        (event_id, job_id, event_type, message, jsonb_param(safe_payload)),
    )
    publish_realtime_message_safely(
        {
            "type": "openclaw_job_event",
            "event_id": event_id,
            "job_id": job_id,
            "event_type": event_type,
            "message": message,
            "payload": safe_payload,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        redis_obj=redis_obj,
    )
    return event_id


def enqueue_openclaw_execution_job(
    conn: psycopg.Connection,
    *,
    packet: dict[str, Any],
    guard: dict[str, Any],
    trace_id: Optional[str] = None,
    max_attempts: int = 3,
    redis_obj: Any = None,
) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    task_id = str(packet.get("task_id") or job_id)
    conn.execute(
        """
        INSERT INTO openclaw_execution_jobs (
          id, task_id, trace_id, status, attempt_count, max_attempts,
          openclaw_task_packet, execution_guard, next_attempt_at, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, 0, %s, %s, %s, now(), now(), now())
        """,
        (job_id, task_id, trace_id, "queued", max_attempts, jsonb_param(packet), jsonb_param(guard)),
    )
    record_openclaw_execution_event(
        conn,
        job_id=job_id,
        event_type="queued",
        message="OpenClaw job queued for isolated execution.",
        payload={"task_id": task_id, "max_attempts": max_attempts},
        redis_obj=redis_obj,
    )
    return {
        "job_id": job_id,
        "task_id": task_id,
        "status": "queued",
        "attempt_count": 0,
        "max_attempts": max_attempts,
        "trace_id": trace_id,
    }


def timestamp_or_value(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def row_to_openclaw_execution_job(row: Any) -> dict[str, Any]:
    return {
        "job_id": str(row[0]),
        "task_id": row[1],
        "trace_id": str(row[2]) if row[2] else None,
        "status": row[3],
        "attempt_count": row[4],
        "max_attempts": row[5],
        "openclaw_task_packet": row[6] or {},
        "execution_guard": row[7] or {},
        "last_result": row[8],
        "last_error": row[9],
        "next_attempt_at": timestamp_or_value(row[10]),
        "created_at": timestamp_or_value(row[11]),
        "updated_at": timestamp_or_value(row[12]),
        "completed_at": timestamp_or_value(row[13]),
    }


def row_to_openclaw_execution_event(row: Any) -> dict[str, Any]:
    return {
        "event_id": str(row[0]),
        "job_id": str(row[1]),
        "event_type": row[2],
        "message": row[3],
        "payload": row[4] or {},
        "created_at": timestamp_or_value(row[5]),
    }


def fetch_openclaw_execution_job(conn: psycopg.Connection, job_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, task_id, trace_id, status, attempt_count, max_attempts,
               openclaw_task_packet, execution_guard, last_result, last_error,
               next_attempt_at, created_at, updated_at, completed_at
        FROM openclaw_execution_jobs
        WHERE id = %s
        """,
        (job_id,),
    ).fetchone()
    return row_to_openclaw_execution_job(row) if row else None


def fetch_openclaw_execution_events(conn: psycopg.Connection, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, job_id, event_type, message, payload, created_at
        FROM openclaw_execution_events
        WHERE job_id = %s
        ORDER BY created_at ASC
        """,
        (job_id,),
    ).fetchall()
    return [row_to_openclaw_execution_event(row) for row in rows]


def final_event_message(status: str) -> str:
    if status == "retry_scheduled":
        return "OpenClaw job scheduled for retry."
    if status == "completed":
        return "OpenClaw job completed."
    if status == "needs_user_input":
        return "OpenClaw job needs user input."
    if status == "blocked":
        return "OpenClaw job blocked before unsafe action."
    return "OpenClaw job failed."


def run_openclaw_execution_job_once(
    conn: psycopg.Connection,
    job_id: str,
    *,
    executor=execute_openclaw_task_packet,
    redis_obj: Any = None,
) -> dict[str, Any]:
    job = fetch_openclaw_execution_job(conn, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="openclaw job not found")
    if job["status"] not in {"queued", "retry_scheduled"}:
        return {"job_id": job_id, "status": job["status"], "attempt_count": job["attempt_count"], "skipped": True}

    attempt_count = int(job["attempt_count"] or 0) + 1
    conn.execute(
        """
        UPDATE openclaw_execution_jobs
        SET status = %s, attempt_count = %s, updated_at = now()
        WHERE id = %s
        """,
        ("running", attempt_count, job_id),
    )
    record_openclaw_execution_event(
        conn,
        job_id=job_id,
        event_type="attempt_started",
        message=f"OpenClaw attempt {attempt_count} started.",
        payload={"attempt_count": attempt_count, "max_attempts": job["max_attempts"]},
        redis_obj=redis_obj,
    )

    result = executor(job["openclaw_task_packet"], job["execution_guard"])
    for event in result.get("events") or []:
        if isinstance(event, dict):
            payload = dict(event.get("payload") or {})
            if event.get("tool_name"):
                payload["tool_name"] = event.get("tool_name")
            record_openclaw_execution_event(
                conn,
                job_id=job_id,
                event_type=str(event.get("event_type") or "gateway_event"),
                message=str(event.get("message") or ""),
                payload=protect_private_value(payload),
                redis_obj=redis_obj,
            )

    transition = classify_openclaw_job_result(
        result,
        attempt_count=attempt_count,
        max_attempts=int(job["max_attempts"] or 1),
    )
    next_attempt = None
    if transition["next_attempt_delay_seconds"]:
        next_attempt = datetime.now(timezone.utc) + timedelta(seconds=transition["next_attempt_delay_seconds"])
    completed_at = datetime.now(timezone.utc) if transition["status"] != "retry_scheduled" else None
    conn.execute(
        """
        UPDATE openclaw_execution_jobs
        SET status = %s, attempt_count = %s, last_result = %s, last_error = %s,
            next_attempt_at = COALESCE(%s, now()), completed_at = %s, updated_at = now()
        WHERE id = %s
        """,
        (
            transition["status"],
            attempt_count,
            jsonb_param(result),
            result.get("error") or result.get("reason"),
            next_attempt,
            completed_at,
            job_id,
        ),
    )
    record_openclaw_execution_event(
        conn,
        job_id=job_id,
        event_type=transition["status"],
        message=final_event_message(transition["status"]),
        payload=transition,
        redis_obj=redis_obj,
    )
    return {
        "job_id": job_id,
        "status": transition["status"],
        "attempt_count": attempt_count,
        "max_attempts": job["max_attempts"],
        "transition": transition,
        "result": result,
    }


def fetch_due_openclaw_execution_job_ids(conn: psycopg.Connection, *, limit: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT id
        FROM openclaw_execution_jobs
        WHERE status IN ('queued', 'retry_scheduled')
          AND next_attempt_at <= now()
        ORDER BY next_attempt_at ASC, created_at ASC
        LIMIT %s
        FOR UPDATE SKIP LOCKED
        """,
        (limit,),
    ).fetchall()
    return [str(row[0]) for row in rows]


def process_due_openclaw_execution_jobs_once(
    *,
    limit: int = OPENCLAW_JOB_RUNNER_BATCH_SIZE,
    executor=execute_openclaw_task_packet,
    redis_obj: Any = None,
) -> dict[str, Any]:
    with db() as conn:
        job_ids = fetch_due_openclaw_execution_job_ids(conn, limit=limit)
        results = [
            run_openclaw_execution_job_once(conn, job_id, executor=executor, redis_obj=redis_obj)
            for job_id in job_ids
        ]
    return {"processed": len(results), "job_ids": job_ids, "results": results}


async def openclaw_execution_job_runner_loop() -> None:
    while True:
        try:
            process_due_openclaw_execution_jobs_once(limit=OPENCLAW_JOB_RUNNER_BATCH_SIZE, redis_obj=redis_client())
        except Exception:
            pass
        await asyncio.sleep(OPENCLAW_JOB_RUNNER_INTERVAL_SECONDS)


def build_long_tail_recovery_scanner() -> PostgresLongTailRecoveryScanner:
    return PostgresLongTailRecoveryScanner(connection_factory=lambda: psycopg.connect(DATABASE_URL))


def build_long_tail_lease_manager() -> PostgresLongTailLeaseManager:
    return PostgresLongTailLeaseManager(connection_factory=lambda: psycopg.connect(DATABASE_URL))


def process_due_long_tail_recovery_once(
    *,
    scanner: Any = None,
    lease_manager: Any = None,
    worker_id: str = "",
    limit: int = LONG_TAIL_RECOVERY_BATCH_SIZE,
    lease_seconds: int = LONG_TAIL_RECOVERY_LEASE_SECONDS,
) -> dict[str, Any]:
    scanner = scanner or build_long_tail_recovery_scanner()
    lease_manager = lease_manager or build_long_tail_lease_manager()
    worker_id = worker_id or f"nomi-long-tail-recovery-{uuid.uuid4().hex[:8]}"
    task_ids = scanner.due_task_ids(limit=limit)
    results: list[dict[str, Any]] = []
    processed = 0
    skipped = 0
    failed = 0
    for task_id in task_ids:
        lease = lease_manager.claim_task(task_id, worker_id=worker_id, lease_seconds=lease_seconds)
        if not lease.get("acquired"):
            skipped += 1
            results.append({"task_id": task_id, "status": "skipped", "lease": lease})
            continue
        try:
            state = long_tail_runner().recover_task(task_id)
            processed += 1
            results.append({"task_id": task_id, "status": "recovered", "state": state, "lease": lease})
        except Exception as exc:
            failed += 1
            results.append({"task_id": task_id, "status": "failed", "error": type(exc).__name__, "lease": lease})
        finally:
            lease_manager.release_task(task_id, worker_id=worker_id)
    return {
        "processed": processed,
        "skipped": skipped,
        "failed": failed,
        "task_ids": task_ids,
        "results": results,
    }


async def long_tail_recovery_runner_loop() -> None:
    while True:
        try:
            process_due_long_tail_recovery_once()
        except Exception:
            pass
        await asyncio.sleep(LONG_TAIL_RECOVERY_INTERVAL_SECONDS)


def clarification_for_ambiguous_external_effect(request: str, capability: dict[str, Any]) -> dict[str, Any]:
    lowered = request.lower()
    context = capability.get("_context") if isinstance(capability.get("_context"), dict) else {}
    missing_fields: list[str] = []
    risk_permission = capability.get("risk_permission")
    has_specific_crm_action = any(term in lowered for term in ["hubspot", "salesforce", "加到", "备注", "更新", "创建", "记录"])
    vague_action = any(term in lowered for term in ["处理一下", "弄一下", "搞一下", "处理这个", "处理下"])

    if capability["id"] == "business.crm.contact.upsert" and vague_action and not has_specific_crm_action:
        missing_fields.extend(["target_contact", "target_action"])

    if capability["id"] == "finance.payment_bill.manage":
        has_amount = bool(
            AMOUNT_RE.search(request)
            or BILL_ID_RE.search(request)
            or context.get("amount_or_bill")
            or context.get("bill")
            or context.get("invoice_id")
        )
        has_counterparty = bool(context.get("counterparty") or context.get("payee")) or any(
            term in request for term in ["给", "向", "转给", "付给", "支付给", "收款方"]
        )
        if not has_amount:
            missing_fields.append("amount_or_bill")
        if not has_counterparty:
            missing_fields.append("counterparty")

    if risk_permission in {"payment_or_purchase", "external_message", "external_execution", "write"} and vague_action:
        if "target_action" not in missing_fields:
            missing_fields.append("target_action")

    return {
        "required": bool(missing_fields),
        "missing_fields": missing_fields,
        "question": "需要先确认具体对象、动作和外部影响范围。请补充要处理谁、做什么、是否会发送/付款/写入外部系统。",
    }


def match_capability(request: str) -> dict[str, Any]:
    lowered = request.lower()
    explicit_capability_id = explicit_capability_id_for_request(request)
    if explicit_capability_id:
        return next(item for item in capability_taxonomy() if item["id"] == explicit_capability_id)
    scored: list[tuple[int, dict[str, Any]]] = []
    for capability in capability_taxonomy():
        score = sum(1 for keyword in capability["keywords"] if str(keyword).lower() in lowered)
        if score:
            scored.append((score, capability))
    if scored:
        return sorted(scored, key=lambda item: item[0], reverse=True)[0][1]
    return next(item for item in capability_taxonomy() if item["id"] == "automation.browser.operate")


def explicit_capability_id_for_request(request: str) -> Optional[str]:
    lowered = request.lower()
    has_ride_intent = any(term in lowered for term in ["打车", "叫车", "uber", "book a ride", "ride"])
    has_route_intent = any(term in lowered for term in ["查路线", "路线", "怎么去", "导航", "多久到", "要多久", "地图", "route", "directions"])
    has_payment_intent = bool(BILL_ID_RE.search(request)) or any(
        term in lowered for term in ["invoice", "bill", "付款", "支付", "账单", "发票", "报销", "转账", "还款", "欠款"]
    )
    has_document_intent = any(
        term in lowered
        for term in [
            "报价单",
            "文档",
            "文件",
            "表格",
            "sheet",
            "docs",
            "drive",
            "pdf",
            "docx",
            "xlsx",
            "总结这个文档",
        ]
    )
    if has_payment_intent:
        return "finance.payment_bill.manage"
    if has_document_intent:
        return "files.document.process"
    if has_ride_intent:
        return "local_service.ride.estimate_or_book"
    if has_route_intent:
        return "local_service.route.lookup"
    return None


def pipeline_for_capability(capability_id: str) -> Optional[dict[str, Any]]:
    for pipeline in core_pipeline_registry():
        if pipeline["capability_id"] == capability_id:
            return pipeline
    return None


def pipeline_for_id(pipeline_id: str) -> Optional[dict[str, Any]]:
    for pipeline in core_pipeline_registry():
        if pipeline["id"] == pipeline_id:
            return pipeline
    return None


def connected_adapters_from_context(context: dict[str, Any]) -> dict[str, set[str]]:
    raw = context.get("connected_adapters") or {}
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, set[str]] = {}
    for adapter, toolkits in raw.items():
        adapter_id = str(adapter).strip()
        if not adapter_id:
            continue
        if isinstance(toolkits, str):
            normalized[adapter_id] = {toolkits}
        elif isinstance(toolkits, (list, tuple, set)):
            normalized[adapter_id] = {str(toolkit) for toolkit in toolkits if str(toolkit).strip()}
        elif isinstance(toolkits, dict):
            normalized[adapter_id] = {str(toolkit) for toolkit, connected in toolkits.items() if connected}
        else:
            normalized[adapter_id] = set()
    return normalized


def tools_for_capability(capability: dict[str, Any]) -> list[dict[str, Any]]:
    catalog = {tool["id"]: tool for tool in default_tool_catalog()}
    candidates = [catalog[tool_id] for tool_id in capability.get("tool_ids", []) if tool_id in catalog]
    if not candidates and "browser_automation" in catalog:
        candidates = [catalog["browser_automation"]]
    return candidates


def route_tool_request(request: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    context = enrich_context_from_source_events(context or {})
    tool_registry_decision = default_tool_registry(
        connected_adapters=connected_adapters_from_context(context),
    ).route_request(request, context)
    capability = match_capability(request)
    capability["_context"] = context
    pipeline = pipeline_for_capability(capability["id"])
    candidate_tools = tools_for_capability(capability)
    clarification = clarification_for_ambiguous_external_effect(request, capability)
    route_type = "ask_user" if clarification["required"] else ("core_pipeline" if pipeline else "openclaw_tool")
    if route_type == "ask_user":
        pipeline = None
    legacy_route_type = route_type if route_type == "core_pipeline" else "long_tail_tool"
    if route_type == "ask_user":
        legacy_route_type = "ask_user"
    permission = str((pipeline or {}).get("permission") or capability.get("risk_permission") or "read_only")
    guard = execution_guard_for_permission(permission)
    decision = build_task_route_decision(
        route_type=route_type,
        capability=capability,
        pipeline=pipeline,
        guard=guard,
    )
    response = {
        "task_trace_id": str(uuid.uuid4()),
        "request": request,
        "route_type": route_type,
        "legacy_route_type": legacy_route_type,
        "task_route_decision": decision,
        "capability": {key: capability[key] for key in ["id", "domain", "category", "action", "risk_permission"]},
        "pipeline": pipeline,
        "candidate_tools": candidate_tools,
        "execution_guard": guard,
        "tool_registry_decision": tool_registry_decision,
        "routing_reason": decision["reason"],
        "context": context,
    }
    if clarification["required"]:
        response["clarification"] = clarification
    if route_type == "openclaw_tool":
        response["openclaw_task_packet"] = build_openclaw_task_packet(
            request=request,
            capability=capability,
            context=context,
            guard=guard,
        )
    return response


def extract_after_marker(text: str, markers: list[str]) -> Optional[str]:
    for marker in markers:
        if marker in text:
            return text.split(marker, 1)[1].strip(" ：:，,。.!！?？")
    return None


def strip_travel_suffix(value: str) -> str:
    cleaned = value.strip(" ：:，,。.!！?？")
    cleaned = re.sub(r"(要多久|多久到|怎么去|路线|导航|打车|叫车|uber|eta).*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"(?:的|地)$", "", cleaned.strip())
    return cleaned.strip(" ：:，,。.!！?？")


def extract_destination_slot(request: str, context: dict[str, Any]) -> Optional[str]:
    explicit = context.get("destination") or context.get("place")
    if explicit:
        return str(explicit)
    match = re.search(r"(?:去|到|至|前往)([A-Za-z0-9\u4e00-\u9fff ._-]{2,80})", request)
    if match:
        destination = strip_travel_suffix(match.group(1))
        if destination:
            return destination
    return None


def recipient_from_active_scope(context: dict[str, Any]) -> Optional[str]:
    scope = context.get("active_source_scope") if isinstance(context.get("active_source_scope"), dict) else {}
    candidates = [
        scope.get("conversation_label"),
        scope.get("contact_name"),
        scope.get("counterparty_name"),
        scope.get("chat_name"),
    ]
    counterparty_ids = scope.get("counterparty_ids")
    if isinstance(counterparty_ids, list):
        candidates.extend(counterparty_ids)
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value and value.lower() not in {"unknown", "user", "me"}:
            return value
    return None


def extract_recipient_slot(request: str, context: dict[str, Any]) -> Optional[str]:
    explicit = context.get("recipient") or context.get("target_contact")
    if explicit:
        return str(explicit)
    match = re.search(r"(?:回复|回消息给?|给)\s*([A-Za-z][\w .'-]{1,60}|[\u4e00-\u9fff]{2,12})", request, flags=re.I)
    if match:
        recipient = re.split(r"[,，。.!！?？；;]|说|告诉|发", match.group(1).strip(), 1)[0]
        return recipient.strip()
    if any(token in request for token in ["她", "他", "对方", "ta", "TA", "那边"]):
        return recipient_from_active_scope(context)
    return recipient_from_active_scope(context)


def extract_message_intent_slot(request: str, context: dict[str, Any]) -> Optional[str]:
    explicit = context.get("message_intent") or context.get("draft_intent")
    if explicit:
        return str(explicit)
    intent = extract_after_marker(request, ["说", "告诉对方", "告诉他", "告诉她"])
    return intent or None


def extract_channel_slot(request: str, context: dict[str, Any]) -> Optional[str]:
    lowered = request.lower()
    if "gmail" in lowered or "邮件" in request or "email" in lowered:
        return "gmail"
    if "whatsapp" in lowered:
        return "whatsapp"
    scope = context.get("active_source_scope") if isinstance(context.get("active_source_scope"), dict) else {}
    source = scope.get("source") or context.get("source")
    if source in {"whatsapp", "gmail", "slack", "telegram"}:
        return str(source)
    return None


def extract_payment_slots(request: str, context: dict[str, Any]) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    amount = context.get("amount_or_bill") or context.get("amount") or context.get("bill") or context.get("invoice_id")
    if not amount:
        amount_match = AMOUNT_RE.search(request)
        if amount_match:
            amount = amount_match.group(0).strip()
    if not amount:
        bill_match = BILL_ID_RE.search(request)
        if bill_match:
            amount = bill_match.group(0).strip()
    if amount:
        slots["amount_or_bill"] = str(amount)
    counterparty = context.get("counterparty")
    if not counterparty:
        match = re.search(r"(?:给|向|转给|付给|支付给)([A-Za-z][\w .'-]{1,60}|[\u4e00-\u9fff]{2,12})", request)
        if match:
            counterparty = match.group(1).strip()
    if counterparty:
        slots["counterparty"] = str(counterparty)
    return slots


def parse_json_object_from_text(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    if "```" in text:
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end >= start:
        text = text[start : end + 1]
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


def pipeline_slot_model_enabled(context: Optional[dict[str, Any]] = None) -> bool:
    context = context or {}
    if context.get("use_model_slots") is True:
        return True
    return os.getenv("PIPELINE_SLOT_MODEL_ENABLED", "false").lower() in {"1", "true", "yes"}


def call_pipeline_slot_model(
    request: str,
    pipeline: dict[str, Any],
    context: dict[str, Any],
    rule_slots: dict[str, Any],
) -> dict[str, Any]:
    if not pipeline_slot_model_enabled(context):
        return {}
    prompt = {
        "request": request,
        "pipeline_id": pipeline.get("id"),
        "required_slots": pipeline.get("required_slots") or [],
        "rule_slots": rule_slots,
        "context": minimize_openclaw_context(context),
        "instruction": (
            "Return JSON only with keys: slots, confidence, reason. "
            "Only fill required slots. Do not invent unsupported details."
        ),
    }
    try:
        response = httpx.post(
            f"{MODEL_BASE_URL.rstrip('/')}/v1/chat/completions",
            json={
                "model": MODEL_NAME,
                "messages": [
                    {
                        "role": "system",
                        "content": "You extract conservative task slots for a private personal assistant pipeline.",
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False, sort_keys=True)},
                ],
                "temperature": 0,
                "stream": False,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        content = ""
        if isinstance(data, dict) and data.get("choices"):
            content = str(data["choices"][0].get("message", {}).get("content", ""))
        elif isinstance(data, dict):
            content = str(data.get("response") or data.get("text") or data.get("content") or "")
        parsed = parse_json_object_from_text(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        return {"slots": {}, "confidence": 0, "reason": "model_slot_extraction_failed", "error": str(exc)[:200]}


def rule_extract_pipeline_slots(
    request: str,
    pipeline: Optional[dict[str, Any]],
    context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    context = context or {}
    if not pipeline:
        return {}
    pipeline_id = pipeline.get("id")
    slots: dict[str, Any] = {}
    if pipeline_id == "reply_pipeline":
        recipient = extract_recipient_slot(request, context)
        channel = extract_channel_slot(request, context)
        message_intent = extract_message_intent_slot(request, context)
        if recipient:
            slots["recipient"] = recipient
        if channel:
            slots["channel"] = channel
        if message_intent:
            slots["message_intent"] = message_intent
    elif pipeline_id in {"route_pipeline", "ride_pipeline"}:
        destination = extract_destination_slot(request, context)
        pickup = context.get("pickup") or context.get("current_location")
        if destination:
            slots["destination"] = destination
        if pickup:
            slots["pickup"] = str(pickup)
    elif pipeline_id == "payment_bill_pipeline":
        slots.update(extract_payment_slots(request, context))
    else:
        for slot in pipeline.get("required_slots") or []:
            value = context.get(slot)
            if value is not None and value != "" and value != []:
                slots[slot] = value
    return slots


def validate_and_merge_pipeline_slots(
    *,
    required_slots: list[str],
    rule_slots: dict[str, Any],
    model_result: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    model_slots = model_result.get("slots") if isinstance(model_result.get("slots"), dict) else {}
    merged = dict(rule_slots)
    warnings: list[str] = []
    for slot, value in model_slots.items():
        if slot not in required_slots:
            warnings.append(f"unknown_model_slot:{slot}")
            continue
        if value is None or value == "" or value == []:
            continue
        if slot in merged and str(merged[slot]).strip() != str(value).strip():
            warnings.append(f"model_conflict:{slot}")
            continue
        if slot not in merged:
            merged[slot] = value
    trace = {
        "parser_mode": "hybrid_model_rules" if model_result else "rules_only",
        "model_used": bool(model_result),
        "rule_slots": rule_slots,
        "model_slots": model_slots,
        "model_confidence": model_result.get("confidence") if model_result else None,
        "model_reason": model_result.get("reason", "") if model_result else "",
        "validation_warnings": warnings,
    }
    if model_result.get("error"):
        trace["validation_warnings"].append("model_slot_extraction_failed")
        trace["model_error"] = model_result["error"]
    return merged, trace


def extract_pipeline_slots_with_trace(
    request: str,
    pipeline: Optional[dict[str, Any]],
    context: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = context or {}
    if not pipeline:
        return {}, {
            "parser_mode": "none",
            "model_used": False,
            "rule_slots": {},
            "model_slots": {},
            "validation_warnings": [],
        }
    required_slots = list(pipeline.get("required_slots") or [])
    rule_slots = rule_extract_pipeline_slots(request, pipeline, context)
    model_result = call_pipeline_slot_model(request, pipeline, context, rule_slots)
    return validate_and_merge_pipeline_slots(
        required_slots=required_slots,
        rule_slots=rule_slots,
        model_result=model_result,
    )


def extract_pipeline_slots(
    request: str,
    pipeline: Optional[dict[str, Any]],
    context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    slots, _trace = extract_pipeline_slots_with_trace(request, pipeline, context)
    return slots


def missing_pipeline_slots(required_slots: list[str], resolved_slots: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for slot in required_slots:
        value = resolved_slots.get(slot)
        if value is None or value == "" or value == []:
            missing.append(slot)
    return missing


def pipeline_status_for_result(
    *,
    route_result: dict[str, Any],
    pipeline: Optional[dict[str, Any]],
    missing_slots: list[str],
) -> str:
    if route_result.get("route_type") == "ask_user":
        return "needs_user_input"
    if missing_slots:
        return "needs_user_input"
    if not pipeline:
        return "blocked"
    permission = str(pipeline.get("permission") or "")
    if permission == "read_only":
        return "completed_read_only"
    if permission == "external_message":
        return "draft_ready"
    if route_result.get("execution_guard", {}).get("requires_confirmation"):
        return "confirmation_required"
    return "completed_read_only"


def build_pipeline_steps(pipeline: Optional[dict[str, Any]], status: str) -> list[dict[str, Any]]:
    if not pipeline:
        return []
    blocked = status in {"needs_user_input", "blocked", "failed"}
    return [
        {"name": step, "status": "pending" if blocked else "completed"}
        for step in pipeline.get("steps", [])
    ]


def explicit_trace_references(context: Optional[dict[str, Any]]) -> dict[str, Any]:
    context = context or {}
    source_event_ids = context.get("source_event_ids") or []
    if isinstance(source_event_ids, str):
        source_event_ids = [source_event_ids]
    agenda_item_ids = context.get("agenda_item_ids") or []
    agenda_item_id = context.get("agenda_item_id")
    if agenda_item_id:
        agenda_item_ids = [*agenda_item_ids, agenda_item_id] if isinstance(agenda_item_ids, list) else [agenda_item_ids, agenda_item_id]
    if isinstance(agenda_item_ids, str):
        agenda_item_ids = [agenda_item_ids]
    return {
        "source_event_ids": [str(item) for item in source_event_ids if item],
        "conversation_id": str(context.get("conversation_id") or "") or None,
        "suggestion_id": str(context.get("suggestion_id") or "") or None,
        "agenda_item_ids": list(dict.fromkeys(str(item) for item in agenda_item_ids if item)),
    }


def safe_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


PLACEHOLDER_VALUE_RE = re.compile(r"\b(?:EMAIL|PHONE|AMOUNT|TOKEN|CARD|SSN)_\d+\b", re.I)


def usable_source_context_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if PLACEHOLDER_VALUE_RE.search(text):
        return None
    if text.lower() in {"unknown", "user", "me", "assistant", "nomi"}:
        return None
    return text


def first_usable_source_value(*values: Any) -> Optional[str]:
    for value in values:
        if isinstance(value, list):
            nested = first_usable_source_value(*value)
            if nested:
                return nested
            continue
        text = usable_source_context_text(value)
        if text:
            return text
    return None


def enrich_context_from_source_events(context: Optional[dict[str, Any]]) -> dict[str, Any]:
    base_context = dict(context or {})
    if base_context.get("source_event_context"):
        return base_context
    source_event_ids = base_context.get("source_event_ids") or []
    if isinstance(source_event_ids, str):
        source_event_ids = [source_event_ids]
    source_event_ids = [str(item) for item in source_event_ids if item]
    if not source_event_ids:
        return base_context

    source_context: list[dict[str, Any]] = []
    try:
        with db() as conn:
            rows = conn.execute(
                """
                SELECT e.event_id::TEXT, e.source, e.event_type, e.raw_data,
                       s.intent, s.summary, s.entities
                FROM events e
                LEFT JOIN semantic_events s ON s.event_id = e.event_id
                WHERE e.event_id = ANY(%s::UUID[])
                ORDER BY e.timestamp DESC
                """,
                (source_event_ids,),
            ).fetchall()
    except Exception:
        return base_context

    for row in rows:
        raw_data = safe_json_dict(row[3])
        entities = safe_json_dict(row[6])
        source = str(row[1] or "")
        source_context.append(
            {
                "event_id": str(row[0]),
                "source": source,
                "event_type": row[2],
                "intent": row[4],
                "summary": row[5],
                "entities": entities,
                "sender": raw_data.get("sender") or raw_data.get("from"),
                "participants": raw_data.get("participants") or [],
                "subject": raw_data.get("subject"),
            }
        )
        if not base_context.get("counterparty") and not base_context.get("payee"):
            counterparty = first_usable_source_value(
                raw_data.get("payee"),
                raw_data.get("counterparty"),
                raw_data.get("sender"),
                raw_data.get("from"),
                raw_data.get("chat_name"),
                raw_data.get("participants"),
            )
            if counterparty:
                base_context["counterparty"] = counterparty
        if not any(base_context.get(key) for key in ["amount_or_bill", "amount", "bill", "invoice_id"]):
            amount_or_bill = first_usable_source_value(
                entities.get("invoice_id"),
                entities.get("bill_id"),
                entities.get("amount"),
                raw_data.get("invoice_id"),
                raw_data.get("amount"),
            )
            if amount_or_bill:
                base_context["amount_or_bill"] = amount_or_bill
        if source == "gmail" and not base_context.get("mailbox"):
            base_context["mailbox"] = "gmail"

    if source_context:
        base_context["source_event_context"] = source_context
    return base_context


def memory_scope_from_metadata(metadata: dict[str, Any], fallback_scope: str = "") -> str:
    scope = metadata.get("scope")
    if isinstance(scope, dict):
        return str(
            scope.get("conversation_id")
            or scope.get("contact_id")
            or scope.get("source")
            or scope.get("kind")
            or fallback_scope
        )
    if scope:
        return str(scope)
    return fallback_scope or "global"


def retrieve_personal_search_hits_from_db(query: str, context: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    cleaned_query = str(query or "").strip()
    if not cleaned_query:
        return []
    like_query = f"%{cleaned_query}%"
    hits: list[dict[str, Any]] = []
    try:
        with db() as conn:
            fact_rows = conn.execute(
                """
                SELECT id::text, subject, predicate, object, confidence, source_event_ids::TEXT[],
                       metadata, created_at
                FROM facts
                WHERE subject ILIKE %s OR predicate ILIKE %s OR object ILIKE %s
                   OR concat_ws(' ', subject, predicate, object) ILIKE %s
                ORDER BY confidence DESC, updated_at DESC
                LIMIT %s
                """,
                (like_query, like_query, like_query, like_query, limit),
            ).fetchall()
            for row in fact_rows:
                metadata = safe_json_dict(row[6])
                hits.append(
                    {
                        "id": str(row[0]),
                        "type": "fact",
                        "content": f"{row[1]} {row[2]}: {row[3]}",
                        "scope": memory_scope_from_metadata(metadata, str(context.get("current_scope") or "")),
                        "score": float(row[4] or 0),
                        "source_event_ids": [str(item) for item in (row[5] or [])],
                        "metadata": metadata,
                        "created_at": isoformat_or_value(row[7]),
                    }
                )

            remaining = max(0, limit - len(hits))
            if remaining:
                memory_rows = conn.execute(
                    """
                    SELECT id, source_event_id, scope, payload, updated_at
                    FROM memory_items
                    WHERE payload::text ILIKE %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                    """,
                    (like_query, remaining),
                ).fetchall()
                for row in memory_rows:
                    scope_payload = safe_json_dict(row[2])
                    payload = safe_json_dict(row[3])
                    content = str(
                        payload.get("content")
                        or payload.get("summary")
                        or payload.get("object")
                        or payload.get("text")
                        or payload
                    )
                    hits.append(
                        {
                            "id": str(row[0]),
                            "type": str(payload.get("kind") or "memory"),
                            "content": content,
                            "scope": memory_scope_from_metadata(scope_payload, str(context.get("current_scope") or "")),
                            "score": float(payload.get("confidence") or payload.get("score") or 0.5),
                            "source_event_ids": [str(row[1])] if row[1] else [],
                            "metadata": payload,
                            "created_at": isoformat_or_value(row[4]),
                        }
                    )
    except Exception:
        return []
    return hits


def retrieve_context_pack_evidence_from_db(query: str, context: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    evidence_items: list[dict[str, Any]] = []
    for hit in retrieve_personal_search_hits_from_db(query, context, limit=limit):
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        scoped_value = metadata.get("scope") if isinstance(metadata.get("scope"), dict) else hit.get("scope") or "global"
        evidence_items.append(
            {
                "id": hit.get("id"),
                "type": "event" if hit.get("type") == "event" else "memory",
                "scope": scoped_value,
                "score": hit.get("score", 0),
                "timestamp": hit.get("created_at"),
                "content": hit.get("content", ""),
                "source_event_ids": hit.get("source_event_ids") or [],
            }
        )
    return evidence_items


def context_turns_from_dialogue(dialogue: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for item in dialogue:
        turns.append(
            {
                "id": item.get("event_id") or item.get("turn_id") or item.get("id"),
                "conversation_id": item.get("conversation_id"),
                "role": item.get("role"),
                "text": item.get("content") or item.get("text") or "",
                "timestamp": item.get("created_at"),
            }
        )
    return turns


def build_pipeline_execution_result(
    *,
    request: str,
    context: dict[str, Any],
    route_result: dict[str, Any],
) -> dict[str, Any]:
    pipeline = route_result.get("pipeline")
    required_slots = list((pipeline or {}).get("required_slots") or [])
    resolved_slots, slot_trace = extract_pipeline_slots_with_trace(request, pipeline, context)
    missing_slots = missing_pipeline_slots(required_slots, resolved_slots)
    if route_result.get("route_type") == "ask_user":
        clarification = route_result.get("clarification") or {}
        for missing in clarification.get("missing_fields") or []:
            if missing not in missing_slots:
                missing_slots.append(missing)
    guard = route_result.get("execution_guard") or {}
    status = pipeline_status_for_result(route_result=route_result, pipeline=pipeline, missing_slots=missing_slots)
    trace_refs = explicit_trace_references(context)
    result = {
        "task_trace_id": route_result.get("task_trace_id"),
        "route_type": route_result.get("route_type"),
        "pipeline_id": (pipeline or {}).get("id"),
        "version": (pipeline or {}).get("version") or "2026-05-28",
        "pipeline_version": (pipeline or {}).get("version") or "2026-05-28",
        "capability_id": route_result.get("capability", {}).get("id"),
        "status": status,
        "source_event_ids": trace_refs["source_event_ids"],
        "conversation_id": trace_refs["conversation_id"],
        "suggestion_id": trace_refs["suggestion_id"],
        "agenda_item_ids": trace_refs["agenda_item_ids"],
        "input": {
            "user_request": request,
            "source_event_ids": trace_refs["source_event_ids"],
            "conversation_id": trace_refs["conversation_id"],
            "suggestion_id": trace_refs["suggestion_id"],
            "agenda_item_ids": trace_refs["agenda_item_ids"],
            "context": minimize_openclaw_context(context),
        },
        "required_slots": required_slots,
        "resolved_slots": resolved_slots,
        "missing_slots": missing_slots,
        "slot_extraction": slot_trace,
        "risk": {
            "permission": guard.get("permission"),
            "confirmation_required": bool(guard.get("requires_confirmation")),
            "final_user_confirmation": bool(guard.get("final_user_confirmation")),
        },
        "execution_guard": guard,
        "external_effects": list((pipeline or {}).get("external_effects") or []),
        "writeback_targets": list((pipeline or {}).get("writeback_targets") or []),
        "steps": build_pipeline_steps(pipeline, status),
        "routing_reason": route_result.get("routing_reason"),
        "clarification": route_result.get("clarification"),
    }
    if pipeline:
        module_context = {
            **context,
            **resolved_slots,
            "resolved_slots": resolved_slots,
            "missing_slots": missing_slots,
            "required_slots": required_slots,
        }
        if str(pipeline.get("id")) == "personal_search_pipeline" and not module_context.get("memory_hits"):
            query = str(module_context.get("query") or request)
            module_context["memory_hits"] = retrieve_personal_search_hits_from_db(query, module_context)
            module_context["retrieval_backend"] = "local_db"
        if str(pipeline.get("id")) == "context_pack_pipeline":
            query = str(module_context.get("query") or request)
            conversation_id = module_context.get("conversation_id")
            if not module_context.get("evidence_items"):
                module_context["evidence_items"] = retrieve_context_pack_evidence_from_db(query, module_context)
            if not module_context.get("active_agenda"):
                module_context["active_agenda"] = retrieve_active_agenda_context(
                    query,
                    conversation_id=str(conversation_id) if conversation_id else None,
                    limit=6,
                )
            if not module_context.get("recent_turns"):
                module_context["recent_turns"] = context_turns_from_dialogue(
                    retrieve_assistant_dialogue_context(
                        query,
                        conversation_id=str(conversation_id) if conversation_id else None,
                        limit=6,
                    )
                )
            module_context["retrieval_backend"] = "local_db"
        module_result = run_registered_pipeline(str(pipeline.get("id")), request, module_context)
        if module_result:
            for key in [
                "status",
                "required_slots",
                "resolved_slots",
                "missing_slots",
                "risk",
                "execution_guard",
                "external_effects",
                "writeback_targets",
                "steps",
            ]:
                if key in module_result:
                    result[key] = module_result[key]
            for key in ["output", "provider_calls", "writeback_plan", "validation_warnings"]:
                result[key] = module_result.get(key, [] if key.endswith("calls") or key.endswith("plan") or key.endswith("warnings") else {})
            for key in ["provider_call_plan", "confirmation_card", "blocked_effects", "safety_checks"]:
                if key in module_result:
                    result[key] = module_result[key]
    result.setdefault("output", {})
    result.setdefault("provider_calls", [])
    result.setdefault("writeback_plan", [])
    result.setdefault("validation_warnings", [])
    return result


def run_core_pipeline(request: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    context = enrich_context_from_source_events(context or {})
    pipeline_id = context.get("pipeline_id")
    if pipeline_id:
        pipeline = pipeline_for_id(str(pipeline_id))
        if not pipeline:
            route_result = route_tool_request(request, context)
        else:
            guard = execution_guard_for_permission(str(pipeline.get("permission") or "read_only"))
            capability = {
                "id": pipeline.get("capability_id", ""),
                "domain": str(pipeline.get("capability_id", "")).split(".", 1)[0],
                "category": "pipeline",
                "action": "direct",
                "risk_permission": pipeline.get("permission", "read_only"),
            }
            route_result = {
                "task_trace_id": str(uuid.uuid4()),
                "request": request,
                "route_type": "core_pipeline",
                "legacy_route_type": "core_pipeline",
                "task_route_decision": build_task_route_decision(
                    route_type="core_pipeline",
                    capability=capability,
                    pipeline=pipeline,
                    guard=guard,
                ),
                "capability": capability,
                "pipeline": pipeline,
                "candidate_tools": tools_for_capability(capability),
                "execution_guard": guard,
                "routing_reason": f"按指定 Pipeline 执行：{pipeline_id}。",
                "context": context,
            }
    else:
        route_result = route_tool_request(request, context)
    return build_pipeline_execution_result(request=request, context=context, route_result=route_result)


def persist_task_route_trace(conn: psycopg.Connection, route_result: dict[str, Any]) -> str:
    trace_id = route_result.get("task_trace_id") or str(uuid.uuid4())
    route_result["task_trace_id"] = trace_id
    decision = route_result.get("task_route_decision") or {}
    capability = route_result.get("capability") or {}
    pipeline = route_result.get("pipeline") or {}
    guard = route_result.get("execution_guard") or {}
    refs = explicit_trace_references(route_result.get("context") or {})
    conn.execute(
        """
        INSERT INTO task_route_traces (
          id, request, route_type, capability_id, pipeline_id, risk_permission,
          confirmation_required, task_route_decision, openclaw_task_packet,
          clarification, context_summary, source_event_ids, conversation_id,
          suggestion_id, agenda_item_ids, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::TEXT[], %s, %s, %s::TEXT[], now())
        """,
        (
            trace_id,
            route_result.get("request", ""),
            route_result.get("route_type", ""),
            capability.get("id", ""),
            pipeline.get("id"),
            guard.get("permission", decision.get("risk_permission", "")),
            bool(guard.get("requires_confirmation", decision.get("confirmation_required", False))),
            jsonb_param(decision),
            jsonb_param(route_result.get("openclaw_task_packet")),
            jsonb_param(route_result.get("clarification")),
            jsonb_param(minimize_openclaw_context(route_result.get("context") or {})),
            refs["source_event_ids"],
            refs["conversation_id"],
            refs["suggestion_id"],
            refs["agenda_item_ids"],
        ),
    )
    return trace_id


def row_to_task_route_trace(row: Any) -> dict[str, Any]:
    created_at = row[11]
    source_event_ids = row[12] if len(row) > 12 else []
    conversation_id = row[13] if len(row) > 13 else None
    suggestion_id = row[14] if len(row) > 14 else None
    agenda_item_ids = row[15] if len(row) > 15 else []
    return {
        "task_trace_id": str(row[0]),
        "request": row[1],
        "route_type": row[2],
        "capability_id": row[3],
        "pipeline_id": row[4],
        "risk_permission": row[5],
        "confirmation_required": bool(row[6]),
        "task_route_decision": row[7] or {},
        "openclaw_task_packet": row[8],
        "clarification": row[9],
        "context_summary": row[10] or {},
        "source_event_ids": [str(item) for item in (source_event_ids or [])],
        "conversation_id": str(conversation_id) if conversation_id else None,
        "suggestion_id": str(suggestion_id) if suggestion_id else None,
        "agenda_item_ids": [str(item) for item in (agenda_item_ids or [])],
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
    }


def persist_pipeline_execution_result(conn: psycopg.Connection, result: dict[str, Any]) -> str:
    execution_id = result.get("pipeline_execution_id") or str(uuid.uuid4())
    result["pipeline_execution_id"] = execution_id
    input_payload = result.get("input") or {}
    conn.execute(
        """
        INSERT INTO pipeline_execution_results (
          id, task_trace_id, request, route_type, capability_id, pipeline_id, status,
          required_slots, resolved_slots, missing_slots, risk, execution_guard,
          source_event_ids, conversation_id, suggestion_id, agenda_item_ids, result, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::TEXT[], %s::jsonb, %s::TEXT[],
                %s::jsonb, %s::jsonb, %s::TEXT[], %s, %s, %s::TEXT[], %s::jsonb, now())
        """,
        (
            execution_id,
            result.get("task_trace_id"),
            input_payload.get("user_request", ""),
            result.get("route_type", ""),
            result.get("capability_id"),
            result.get("pipeline_id"),
            result.get("status", ""),
            [str(item) for item in result.get("required_slots") or []],
            json.dumps(result.get("resolved_slots") or {}, ensure_ascii=False, default=str),
            [str(item) for item in result.get("missing_slots") or []],
            json.dumps(result.get("risk") or {}, ensure_ascii=False, default=str),
            json.dumps(result.get("execution_guard") or {}, ensure_ascii=False, default=str),
            [str(item) for item in input_payload.get("source_event_ids") or []],
            input_payload.get("conversation_id"),
            input_payload.get("suggestion_id"),
            [str(item) for item in input_payload.get("agenda_item_ids") or []],
            json.dumps(result, ensure_ascii=False, default=str),
        ),
    )
    return execution_id


def apply_pipeline_writeback_plan(conn: psycopg.Connection, result: dict[str, Any]) -> dict[str, Any]:
    plans = [plan for plan in result.get("writeback_plan") or [] if isinstance(plan, dict)]
    summary = {
        "attempted": len(plans),
        "applied": False,
        "applied_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "errors": [],
    }
    for plan in plans:
        target = str(plan.get("target") or "")
        if target.startswith("external_") or target in {"external_calendar", "external_task_tool"}:
            summary["skipped_count"] += 1
            record_pipeline_writeback_event(conn, result, plan, status="skipped_external")
            continue
        try:
            apply_pipeline_writeback_target(conn, result, plan)
            record_pipeline_writeback_event(conn, result, plan, status="applied")
            summary["applied_count"] += 1
        except Exception as exc:
            summary["failed_count"] += 1
            error = str(exc)[:300]
            summary["errors"].append({"target": target, "error": error})
            try:
                record_pipeline_writeback_event(conn, result, plan, status="failed", error=error)
            except Exception:
                pass
    record_pipeline_health_metric(conn, result, summary)
    summary["applied"] = int(summary["applied_count"]) > 0 and int(summary["failed_count"]) == 0
    summary["failed"] = int(summary["failed_count"])
    summary["skipped"] = int(summary["skipped_count"])
    return summary


def record_pipeline_writeback_event(
    conn: psycopg.Connection,
    result: dict[str, Any],
    plan: dict[str, Any],
    *,
    status: str,
    error: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_writeback_events (
          id, pipeline_execution_id, task_trace_id, pipeline_id, target,
          operation, status, payload, error, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now())
        """,
        (
            str(uuid.uuid4()),
            result.get("pipeline_execution_id"),
            result.get("task_trace_id"),
            result.get("pipeline_id"),
            str(plan.get("target") or ""),
            str(plan.get("operation") or plan.get("action") or ""),
            status,
            json.dumps(plan, ensure_ascii=False, default=str),
            error,
        ),
    )


def record_pipeline_health_metric(conn: psycopg.Connection, result: dict[str, Any], summary: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_health_metrics (
          id, pipeline_id, status, applied_count, failed_count, skipped_count,
          payload, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, now())
        """,
        (
            str(uuid.uuid4()),
            result.get("pipeline_id"),
            result.get("status", ""),
            int(summary.get("applied_count") or 0),
            int(summary.get("failed_count") or summary.get("failed") or 0),
            int(summary.get("skipped_count") or summary.get("skipped") or 0),
            json.dumps(summary, ensure_ascii=False, default=str),
        ),
    )


def stable_uuid_from_value(value: Any) -> uuid.UUID:
    if value:
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return uuid.uuid5(uuid.NAMESPACE_URL, f"nomi:{value}")
    return uuid.uuid4()


def stable_uuid_text(value: Any) -> str:
    return str(stable_uuid_from_value(value))


def uuid_list_from_values(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    return [stable_uuid_text(value) for value in values if value]


def apply_pipeline_writeback_target(conn: psycopg.Connection, result: dict[str, Any], plan: dict[str, Any]) -> None:
    target = str(plan.get("target") or "")
    payload = plan.get("payload") if isinstance(plan.get("payload"), dict) else {}
    item = plan.get("item") if isinstance(plan.get("item"), dict) else {}
    data = payload or item or plan
    if target == "events":
        event_id = data.get("event_id") or data.get("id") or result.get("task_trace_id") or uuid.uuid4()
        event_timestamp = data.get("timestamp") or None
        raw_data = {
            **data,
            "source_event_id": str(event_id),
            "source_scope": data.get("source_scope") or data.get("scope") or {},
        }
        conn.execute(
            """
            INSERT INTO events (event_id, timestamp, source, event_type, raw_data, raw_data_private, created_at)
            VALUES (%s, COALESCE(%s::timestamptz, now()), %s, %s, %s::jsonb, %s::jsonb, now())
            ON CONFLICT (event_id) DO UPDATE SET
              timestamp = EXCLUDED.timestamp,
              source = EXCLUDED.source,
              event_type = EXCLUDED.event_type,
              raw_data = EXCLUDED.raw_data
            """,
            (
                stable_uuid_text(event_id),
                event_timestamp,
                str(data.get("source") or "pipeline"),
                str(data.get("event_type") or "pipeline_event"),
                json.dumps(raw_data, ensure_ascii=False, default=str),
                json.dumps({"source_event_id": str(event_id)}, ensure_ascii=False, default=str),
            ),
        )
    elif target == "duplicate_skip":
        conn.execute(
            """
            INSERT INTO duplicate_skip (id, event_id, dedupe_key, duplicate_of, source, event_type, payload, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, now())
            """,
            (
                str(uuid.uuid4()),
                data.get("event_id"),
                data.get("dedupe_key"),
                data.get("duplicate_of"),
                data.get("source"),
                data.get("event_type"),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "event_quarantine":
        conn.execute(
            """
            INSERT INTO event_quarantine (
              id, event_id, dedupe_key, source, event_type, event_timestamp,
              schema_errors, raw_event, summary, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::TEXT[], %s::jsonb, %s, now())
            """,
            (
                str(uuid.uuid4()),
                data.get("event_id"),
                data.get("dedupe_key"),
                data.get("source"),
                data.get("event_type"),
                data.get("timestamp"),
                [str(item) for item in data.get("schema_errors") or []],
                json.dumps(data.get("raw_event") or {}, ensure_ascii=False, default=str),
                str(data.get("summary") or ""),
            ),
        )
    elif target == "collector_health":
        conn.execute(
            """
            INSERT INTO collector_health (collector, status, details, updated_at)
            VALUES (%s, %s, %s::jsonb, now())
            ON CONFLICT (collector) DO UPDATE SET
              status = EXCLUDED.status,
              details = EXCLUDED.details,
              updated_at = now()
            """,
            (
                str(data.get("source") or data.get("collector") or result.get("pipeline_id") or "unknown"),
                str(data.get("status") or plan.get("operation") or "updated"),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "memory_items":
        conn.execute(
            """
            INSERT INTO memory_items (id, source_event_id, scope, payload, updated_at)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, now())
            ON CONFLICT (id) DO UPDATE SET
              source_event_id = EXCLUDED.source_event_id,
              scope = EXCLUDED.scope,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            (
                str(data.get("id") or data.get("memory_id") or uuid.uuid4()),
                data.get("source_event_id"),
                json.dumps(data.get("scope") or {}, ensure_ascii=False, default=str),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "facts":
        if data.get("subject") and data.get("predicate") and data.get("object"):
            conn.execute(
                """
                INSERT INTO facts (
                  id, subject, predicate, object, confidence, source_event_ids, metadata, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::UUID[], %s::jsonb, now(), now())
                ON CONFLICT (subject, predicate, object) DO UPDATE SET
                  confidence = GREATEST(facts.confidence, EXCLUDED.confidence),
                  source_event_ids = EXCLUDED.source_event_ids,
                  metadata = facts.metadata || EXCLUDED.metadata,
                  updated_at = now()
                """,
                (
                    stable_uuid_text(data.get("id")),
                    str(data.get("subject")),
                    str(data.get("predicate")),
                    str(data.get("object")),
                    float(data.get("confidence") or 0.5),
                    uuid_list_from_values(data.get("source_event_ids") or [data.get("source_event_id")]),
                    json.dumps(data.get("metadata") or {"scope": data.get("scope") or {}}, ensure_ascii=False, default=str),
                ),
            )
        conn.execute(
            """
            INSERT INTO memory_items (id, source_event_id, scope, payload, updated_at)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, now())
            ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
            """,
            (
                str(data.get("id") or uuid.uuid4()),
                data.get("source_event_id"),
                json.dumps(data.get("scope") or {}, ensure_ascii=False, default=str),
                json.dumps({"kind": "fact", **data}, ensure_ascii=False, default=str),
            ),
        )
    elif target == "knowledge_entities":
        rows = data if isinstance(data, list) else plan.get("payload") if isinstance(plan.get("payload"), list) else [data]
        for row in rows:
            if not isinstance(row, dict):
                row = {"name": str(row)}
            conn.execute(
                """
                INSERT INTO knowledge_entities (id, name, scope, payload, updated_at)
                VALUES (%s, %s, %s::jsonb, %s::jsonb, now())
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, scope = EXCLUDED.scope, payload = EXCLUDED.payload, updated_at = now()
                """,
                (
                    str(row.get("id") or row.get("name") or uuid.uuid4()),
                    str(row.get("name") or row.get("id") or ""),
                    json.dumps(row.get("scope") or {}, ensure_ascii=False, default=str),
                    json.dumps(row, ensure_ascii=False, default=str),
                ),
            )
    elif target == "knowledge_edges":
        rows = data if isinstance(data, list) else plan.get("payload") if isinstance(plan.get("payload"), list) else [data]
        for row in rows:
            if not isinstance(row, dict):
                row = {"fact": str(row)}
            conn.execute(
                """
                INSERT INTO knowledge_edges (id, source_id, target_id, relation_type, scope, payload, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, now())
                """,
                (
                    str(uuid.uuid4()),
                    str(row.get("source") or row.get("from") or row.get("contact_or_actor") or ""),
                    str(row.get("target") or row.get("to") or ""),
                    str(row.get("relation_type") or row.get("type") or "scoped_fact"),
                    json.dumps(row.get("scope") or {}, ensure_ascii=False, default=str),
                    json.dumps(row, ensure_ascii=False, default=str),
                ),
            )
    elif target == "memory_vectors":
        if str(data.get("status") or "") == "queued_for_retry":
            conn.execute(
                """
                INSERT INTO memory_vector_retries (id, source_event_id, chunk_id, reason, payload, created_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, now())
                """,
                (
                    str(uuid.uuid4()),
                    data.get("source_event_id"),
                    data.get("chunk_id"),
                    str(data.get("retry_reason") or "embedding_unavailable"),
                    json.dumps(data, ensure_ascii=False, default=str),
                ),
            )
    elif target == "memory_audit_log":
        conn.execute(
            """
            INSERT INTO memory_audit_log (id, action, target_type, target_id, reason, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
            """,
            (
                str(uuid.uuid4()),
                str(plan.get("operation") or "append"),
                str(data.get("target_type") or result.get("pipeline_id") or "pipeline"),
                str(data.get("target_id") or data.get("memory_id") or data.get("event_id") or result.get("task_trace_id") or ""),
                str(data.get("reason") or data.get("status") or ""),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "context_snapshots":
        conn.execute(
            """
            INSERT INTO context_snapshot_plans (id, request_or_event_id, current_scope, payload, created_at)
            VALUES (%s, %s, %s, %s::jsonb, now())
            """,
            (
                str(uuid.uuid4()),
                str(data.get("request_or_event_id") or data.get("conversation_id") or ""),
                json.dumps(data.get("current_scope") or {}, ensure_ascii=False, default=str),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "agenda_items":
        agenda_id = stable_uuid_text(data.get("agenda_item_id") or data.get("id") or f"{result.get('pipeline_id')}:{data.get('title')}")
        metadata = {
            **(data.get("metadata") if isinstance(data.get("metadata"), dict) else {}),
            "pipeline_execution_id": result.get("pipeline_execution_id"),
            "task_trace_id": result.get("task_trace_id"),
            "literal_source_event_ids": [str(item) for item in data.get("source_event_ids") or []],
        }
        conn.execute(
            """
            INSERT INTO agenda_items (
              id, type, title, status, certainty, time_window, place, participants,
              missing_fields, needs_clarification, confidence, source_event_ids,
              metadata, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s, %s, %s::UUID[], %s::jsonb, now(), now())
            ON CONFLICT (id) DO UPDATE SET
              title = EXCLUDED.title,
              status = EXCLUDED.status,
              certainty = EXCLUDED.certainty,
              time_window = EXCLUDED.time_window,
              place = EXCLUDED.place,
              participants = EXCLUDED.participants,
              missing_fields = EXCLUDED.missing_fields,
              needs_clarification = EXCLUDED.needs_clarification,
              confidence = EXCLUDED.confidence,
              metadata = agenda_items.metadata || EXCLUDED.metadata,
              updated_at = now()
            """,
            (
                agenda_id,
                str(data.get("type") or "appointment"),
                str(data.get("title") or data.get("task_title") or "Untitled agenda item"),
                str(data.get("status") or data.get("operation") or "scheduled"),
                str(data.get("certainty") or ("fuzzy" if data.get("missing_fields") else "exact")),
                json.dumps(data.get("time_window") or data.get("due_window") or {}, ensure_ascii=False, default=str),
                data.get("place"),
                json.dumps(data.get("participants") or [], ensure_ascii=False, default=str),
                json.dumps(data.get("missing_fields") or [], ensure_ascii=False, default=str),
                bool(data.get("needs_clarification") or data.get("missing_fields")),
                float(data.get("confidence") or 0.7),
                uuid_list_from_values(data.get("source_event_ids")),
                json.dumps(metadata, ensure_ascii=False, default=str),
            ),
        )
        conn.execute(
            """
            INSERT INTO agenda_item_versions (
              id, agenda_item_id, operation, previous_value, new_value, reason,
              source_event_ids, confidence, created_at
            )
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::UUID[], %s, now())
            """,
            (
                str(uuid.uuid4()),
                agenda_id,
                str(data.get("operation") or plan.get("operation") or "upsert"),
                json.dumps({}, ensure_ascii=False),
                json.dumps(data, ensure_ascii=False, default=str),
                str(data.get("reason") or "pipeline_writeback"),
                uuid_list_from_values(data.get("source_event_ids")),
                float(data.get("confidence") or 0.7),
            ),
        )
    elif target == "internal_todos" and "task_title" in data:
        conn.execute(
            """
            INSERT INTO internal_todos (id, task_title, owner, status, due_window, source_event_ids, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::TEXT[], %s::jsonb, now())
            ON CONFLICT (id) DO UPDATE SET
              task_title = EXCLUDED.task_title,
              owner = EXCLUDED.owner,
              status = EXCLUDED.status,
              due_window = EXCLUDED.due_window,
              payload = EXCLUDED.payload,
              updated_at = now()
            """,
            (
                str(data.get("todo_item_id") or uuid.uuid4()),
                str(data.get("task_title") or ""),
                str(data.get("owner") or "unknown"),
                str(data.get("status") or "open"),
                json.dumps(data.get("due_window") or {}, ensure_ascii=False, default=str),
                [str(item) for item in data.get("source_event_ids") or []],
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "internal_reminders":
        conn.execute(
            """
            INSERT INTO internal_reminders (id, status, due_window, source_event_ids, payload, updated_at)
            VALUES (%s, %s, %s::jsonb, %s::TEXT[], %s::jsonb, now())
            """,
            (
                str(uuid.uuid4()),
                str(data.get("status") or "planned_internal"),
                json.dumps(data.get("due_window") or {}, ensure_ascii=False, default=str),
                [str(item) for item in data.get("source_event_ids") or []],
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "proactive_candidates":
        conn.execute(
            """
            INSERT INTO proactive_candidates (
              id, candidate_type, agenda_item_id, event_ids, scores, decision,
              cooldown_key, metadata, created_at
            )
            VALUES (%s, %s, %s, %s::UUID[], %s::jsonb, %s, %s, %s::jsonb, now())
            """,
            (
                stable_uuid_text(data.get("id") or f"{result.get('task_trace_id')}:{data.get('candidate_type') or data.get('title')}"),
                str(data.get("candidate_type") or data.get("type") or "pipeline_candidate"),
                stable_uuid_text(data.get("agenda_item_id")) if data.get("agenda_item_id") else None,
                uuid_list_from_values(data.get("event_ids") or data.get("source_event_ids")),
                json.dumps(data.get("scores") or data.get("score_breakdown") or {}, ensure_ascii=False, default=str),
                str(data.get("decision") or "planned"),
                data.get("cooldown_key") or data.get("dedupe_key"),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "proactive_suggestions":
        conn.execute(
            """
            INSERT INTO proactive_suggestions (id, title, body, priority, status, metadata, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, now(), now())
            """,
            (
                str(uuid.uuid4()),
                str(data.get("title") or ""),
                str(data.get("body") or ""),
                float(data.get("priority") or 0),
                str(data.get("status") or "open"),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "user_feedback":
        conn.execute(
            """
            INSERT INTO user_feedback (id, suggestion_id, action, rating, reason, metadata, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
            """,
            (
                str(uuid.uuid4()),
                stable_uuid_text(data.get("suggestion_id")) if data.get("suggestion_id") else None,
                str(data.get("action") or plan.get("operation") or "feedback"),
                data.get("rating"),
                str(data.get("reason") or ""),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "search_audit":
        conn.execute(
            """
            INSERT INTO search_audit (id, pipeline_id, query, scope, result_count, payload, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
            """,
            (
                str(uuid.uuid4()),
                str(data.get("pipeline_id") or result.get("pipeline_id") or ""),
                str(data.get("query") or ""),
                str(data.get("scope") or ""),
                int(data.get("result_count") or 0),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "provider_call_traces":
        conn.execute(
            """
            INSERT INTO provider_call_traces (id, task_id, provider, action, call_status, payload, created_at)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
            """,
            (
                str(uuid.uuid4()),
                str(plan.get("task_id") or data.get("task_id") or ""),
                str(data.get("provider") or ""),
                str(data.get("action") or ""),
                str(data.get("call_status") or data.get("status") or ""),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "confirmation_ledger":
        conn.execute(
            """
            INSERT INTO confirmation_ledger (id, task_id, kind, confirm_action, final_user_confirmation, status, payload, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, now())
            """,
            (
                str(uuid.uuid4()),
                str(plan.get("task_id") or data.get("task_id") or ""),
                str(data.get("kind") or ""),
                str(data.get("confirm_action") or ""),
                bool(data.get("final_user_confirmation")),
                "required",
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "assistant_turns":
        conn.execute(
            """
            INSERT INTO pipeline_writeback_events (
              id, pipeline_execution_id, task_trace_id, pipeline_id, target, operation, status, payload, error, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, now())
            """,
            (
                str(uuid.uuid4()),
                result.get("pipeline_execution_id"),
                result.get("task_trace_id"),
                result.get("pipeline_id"),
                target,
                str(plan.get("operation") or plan.get("action") or "show"),
                "ui_plan_recorded",
                json.dumps(plan, ensure_ascii=False, default=str),
                "",
            ),
        )
    elif target == "task_trace":
        return
    elif target == "account_connections":
        conn.execute(
            """
            INSERT INTO account_connections (provider, status, metadata, updated_at)
            VALUES (%s, %s, %s::jsonb, now())
            ON CONFLICT (provider) DO UPDATE SET status = EXCLUDED.status, metadata = EXCLUDED.metadata, updated_at = now()
            """,
            (
                str(data.get("account_provider") or data.get("provider") or ""),
                str(data.get("status") or "not_connected"),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "collector_settings":
        conn.execute(
            """
            INSERT INTO collector_settings (source, enabled, paused_until, reason, metadata, updated_at)
            VALUES (%s, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (source) DO UPDATE SET
              enabled = EXCLUDED.enabled,
              paused_until = EXCLUDED.paused_until,
              reason = EXCLUDED.reason,
              metadata = collector_settings.metadata || EXCLUDED.metadata,
              updated_at = now()
            """,
            (
                str(data.get("source") or data.get("account_provider") or data.get("provider") or ""),
                bool(data.get("enabled", True)),
                data.get("paused_until"),
                str(data.get("reason") or plan.get("operation") or ""),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )
    elif target == "route_cache":
        conn.execute(
            """
            INSERT INTO route_cache (id, origin, destination, mode, payload, updated_at)
            VALUES (%s, %s, %s, %s, %s::jsonb, now())
            """,
            (
                str(uuid.uuid4()),
                str(data.get("origin") or ""),
                str(data.get("destination") or ""),
                str(data.get("mode") or ""),
                json.dumps(data, ensure_ascii=False, default=str),
            ),
        )


def should_attempt_pipeline_execution_persistence() -> bool:
    if os.getenv("PIPELINE_EXECUTION_PERSISTENCE", "true").lower() not in {"1", "true", "yes"}:
        return False
    if DATABASE_URL == "postgresql://test" and os.getenv("PIPELINE_EXECUTION_TEST_PERSIST") != "1":
        return False
    return True


def persist_pipeline_execution_result_safely(result: dict[str, Any]) -> dict[str, Any]:
    if not should_attempt_pipeline_execution_persistence():
        result["execution_persisted"] = False
        result["execution_persistence_reason"] = "disabled_or_test_database"
        result["writeback_applied"] = False
        result["writeback_summary"] = {
            "attempted": 0,
            "applied": False,
            "applied_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "failed": 0,
            "skipped": 0,
        }
        return result
    try:
        with db() as conn:
            persist_pipeline_execution_result(conn, result)
            result["writeback_summary"] = apply_pipeline_writeback_plan(conn, result)
        result["execution_persisted"] = True
        result["writeback_applied"] = bool(result["writeback_summary"].get("applied"))
    except Exception as exc:
        result["execution_persisted"] = False
        result["execution_persistence_reason"] = str(exc)[:300]
        result["writeback_applied"] = False
        result.setdefault(
            "writeback_summary",
            {
                "attempted": 0,
                "applied": False,
                "applied_count": 0,
                "failed_count": 1,
                "skipped_count": 0,
                "failed": 1,
                "skipped": 0,
            },
        )
    return result


def row_to_pipeline_execution_result(row: Any) -> dict[str, Any]:
    return {
        "pipeline_execution_id": str(row[0]),
        "task_trace_id": str(row[1]) if row[1] else None,
        "request": row[2],
        "route_type": row[3],
        "capability_id": row[4],
        "pipeline_id": row[5],
        "status": row[6],
        "required_slots": [str(item) for item in (row[7] or [])],
        "resolved_slots": row[8] or {},
        "missing_slots": [str(item) for item in (row[9] or [])],
        "risk": row[10] or {},
        "execution_guard": row[11] or {},
        "source_event_ids": [str(item) for item in (row[12] or [])],
        "conversation_id": str(row[13]) if row[13] else None,
        "suggestion_id": str(row[14]) if row[14] else None,
        "agenda_item_ids": [str(item) for item in (row[15] or [])],
        "result": row[16] or {},
        "created_at": isoformat_or_value(row[17]),
    }


def isoformat_or_value(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def agenda_item_from_row(row: Any) -> dict[str, Any]:
    source_event_ids = [str(item) for item in (row[11] or [])]
    metadata = row[12] or {}
    item = {
        "id": str(row[0]),
        "type": row[1],
        "title": row[2],
        "status": row[3],
        "certainty": row[4],
        "time_window": row[5] or {},
        "place": row[6] or "",
        "participants": row[7] or [],
        "missing_fields": row[8] or [],
        "needs_clarification": bool(row[9]),
        "confidence": row[10],
        "source_event_ids": source_event_ids,
        "metadata": metadata,
        "scope": metadata.get("scope") or metadata.get("source_scope") or "global",
        "created_at": isoformat_or_value(row[13]),
        "updated_at": isoformat_or_value(row[14]),
        "latest_version": None,
    }
    if len(row) > 15 and row[15]:
        item["latest_version"] = {
            "operation": row[15],
            "reason": row[16] or "",
            "created_at": isoformat_or_value(row[17]) if len(row) > 17 else None,
        }
    return item


def agenda_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title", ""),
        "status": item.get("status", ""),
        "certainty": item.get("certainty", ""),
        "time_window": item.get("time_window") or {},
        "place": item.get("place") or "",
        "participants": item.get("participants") or [],
        "missing_fields": item.get("missing_fields") or [],
        "needs_clarification": bool(item.get("needs_clarification")),
        "confidence": item.get("confidence") or 0,
        "metadata": item.get("metadata") or {},
        "source_event_ids": item.get("source_event_ids") or [],
    }


def fetch_agenda_item(conn: psycopg.Connection, agenda_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, type, title, status, certainty, time_window, place, participants,
               missing_fields, needs_clarification, confidence, source_event_ids,
               metadata, created_at, updated_at,
               latest.operation, latest.reason, latest.created_at
        FROM agenda_items
        LEFT JOIN LATERAL (
          SELECT operation, reason, created_at
          FROM agenda_item_versions
          WHERE agenda_item_id = agenda_items.id
          ORDER BY created_at DESC
          LIMIT 1
        ) latest ON TRUE
        WHERE id = %s
        """,
        (agenda_id,),
    ).fetchone()
    return agenda_item_from_row(row) if row else None


def fetch_agenda_items(
    conn: psycopg.Connection,
    *,
    status: Optional[str] = None,
    certainty: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    if status:
        conditions.append("status = %s")
        params.append(status)
    if certainty:
        conditions.append("certainty = %s")
        params.append(certainty)
    if source:
        conditions.append("metadata->>'source' = %s")
        params.append(source)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"""
        SELECT a.id, a.type, a.title, a.status, a.certainty, a.time_window, a.place, a.participants,
               a.missing_fields, a.needs_clarification, a.confidence, a.source_event_ids,
               a.metadata, a.created_at, a.updated_at,
               latest.operation, latest.reason, latest.created_at
        FROM agenda_items a
        LEFT JOIN LATERAL (
          SELECT operation, reason, created_at
          FROM agenda_item_versions
          WHERE agenda_item_id = a.id
          ORDER BY created_at DESC
          LIMIT 1
        ) latest ON TRUE
        {where_clause}
        ORDER BY a.updated_at DESC
        LIMIT %s
        """,
        (*params, limit),
    ).fetchall()
    return [agenda_item_from_row(row) for row in rows]


def pydantic_payload(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_none=True)
    return model.dict(exclude_none=True)


def write_agenda_version(
    conn: psycopg.Connection,
    *,
    agenda_id: str,
    operation: str,
    previous_value: dict[str, Any],
    new_value: dict[str, Any],
    reason: str,
    source_event_ids: list[str],
    confidence: float,
) -> dict[str, Any]:
    version_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO agenda_item_versions
          (id, agenda_item_id, operation, previous_value, new_value, reason, source_event_ids, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s::UUID[], %s)
        """,
        (
            version_id,
            agenda_id,
            operation,
            json.dumps(previous_value, ensure_ascii=False, default=str),
            json.dumps(new_value, ensure_ascii=False, default=str),
            reason,
            source_event_ids,
            confidence,
        ),
    )
    return {
        "id": version_id,
        "agenda_item_id": agenda_id,
        "operation": operation,
        "previous_value": previous_value,
        "new_value": new_value,
        "reason": reason,
        "source_event_ids": source_event_ids,
        "confidence": confidence,
    }


def update_agenda_item_with_version(
    conn: psycopg.Connection,
    agenda_id: str,
    patch: AgendaPatchIn,
) -> dict[str, Any]:
    existing = fetch_agenda_item(conn, agenda_id)
    if not existing:
        raise HTTPException(status_code=404, detail="agenda item not found")

    payload = pydantic_payload(patch)
    reason = str(payload.pop("reason", "") or "user correction")
    previous_value = agenda_snapshot(existing)
    new_value = {**previous_value, **payload}
    if "missing_fields" in payload and "needs_clarification" not in payload:
        new_value["needs_clarification"] = bool(payload["missing_fields"])

    assignments: list[str] = []
    params: list[Any] = []
    for field_name in [
        "title",
        "status",
        "certainty",
        "time_window",
        "place",
        "participants",
        "missing_fields",
        "needs_clarification",
        "confidence",
        "metadata",
    ]:
        if field_name not in new_value or new_value[field_name] == previous_value.get(field_name):
            continue
        assignments.append(f"{field_name} = %s")
        value = new_value[field_name]
        if field_name in {"time_window", "participants", "missing_fields", "metadata"}:
            params.append(json.dumps(value, ensure_ascii=False, default=str))
        else:
            params.append(value)

    if assignments:
        conn.execute(
            f"""
            UPDATE agenda_items
            SET {', '.join(assignments)}, updated_at = now()
            WHERE id = %s
            """,
            (*params, agenda_id),
        )

    version = write_agenda_version(
        conn,
        agenda_id=agenda_id,
        operation="user_correction",
        previous_value=previous_value,
        new_value=new_value,
        reason=reason,
        source_event_ids=previous_value["source_event_ids"],
        confidence=float(new_value.get("confidence") or previous_value.get("confidence") or 0),
    )
    return {"agenda_id": agenda_id, "version": version}


def snooze_agenda_item_with_version(
    conn: psycopg.Connection,
    agenda_id: str,
    body: AgendaSnoozeIn,
) -> dict[str, Any]:
    existing = fetch_agenda_item(conn, agenda_id)
    if not existing:
        raise HTTPException(status_code=404, detail="agenda item not found")
    previous_value = agenda_snapshot(existing)
    metadata = {**(previous_value.get("metadata") or {})}
    metadata["snoozed_until"] = body.snoozed_until
    metadata["snooze_reason"] = body.reason
    new_value = {**previous_value, "metadata": metadata}
    conn.execute(
        """
        UPDATE agenda_items
        SET metadata = %s, updated_at = now()
        WHERE id = %s
        """,
        (json.dumps(metadata, ensure_ascii=False, default=str), agenda_id),
    )
    version = write_agenda_version(
        conn,
        agenda_id=agenda_id,
        operation="snooze",
        previous_value=previous_value,
        new_value=new_value,
        reason=body.reason or "snooze agenda reminder",
        source_event_ids=previous_value["source_event_ids"],
        confidence=float(previous_value.get("confidence") or 0),
    )
    return {"agenda_id": agenda_id, "version": version}


def row_to_suggestion_item(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "source_event_id": str(row[1]) if row[1] else None,
        "title": row[2],
        "body": row[3],
        "priority": row[4],
        "status": row[5],
        "metadata": row[6] or {},
        "created_at": isoformat_or_value(row[7]),
        "updated_at": isoformat_or_value(row[8]),
    }


def fetch_suggestion_for_action(conn: psycopg.Connection, suggestion_id: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        """
        SELECT id, source_event_id, title, body, priority, status, metadata, created_at, updated_at
        FROM proactive_suggestions
        WHERE id = %s
        """,
        (suggestion_id,),
    ).fetchone()
    return row_to_suggestion_item(row) if row else None


def record_user_feedback(
    conn: psycopg.Connection,
    *,
    suggestion_id: str,
    action: str,
    reason: str,
    rating: Optional[float],
    metadata: dict[str, Any],
) -> str:
    feedback_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO user_feedback (id, suggestion_id, action, rating, reason, metadata, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, now())
        """,
        (
            feedback_id,
            suggestion_id,
            action,
            rating,
            reason,
            json.dumps(metadata, ensure_ascii=False, default=str),
        ),
    )
    return feedback_id


def build_suggestion_action_route_request(suggestion: dict[str, Any], action_id: str) -> Optional[str]:
    title = str(suggestion.get("title") or "").strip()
    body = str(suggestion.get("body") or "").strip()
    text = " ".join(part for part in [title, body] if part)
    if action_id == "route_lookup":
        return f"查路线 导航 地图 多久到：{text}"
    if action_id == "ride_prepare":
        return f"帮我打车 uber 叫车 eta：{text}"
    if action_id in {"reply_draft", "email_draft"}:
        return f"起草回复：{text}"
    return None


def apply_suggestion_local_action(
    conn: psycopg.Connection,
    suggestion_id: str,
    body: SuggestionActionIn,
) -> dict[str, Any]:
    metadata_patch = dict(body.metadata)
    if body.snoozed_until:
        metadata_patch["snoozed_until"] = body.snoozed_until
    status = "dismissed" if body.action_id in {"dismiss", "dismissed"} else "open"
    if body.action_id == "done":
        status = "done"
    conn.execute(
        """
        UPDATE proactive_suggestions
        SET status = %s,
            metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
            updated_at = now()
        WHERE id = %s
        """,
        (status, json.dumps(metadata_patch, ensure_ascii=False, default=str), suggestion_id),
    )
    return {"local_action": body.action_id, "status": status, "metadata": metadata_patch}


def row_to_event_trace(row: Any) -> dict[str, Any]:
    return {
        "event_id": str(row[0]),
        "source": row[1],
        "event_type": row[2],
        "raw_data": row[3] or {},
        "timestamp": isoformat_or_value(row[4]),
    }


def row_to_semantic_event(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "intent": row[1],
        "entities": row[2] or {},
        "importance": row[3],
        "summary": row[4],
        "model_version": row[5],
    }


def row_to_memory_vector(row: Any) -> dict[str, Any]:
    return {"id": str(row[0]), "content": row[1], "metadata": row[2] or {}}


def row_to_fact_trace(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "subject": row[1],
        "predicate": row[2],
        "object": row[3],
        "confidence": row[4],
        "source_event_ids": [str(item) for item in (row[5] or [])],
        "metadata": row[6] or {},
    }


def row_to_agenda_version(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "agenda_item_id": str(row[1]),
        "operation": row[2],
        "previous_value": row[3] or {},
        "new_value": row[4] or {},
        "reason": row[5] or "",
        "source_event_ids": [str(item) for item in (row[6] or [])],
        "confidence": row[7],
        "created_at": isoformat_or_value(row[8]),
    }


def row_to_conversation(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "client_type": row[1],
        "started_at": isoformat_or_value(row[2]),
        "last_active_at": isoformat_or_value(row[3]),
        "active_task_id": row[4],
        "scope": row[5] or {},
        "status": row[6],
    }


def row_to_assistant_turn(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "conversation_id": str(row[1]),
        "role": row[2],
        "content": row[3],
        "event_id": str(row[4]) if row[4] else None,
        "suggestion_id": str(row[5]) if row[5] else None,
        "tool_call_id": row[6],
        "created_at": isoformat_or_value(row[7]),
        "finalized_at": isoformat_or_value(row[8]),
    }


def row_to_context_snapshot(row: Any) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "event_id": str(row[1]) if row[1] else None,
        "context_type": row[2],
        "included_event_ids": [str(item) for item in (row[3] or [])],
        "included_memory_ids": [str(item) for item in (row[4] or [])],
        "included_agenda_ids": [str(item) for item in (row[5] or [])],
        "reason": row[6] or "",
        "payload": row[7] or {},
        "created_at": isoformat_or_value(row[8]),
    }


def fetch_task_route_traces(
    conn: psycopg.Connection,
    *,
    route_type: Optional[str] = None,
    capability: Optional[str] = None,
    q: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    if route_type:
        conditions.append("route_type = %s")
        params.append(route_type)
    if capability:
        conditions.append("capability_id = %s")
        params.append(capability)
    if q:
        conditions.append("request ILIKE %s")
        params.append(f"%{q}%")
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT id, request, route_type, capability_id, pipeline_id, risk_permission,
               confirmation_required, task_route_decision, openclaw_task_packet,
               clarification, context_summary, created_at,
               source_event_ids, conversation_id, suggestion_id, agenda_item_ids
        FROM task_route_traces
        {where_clause}
        ORDER BY created_at DESC
        LIMIT %s
        """,
        tuple(params),
    ).fetchall()
    return [row_to_task_route_trace(row) for row in rows]


def should_attempt_task_route_trace_persistence() -> bool:
    if os.getenv("TASK_ROUTE_TRACE_PERSISTENCE", "true").lower() not in {"1", "true", "yes"}:
        return False
    if DATABASE_URL == "postgresql://test" and os.getenv("TASK_ROUTE_TRACE_TEST_PERSIST") != "1":
        return False
    return True


def persist_task_route_trace_safely(route_result: dict[str, Any]) -> dict[str, Any]:
    if not should_attempt_task_route_trace_persistence():
        route_result["trace_persisted"] = False
        route_result["trace_persistence_reason"] = "disabled_or_test_database"
        return route_result
    try:
        with db() as conn:
            persist_task_route_trace(conn, route_result)
        route_result["trace_persisted"] = True
    except Exception as exc:
        route_result["trace_persisted"] = False
        route_result["trace_persistence_reason"] = str(exc)[:300]
    return route_result


def current_composio_api_key() -> str:
    return os.getenv("COMPOSIO_API_KEY", COMPOSIO_API_KEY).strip()


def current_composio_base_url() -> str:
    return os.getenv("COMPOSIO_API_BASE_URL", COMPOSIO_API_BASE_URL).strip().rstrip("/")


def current_composio_user_id() -> str:
    return os.getenv("COMPOSIO_USER_ID", COMPOSIO_USER_ID).strip() or "nomi_owner"


def current_composio_callback_url() -> str:
    return os.getenv("COMPOSIO_CALLBACK_URL", COMPOSIO_CALLBACK_URL).strip()


def env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return list(default)
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def composio_readonly_toolkits() -> list[str]:
    return env_list("COMPOSIO_READONLY_TOOLKITS", DEFAULT_COMPOSIO_READONLY_TOOLKITS)


def composio_write_toolkits() -> list[str]:
    return env_list("COMPOSIO_WRITE_TOOLKITS", DEFAULT_COMPOSIO_WRITE_TOOLKITS)


def create_composio_sdk_client(api_key: str) -> Any:
    try:
        from composio import Composio
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "composio_sdk_missing",
                "message": "Composio SDK is not installed in the runtime environment.",
            },
        ) from exc
    return Composio(api_key=api_key)


def composio_session_policy(session_kind: str) -> dict[str, Any]:
    kind = session_kind.lower().strip()
    if kind == "readonly":
        toolkits = composio_readonly_toolkits()
        tags = {"enable": ["readOnlyHint"], "disable": ["destructiveHint"]}
    elif kind == "write":
        toolkits = composio_write_toolkits()
        tags = {"disable": ["destructiveHint"]}
    else:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_composio_session_kind",
                "message": "session_kind must be readonly or write.",
            },
        )
    return {
        "session_kind": kind,
        "toolkits": {"enable": toolkits},
        "tags": tags,
        "manage_connections": False,
    }


def choose_composio_session_kind(toolkit_slug: str, requested_kind: str = "") -> str:
    if requested_kind:
        policy = composio_session_policy(requested_kind)
        if toolkit_slug not in set(policy["toolkits"]["enable"]):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "toolkit_not_enabled_for_session",
                    "message": f"{toolkit_slug} is not enabled for {policy['session_kind']} Composio sessions.",
                    "enabled_toolkits": policy["toolkits"]["enable"],
                },
            )
        return policy["session_kind"]
    if toolkit_slug in set(composio_readonly_toolkits()):
        return "readonly"
    if toolkit_slug in set(composio_write_toolkits()):
        return "write"
    raise HTTPException(
        status_code=400,
        detail={
            "code": "unsupported_composio_toolkit",
            "message": f"{toolkit_slug} is not in Nomi's Composio toolkit allowlist.",
            "readonly_toolkits": composio_readonly_toolkits(),
            "write_toolkits": composio_write_toolkits(),
        },
    )


def object_value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def composio_mcp_payload(session: Any) -> dict[str, Any]:
    mcp = object_value(session, "mcp") or {}
    headers = object_value(mcp, "headers", {}) or {}
    return {
        "mcp_url": object_value(mcp, "url", "") or "",
        "mcp_headers": headers if isinstance(headers, dict) else {},
    }


def composio_session_id(session: Any) -> str:
    return str(object_value(session, "session_id") or object_value(session, "sessionId") or "")


def public_composio_session_payload(session: Any, policy: dict[str, Any]) -> dict[str, Any]:
    mcp_payload = composio_mcp_payload(session)
    return {
        "session_id": composio_session_id(session),
        "session_kind": policy["session_kind"],
        "mcp_url": mcp_payload["mcp_url"],
        "mcp_headers_present": bool(mcp_payload["mcp_headers"]),
        "enabled_toolkits": policy["toolkits"]["enable"],
        "tags": policy["tags"],
        "manage_connections": policy["manage_connections"],
    }


def fetch_composio_session_row(conn: psycopg.Connection, user_id: str, session_kind: str) -> Optional[dict[str, Any]]:
    row = conn.execute(
        """
        SELECT session_id, mcp_url, mcp_headers
        FROM composio_sessions
        WHERE user_id = %s AND session_kind = %s AND status = 'active'
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (user_id, session_kind),
    ).fetchone()
    if not row:
        return None
    return {"session_id": row[0], "mcp_url": row[1], "mcp_headers": row[2] or {}}


def store_composio_session(
    conn: psycopg.Connection,
    *,
    user_id: str,
    policy: dict[str, Any],
    session: Any,
) -> None:
    mcp_payload = composio_mcp_payload(session)
    conn.execute(
        """
        INSERT INTO composio_sessions (
          id, user_id, session_kind, session_id, mcp_url, mcp_headers,
          enabled_toolkits, tags, status, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::TEXT[], %s::jsonb, 'active', now())
        ON CONFLICT (session_id) DO UPDATE
        SET mcp_url = EXCLUDED.mcp_url,
            mcp_headers = EXCLUDED.mcp_headers,
            enabled_toolkits = EXCLUDED.enabled_toolkits,
            tags = EXCLUDED.tags,
            status = 'active',
            updated_at = now()
        """,
        (
            uuid.uuid4(),
            user_id,
            policy["session_kind"],
            composio_session_id(session),
            mcp_payload["mcp_url"],
            json.dumps(mcp_payload["mcp_headers"], ensure_ascii=False, default=str),
            policy["toolkits"]["enable"],
            json.dumps(policy["tags"], ensure_ascii=False, default=str),
        ),
    )


def get_or_create_composio_session(user_id: str, session_kind: str) -> tuple[Any, dict[str, Any]]:
    api_key = current_composio_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "composio_api_key_missing",
                "message": "COMPOSIO_API_KEY is not configured.",
            },
        )
    policy = composio_session_policy(session_kind)
    client = create_composio_sdk_client(api_key)
    with db() as conn:
        existing = fetch_composio_session_row(conn, user_id, policy["session_kind"])
        if existing and hasattr(client, "use"):
            session = client.use(existing["session_id"])
        else:
            session = client.create(
                user_id=user_id,
                toolkits=policy["toolkits"],
                tags=policy["tags"],
                manage_connections=policy["manage_connections"],
            )
        store_composio_session(conn, user_id=user_id, policy=policy, session=session)
    return session, policy


def composio_callback_for_toolkit(toolkit_slug: str, session_kind: str) -> Optional[str]:
    callback_url = current_composio_callback_url()
    if not callback_url:
        return None
    separator = "&" if "?" in callback_url else "?"
    return f"{callback_url}{separator}toolkit={toolkit_slug}&session_kind={session_kind}"


def composio_session_connected_toolkit(session: Any, toolkit_slug: str) -> Optional[dict[str, str]]:
    try:
        result = session.toolkits()
    except Exception:
        return None
    items = getattr(result, "items", None)
    if items is None and isinstance(result, dict):
        items = result.get("items", [])
    for item in items or []:
        toolkit = normalize_composio_toolkit(item)
        if toolkit["slug"].lower() == toolkit_slug.lower() and toolkit["connected"]:
            return toolkit
    return None


def composio_live_registry() -> ExecutorAdapterRegistry:
    return ExecutorAdapterRegistry(event_store=long_tail_event_store(), policy_gate=PolicyGate())


def composio_link_request_fields(connection_request: Any) -> dict[str, Any]:
    return {
        "redirect_url": str(object_value(connection_request, "redirect_url") or object_value(connection_request, "redirectUrl") or ""),
        "connection_request_id": str(object_value(connection_request, "id") or object_value(connection_request, "link_token") or object_value(connection_request, "linkToken") or ""),
        "connected_account_id": str(object_value(connection_request, "connected_account_id") or object_value(connection_request, "connectedAccountId") or ""),
        "expires_at": object_value(connection_request, "expires_at") or object_value(connection_request, "expiresAt"),
    }


def create_composio_connect_link(toolkit_slug: str, requested_kind: str = "", force: bool = False) -> dict[str, Any]:
    slug = toolkit_slug.lower().strip()
    session_kind = choose_composio_session_kind(slug, requested_kind)
    user_id = current_composio_user_id()
    session, policy = get_or_create_composio_session(user_id, session_kind)
    connected_toolkit = None if force else composio_session_connected_toolkit(session, slug)
    if connected_toolkit:
        session_payload = public_composio_session_payload(session, policy)
        return {
            "status": "already_connected",
            "toolkit_slug": slug,
            "session_kind": session_kind,
            "user_id": user_id,
            "redirect_url": "",
            "connection_request_id": "",
            "connected_account_id": connected_toolkit.get("connected_account_id", ""),
            "expires_at": None,
            "session": session_payload,
        }
    callback_url = composio_callback_for_toolkit(slug, session_kind)
    authorized: dict[str, Any] = {}

    def authorize_toolkit(action_request: dict[str, Any]) -> dict[str, Any]:
        if callback_url:
            connection_request = session.authorize(slug, callback_url=callback_url)
        else:
            connection_request = session.authorize(slug)
        fields = composio_link_request_fields(connection_request)
        authorized["fields"] = fields
        return {
            "status": "link_created",
            "toolkit": slug,
            "session_kind": session_kind,
            "connection_request_id": fields["connection_request_id"],
            "connected_account_id_present": bool(fields["connected_account_id"]),
            "redirect_url_present": bool(fields["redirect_url"]),
            "callback_url_configured": bool(callback_url),
            "external_side_effect": False,
        }

    live = composio_live_registry().execute_live(
        task_id=f"composio:{session_kind}:{slug}:connect",
        step_id="create_connect_link",
        adapter="composio",
        action_type="composio.authorize_toolkit",
        target={"kind": "toolkit", "toolkit_slug": slug, "session_kind": session_kind},
        input_summary={
            "user_id": user_id,
            "callback_url_configured": bool(callback_url),
            "force": bool(force),
            "mcp_headers_redacted": True,
        },
        risk_level="external_draft",
        expected_effect="Create a Composio connect link only; do not read, write, send, buy, or submit through the connected account.",
        allowed_actions={"composio.authorize_toolkit"},
        executor=authorize_toolkit,
        executor_trace={"provider": "composio", "toolkit": slug, "session_kind": session_kind},
    )
    live_result = dict(live.get("live_result") or {})
    if live.get("status") == "blocked_by_policy" or live_result.get("status") == "blocked_by_policy":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "composio_connect_blocked_by_policy",
                "message": live_result.get("reason") or "Composio connect link creation was blocked before external execution.",
            },
        )
    if live_result.get("status") == "failed":
        raise HTTPException(
            status_code=502,
            detail={
                "code": "composio_connect_failed",
                "message": live_result.get("summary") or "Composio connect link creation failed.",
            },
        )
    fields = dict(authorized.get("fields") or {})
    redirect_url = str(fields.get("redirect_url") or "")
    connection_request_id = str(fields.get("connection_request_id") or "")
    connected_account_id = str(fields.get("connected_account_id") or "")
    expires_at = fields.get("expires_at")
    session_payload = public_composio_session_payload(session, policy)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO composio_connect_requests (
              id, user_id, toolkit_slug, session_kind, session_id, connection_request_id,
              redirect_url, connected_account_id, status, expires_at, metadata, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'link_created', %s, %s::jsonb, now())
            """,
            (
                uuid.uuid4(),
                user_id,
                slug,
                session_kind,
                session_payload["session_id"],
                connection_request_id,
                redirect_url,
                connected_account_id,
                expires_at,
                json.dumps({"callback_url_configured": bool(callback_url)}, ensure_ascii=False),
            ),
        )
        conn.execute(
            """
            INSERT INTO account_connections (provider, status, metadata, updated_at)
            VALUES (%s, 'auth_link_created', %s::jsonb, now())
            ON CONFLICT (provider) DO UPDATE
            SET status = EXCLUDED.status,
                metadata = EXCLUDED.metadata,
                updated_at = now()
            """,
            (
                slug,
                json.dumps(
                    {
                        "source": "composio",
                        "session_kind": session_kind,
                        "session_id": session_payload["session_id"],
                        "connection_request_id": connection_request_id,
                        "connected_account_id": connected_account_id,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
    return {
        "status": "link_created",
        "toolkit_slug": slug,
        "session_kind": session_kind,
        "user_id": user_id,
        "redirect_url": redirect_url,
        "connection_request_id": connection_request_id,
        "connected_account_id": connected_account_id,
        "expires_at": expires_at,
        "session": session_payload,
    }


def clean_composio_callback_value(value: str, fallback: str = "") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "", (value or "").strip())
    return (cleaned or fallback)[:80]


def composio_android_callback_html(toolkit: str, session_kind: str, status: str) -> str:
    safe_toolkit = clean_composio_callback_value(toolkit, "unknown")
    safe_session_kind = clean_composio_callback_value(session_kind, "readonly")
    safe_status = clean_composio_callback_value(status, "success")
    query = urlencode(
        {
            "toolkit": safe_toolkit,
            "session_kind": safe_session_kind,
            "status": safe_status,
        }
    )
    deep_link = f"nomi://composio/connected?{query}"
    intent_link = f"intent://composio/connected?{query}#Intent;scheme=nomi;package=com.par.assistant.android;end"
    escaped_deep_link = html.escape(deep_link, quote=True)
    escaped_intent_link = html.escape(intent_link, quote=True)
    escaped_toolkit = html.escape(safe_toolkit, quote=True)
    escaped_status = html.escape(safe_status, quote=True)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Nomi 授权完成</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #f8fafc;
      color: #0f172a;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      width: min(88vw, 460px);
      padding: 28px;
      border: 1px solid #cbd5e1;
      border-radius: 18px;
      background: white;
      box-shadow: 0 18px 50px rgba(15, 23, 42, 0.12);
    }}
    h1 {{ margin: 0 0 10px; font-size: 24px; }}
    p {{ margin: 0 0 18px; line-height: 1.55; color: #475569; }}
    a {{
      display: block;
      padding: 14px 16px;
      border-radius: 14px;
      text-align: center;
      text-decoration: none;
      color: white;
      background: #0f766e;
      font-weight: 700;
    }}
    small {{ display: block; margin-top: 14px; color: #64748b; line-height: 1.5; }}
  </style>
</head>
<body>
  <main>
    <h1>授权已返回 Nomi</h1>
    <p>{escaped_toolkit} 授权状态：{escaped_status}。如果没有自动回到授权列表，请点击下面的按钮。</p>
    <a href="{escaped_intent_link}">返回 Nomi 授权列表</a>
    <small>这个页面只负责唤起本机 Nomi，不展示或保存任何账号令牌。</small>
  </main>
  <script>
    setTimeout(function () {{
      window.location.replace("{escaped_intent_link}");
    }}, 250);
  </script>
  <noscript><a href="{escaped_deep_link}">打开 Nomi</a></noscript>
</body>
</html>"""


def connection_account_id(connection: Any) -> str:
    connected_account = object_value(connection, "connected_account") or object_value(connection, "connectedAccount")
    return str(object_value(connected_account, "id") or object_value(connection, "connected_account_id") or object_value(connection, "connectedAccountId") or "")


def toolkit_connection_active(connection: Any) -> bool:
    if not connection:
        return False
    return bool(object_value(connection, "is_active") or object_value(connection, "isActive") or connection_account_id(connection))


def normalize_composio_toolkit(toolkit: Any) -> dict[str, Any]:
    connection = object_value(toolkit, "connection")
    return {
        "slug": str(object_value(toolkit, "slug") or ""),
        "name": str(object_value(toolkit, "name") or object_value(toolkit, "slug") or ""),
        "logo": str(object_value(toolkit, "logo") or ""),
        "connected": toolkit_connection_active(connection),
        "connected_account_id": connection_account_id(connection),
    }


def sync_composio_toolkits(session_kind: str = "readonly") -> dict[str, Any]:
    user_id = current_composio_user_id()
    session, policy = get_or_create_composio_session(user_id, session_kind)
    session_payload = public_composio_session_payload(session, policy)
    synced: dict[str, Any] = {}

    def list_toolkits(action_request: dict[str, Any]) -> dict[str, Any]:
        result = session.toolkits()
        items = getattr(result, "items", None)
        if items is None and isinstance(result, dict):
            items = result.get("items", [])
        toolkits = [normalize_composio_toolkit(item) for item in (items or [])]
        synced["toolkits"] = toolkits
        return {
            "status": "toolkits_synced",
            "session_kind": policy["session_kind"],
            "toolkit_count": len(toolkits),
            "connected_count": sum(1 for toolkit in toolkits if toolkit.get("connected")),
            "external_side_effect": False,
        }

    live = composio_live_registry().execute_live(
        task_id=f"composio:{policy['session_kind']}:toolkits:sync",
        step_id="sync_toolkits",
        adapter="composio",
        action_type="composio.list_toolkits",
        target={"kind": "toolkit_catalog", "session_kind": policy["session_kind"]},
        input_summary={
            "user_id": user_id,
            "session_id": session_payload["session_id"],
            "mcp_headers_redacted": True,
        },
        risk_level="read_only",
        expected_effect="Read Composio toolkit connection status for the current Nomi owner.",
        allowed_actions={"composio.list_toolkits"},
        executor=list_toolkits,
        executor_trace={"provider": "composio", "session_kind": policy["session_kind"]},
    )
    live_result = dict(live.get("live_result") or {})
    if live.get("status") == "blocked_by_policy" or live_result.get("status") == "blocked_by_policy":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "composio_toolkits_sync_blocked_by_policy",
                "message": live_result.get("reason") or "Composio toolkit sync was blocked before external execution.",
            },
        )
    if live_result.get("status") == "failed":
        raise HTTPException(
            status_code=502,
            detail={
                "code": "composio_toolkits_sync_failed",
                "message": live_result.get("summary") or "Composio toolkit sync failed.",
            },
        )
    toolkits = list(synced.get("toolkits") or [])
    with db() as conn:
        for toolkit in toolkits:
            conn.execute(
                """
                INSERT INTO composio_toolkits (
                  slug, name, logo, is_connected, connected_account_id,
                  session_kind, session_id, raw, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                ON CONFLICT (slug, session_kind) DO UPDATE
                SET name = EXCLUDED.name,
                    logo = EXCLUDED.logo,
                    is_connected = EXCLUDED.is_connected,
                    connected_account_id = EXCLUDED.connected_account_id,
                    session_id = EXCLUDED.session_id,
                    raw = EXCLUDED.raw,
                    updated_at = now()
                """,
                (
                    toolkit["slug"],
                    toolkit["name"],
                    toolkit["logo"],
                    toolkit["connected"],
                    toolkit["connected_account_id"],
                    policy["session_kind"],
                    session_payload["session_id"],
                    json.dumps(toolkit, ensure_ascii=False, default=str),
                ),
            )
    return {"session": session_payload, "toolkits": toolkits}


def composio_tool_execution_policy(tool_slug: str) -> dict[str, Any]:
    slug = (tool_slug or "").strip().upper()
    read_markers = ("GET", "FETCH", "LIST", "SEARCH", "READ", "RETRIEVE", "QUERY", "FIND")
    draft_markers = ("DRAFT", "CREATE_DRAFT", "PREPARE_DRAFT")
    send_markers = ("SEND", "SUBMIT", "PAY", "PURCHASE", "TRANSFER", "DELETE", "REMOVE")
    if any(marker in slug for marker in draft_markers):
        return {
            "risk_level": "external_draft",
            "action_type": "composio.prepare_draft",
            "expected_effect": "Prepare or update a third-party draft only; do not send, pay, submit, delete, or finalize anything.",
        }
    if any(marker in slug for marker in read_markers):
        return {
            "risk_level": "read_only",
            "action_type": "composio.execute_tool",
            "expected_effect": "Read data from the connected toolkit and return a scoped result.",
        }
    if any(marker in slug for marker in send_markers):
        return {
            "risk_level": "external_message" if "SEND" in slug else "external_write",
            "action_type": "email.send" if "SEND" in slug else "composio.execute_tool",
            "expected_effect": "This tool may change the external world and requires an explicit external-effect confirmation flow.",
        }
    return {
        "risk_level": "external_write",
        "action_type": "composio.execute_tool",
        "expected_effect": "Unknown Composio tool risk; require explicit confirmation before live execution.",
    }


def normalize_composio_tool_result(result: Any) -> Any:
    if hasattr(result, "model_dump") and callable(result.model_dump):
        return result.model_dump()
    if hasattr(result, "dict") and callable(result.dict):
        return result.dict()
    if isinstance(result, dict):
        return {str(key): normalize_composio_tool_result(value) for key, value in result.items()}
    if isinstance(result, list):
        return [normalize_composio_tool_result(item) for item in result]
    if isinstance(result, tuple):
        return [normalize_composio_tool_result(item) for item in result]
    if isinstance(result, (str, int, float, bool)) or result is None:
        return result
    return str(result)


def invoke_composio_session_tool(session: Any, tool_slug: str, arguments: dict[str, Any]) -> Any:
    if hasattr(session, "execute_tool") and callable(session.execute_tool):
        return session.execute_tool(tool_slug, arguments)
    execute = getattr(session, "execute", None)
    if callable(execute):
        try:
            return execute(tool_slug=tool_slug, arguments=arguments)
        except TypeError:
            return execute(tool_slug, arguments)
    tools_attr = getattr(session, "tools", None)
    if tools_attr is not None and not callable(tools_attr):
        tools_execute = getattr(tools_attr, "execute", None)
        if callable(tools_execute):
            try:
                return tools_execute(tool_slug=tool_slug, arguments=arguments)
            except TypeError:
                return tools_execute(tool_slug, arguments)
    raise RuntimeError("The active Composio SDK session does not expose a supported tool execution method.")


def persist_composio_tool_invocation(
    *,
    task_trace_id: str,
    toolkit_slug: str,
    tool_slug: str,
    session_kind: str,
    status: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    error: str = "",
) -> None:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO composio_tool_invocations (
              id, task_trace_id, toolkit_slug, tool_slug, session_kind, status,
              request, response, error, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, now())
            """,
            (
                uuid.uuid4(),
                task_trace_id,
                toolkit_slug,
                tool_slug,
                session_kind,
                status,
                json.dumps(request_payload, ensure_ascii=False, default=str),
                json.dumps(response_payload, ensure_ascii=False, default=str),
                error[:1000],
            ),
        )


def execute_composio_tool_call(body: ComposioToolExecuteIn) -> dict[str, Any]:
    toolkit_slug = body.toolkit_slug.strip().lower()
    tool_slug = body.tool_slug.strip()
    requested_kind = body.session_kind.strip().lower() or "readonly"
    session_kind = choose_composio_session_kind(toolkit_slug, requested_kind)
    policy = composio_tool_execution_policy(tool_slug)
    user_id = current_composio_user_id()
    session, session_policy = get_or_create_composio_session(user_id, session_kind)
    task_id = (body.task_id or f"composio:{session_kind}:{toolkit_slug}:{tool_slug}").strip()
    step_id = (body.step_id or "execute_tool").strip()
    argument_keys = sorted(str(key) for key in body.arguments.keys())

    def run_tool(action_request: dict[str, Any]) -> dict[str, Any]:
        raw_result = invoke_composio_session_tool(session, tool_slug, dict(body.arguments))
        normalized_result = normalize_composio_tool_result(raw_result)
        return {
            "status": "completed",
            "toolkit": toolkit_slug,
            "tool_slug": tool_slug,
            "result": normalized_result,
            "external_side_effect": policy["risk_level"] != "read_only",
        }

    live = composio_live_registry().execute_live(
        task_id=task_id,
        step_id=step_id,
        adapter="composio",
        action_type=policy["action_type"],
        target={"kind": "composio_tool", "toolkit_slug": toolkit_slug, "tool_slug": tool_slug},
        input_summary={
            "user_id": user_id,
            "session_kind": session_policy["session_kind"],
            "argument_keys": argument_keys,
            "arguments_present": bool(body.arguments),
        },
        risk_level=policy["risk_level"],
        expected_effect=policy["expected_effect"],
        allowed_actions={"composio.execute_tool", "composio.prepare_draft", "email.send"},
        executor=run_tool,
        executor_trace={
            "provider": "composio",
            "toolkit": toolkit_slug,
            "tool_slug": tool_slug,
            "session_kind": session_policy["session_kind"],
        },
    )
    live_result = dict(live.get("live_result") or {})
    status = str(live.get("status") or live_result.get("status") or "")
    request_payload = {
        "toolkit_slug": toolkit_slug,
        "tool_slug": tool_slug,
        "session_kind": session_kind,
        "arguments": dict(body.arguments),
        "argument_keys": argument_keys,
        "task_id": task_id,
        "step_id": step_id,
        "risk_level": policy["risk_level"],
    }
    response_payload = {
        "status": status,
        "live_result": live_result,
        "policy_report": live.get("policy_report", {}),
    }
    if live.get("policy_report", {}).get("status") == "requires_confirmation":
        persist_composio_tool_invocation(
            task_trace_id=task_id,
            toolkit_slug=toolkit_slug,
            tool_slug=tool_slug,
            session_kind=session_kind,
            status="requires_confirmation",
            request_payload=request_payload,
            response_payload=response_payload,
            error=str(live.get("policy_report", {}).get("reason") or ""),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "composio_tool_execution_requires_confirmation",
                "message": live.get("policy_report", {}).get("reason") or "Composio tool execution requires explicit confirmation.",
                "policy_report": live.get("policy_report", {}),
            },
        )
    if status == "blocked_by_policy" or live_result.get("status") == "blocked_by_policy":
        persist_composio_tool_invocation(
            task_trace_id=task_id,
            toolkit_slug=toolkit_slug,
            tool_slug=tool_slug,
            session_kind=session_kind,
            status="blocked_by_policy",
            request_payload=request_payload,
            response_payload=response_payload,
            error=str(live_result.get("reason") or live.get("policy_report", {}).get("reason") or ""),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "composio_tool_execution_blocked_by_policy",
                "message": live_result.get("reason") or live.get("policy_report", {}).get("reason") or "Composio tool execution was blocked by policy.",
                "policy_report": live.get("policy_report", {}),
            },
        )
    if live_result.get("status") == "failed":
        persist_composio_tool_invocation(
            task_trace_id=task_id,
            toolkit_slug=toolkit_slug,
            tool_slug=tool_slug,
            session_kind=session_kind,
            status="failed",
            request_payload=request_payload,
            response_payload=response_payload,
            error=str(live_result.get("summary") or live_result.get("error") or ""),
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "composio_tool_execution_failed",
                "message": live_result.get("summary") or "Composio tool execution failed.",
            },
        )
    persist_composio_tool_invocation(
        task_trace_id=task_id,
        toolkit_slug=toolkit_slug,
        tool_slug=tool_slug,
        session_kind=session_kind,
        status=status or "completed",
        request_payload=request_payload,
        response_payload=response_payload,
    )
    return {
        "status": status or "completed",
        "toolkit_slug": toolkit_slug,
        "tool_slug": tool_slug,
        "session_kind": session_kind,
        "live_result": live_result,
        "policy_report": live.get("policy_report", {}),
        "trace": {
            "action_request": live.get("action_request", {}),
            "executor_trace": live.get("executor_trace", {}),
        },
    }


def attach_pipeline_provider_execution(result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    context = context or {}
    if result.get("missing_slots"):
        return result
    plan = result.get("provider_call_plan") if isinstance(result.get("provider_call_plan"), dict) else {}
    if not plan and isinstance(context.get("provider_call_plan"), dict):
        plan = dict(context["provider_call_plan"])
    if not plan:
        return result
    mode = str(plan.get("mode") or plan.get("status") or "").strip().lower()
    if mode not in {"execute_read_only", "execute_draft"}:
        return result
    provider = str(plan.get("provider") or plan.get("adapter") or "").strip().lower()
    if provider != "composio":
        return result
    toolkit_slug = str(plan.get("toolkit_slug") or "").strip()
    tool_slug = str(plan.get("tool_slug") or "").strip()
    if not toolkit_slug or not tool_slug:
        result["provider_execution"] = {
            "status": "skipped",
            "reason": "Explicit Composio provider execution requires toolkit_slug and tool_slug.",
        }
        return result
    session_kind = str(plan.get("session_kind") or ("readonly" if mode == "execute_read_only" else "write")).strip()
    arguments = plan.get("arguments")
    if not isinstance(arguments, dict):
        arguments = plan.get("params") if isinstance(plan.get("params"), dict) else {}
    try:
        execution = execute_composio_tool_call(
            ComposioToolExecuteIn(
                toolkit_slug=toolkit_slug,
                tool_slug=tool_slug,
                arguments=dict(arguments),
                session_kind=session_kind,
                task_id=str(result.get("task_trace_id") or context.get("task_id") or ""),
                step_id=f"{result.get('pipeline_id') or 'pipeline'}:provider_call",
            )
        )
        result["provider_execution"] = execution
        result.setdefault("provider_calls", []).append(
            {
                "provider": "composio",
                "toolkit_slug": toolkit_slug,
                "tool_slug": tool_slug,
                "status": execution.get("status"),
                "mode": mode,
            }
        )
        return result
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        result["provider_execution"] = {
            "status": detail.get("code") or "failed",
            "http_status": exc.status_code,
            "detail": detail,
            "toolkit_slug": toolkit_slug,
            "tool_slug": tool_slug,
        }
        return result


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


def ensure_private_event_gateway_schema() -> None:
    with db() as conn:
        for sql in private_event_gateway_schema_sql():
            conn.execute(sql)


def ensure_assistant_identity_schema() -> None:
    with db() as conn:
        for sql in assistant_identity_schema_sql():
            conn.execute(sql)


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


def ensure_model_gateway_schema() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_providers (
              provider_id TEXT PRIMARY KEY,
              display_name TEXT NOT NULL DEFAULT '',
              base_url TEXT NOT NULL DEFAULT '',
              model TEXT NOT NULL DEFAULT '',
              priority INTEGER NOT NULL DEFAULT 100,
              enabled BOOLEAN NOT NULL DEFAULT TRUE,
              supports_streaming BOOLEAN NOT NULL DEFAULT TRUE,
              supports_tool_calling BOOLEAN NOT NULL DEFAULT FALSE,
              context_window_tokens INTEGER NOT NULL DEFAULT 0,
              privacy_tier TEXT NOT NULL DEFAULT '',
              task_classes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_health_checks (
              id UUID PRIMARY KEY,
              provider_id TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT '',
              state TEXT NOT NULL DEFAULT '',
              error_type TEXT NOT NULL DEFAULT '',
              error TEXT NOT NULL DEFAULT '',
              latency_ms INTEGER,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_request_traces (
              id UUID PRIMARY KEY,
              task_class TEXT NOT NULL DEFAULT '',
              selected_provider_id TEXT NOT NULL DEFAULT '',
              fallback_provider_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              status TEXT NOT NULL DEFAULT '',
              error_type TEXT NOT NULL DEFAULT '',
              user_visible_message TEXT NOT NULL DEFAULT '',
              context_snapshot_id TEXT,
              input_token_estimate INTEGER,
              output_token_estimate INTEGER,
              stream_first_token_ms INTEGER,
              latency_ms INTEGER,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS model_health_checks_provider_idx
            ON model_health_checks(provider_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS model_request_traces_provider_idx
            ON model_request_traces(selected_provider_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS model_request_traces_status_idx
            ON model_request_traces(status, created_at DESC)
            """
        )


def ensure_assistant_context_schema() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assistant_conversations (
              id UUID PRIMARY KEY,
              client_type TEXT NOT NULL DEFAULT 'web',
              started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              last_active_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              active_task_id TEXT,
              scope JSONB NOT NULL DEFAULT '{}'::jsonb,
              status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assistant_turns (
              id UUID PRIMARY KEY,
              conversation_id UUID REFERENCES assistant_conversations(id) ON DELETE CASCADE,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              event_id UUID UNIQUE REFERENCES events(event_id) ON DELETE CASCADE,
              suggestion_id UUID,
              tool_call_id TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              finalized_at TIMESTAMPTZ
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS context_snapshots (
              id UUID PRIMARY KEY,
              event_id UUID REFERENCES events(event_id) ON DELETE CASCADE,
              context_type TEXT NOT NULL,
              included_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              included_memory_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              included_agenda_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              reason TEXT NOT NULL DEFAULT '',
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS assistant_turns_conversation_idx
            ON assistant_turns(conversation_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS assistant_turns_event_idx
            ON assistant_turns(event_id)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS context_snapshots_event_idx
            ON context_snapshots(event_id, created_at DESC)
            """
        )


def ensure_curated_assistant_memory_schema() -> None:
    with db() as conn:
        for sql in assistant_memory_schema_sql():
            conn.execute(sql)


def ensure_proactive_feedback_schema() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proactive_candidates (
              id UUID PRIMARY KEY,
              candidate_type TEXT NOT NULL,
              agenda_item_id UUID,
              event_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
              scores JSONB NOT NULL DEFAULT '{}'::jsonb,
              decision TEXT NOT NULL DEFAULT 'pending',
              cooldown_key TEXT,
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_feedback (
              id UUID PRIMARY KEY,
              suggestion_id UUID,
              action TEXT NOT NULL,
              rating DOUBLE PRECISION,
              reason TEXT NOT NULL DEFAULT '',
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS proactive_candidates_decision_idx
            ON proactive_candidates(decision, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS user_feedback_suggestion_idx
            ON user_feedback(suggestion_id, created_at DESC)
            """
        )


def ensure_task_routing_schema() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_route_traces (
              id UUID PRIMARY KEY,
              request TEXT NOT NULL,
              route_type TEXT NOT NULL,
              capability_id TEXT NOT NULL,
              pipeline_id TEXT,
              risk_permission TEXT NOT NULL,
              confirmation_required BOOLEAN NOT NULL DEFAULT FALSE,
              task_route_decision JSONB NOT NULL DEFAULT '{}'::jsonb,
              openclaw_task_packet JSONB,
              clarification JSONB,
              context_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute("ALTER TABLE task_route_traces ADD COLUMN IF NOT EXISTS source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]")
        conn.execute("ALTER TABLE task_route_traces ADD COLUMN IF NOT EXISTS conversation_id TEXT")
        conn.execute("ALTER TABLE task_route_traces ADD COLUMN IF NOT EXISTS suggestion_id TEXT")
        conn.execute("ALTER TABLE task_route_traces ADD COLUMN IF NOT EXISTS agenda_item_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_execution_results (
              id UUID PRIMARY KEY,
              task_trace_id TEXT,
              request TEXT NOT NULL,
              route_type TEXT NOT NULL,
              capability_id TEXT,
              pipeline_id TEXT,
              status TEXT NOT NULL,
              required_slots TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              resolved_slots JSONB NOT NULL DEFAULT '{}'::jsonb,
              missing_slots TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              risk JSONB NOT NULL DEFAULT '{}'::jsonb,
              execution_guard JSONB NOT NULL DEFAULT '{}'::jsonb,
              source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              conversation_id TEXT,
              suggestion_id TEXT,
              agenda_item_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              result JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS task_route_traces_created_idx
            ON task_route_traces(created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS task_route_traces_route_idx
            ON task_route_traces(route_type, capability_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS task_route_traces_source_event_idx
            ON task_route_traces USING GIN(source_event_ids)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS task_route_traces_conversation_idx
            ON task_route_traces(conversation_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS pipeline_execution_results_trace_idx
            ON pipeline_execution_results(task_trace_id, created_at DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS pipeline_execution_results_source_event_idx
            ON pipeline_execution_results USING GIN(source_event_ids)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS pipeline_execution_results_conversation_idx
            ON pipeline_execution_results(conversation_id, created_at DESC)
            """
        )
        backfill_explicit_trace_references(conn)
    ensure_pipeline_local_state_schema()


def ensure_task_orchestrator_schema() -> None:
    with db() as conn:
        for sql in task_orchestrator_schema_sql():
            conn.execute(sql)


def ensure_long_tail_agent_schema() -> None:
    with db() as conn:
        for sql in long_tail_agent_schema_sql():
            conn.execute(sql)


def ensure_tool_registry_schema() -> None:
    with db() as conn:
        for sql in tool_registry_schema_sql():
            conn.execute(sql)


def ensure_workflow_distillation_schema() -> None:
    with db() as conn:
        for sql in workflow_distillation_schema_sql():
            conn.execute(sql)


def backfill_explicit_trace_references(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        UPDATE task_route_traces t
        SET source_event_ids = COALESCE(
          (
            SELECT array_agg(value)
            FROM jsonb_array_elements_text(t.context_summary->'source_event_ids') AS value
          ),
          ARRAY[]::TEXT[]
        )
        WHERE cardinality(t.source_event_ids) = 0
          AND jsonb_typeof(t.context_summary->'source_event_ids') = 'array'
        """
    )
    conn.execute(
        """
        UPDATE task_route_traces
        SET conversation_id = NULLIF(context_summary->>'conversation_id', '')
        WHERE conversation_id IS NULL
          AND context_summary ? 'conversation_id'
        """
    )
    conn.execute(
        """
        UPDATE task_route_traces
        SET suggestion_id = NULLIF(context_summary->>'suggestion_id', '')
        WHERE suggestion_id IS NULL
          AND context_summary ? 'suggestion_id'
        """
    )
    conn.execute(
        """
        UPDATE task_route_traces t
        SET agenda_item_ids = COALESCE(
          (
            SELECT array_agg(value)
            FROM jsonb_array_elements_text(t.context_summary->'agenda_item_ids') AS value
          ),
          ARRAY[]::TEXT[]
        )
        WHERE cardinality(t.agenda_item_ids) = 0
          AND jsonb_typeof(t.context_summary->'agenda_item_ids') = 'array'
        """
    )
    conn.execute(
        """
        UPDATE task_route_traces
        SET agenda_item_ids = ARRAY[context_summary->>'agenda_item_id']::TEXT[]
        WHERE cardinality(agenda_item_ids) = 0
          AND NULLIF(context_summary->>'agenda_item_id', '') IS NOT NULL
        """
    )
    conn.execute(
        """
        UPDATE pipeline_execution_results p
        SET source_event_ids = COALESCE(
          (
            SELECT array_agg(value)
            FROM jsonb_array_elements_text(p.result->'input'->'source_event_ids') AS value
          ),
          ARRAY[]::TEXT[]
        )
        WHERE cardinality(p.source_event_ids) = 0
          AND jsonb_typeof(p.result->'input'->'source_event_ids') = 'array'
        """
    )
    conn.execute(
        """
        UPDATE pipeline_execution_results
        SET conversation_id = NULLIF(result->'input'->>'conversation_id', '')
        WHERE conversation_id IS NULL
          AND result->'input' ? 'conversation_id'
        """
    )
    conn.execute(
        """
        UPDATE pipeline_execution_results
        SET suggestion_id = NULLIF(result->'input'->>'suggestion_id', '')
        WHERE suggestion_id IS NULL
          AND result->'input' ? 'suggestion_id'
        """
    )
    conn.execute(
        """
        UPDATE pipeline_execution_results p
        SET agenda_item_ids = COALESCE(
          (
            SELECT array_agg(value)
            FROM jsonb_array_elements_text(p.result->'input'->'agenda_item_ids') AS value
          ),
          ARRAY[]::TEXT[]
        )
        WHERE cardinality(p.agenda_item_ids) = 0
          AND jsonb_typeof(p.result->'input'->'agenda_item_ids') = 'array'
        """
    )
    conn.execute(
        """
        UPDATE pipeline_execution_results
        SET agenda_item_ids = ARRAY[result->'input'->>'agenda_item_id']::TEXT[]
        WHERE cardinality(agenda_item_ids) = 0
          AND NULLIF(result->'input'->>'agenda_item_id', '') IS NOT NULL
        """
    )


def ensure_pipeline_local_state_schema() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_writeback_events (
              id UUID PRIMARY KEY,
              pipeline_execution_id TEXT,
              task_trace_id TEXT,
              pipeline_id TEXT,
              target TEXT NOT NULL,
              operation TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              error TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_quarantine (
              id UUID PRIMARY KEY,
              event_id TEXT,
              dedupe_key TEXT,
              source TEXT NOT NULL DEFAULT '',
              event_type TEXT NOT NULL DEFAULT '',
              event_timestamp TEXT,
              schema_errors TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              raw_event JSONB NOT NULL DEFAULT '{}'::jsonb,
              summary TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS duplicate_skip (
              id UUID PRIMARY KEY,
              event_id TEXT,
              dedupe_key TEXT,
              duplicate_of TEXT,
              source TEXT NOT NULL DEFAULT '',
              event_type TEXT NOT NULL DEFAULT '',
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_items (
              id TEXT PRIMARY KEY,
              source_event_id TEXT,
              scope JSONB NOT NULL DEFAULT '{}'::jsonb,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_entities (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL DEFAULT '',
              scope JSONB NOT NULL DEFAULT '{}'::jsonb,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_edges (
              id UUID PRIMARY KEY,
              source_id TEXT NOT NULL DEFAULT '',
              target_id TEXT NOT NULL DEFAULT '',
              relation_type TEXT NOT NULL DEFAULT '',
              scope JSONB NOT NULL DEFAULT '{}'::jsonb,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_vector_retries (
              id UUID PRIMARY KEY,
              source_event_id TEXT,
              chunk_id TEXT,
              reason TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'queued',
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS context_snapshot_plans (
              id UUID PRIMARY KEY,
              request_or_event_id TEXT NOT NULL DEFAULT '',
              current_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS internal_todos (
              id UUID PRIMARY KEY,
              task_title TEXT NOT NULL DEFAULT '',
              owner TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'open',
              due_window JSONB NOT NULL DEFAULT '{}'::jsonb,
              source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS internal_reminders (
              id UUID PRIMARY KEY,
              status TEXT NOT NULL DEFAULT 'planned_internal',
              due_window JSONB NOT NULL DEFAULT '{}'::jsonb,
              source_event_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_call_traces (
              id UUID PRIMARY KEY,
              task_id TEXT NOT NULL DEFAULT '',
              provider TEXT NOT NULL DEFAULT '',
              action TEXT NOT NULL DEFAULT '',
              call_status TEXT NOT NULL DEFAULT '',
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS confirmation_ledger (
              id UUID PRIMARY KEY,
              task_id TEXT NOT NULL DEFAULT '',
              kind TEXT NOT NULL DEFAULT '',
              confirm_action TEXT NOT NULL DEFAULT '',
              final_user_confirmation BOOLEAN NOT NULL DEFAULT FALSE,
              status TEXT NOT NULL DEFAULT 'required',
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pipeline_health_metrics (
              id UUID PRIMARY KEY,
              pipeline_id TEXT,
              status TEXT NOT NULL DEFAULT '',
              applied_count INTEGER NOT NULL DEFAULT 0,
              failed_count INTEGER NOT NULL DEFAULT 0,
              skipped_count INTEGER NOT NULL DEFAULT 0,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_audit (
              id UUID PRIMARY KEY,
              pipeline_id TEXT NOT NULL DEFAULT '',
              query TEXT NOT NULL DEFAULT '',
              scope TEXT NOT NULL DEFAULT '',
              result_count INTEGER NOT NULL DEFAULT 0,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS account_connections (
              provider TEXT PRIMARY KEY,
              status TEXT NOT NULL DEFAULT 'not_connected',
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS composio_sessions (
              id UUID PRIMARY KEY,
              user_id TEXT NOT NULL,
              session_kind TEXT NOT NULL,
              session_id TEXT NOT NULL UNIQUE,
              mcp_url TEXT NOT NULL DEFAULT '',
              mcp_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
              enabled_toolkits TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
              tags JSONB NOT NULL DEFAULT '{}'::jsonb,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS composio_connect_requests (
              id UUID PRIMARY KEY,
              user_id TEXT NOT NULL,
              toolkit_slug TEXT NOT NULL,
              session_kind TEXT NOT NULL,
              session_id TEXT NOT NULL DEFAULT '',
              connection_request_id TEXT NOT NULL DEFAULT '',
              redirect_url TEXT NOT NULL DEFAULT '',
              connected_account_id TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'link_created',
              expires_at TIMESTAMPTZ,
              metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS composio_toolkits (
              slug TEXT NOT NULL,
              session_kind TEXT NOT NULL,
              name TEXT NOT NULL DEFAULT '',
              logo TEXT NOT NULL DEFAULT '',
              is_connected BOOLEAN NOT NULL DEFAULT FALSE,
              connected_account_id TEXT NOT NULL DEFAULT '',
              session_id TEXT NOT NULL DEFAULT '',
              raw JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              PRIMARY KEY (slug, session_kind)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS composio_tool_invocations (
              id UUID PRIMARY KEY,
              task_trace_id TEXT,
              toolkit_slug TEXT NOT NULL DEFAULT '',
              tool_slug TEXT NOT NULL DEFAULT '',
              session_kind TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT '',
              request JSONB NOT NULL DEFAULT '{}'::jsonb,
              response JSONB NOT NULL DEFAULT '{}'::jsonb,
              error TEXT NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS composio_triggers (
              id UUID PRIMARY KEY,
              trigger_id TEXT NOT NULL DEFAULT '',
              trigger_slug TEXT NOT NULL DEFAULT '',
              toolkit_slug TEXT NOT NULL DEFAULT '',
              user_id TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT '',
              config JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS route_cache (
              id UUID PRIMARY KEY,
              origin TEXT NOT NULL DEFAULT '',
              destination TEXT NOT NULL DEFAULT '',
              mode TEXT NOT NULL DEFAULT '',
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS pipeline_writeback_events_trace_idx ON pipeline_writeback_events(task_trace_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS pipeline_writeback_events_target_idx ON pipeline_writeback_events(target, status, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS event_quarantine_source_idx ON event_quarantine(source, event_type, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS duplicate_skip_dedupe_idx ON duplicate_skip(dedupe_key, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS memory_items_source_event_idx ON memory_items(source_event_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS knowledge_entities_name_idx ON knowledge_entities(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS knowledge_edges_source_idx ON knowledge_edges(source_id, relation_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS internal_todos_status_idx ON internal_todos(status, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS internal_reminders_status_idx ON internal_reminders(status, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS provider_call_traces_task_idx ON provider_call_traces(task_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS confirmation_ledger_task_idx ON confirmation_ledger(task_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS pipeline_health_metrics_pipeline_idx ON pipeline_health_metrics(pipeline_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS search_audit_query_idx ON search_audit(query, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS route_cache_destination_idx ON route_cache(destination, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS composio_sessions_user_kind_idx ON composio_sessions(user_id, session_kind, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS composio_connect_requests_toolkit_idx ON composio_connect_requests(toolkit_slug, status, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS composio_tool_invocations_tool_idx ON composio_tool_invocations(toolkit_slug, tool_slug, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS composio_triggers_slug_idx ON composio_triggers(trigger_slug, status, updated_at DESC)")


def ensure_openclaw_execution_schema() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openclaw_execution_jobs (
              id UUID PRIMARY KEY,
              task_id TEXT NOT NULL,
              trace_id UUID,
              status TEXT NOT NULL,
              attempt_count INTEGER NOT NULL DEFAULT 0,
              max_attempts INTEGER NOT NULL DEFAULT 3,
              openclaw_task_packet JSONB NOT NULL,
              execution_guard JSONB NOT NULL DEFAULT '{}'::jsonb,
              last_result JSONB,
              last_error TEXT,
              next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              completed_at TIMESTAMPTZ
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openclaw_execution_events (
              id UUID PRIMARY KEY,
              job_id UUID NOT NULL REFERENCES openclaw_execution_jobs(id) ON DELETE CASCADE,
              event_type TEXT NOT NULL,
              message TEXT NOT NULL DEFAULT '',
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS openclaw_execution_jobs_status_idx
            ON openclaw_execution_jobs(status, next_attempt_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS openclaw_execution_events_job_idx
            ON openclaw_execution_events(job_id, created_at)
            """
        )


def ensure_delegated_automation_schema() -> None:
    with db() as conn:
        for sql in delegated_automation_schema_sql():
            conn.execute(sql)


def default_collector_settings() -> list[str]:
    return ["bookmark", "calendar", "focus", "gmail", "search", "telegram", "whatsapp"]


def collector_capability_profile(source: str) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = {
        "gmail": {
            "mode": "api_or_browser",
            "adapters": ["composio:gmail", "managed_browser_visible_dom"],
            "supported_operations": [
                "full_mailbox_sync_when_connected",
                "visible_inbox_snapshot",
                "message_subject_sender_snippet_body_when_available",
            ],
            "full_history_guarantee": True,
            "limitations": [
                "Full mailbox sync requires a connected Composio Gmail account.",
                "Browser fallback only captures visible Gmail pages.",
            ],
        },
        "calendar": {
            "mode": "api_or_browser",
            "adapters": ["composio:googlecalendar", "managed_browser_visible_dom"],
            "supported_operations": ["event_read_when_connected", "visible_calendar_snapshot"],
            "full_history_guarantee": True,
            "limitations": ["Calendar API reads require Google Calendar authorization."],
        },
        "whatsapp": {
            "mode": "managed_browser_visible_dom",
            "adapters": ["server_chromium_dom"],
            "supported_operations": ["visible_chat_list", "opened_conversation_visible_messages", "manual_reply_draft"],
            "full_history_guarantee": False,
            "limitations": [
                "No official full-history WhatsApp API is used in this version.",
                "Only logged-in, visible, or explicitly opened WhatsApp Web content can be collected.",
            ],
        },
        "telegram": {
            "mode": "managed_browser_visible_dom",
            "adapters": ["server_chromium_dom"],
            "supported_operations": ["visible_chat_list", "opened_conversation_visible_messages"],
            "full_history_guarantee": False,
            "limitations": [
                "No Telegram account API sync is used in this version.",
                "Only logged-in, visible, or explicitly opened Telegram Web content can be collected.",
            ],
        },
        "search": {
            "mode": "managed_browser_visible_dom",
            "adapters": ["server_chromium_dom"],
            "supported_operations": ["visible_search_page", "query_and_result_snapshot"],
            "full_history_guarantee": False,
            "limitations": ["Does not claim browser-wide Google account search history export."],
        },
        "bookmark": {
            "mode": "local_browser_profile",
            "adapters": ["server_chromium_profile"],
            "supported_operations": ["bookmark_snapshot"],
            "full_history_guarantee": False,
            "limitations": ["Only the managed server browser profile is in scope."],
        },
        "focus": {
            "mode": "local_browser_signal",
            "adapters": ["server_chromium_focus"],
            "supported_operations": ["active_url", "title", "visible_text_hint"],
            "full_history_guarantee": False,
            "limitations": ["Focus signals are contextual hints, not complete page archives."],
        },
    }
    fallback = {
        "mode": "unknown",
        "adapters": [],
        "supported_operations": [],
        "full_history_guarantee": False,
        "limitations": ["No explicit collector capability profile has been declared for this source."],
    }
    profile = profiles.get((source or "").strip().lower(), fallback)
    return json.loads(json.dumps(profile, ensure_ascii=False))


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
                "capability": collector_capability_profile(setting["source"]),
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


@app.get("/api/model/status")
def model_status(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    return model_gateway().status()


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


@app.get("/api/assistant-identities")
def assistant_identities(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    identities = _ASSISTANT_IDENTITY_REGISTRY.bootstrap_defaults()
    return {
        "count": len(identities),
        "identities": [identity.to_dict() for identity in identities],
    }


@app.post("/api/assistant-identities/{kind}/connect")
def assistant_identity_connect(
    kind: str,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    try:
        identity = _ASSISTANT_IDENTITY_REGISTRY.connect_kind(kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="assistant identity kind not found") from exc
    return {"status": "connected", "identity": identity.to_dict()}


@app.patch("/api/assistant-identities/{identity_id}")
def assistant_identity_patch(
    identity_id: str,
    body: AssistantIdentityPatchIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    try:
        identity = _ASSISTANT_IDENTITY_REGISTRY.update(
            identity_id,
            display_name=body.display_name,
            status=body.status,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="assistant identity not found") from exc
    return {"status": "updated", "identity": identity.to_dict()}


@app.get("/api/assistant-identities/{identity_id}/health")
def assistant_identity_health(
    identity_id: str,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    identity = _ASSISTANT_IDENTITY_REGISTRY.get(identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="assistant identity not found")
    healthy_statuses = {"connected", "configured", "healthy"}
    return {
        "identity_id": identity.identity_id,
        "kind": identity.kind,
        "status": identity.status,
        "healthy": identity.status in healthy_statuses,
        "capabilities": identity.capabilities,
    }


@app.post("/api/assistant-inbox/gmail/sync")
def assistant_gmail_sync(
    body: AssistantGmailSyncIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    gateway = AssistantInboxGateway(
        ContactResolver(user_keys=set(body.user_keys), known_contacts=body.known_contacts)
    )
    event = gateway.normalize_gmail(identity_id=body.identity_id, message=body.message)
    _ASSISTANT_INBOX_EVENTS.append(event)
    return {"status": "accepted", "event": event}


@app.post("/api/assistant-inbox/gmail/pubsub")
def assistant_gmail_pubsub(
    body: AssistantGmailPubSubIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    message = body.message
    decoded_payload: dict[str, Any] = {}
    encoded = str(message.get("data") or "")
    if encoded:
        try:
            padding = "=" * (-len(encoded) % 4)
            decoded_payload = json.loads(base64.b64decode(encoded + padding).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            decoded_payload = {"decode_error": True}
    event = {
        "event_id": "gmail-pubsub-" + str(message.get("messageId") or uuid.uuid4()),
        "provider": "gmail_pubsub",
        "source_type": "assistant_gmail",
        "source_account_id": "nomi_gmail_primary",
        "event_type": "assistant_gmail_pubsub_notification",
        "external_message_id": str(message.get("messageId") or ""),
        "normalized_payload": decoded_payload,
        "classification": "provider_status",
        "suggestion_channel": "assistant_channel_provider_status",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    _ASSISTANT_INBOX_EVENTS.append(event)
    return {"status": "accepted", "provider": "gmail_pubsub", "event": event}


@app.get("/api/assistant-inbox")
def assistant_inbox(
    x_par_password: Optional[str] = Header(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    require_password(x_par_password)
    items = list(reversed(_ASSISTANT_INBOX_EVENTS))[:limit]
    return {"count": len(items), "items": items}


@app.get("/api/assistant-inbox/{event_id}")
def assistant_inbox_detail(
    event_id: str,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    for event in _ASSISTANT_INBOX_EVENTS:
        if str(event.get("event_id")) == event_id:
            return {"event": event}
    raise HTTPException(status_code=404, detail="assistant inbox event not found")


@app.post("/api/assistant-inbox/whatsapp/webhook")
def assistant_whatsapp_webhook(
    body: AssistantWhatsAppWebhookIn,
    x_assistant_webhook_token: Optional[str] = Header(default=None, alias="x-assistant-webhook-token"),
) -> dict[str, Any]:
    expected_token = os.getenv("ASSISTANT_WHATSAPP_VERIFY_TOKEN", "").strip()
    if expected_token and x_assistant_webhook_token != expected_token:
        raise HTTPException(status_code=403, detail="invalid assistant WhatsApp webhook token")
    gateway = AssistantInboxGateway(ContactResolver(known_contacts=body.known_contacts))
    events: list[dict[str, Any]] = []
    for entry in body.entry:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                text_value = message.get("text")
                if isinstance(text_value, dict):
                    text = str(text_value.get("body") or "")
                else:
                    text = str(text_value or message.get("body") or "")
                event = gateway.normalize_whatsapp(
                    identity_id="nomi_whatsapp_primary",
                    payload={
                        "wamid": message.get("id") or message.get("wamid"),
                        "from": message.get("from") or "",
                        "text": text,
                        "timestamp": message.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                        "type": message.get("type") or "text",
                    },
                )
                events.append(event)
                _ASSISTANT_INBOX_EVENTS.append(event)
    return {"status": "accepted", "events": events}


def _verify_assistant_phone_webhook_token(token: Optional[str]) -> None:
    verifier = PhoneWebhookVerifier(os.getenv("ASSISTANT_PHONE_WEBHOOK_TOKEN", "").strip())
    try:
        verifier.verify(token or "")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="invalid assistant phone webhook token")


@app.post("/api/assistant-inbox/phone/sms/webhook")
def assistant_phone_sms_webhook(
    body: AssistantPhoneSmsWebhookIn,
    x_assistant_webhook_token: Optional[str] = Header(default=None, alias="x-assistant-webhook-token"),
) -> dict[str, Any]:
    _verify_assistant_phone_webhook_token(x_assistant_webhook_token)
    gateway = AssistantInboxGateway(
        ContactResolver(user_keys=set(body.user_keys), known_contacts=body.known_contacts)
    )
    event = gateway.normalize_sms(
        identity_id=body.identity_id,
        payload={
            "provider_message_id": body.provider_message_id,
            "from": body.from_number,
            "to": body.to_number,
            "body": body.body,
            "timestamp": body.timestamp or datetime.now(timezone.utc).isoformat(),
        },
    )
    _ASSISTANT_INBOX_EVENTS.append(event)
    return {"status": "accepted", "event": event}


@app.post("/api/assistant-inbox/phone/calls/inbound")
def assistant_phone_call_inbound_webhook(
    body: AssistantPhoneCallWebhookIn,
    x_assistant_webhook_token: Optional[str] = Header(default=None, alias="x-assistant-webhook-token"),
) -> dict[str, Any]:
    _verify_assistant_phone_webhook_token(x_assistant_webhook_token)
    gateway = AssistantInboxGateway(
        ContactResolver(user_keys=set(body.user_keys), known_contacts=body.known_contacts)
    )
    event = gateway.normalize_phone_call(
        identity_id=body.identity_id,
        payload={
            "provider_call_id": body.provider_call_id,
            "from": body.from_number,
            "to": body.to_number,
            "direction": body.direction or "inbound",
            "status": body.status or "received",
            "timestamp": body.timestamp or datetime.now(timezone.utc).isoformat(),
        },
    )
    _ASSISTANT_INBOX_EVENTS.append(event)
    greeting = PhoneCallInstructionBuilder().build_tts_instruction(
        script_text="我是 Nomi，张子长的个人助理。请发送短信或邮件说明你的事情，我会转达。",
        voice="default",
    )
    return {"status": "accepted", "event": event, "greeting": greeting}


@app.post("/api/assistant-inbox/phone/calls/status")
def assistant_phone_call_status_webhook(
    body: AssistantPhoneCallWebhookIn,
    x_assistant_webhook_token: Optional[str] = Header(default=None, alias="x-assistant-webhook-token"),
) -> dict[str, Any]:
    _verify_assistant_phone_webhook_token(x_assistant_webhook_token)
    event = AssistantInboxGateway(ContactResolver()).normalize_phone_call(
        identity_id=body.identity_id,
        payload={
            "provider_call_id": body.provider_call_id,
            "from": body.from_number,
            "to": body.to_number,
            "direction": body.direction or "outbound",
            "status": body.status or "unknown",
            "timestamp": body.timestamp or datetime.now(timezone.utc).isoformat(),
        },
    )
    _ASSISTANT_INBOX_EVENTS.append(event)
    return {"status": "accepted", "event": event}


@app.get("/api/assistant-inbox/phone/calls/{call_instruction_id}/instruction")
def assistant_phone_call_instruction(
    call_instruction_id: str,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    script_text = "我是 Nomi，张子长的个人助理。请发送短信或邮件说明你的事情，我会转达。"
    instruction = PhoneCallInstructionBuilder().build_tts_instruction(script_text=script_text, voice="default")
    instruction["call_instruction_id"] = call_instruction_id
    return instruction


@app.post("/api/assistant-outbound/drafts")
def assistant_outbound_create_draft(
    body: AssistantOutboundDraftIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    return _ASSISTANT_OUTBOUND_PIPELINE.prepare_draft(
        identity_id=body.identity_id,
        channel=body.channel,
        recipient=body.recipient,
        subject=body.subject,
        body_text=body.body_text,
        source_evidence_ids=body.source_evidence_ids,
        risk_notes=body.risk_notes,
    )


@app.patch("/api/assistant-outbound/drafts/{draft_id}")
def assistant_outbound_patch_draft(
    draft_id: str,
    body: AssistantOutboundDraftPatchIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    try:
        draft = _ASSISTANT_OUTBOUND_PIPELINE.get_draft(draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="draft not found") from exc
    if body.subject is not None:
        draft["subject"] = body.subject
        draft["confirmation_card"]["subject"] = body.subject
    if body.body_text is not None:
        draft["body_text"] = body.body_text
        draft["confirmation_card"]["body_preview"] = body.body_text
    if body.risk_notes is not None:
        draft["risk_notes"] = body.risk_notes
        draft["confirmation_card"]["risk_notes"] = body.risk_notes
    return draft


@app.post("/api/assistant-outbound/drafts/{draft_id}/send")
def assistant_outbound_send_draft(
    draft_id: str,
    body: AssistantOutboundSendIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    try:
        result = _ASSISTANT_OUTBOUND_PIPELINE.confirm_and_send(
            draft_id, confirmation_token=body.confirmation_token
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="draft not found") from exc
    _ASSISTANT_OUTBOUND_MESSAGES.append(result)
    return result


@app.post("/api/assistant-outbound/drafts/{draft_id}/call")
def assistant_outbound_call_draft(
    draft_id: str,
    body: AssistantOutboundSendIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    try:
        result = _ASSISTANT_OUTBOUND_PIPELINE.confirm_and_call(
            draft_id, confirmation_token=body.confirmation_token
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="draft not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _ASSISTANT_OUTBOUND_MESSAGES.append(result)
    return result


@app.post("/api/assistant-outbound/drafts/{draft_id}/cancel")
def assistant_outbound_cancel_draft(
    draft_id: str,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    try:
        return _ASSISTANT_OUTBOUND_PIPELINE.cancel_draft(draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="draft not found") from exc


@app.get("/api/assistant-outbound/messages")
def assistant_outbound_messages(
    x_par_password: Optional[str] = Header(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    require_password(x_par_password)
    items = list(reversed(_ASSISTANT_OUTBOUND_MESSAGES))[:limit]
    return {"count": len(items), "items": items}


@app.post("/api/tools/route")
def tool_route(body: ToolRouteIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    return persist_task_route_trace_safely(route_tool_request(body.request, body.context))


@app.post("/api/pipelines/run")
def pipeline_run(body: PipelineRunIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    result = run_core_pipeline(body.request, body.context)
    result = attach_pipeline_provider_execution(result, body.context)
    return persist_pipeline_execution_result_safely(result)


@app.post("/api/delegated-automation/grants")
def delegated_automation_upsert_grant(
    body: dict[str, Any],
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    grant = DelegationGrant.from_dict(body)
    stored = _DELEGATED_AUTOMATION_STORE.upsert_grant(grant)
    return {"grant": stored.to_dict()}


@app.get("/api/delegated-automation/grants")
def delegated_automation_grants(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    grants = [grant.to_dict() for grant in _DELEGATED_AUTOMATION_STORE.list_grants()]
    return {"count": len(grants), "grants": grants}


@app.post("/api/delegated-automation/manifests")
def delegated_automation_upsert_manifest(
    body: dict[str, Any],
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    manifest = TargetManifest.from_dict(body)
    stored = _DELEGATED_AUTOMATION_STORE.upsert_manifest(manifest)
    return {"manifest": stored.to_dict()}


@app.post("/api/delegated-automation/evaluate")
def delegated_automation_evaluate(
    body: DelegatedAutomationEvaluateIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    grant = _DELEGATED_AUTOMATION_STORE.get_grant(body.grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="delegation grant not found")
    manifest = _DELEGATED_AUTOMATION_STORE.get_manifest(body.manifest_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="target manifest not found")
    now = parse_datetime(body.now) or datetime.now(timezone.utc)
    decision = evaluate_delegated_action(
        grant=grant,
        manifest=manifest,
        target_id=body.target_id,
        traces=_DELEGATED_AUTOMATION_STORE.traces_for_grant(grant.grant_id),
        now=now,
        page_state=body.page_state,
        content_evidence_ids=body.content_evidence_ids,
        user_paused=body.user_paused,
    )
    return {"decision": decision.to_dict()}


@app.post("/api/delegated-automation/traces")
def delegated_automation_trace(
    body: DelegatedAutomationTraceIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    decision = AutomationDecision.from_dict(body.decision)
    if not decision.allowed and body.status == "completed":
        raise HTTPException(status_code=409, detail="cannot complete a denied delegated action")
    trace = build_execution_trace(
        decision=decision,
        trace_id=body.trace_id,
        status=body.status,
        result_summary=body.result_summary,
        evidence_ids=body.evidence_ids,
        now=parse_datetime(body.now) or datetime.now(timezone.utc),
    )
    stored = _DELEGATED_AUTOMATION_STORE.append_trace(trace)
    return {"trace": stored.to_dict()}


@app.post("/api/delegated-automation/grants/{grant_id}/pause")
def delegated_automation_pause_grant(
    grant_id: str,
    body: DelegatedAutomationPauseIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    if _DELEGATED_AUTOMATION_STORE.get_grant(grant_id) is None:
        raise HTTPException(status_code=404, detail="delegation grant not found")
    grant = _DELEGATED_AUTOMATION_STORE.pause_grant(grant_id, reason=body.reason)
    return {"grant": grant.to_dict()}


@app.post("/api/agent-tasks/route")
def agent_task_route(body: ToolRouteIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    decision = route_tool_request(body.request, body.context)
    if decision.get("route_type") == "openclaw_tool":
        capability_id = (
            (decision.get("task_route_decision") or {}).get("capability_id")
            or (decision.get("capability") or {}).get("id")
            or "long_tail.agent"
        )
        decision = {
            **decision,
            "route_type": "long_tail_agent",
            "legacy_route_type": "openclaw_tool",
            "capability_id": capability_id,
        }
    return decision


@app.post("/api/agent-tasks")
def agent_task_create(body: AgentTaskCreateIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    return long_tail_runner().create_task(
        original_goal=body.original_goal,
        route_decision=body.route_decision,
        plan=body.plan,
    )


@app.get("/api/agent-tasks/{task_id}")
def agent_task_state(task_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    state = require_long_tail_task(task_id)
    return {"state": state, "event_count": len(long_tail_event_store().task_events(task_id))}


@app.get("/api/agent-tasks/{task_id}/events")
def agent_task_events(task_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return {"task_id": task_id, "events": long_tail_event_store().task_events(task_id)}


@app.post("/api/agent-tasks/{task_id}/run-next")
def agent_task_run_next(task_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_runner().run_next(task_id)


@app.post("/api/agent-tasks/{task_id}/resume")
def agent_task_resume(task_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    state = require_long_tail_task(task_id)
    if state.get("current_node") == "awaiting_executor":
        return {"state": state, "message": "Task is waiting for executor result."}
    return long_tail_runner().run_next(task_id)


@app.post("/api/agent-tasks/{task_id}/complete-step")
def agent_task_complete_step(
    task_id: str,
    body: AgentTaskCompleteStepIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_runner().complete_current_step(task_id, executor_result=body.executor_result)


@app.post("/api/agent-tasks/{task_id}/finalize")
def agent_task_finalize(task_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_runner().evaluate_final(task_id)


@app.post("/api/agent-tasks/{task_id}/cancel")
def agent_task_cancel(
    task_id: str,
    body: AgentTaskCancelIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return {"state": long_tail_runner().cancel_task(task_id, reason=body.reason)}


@app.post("/api/agent-tasks/{task_id}/human-input")
def agent_task_human_input(
    task_id: str,
    body: AgentTaskHumanInputIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_runner().record_human_input(
        task_id,
        step_id=body.step_id,
        input_type=body.input_type,
        response=body.response,
    )


@app.post("/api/agent-tasks/{task_id}/external-effects")
def agent_task_external_effect_propose(
    task_id: str,
    body: AgentTaskExternalEffectIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_effect_controller().propose(
        task_id=task_id,
        step_id=body.step_id,
        action_request_id=body.action_request_id,
        effect_type=body.effect_type,
        proposal=body.proposal,
    )


@app.post("/api/agent-tasks/{task_id}/external-effects/{effect_id}/confirm")
def agent_task_external_effect_confirm(
    task_id: str,
    effect_id: str,
    body: AgentTaskExternalEffectConfirmIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_effect_controller().confirm(
        effect_id,
        task_id=task_id,
        confirmation_payload=body.confirmation,
    )


@app.post("/api/agent-tasks/{task_id}/external-effects/{effect_id}/execute")
def agent_task_external_effect_execute(
    task_id: str,
    effect_id: str,
    body: AgentTaskExternalEffectExecuteIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_effect_controller().execute(
        effect_id,
        task_id=task_id,
        execution_payload=body.execution_payload,
    )


@app.post("/api/agent-tasks/{task_id}/external-effects/{effect_id}/rollback")
def agent_task_external_effect_rollback(
    task_id: str,
    effect_id: str,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_effect_controller().describe_internal_rollback(effect_id, task_id=task_id)


@app.post("/api/agent-tasks/{task_id}/external-effects/{effect_id}/compensation")
def agent_task_external_effect_compensation(
    task_id: str,
    effect_id: str,
    body: AgentTaskExternalEffectCompensationIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_effect_controller().propose_compensation(
        effect_id,
        task_id=task_id,
        proposal=body.proposal,
    )


@app.post("/api/agent-tasks/{task_id}/confirm")
def agent_task_confirm(
    task_id: str,
    body: AgentTaskConfirmIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    require_long_tail_task(task_id)
    return long_tail_event_store().append_event(
        task_id=task_id,
        event_type="external_effect.confirmed",
        step_id=body.step_id,
        payload={"confirmation": body.confirmation},
        idempotency_key=f"{task_id}:api_confirm:{len(long_tail_event_store().task_events(task_id))}",
    )


@app.post("/api/browser/open")
def browser_open(body: BrowserOpenIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    target = browser_open_target(body.source)
    task_id = f"browser_login:{target['source']}"
    step_id = "open_managed_browser"
    executor_trace = {
        "provider": "managed_browser",
        "executor_trace_id": f"browser_exec_{uuid.uuid4().hex}",
        "adapter_mode": "command_queue",
        "source": target["source"],
    }
    proposed = ExecutorAdapterRegistry(event_store=long_tail_event_store(), policy_gate=PolicyGate()).propose_action(
        task_id=task_id,
        step_id=step_id,
        adapter="browser",
        action_type="browser.open_url",
        target={
            "kind": "managed_login_url",
            "source": target["source"],
            "url": target["url"],
            "host_fragment": target["host_fragment"],
        },
        input_summary={"source": target["source"], "host_fragment": target["host_fragment"]},
        risk_level="read_only",
        expected_effect="Open a managed local browser login target without submitting forms.",
        allowed_actions={"browser.open_url"},
        executor_trace=executor_trace,
    )
    if not proposed["policy_report"].get("may_execute"):
        raise HTTPException(status_code=403, detail=proposed["policy_report"])
    command = {
        "command_id": str(uuid.uuid4()),
        "action": "open_url",
        "source": target["source"],
        "url": target["url"],
        "host_fragment": target["host_fragment"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    redis_client().rpush(BROWSER_COMMAND_QUEUE_KEY, json.dumps(command, ensure_ascii=False))
    long_tail_event_store().append_event(
        task_id=task_id,
        event_type="executor.live_completed",
        step_id=step_id,
        payload={
            "action_request_id": proposed["action_request"]["action_id"],
            "policy_status": proposed["policy_report"]["status"],
            "live_result": {
                "mode": "command_queue",
                "status": "queued",
                "command_id": command["command_id"],
                "external_side_effect": False,
            },
            "executor_trace": executor_trace,
        },
        idempotency_key=f"{proposed['action_request']['idempotency_key']}:live_completed",
    )
    return {
        "status": "queued",
        "command_id": command["command_id"],
        "source": target["source"],
        "target_url": target["url"],
        "host_fragment": target["host_fragment"],
    }


@app.get("/api/browser/commands/next")
def browser_command_next(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    command = normalize_browser_command_payload(redis_client().lpop(BROWSER_COMMAND_QUEUE_KEY))
    return {"command": command}


@app.get("/api/pipelines/registry")
def pipeline_registry(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    pipelines = core_pipeline_registry()
    return {
        "count": len(pipelines),
        "pipelines": pipelines,
        "routing_policy": {
            "core_pipeline_first": True,
            "long_tail_fallback": "openclaw_tool",
            "external_effects_require_confirmation": True,
        },
    }


@app.get("/api/pipelines/health")
def pipeline_health_dashboard(
    x_par_password: Optional[str] = Header(default=None),
    limit: int = 50,
) -> dict[str, Any]:
    require_password(x_par_password)
    bounded_limit = max(1, min(limit, 200))
    with db() as conn:
        metric_rows = conn.execute(
            """
            SELECT id, pipeline_id, status, applied_count, failed_count, skipped_count, payload, created_at
            FROM pipeline_health_metrics
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (bounded_limit,),
        ).fetchall()
        provider_rows = conn.execute(
            """
            SELECT id, task_id, provider, action, call_status, payload, created_at
            FROM provider_call_traces
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (bounded_limit,),
        ).fetchall()
        confirmation_rows = conn.execute(
            """
            SELECT id, task_id, kind, confirm_action, final_user_confirmation, status, payload, created_at
            FROM confirmation_ledger
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (bounded_limit,),
        ).fetchall()
        search_rows = conn.execute(
            """
            SELECT id, pipeline_id, query, scope, result_count, payload, created_at
            FROM search_audit
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (bounded_limit,),
        ).fetchall()
    return {
        "pipeline_health_metrics": [
            {
                "id": str(row[0]),
                "pipeline_id": row[1],
                "status": row[2],
                "applied_count": row[3],
                "failed_count": row[4],
                "skipped_count": row[5],
                "payload": row[6] or {},
                "created_at": isoformat_or_value(row[7]),
            }
            for row in metric_rows
        ],
        "provider_call_traces": [
            {
                "id": str(row[0]),
                "task_id": row[1],
                "provider": row[2],
                "action": row[3],
                "call_status": row[4],
                "payload": row[5] or {},
                "created_at": isoformat_or_value(row[6]),
            }
            for row in provider_rows
        ],
        "confirmation_ledger": [
            {
                "id": str(row[0]),
                "task_id": row[1],
                "kind": row[2],
                "confirm_action": row[3],
                "final_user_confirmation": bool(row[4]),
                "status": row[5],
                "payload": row[6] or {},
                "created_at": isoformat_or_value(row[7]),
            }
            for row in confirmation_rows
        ],
        "search_audit": [
            {
                "id": str(row[0]),
                "pipeline_id": row[1],
                "query": row[2],
                "scope": row[3],
                "result_count": row[4],
                "payload": row[5] or {},
                "created_at": isoformat_or_value(row[6]),
            }
            for row in search_rows
        ],
    }


@app.get("/api/tools/route/traces")
def task_route_traces(
    x_par_password: Optional[str] = Header(default=None),
    route_type: Optional[str] = None,
    capability: Optional[str] = None,
    q: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    require_password(x_par_password)
    bounded_limit = max(1, min(limit, 100))
    with db() as conn:
        traces = fetch_task_route_traces(
            conn,
            route_type=route_type,
            capability=capability,
            q=q.strip(),
            limit=bounded_limit,
        )
    return {
        "filters": {
            "route_type": route_type,
            "capability": capability,
            "q": q.strip(),
            "limit": bounded_limit,
        },
        "traces": traces,
    }


@app.post("/api/tools/openclaw/field-release")
def openclaw_field_release(
    body: SensitiveFieldReleaseIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    return build_sensitive_field_release(
        field=body.field,
        value=body.value,
        purpose=body.purpose,
        task_id=body.task_id,
    )


@app.post("/api/tools/openclaw/jobs")
def openclaw_create_job(body: OpenClawJobIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        return enqueue_openclaw_execution_job(
            conn,
            packet=body.packet,
            guard=body.execution_guard,
            trace_id=body.trace_id,
            max_attempts=body.max_attempts,
            redis_obj=redis_client(),
        )


@app.get("/api/tools/openclaw/jobs/{job_id}")
def openclaw_job_status(job_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        job = fetch_openclaw_execution_job(conn, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="openclaw job not found")
        events = fetch_openclaw_execution_events(conn, job_id)
    return {"job": job, "events": events}


@app.post("/api/tools/openclaw/jobs/{job_id}/run-once")
def openclaw_job_run_once(job_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        return run_openclaw_execution_job_once(conn, job_id, redis_obj=redis_client())


@app.post("/api/tools/openclaw/execute")
def openclaw_execute(body: OpenClawExecuteIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    return execute_openclaw_task_packet(body.packet, body.execution_guard)


@app.get("/api/tools/composio/status")
def composio_status(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    return composio_status_payload()


@app.get("/api/integrations/composio/status")
def composio_integration_status(x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    payload = composio_status_payload()
    payload["user_id"] = current_composio_user_id()
    payload["readonly_toolkits"] = composio_readonly_toolkits()
    payload["write_toolkits"] = composio_write_toolkits()
    payload["auth_mode"] = "manual_connect_link"
    return payload


@app.post("/api/integrations/composio/connect/{toolkit_slug}")
def composio_connect_toolkit(
    toolkit_slug: str,
    session_kind: str = "",
    force: bool = False,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    return create_composio_connect_link(toolkit_slug, requested_kind=session_kind, force=force)


@app.get("/api/integrations/composio/callback", response_class=HTMLResponse)
def composio_connect_callback(
    toolkit: str = "",
    session_kind: str = "",
    status: str = "success",
) -> HTMLResponse:
    return HTMLResponse(composio_android_callback_html(toolkit, session_kind, status))


@app.get("/api/integrations/composio/toolkits")
def composio_toolkit_connections(
    session_kind: str = "readonly",
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    return sync_composio_toolkits(session_kind=session_kind)


@app.post("/api/integrations/composio/tools/execute")
def composio_tool_execute(
    body: ComposioToolExecuteIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    return execute_composio_tool_call(body)


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


def parse_uuid_or_new(value: Optional[str]) -> uuid.UUID:
    if value:
        try:
            return uuid.UUID(str(value))
        except ValueError:
            pass
    return uuid.uuid4()


def enqueue_raw_event(
    redis_obj: Any,
    event_id: uuid.UUID,
    ts: datetime,
    source: str,
    event_type: str,
    protected_raw_data: dict[str, Any],
) -> None:
    if redis_obj is None or not hasattr(redis_obj, "xadd"):
        return
    redis_obj.xadd(
        "events:raw",
        {
            "event_id": str(event_id),
            "timestamp": ts.isoformat(),
            "source": source,
            "event_type": event_type,
            "raw_data": json.dumps(protected_raw_data, ensure_ascii=False),
        },
    )


def insert_private_event(
    conn: psycopg.Connection,
    source: str,
    event_type: str,
    raw_data: dict[str, Any],
    ts: Optional[datetime] = None,
) -> tuple[uuid.UUID, datetime, dict[str, Any]]:
    event_id = uuid.uuid4()
    timestamp = ts or datetime.now(timezone.utc)
    protected_raw_data = protect_private_payload(raw_data)
    private_raw_data = encrypt_private_raw_data(raw_data)
    conn.execute(
        """
        INSERT INTO events (event_id, timestamp, source, event_type, raw_data, raw_data_private)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (event_id, timestamp, source, event_type, json.dumps(protected_raw_data), json.dumps(private_raw_data)),
    )
    return event_id, timestamp, protected_raw_data


def composio_execution_result_payload(execution: dict[str, Any]) -> Any:
    live_result = execution.get("live_result") if isinstance(execution, dict) else {}
    if isinstance(live_result, dict) and "result" in live_result:
        return live_result.get("result")
    return live_result


def extract_items_from_composio_result(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ["messages", "emails", "items", "data", "results"]:
            nested = value.get(key)
            if isinstance(nested, list):
                return nested
            if isinstance(nested, dict):
                extracted = extract_items_from_composio_result(nested)
                if extracted:
                    return extracted
        if "result" in value:
            return extract_items_from_composio_result(value.get("result"))
    return []


def list_from_message_field(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in text.split(",") if item.strip()]


def gmail_message_payload_from_composio(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {
            "message_id": "",
            "thread_id": "",
            "subject": "",
            "from": "",
            "to": [],
            "snippet": str(item),
            "body": str(item),
            "source_adapter": "composio:gmail",
            "raw": item,
        }
    message_id = str(item.get("message_id") or item.get("messageId") or item.get("id") or "").strip()
    thread_id = str(item.get("thread_id") or item.get("threadId") or item.get("thread") or "").strip()
    snippet = str(item.get("snippet") or item.get("preview") or item.get("summary") or "").strip()
    body = str(item.get("body") or item.get("text") or item.get("plain_text") or item.get("content") or snippet).strip()
    return {
        "message_id": message_id,
        "thread_id": thread_id,
        "subject": str(item.get("subject") or "").strip(),
        "from": str(item.get("from") or item.get("sender") or "").strip(),
        "to": list_from_message_field(item.get("to") or item.get("recipients")),
        "cc": list_from_message_field(item.get("cc")),
        "date": str(item.get("date") or item.get("received_at") or item.get("receivedAt") or "").strip(),
        "snippet": snippet,
        "body": body,
        "source_adapter": "composio:gmail",
        "raw": item,
    }


def persist_gmail_composio_messages(messages: list[Any]) -> list[dict[str, str]]:
    persisted: list[dict[str, str]] = []
    redis_obj = redis_client()
    with db() as conn:
        ensure_collector_event_allowed(conn, "gmail")
        for item in messages:
            raw_data = gmail_message_payload_from_composio(item)
            event_id, ts, protected_raw_data = insert_private_event(
                conn,
                "gmail",
                "gmail_message_snapshot",
                raw_data,
            )
            enqueue_raw_event(redis_obj, event_id, ts, "gmail", "gmail_message_snapshot", protected_raw_data)
            persisted.append({"event_id": str(event_id), "message_id": raw_data.get("message_id", "")})
    return persisted


def persist_assistant_turn(
    conn: psycopg.Connection,
    redis_obj: Any,
    role: str,
    content: str,
    conversation_id: Optional[str] = None,
    client_type: str = "web",
    suggestion_id: Optional[str] = None,
    tool_call_id: Optional[str] = None,
) -> dict[str, str]:
    if role not in {"user", "assistant", "system"}:
        raise ValueError("role must be user, assistant, or system")
    conversation_uuid = parse_uuid_or_new(conversation_id)
    turn_id = uuid.uuid4()
    raw_data = {
        "role": role,
        "content": content,
        "conversation_id": str(conversation_uuid),
        "client_type": client_type,
        "suggestion_id": suggestion_id,
        "tool_call_id": tool_call_id,
    }
    conn.execute(
        """
        INSERT INTO assistant_conversations (id, client_type, last_active_at, scope, status)
        VALUES (%s, %s, now(), %s, 'active')
        ON CONFLICT (id) DO UPDATE SET
          client_type = EXCLUDED.client_type,
          last_active_at = now(),
          status = 'active'
        """,
        (conversation_uuid, client_type, json.dumps({"source": "nomi_chat", "client_type": client_type})),
    )
    event_type = f"{role}_message"
    event_id, ts, protected_raw_data = insert_private_event(conn, "nomi_chat", event_type, raw_data)
    conn.execute(
        """
        INSERT INTO assistant_turns
          (id, conversation_id, role, content, event_id, suggestion_id, tool_call_id, created_at, finalized_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            turn_id,
            conversation_uuid,
            role,
            content,
            event_id,
            suggestion_id,
            tool_call_id,
            ts,
            ts if role == "assistant" else None,
        ),
    )
    enqueue_raw_event(redis_obj, event_id, ts, "nomi_chat", event_type, protected_raw_data)
    return {
        "conversation_id": str(conversation_uuid),
        "turn_id": str(turn_id),
        "event_id": str(event_id),
        "role": role,
    }


@app.post("/event")
def create_event(event: EventIn) -> dict[str, str]:
    ts = event.timestamp or datetime.now(timezone.utc)

    with db() as conn:
        ensure_collector_event_allowed(conn, event.source)
        event_id, ts, protected_raw_data = insert_private_event(conn, event.source, event.event_type, event.raw_data, ts)

    enqueue_raw_event(redis_client(), event_id, ts, event.source, event.event_type, protected_raw_data)
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


@app.post("/api/collectors/gmail/composio/fetch")
def gmail_composio_fetch(
    body: GmailComposioFetchIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    query = body.query.strip() or "newer_than:1d"
    execution = execute_composio_tool_call(
        ComposioToolExecuteIn(
            session_kind="readonly",
            toolkit_slug="gmail",
            tool_slug="GMAIL_FETCH_EMAILS",
            arguments={"query": query, "max_results": body.limit},
            task_id="collector:gmail:composio_fetch",
            step_id="gmail_composio_fetch",
        )
    )
    result_payload = composio_execution_result_payload(execution)
    messages = extract_items_from_composio_result(result_payload)
    persisted = persist_gmail_composio_messages(messages)
    return {
        "status": execution.get("status") or "completed",
        "source": "gmail",
        "adapter": "composio:gmail",
        "query": query,
        "fetched_count": len(messages),
        "persisted_count": len(persisted),
        "events": persisted,
        "tool_execution": {
            "status": execution.get("status"),
            "toolkit_slug": "gmail",
            "tool_slug": "GMAIL_FETCH_EMAILS",
        },
    }


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
        "assistant_dialogue": "Nomi 对话上下文：用户指令、纠正、偏好和任务反馈",
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


def load_context_tokenizer() -> Any:
    global _CONTEXT_TOKENIZER, _CONTEXT_TOKENIZER_BACKEND, _CONTEXT_TOKENIZER_LOAD_ATTEMPTED
    if _CONTEXT_TOKENIZER is not None:
        return _CONTEXT_TOKENIZER
    if _CONTEXT_TOKENIZER_LOAD_ATTEMPTED:
        return None
    _CONTEXT_TOKENIZER_LOAD_ATTEMPTED = True
    if CONTEXT_TOKENIZER_BACKEND in {"off", "none", "char", "conservative"}:
        _CONTEXT_TOKENIZER_BACKEND = "conservative_char_estimator"
        return None
    if not CONTEXT_TOKENIZER_MODEL:
        _CONTEXT_TOKENIZER_BACKEND = "conservative_char_estimator"
        return None
    try:
        from transformers import AutoTokenizer  # type: ignore

        _CONTEXT_TOKENIZER = AutoTokenizer.from_pretrained(CONTEXT_TOKENIZER_MODEL, trust_remote_code=True)
        _CONTEXT_TOKENIZER_BACKEND = f"hf:{CONTEXT_TOKENIZER_MODEL}"
        return _CONTEXT_TOKENIZER
    except Exception:
        _CONTEXT_TOKENIZER = None
        _CONTEXT_TOKENIZER_BACKEND = "conservative_char_estimator"
        return None


def context_tokenizer_backend() -> str:
    load_context_tokenizer()
    return str(_CONTEXT_TOKENIZER_BACKEND or "conservative_char_estimator")


def estimate_context_tokens(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, default=str)
    tokenizer = load_context_tokenizer()
    if tokenizer is not None:
        try:
            return max(1, len(tokenizer.encode(text, add_special_tokens=False)))
        except TypeError:
            return max(1, len(tokenizer.encode(text)))
        except Exception:
            pass
    cjk_chars = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    non_cjk_chars = len(text) - cjk_chars
    return max(1, cjk_chars + (non_cjk_chars + 3) // 4)


def truncate_text_by_token_budget(text: str, max_tokens: int) -> str:
    clean = str(text or "")
    if estimate_context_tokens(clean) <= max_tokens:
        return clean
    if max_tokens <= 8:
        return clean[: max(max_tokens, 1)]
    result: list[str] = []
    used = 0
    for char in clean:
        char_tokens = estimate_context_tokens(char)
        if used + char_tokens > max_tokens - 6:
            break
        result.append(char)
        used += char_tokens
    return "".join(result).rstrip() + "\n[truncated]"


def tail_text_by_token_budget(text: str, max_tokens: int) -> str:
    clean = str(text or "")
    if estimate_context_tokens(clean) <= max_tokens:
        return clean
    if max_tokens <= 8:
        return clean[-max(max_tokens, 1) :]
    result: list[str] = []
    used = 0
    for char in reversed(clean):
        char_tokens = estimate_context_tokens(char)
        if used + char_tokens > max_tokens - 6:
            break
        result.append(char)
        used += char_tokens
    return "[truncated]\n" + "".join(reversed(result)).lstrip()


def summarize_oversized_context_text(text: str, max_tokens: int) -> dict[str, Any]:
    original_tokens = estimate_context_tokens(text)
    summary_budget = max(24, max_tokens - 18)
    head_budget = max(8, summary_budget // 2)
    tail_budget = max(8, summary_budget - head_budget)
    head = truncate_text_by_token_budget(text, head_budget).replace("\n[truncated]", "")
    tail = tail_text_by_token_budget(text, tail_budget).replace("[truncated]\n", "")
    if tail and tail in head:
        body = head
    else:
        body = f"{head}\n...\n{tail}".strip()
    summarized = f"[summary]\n{body}\n[/summary]"
    if estimate_context_tokens(summarized) > max_tokens:
        summarized = truncate_text_by_token_budget(summarized, max_tokens)
    summary_tokens = estimate_context_tokens(summarized)
    return {
        "content": summarized,
        "summary_method": "extractive_provenance_summary",
        "original_token_estimate": original_tokens,
        "summary_token_estimate": summary_tokens,
        "omitted_token_estimate": max(0, original_tokens - summary_tokens),
    }


def source_id_for_context_item(item: dict[str, Any], fallback: str) -> str:
    for key in ("event_id", "id", "memory_id"):
        value = item.get(key)
        if value:
            return str(value)
    source_event_ids = item.get("source_event_ids") or []
    if source_event_ids:
        return str(source_event_ids[0])
    return fallback


def resolve_context_budget(context_budget: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    raw = context_budget or {}
    model_window = int(raw.get("model_window", CONTEXT_MODEL_WINDOW_TOKENS))
    output_reserved = int(raw.get("output_reserved", CONTEXT_OUTPUT_RESERVED_TOKENS))
    safety_reserved = int(raw.get("safety_reserved", CONTEXT_SAFETY_RESERVED_TOKENS))
    hard_input_ceiling = int(raw.get("hard_input_ceiling", CONTEXT_HARD_INPUT_CEILING_TOKENS))
    hard_input_ceiling = min(hard_input_ceiling, max(model_window - output_reserved - safety_reserved, 1))
    input_target = int(raw.get("input_target", CONTEXT_INPUT_TARGET_TOKENS))
    input_target = min(input_target, hard_input_ceiling)
    single_item_limit = int(raw.get("single_item_token_limit", CONTEXT_SINGLE_ITEM_TOKEN_LIMIT))
    single_item_limit = max(1, min(single_item_limit, hard_input_ceiling))
    return {
        "model_window": model_window,
        "output_reserved": output_reserved,
        "safety_reserved": safety_reserved,
        "input_target": input_target,
        "hard_input_ceiling": hard_input_ceiling,
        "single_item_token_limit": single_item_limit,
        "tokenizer_backend": context_tokenizer_backend(),
    }


def section_token_cap(budget: dict[str, int], section_name: str) -> int:
    target = max(int(budget.get("input_target", 1)), 1)
    fractions = {
        "current_request": 0.06,
        "same_conversation": 0.16,
        "source_context": 0.22,
        "task_context": 0.09,
        "agenda_context": 0.05,
        "kv_profile": 0.04,
        "knowledge_graph_context": 0.08,
        "rag_event_memory": 0.22,
        "memory_context": 0.04,
        "provenance": 0.04,
    }
    minimums = {
        "current_request": 4000,
        "same_conversation": 4000,
        "source_context": 4000,
        "task_context": 2000,
        "agenda_context": 2000,
        "kv_profile": 1000,
        "knowledge_graph_context": 2000,
        "rag_event_memory": 4000,
        "memory_context": 1000,
        "provenance": 1000,
    }
    cap = max(int(target * fractions.get(section_name, 0.1)), minimums.get(section_name, 1000))
    return min(cap, int(budget.get("hard_input_ceiling", target)))


def normalize_scope_values(values: Any) -> set[str]:
    if values is None:
        return set()
    if isinstance(values, str):
        values = [values]
    result: set[str] = set()
    for value in values or []:
        clean = str(value or "").strip().lower()
        if clean:
            result.add(clean)
    return result


def sorted_scope_values(values: Any) -> list[str]:
    return sorted(normalize_scope_values(values))


def normalize_counterparty_values(values: Any) -> set[str]:
    cleaned: set[str] = set()
    for value in normalize_scope_values(values):
        trimmed = re.sub(r"\s+(可以|需要|确认|好的|好|不用|不要|ok|yes)$", "", value).strip()
        if trimmed:
            cleaned.add(trimmed)
    return cleaned


def context_item_counterparties(item: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    values.extend(normalize_scope_values(item.get("counterparty_ids")))
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    scope = metadata.get("memory_scope") if isinstance(metadata.get("memory_scope"), dict) else {}
    if scope:
        values.extend(normalize_scope_values(scope.get("counterparty_ids")))
        values.extend(normalize_scope_values(scope.get("related_entities")))
        values.extend([scope.get("conversation_label"), scope.get("speaker")])
    raw_data = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
    if raw_data:
        values.extend([raw_data.get("chat_name"), raw_data.get("sender"), raw_data.get("speaker")])
    for key in ("subject", "object"):
        value = item.get(key)
        if value:
            values.append(value)
    return normalize_scope_values(values)


def context_item_scope_exclusion(
    item: dict[str, Any],
    request_scope: Optional[dict[str, Any]],
) -> Optional[str]:
    if not request_scope:
        return None
    allowed_counterparties = normalize_scope_values(request_scope.get("counterparty_ids"))
    item_counterparties = context_item_counterparties(item)
    if not allowed_counterparties or not item_counterparties:
        return None
    visibility = str(item.get("visibility_scope") or "").lower()
    sensitivity = str(item.get("sensitivity_level") or "").lower()
    protected_scope = visibility in {"contact_scoped", "thread_scoped", "private_third_party"} or sensitivity in {
        "high",
        "critical",
    }
    if protected_scope and allowed_counterparties.isdisjoint(item_counterparties):
        return (
            "Different contact scope: candidate counterparties "
            f"{sorted(item_counterparties)} not in request scope {sorted(allowed_counterparties)}"
        )
    return None


def parse_context_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def context_importance(item: dict[str, Any]) -> float:
    for key in ("importance", "confidence", "score", "rank"):
        value = item.get(key)
        try:
            if value is not None:
                return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            continue
    return 0.0


def score_context_item(
    query: str,
    item: dict[str, Any],
    section_name: str,
    request_scope: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    request_scope = request_scope or {}
    item_text = context_text(item)
    tokens = query_tokens(query)
    semantic_hits = sum(1 for token in tokens if token in item_text)
    semantic_score = min(1.0, semantic_hits / max(len(tokens), 1)) if tokens else 0.0

    allowed_counterparties = normalize_scope_values(request_scope.get("counterparty_ids"))
    item_counterparties = context_item_counterparties(item)
    if allowed_counterparties and item_counterparties:
        scope_score = 1.0 if not allowed_counterparties.isdisjoint(item_counterparties) else 0.0
    elif section_name in {"current_request", "same_conversation", "source_context", "task_context", "agenda_context"}:
        scope_score = 1.0
    else:
        scope_score = 0.45

    active_tokens = normalize_scope_values(request_scope.get("active_task_ids")) | normalize_scope_values(
        request_scope.get("topic_ids")
    )
    item_topics = normalize_scope_values(item.get("active_task_ids")) | normalize_scope_values(item.get("topic_ids"))
    active_task_score = 0.0
    if active_tokens:
        if active_tokens.intersection(item_topics):
            active_task_score = 1.0
        elif any(token and token in item_text for token in active_tokens):
            active_task_score = 0.7
    if section_name == "task_context":
        active_task_score = max(active_task_score, 0.8)

    timestamp = (
        parse_context_datetime(item.get("updated_at"))
        or parse_context_datetime(item.get("created_at"))
        or parse_context_datetime(item.get("time"))
        or parse_context_datetime(item.get("timestamp"))
    )
    recency_score = 0.0
    if timestamp:
        age_days = max((datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() / 86400, 0)
        recency_score = max(0.0, min(1.0, 1.0 / (1.0 + age_days / 30.0)))

    content = str(item.get("content") or item.get("summary") or item.get("value") or "")
    user_correction_score = 1.0 if any(marker in content for marker in ["不是", "别提醒", "不用提醒", "以后", "记住", "纠正"]) else 0.0
    sensitivity = str(item.get("sensitivity_level") or "").lower()
    risk_penalty = 0.25 if sensitivity in {"high", "critical"} else 0.0
    importance_score = context_importance(item)
    final_score = (
        semantic_score * 0.36
        + scope_score * 0.22
        + importance_score * 0.16
        + active_task_score * 0.14
        + recency_score * 0.08
        + user_correction_score * 0.04
        - risk_penalty
    )
    final_score = round(max(0.0, final_score), 6)
    reason_parts = []
    if semantic_score:
        reason_parts.append("query terms overlap")
    if active_task_score:
        reason_parts.append("matches active task or topic")
    if scope_score >= 1.0:
        reason_parts.append("inside active scope")
    if risk_penalty:
        reason_parts.append("risk penalty applied")
    return {
        "scope_score": round(scope_score, 6),
        "semantic_score": round(semantic_score, 6),
        "recency_score": round(recency_score, 6),
        "importance_score": round(importance_score, 6),
        "active_task_score": round(active_task_score, 6),
        "user_correction_score": round(user_correction_score, 6),
        "risk_penalty": round(risk_penalty, 6),
        "final_score": final_score,
        "reason": "; ".join(reason_parts) or "included by section priority and available budget",
    }


def score_context_candidates(
    query: str,
    items: list[dict[str, Any]],
    section_name: str,
    request_scope: Optional[dict[str, Any]] = None,
    sort_items: bool = True,
) -> list[dict[str, Any]]:
    scored: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(items):
        next_item = dict(item)
        score = score_context_item(query, next_item, section_name, request_scope)
        next_item["score"] = score
        next_item.setdefault("inclusion_reason", score["reason"])
        scored.append((index, next_item))
    if sort_items:
        scored.sort(key=lambda pair: (-float(pair[1]["score"]["final_score"]), pair[0]))
    return [item for _, item in scored]


def infer_request_scope(message: str, ui_state: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    ui_state = ui_state or {}
    policy = infer_memory_access_policy(message, explicit_context=ui_state)
    counterparties: set[str] = set()
    counterparties.update(normalize_counterparty_values(ui_state.get("counterparty_ids")))
    counterparties.update(normalize_counterparty_values(ui_state.get("counterparty_id")))
    counterparties.update(normalize_counterparty_values(ui_state.get("contact_id")))
    counterparties.update(normalize_counterparty_values(ui_state.get("contact_name")))
    counterparties.update(normalize_counterparty_values(policy.get("target_entities")))
    current_source = ui_state.get("current_source") if isinstance(ui_state.get("current_source"), dict) else {}
    if current_source:
        counterparties.update(normalize_counterparty_values(current_source.get("counterparty_ids")))
        counterparties.update(normalize_counterparty_values(current_source.get("counterparty_id")))
        counterparties.update(normalize_counterparty_values(current_source.get("contact_name")))
    source_type = str(ui_state.get("source_type") or current_source.get("source_type") or "").strip().lower()
    active_task_ids = sorted_scope_values(ui_state.get("active_task_ids") or ui_state.get("active_task_id"))
    topic_ids = sorted_scope_values(ui_state.get("topic_ids") or ui_state.get("topic_id"))
    return {
        "primary_scope": str(ui_state.get("primary_scope") or ("contact_scoped" if counterparties else "assistant_conversation")),
        "source_type": source_type,
        "conversation_id": str(ui_state.get("conversation_id") or current_source.get("conversation_id") or "").strip(),
        "counterparty_ids": sorted(counterparties),
        "active_task_ids": active_task_ids,
        "topic_ids": topic_ids,
        "output_context": policy.get("output_context"),
    }


def normalize_ui_state_source_context(
    ui_state: Optional[dict[str, Any]],
    request_scope: dict[str, Any],
) -> list[dict[str, Any]]:
    ui_state = ui_state or {}
    raw_items: list[dict[str, Any]] = []
    current_source = ui_state.get("current_source")
    if isinstance(current_source, dict):
        raw_items.append(current_source)
    source_context = ui_state.get("source_context")
    if isinstance(source_context, list):
        raw_items.extend([item for item in source_context if isinstance(item, dict)])
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items):
        content = str(item.get("content") or item.get("text") or item.get("summary") or "").strip()
        if not content and not item.get("raw_data"):
            continue
        normalized.append(
            {
                "layer": "current_source_thread",
                "source": "ui_state",
                "event_id": str(item.get("event_id") or f"ui-source-{index}"),
                "source_type": str(item.get("source_type") or request_scope.get("source_type") or "").strip().lower(),
                "conversation_id": str(item.get("conversation_id") or request_scope.get("conversation_id") or ""),
                "counterparty_ids": sorted_scope_values(item.get("counterparty_ids") or request_scope.get("counterparty_ids")),
                "content": truncate_text_by_token_budget(content or json.dumps(item.get("raw_data"), ensure_ascii=False), 4000),
            }
        )
    return normalized


def dedupe_context_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        source_id = source_id_for_context_item(item, f"context-{index}")
        if source_id in seen:
            continue
        seen.add(source_id)
        deduped.append(item)
    return deduped


def raw_source_counterparties(raw_data: dict[str, Any], request_scope: dict[str, Any]) -> list[str]:
    values: list[Any] = [
        raw_data.get("chat_name"),
        raw_data.get("sender"),
        raw_data.get("speaker"),
        raw_data.get("from"),
        raw_data.get("to"),
    ]
    scope_counterparties = request_scope.get("counterparty_ids")
    if isinstance(scope_counterparties, list):
        values.extend(scope_counterparties)
    elif scope_counterparties:
        values.append(scope_counterparties)
    return sorted_scope_values(values)


def raw_source_content(raw_data: dict[str, Any], summary: Any) -> str:
    parts: list[str] = []
    if summary:
        parts.append(str(summary))
    for key in ("text", "message", "body", "subject", "title"):
        value = raw_data.get(key)
        if value:
            parts.append(str(value))
    if not parts and raw_data:
        parts.append(json.dumps(raw_data, ensure_ascii=False, default=str))
    return "\n".join(list(dict.fromkeys(part.strip() for part in parts if part and part.strip())))


def retrieve_current_source_context(
    query: str,
    request_scope: dict[str, Any],
    limit: int = 6,
) -> list[dict[str, Any]]:
    source_type = str(request_scope.get("source_type") or "").strip().lower()
    if not source_type:
        return []
    patterns: list[str] = []
    conversation_id = str(request_scope.get("conversation_id") or "").strip()
    if conversation_id:
        patterns.append(f"%{conversation_id}%")
    for counterparty in sorted_scope_values(request_scope.get("counterparty_ids")):
        patterns.append(f"%{counterparty}%")
    patterns.extend(token_patterns(query, max_tokens=4))
    patterns = list(dict.fromkeys(patterns)) or ["%"]
    clauses = []
    params: list[Any] = [source_type]
    for pattern in patterns:
        clauses.append("(e.raw_data::text ILIKE %s OR COALESCE(s.summary, '') ILIKE %s)")
        params.extend([pattern, pattern])
    where = " OR ".join(clauses)
    try:
        with db() as conn:
            if not hasattr(conn, "execute"):
                return []
            rows = conn.execute(
                f"""
                SELECT e.event_id::text, e.source, e.event_type, e.raw_data, e.timestamp,
                       s.summary, s.intent, s.importance
                FROM events e
                LEFT JOIN semantic_events s ON s.event_id = e.event_id
                WHERE lower(e.source) = %s
                  AND ({where})
                ORDER BY e.timestamp DESC
                LIMIT %s
                """,
                (*params, limit),
            ).fetchall()
    except (psycopg.Error, AttributeError):
        return []
    items: list[dict[str, Any]] = []
    for row in rows:
        raw_data = row[3] if isinstance(row[3], dict) else {}
        content = raw_source_content(raw_data, row[5])
        if not content:
            continue
        items.append(
            {
                "layer": "current_source_thread",
                "source": "durable_events",
                "event_id": str(row[0]),
                "source_id": str(row[0]),
                "source_type": str(row[1]).lower(),
                "event_type": row[2],
                "timestamp": row[4].isoformat() if hasattr(row[4], "isoformat") else row[4],
                "content": truncate_text_by_token_budget(content, 4000),
                "counterparty_ids": raw_source_counterparties(raw_data, request_scope),
                "intent": row[6],
                "importance": row[7] or 0,
                "raw_data": raw_data,
                "inclusion_reason": "Durable current source/thread context matched active scope.",
            }
        )
    return items


def context_section_name_for_memory_item(item: dict[str, Any]) -> str:
    layer = str(item.get("layer") or "").lower()
    if layer == "working_memory":
        return "kv_profile"
    if layer == "entity_graph":
        return "knowledge_graph_context"
    if layer in {"vector_recall", "bm25_recall", "semantic_memory", "timeline"}:
        return "rag_event_memory"
    return "memory_context"


def retrieval_modes_for_pack(sections: list[dict[str, Any]]) -> dict[str, int]:
    modes: dict[str, int] = {}
    for section in sections:
        items = section.get("items") or []
        if items:
            modes[str(section.get("name") or "unknown")] = len(items)
    return modes


def pack_context_section(
    section_name: str,
    items: list[dict[str, Any]],
    budget: dict[str, int],
    warnings: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cap = section_token_cap(budget, section_name)
    single_item_limit = int(budget["single_item_token_limit"])
    packed: list[dict[str, Any]] = []
    used = 0
    for index, item in enumerate(items):
        source_id = source_id_for_context_item(item, f"{section_name}-{index}")
        next_item = dict(item)
        next_item.setdefault("source_id", source_id)
        score = next_item.get("score") if isinstance(next_item.get("score"), dict) else {}
        next_item.setdefault(
            "inclusion_reason",
            str(score.get("reason") or f"Included in {section_name} by scope, relevance, and token budget."),
        )
        content = next_item.get("content")
        if isinstance(content, str) and estimate_context_tokens(content) > single_item_limit:
            summary = summarize_oversized_context_text(content, single_item_limit)
            next_item["content"] = summary["content"]
            next_item["truncated"] = True
            next_item["summary_method"] = summary["summary_method"]
            next_item["original_token_estimate"] = summary["original_token_estimate"]
            next_item["summary_token_estimate"] = summary["summary_token_estimate"]
            next_item["omitted_token_estimate"] = summary["omitted_token_estimate"]
            warnings.append(
                {
                    "type": "summarized",
                    "source_id": source_id,
                    "section": section_name,
                    "reason": "Single item exceeded token budget and was summarized with provenance retained.",
                    "summary_method": summary["summary_method"],
                    "omitted_token_estimate": summary["omitted_token_estimate"],
                }
            )
        else:
            next_item.setdefault("truncated", False)
        token_count = estimate_context_tokens(next_item)
        if used + token_count > cap and packed:
            excluded.append(
                {
                    "source_id": source_id,
                    "section": section_name,
                    "reason": "Section token budget exceeded after higher-priority items were packed.",
                }
            )
            continue
        next_item["token_count"] = token_count
        packed.append(next_item)
        used += token_count
    return packed, {"name": section_name, "tokens_used": used, "items": packed}


def relevant_assistant_dialogue_items(
    query: str,
    assistant_context: list[dict[str, Any]],
    conversation_id: Optional[str] = None,
    limit: int = 64,
) -> list[dict[str, Any]]:
    tokens = set(query_tokens(query))
    is_short_followup = short_followup_query(query)
    selected: list[dict[str, Any]] = []
    for item in assistant_context:
        item_conversation_id = str(item.get("conversation_id") or "")
        content = str(item.get("content") or "")
        content_tokens = set(query_tokens(content))
        same_conversation = bool(conversation_id and item_conversation_id == str(conversation_id))
        from_client_context = item.get("source") in {"client_context", "client_context_delta"}
        is_user_correction = any(marker in content for marker in ["不是", "别提醒", "不用提醒", "以后", "记住", "纠正"])
        overlaps = bool(tokens and tokens.intersection(content_tokens))
        if same_conversation or overlaps or is_user_correction or (is_short_followup and from_client_context):
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def short_followup_query(query: str) -> bool:
    text = str(query or "").strip().lower()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    if len(compact) <= 12 and not query_tokens(text):
        return True
    markers = {
        "需要",
        "可以",
        "好的",
        "好",
        "要",
        "是",
        "确认",
        "继续",
        "不用",
        "不要",
        "yes",
        "ok",
        "sure",
        "go ahead",
    }
    return compact in markers


def normalize_client_dialogue_context(
    items: list[dict[str, Any]],
    conversation_id: Optional[str],
    limit: Optional[int] = None,
    current_message: Optional[str] = None,
    token_budget: Optional[int] = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    raw_items = list(items or [])
    if limit is not None:
        raw_items = raw_items[-limit:]
    current_clean = str(current_message or "").strip()
    used_tokens = 0
    for index, item in enumerate(raw_items):
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        if role == "user" and current_clean and content == current_clean:
            continue
        candidate = {
            "layer": "assistant_dialogue",
            "source": "client_context_delta",
            "event_id": f"client-context-{index}",
            "conversation_id": str(conversation_id or item.get("conversation_id") or "client-local"),
            "role": role,
            "content": truncate_text_by_token_budget(content, 1200),
        }
        candidate_tokens = estimate_context_tokens(candidate)
        if token_budget is not None and normalized and used_tokens + candidate_tokens > token_budget:
            continue
        candidate["token_count"] = candidate_tokens
        normalized.append(
            {
                **candidate,
            }
        )
        used_tokens += candidate_tokens
    return normalized


def agenda_item_matches_query(query: str, item: dict[str, Any]) -> bool:
    query_text = str(query or "").lower()
    item_text = json.dumps(item, ensure_ascii=False, default=str).lower()
    tokens = set(query_tokens(query_text))
    if tokens and any(token in item_text for token in tokens):
        return True

    time_pairs = [
        ("周日", ["周末", "周日", "星期天", "sunday"]),
        ("周六", ["周末", "周六", "星期六", "saturday"]),
        ("周末", ["周末", "周六", "周日", "weekend"]),
        ("明天", ["明天", "tomorrow"]),
        ("今天", ["今天", "today"]),
        ("今晚", ["今晚", "今天晚上", "tonight"]),
    ]
    for query_marker, item_markers in time_pairs:
        if query_marker in query_text and any(marker in item_text for marker in item_markers):
            return True

    participants = [str(value).lower() for value in item.get("participants") or []]
    if participants and any(participant and participant in query_text for participant in participants):
        return True

    is_fuzzy_followup = item.get("certainty") == "fuzzy" and bool(item.get("missing_fields"))
    if is_fuzzy_followup and any(marker in query_text for marker in ["就", "改", "可以", "不行", "确认", "取消"]):
        return True
    return False


def relevant_agenda_items(query: str, agenda_context: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in agenda_context:
        if str(item.get("status") or "scheduled") in {"done", "dismissed", "cancelled", "canceled"}:
            continue
        if agenda_item_matches_query(query, item):
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def retrieve_active_agenda_context(
    query: str,
    conversation_id: Optional[str] = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    try:
        with db() as conn:
            if not hasattr(conn, "execute"):
                return []
            rows = conn.execute(
                """
                SELECT id, type, title, status, certainty, time_window, place, participants,
                       missing_fields, needs_clarification, confidence, source_event_ids,
                       metadata, created_at, updated_at,
                       NULL AS operation, NULL AS reason, NULL AS version_created_at
                FROM agenda_items
                WHERE status NOT IN ('done', 'dismissed', 'cancelled', 'canceled')
                ORDER BY needs_clarification DESC, updated_at DESC
                LIMIT %s
                """,
                (max(limit * 4, 12),),
            ).fetchall()
    except (psycopg.Error, AttributeError):
        return []
    candidates = [agenda_item_from_row(row) for row in rows]
    return relevant_agenda_items(query, candidates, limit=limit)


def retrieve_active_task_context(
    query: str,
    conversation_id: Optional[str] = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    pattern = f"%{query}%"
    conversation_text = str(conversation_id or "")
    items: list[dict[str, Any]] = []
    try:
        with db() as conn:
            if not hasattr(conn, "execute"):
                return []
            suggestion_rows = conn.execute(
                """
                SELECT id, source_event_id, title, body, priority, status, metadata, created_at, updated_at
                FROM proactive_suggestions
                WHERE status = 'open'
                  AND (title ILIKE %s OR body ILIKE %s OR metadata::text ILIKE %s)
                ORDER BY priority DESC, created_at DESC
                LIMIT %s
                """,
                (pattern, pattern, f"%{conversation_text}%" if conversation_text else pattern, limit),
            ).fetchall()
            route_rows = conn.execute(
                """
                SELECT id, request, route_type, capability_id, pipeline_id, risk_permission,
                       confirmation_required, task_route_decision, openclaw_task_packet,
                       clarification, context_summary, created_at,
                       source_event_ids, conversation_id, suggestion_id, agenda_item_ids
                FROM task_route_traces
                WHERE conversation_id = %s
                   OR request ILIKE %s
                   OR context_summary::text ILIKE %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (conversation_text, pattern, pattern, limit),
            ).fetchall()
            execution_rows = conn.execute(
                """
                SELECT id, task_trace_id, request, route_type, capability_id, pipeline_id, status,
                       required_slots, resolved_slots, missing_slots, risk, execution_guard,
                       source_event_ids, conversation_id, suggestion_id, agenda_item_ids, result, created_at
                FROM pipeline_execution_results
                WHERE conversation_id = %s
                   OR request ILIKE %s
                   OR result::text ILIKE %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (conversation_text, pattern, pattern, limit),
            ).fetchall()
    except (psycopg.Error, AttributeError):
        return []

    for row in suggestion_rows:
        items.append(
            {
                "layer": "proactive_suggestion",
                "event_id": str(row[1]) if row[1] else str(row[0]),
                "suggestion_id": str(row[0]),
                "title": row[2],
                "content": row[3],
                "priority": row[4],
                "status": row[5],
                "metadata": row[6] or {},
                "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else row[7],
                "inclusion_reason": "Open proactive suggestion relevant to current conversation or query.",
            }
        )
    for row in route_rows:
        items.append(
            {
                "layer": "task_trace",
                "event_id": str(row[0]),
                "trace_id": str(row[0]),
                "request": row[1],
                "route_type": row[2],
                "capability_id": row[3],
                "pipeline_id": row[4],
                "risk_permission": row[5],
                "confirmation_required": bool(row[6]),
                "source_event_ids": [str(item) for item in (row[12] or [])],
                "conversation_id": str(row[13]) if row[13] else None,
                "suggestion_id": str(row[14]) if row[14] else None,
                "agenda_item_ids": [str(item) for item in (row[15] or [])],
                "inclusion_reason": "Recent task routing trace relevant to current conversation or query.",
            }
        )
    for row in execution_rows:
        items.append(
            {
                "layer": "pipeline_execution",
                "event_id": str(row[0]),
                "execution_id": str(row[0]),
                "task_trace_id": str(row[1]) if row[1] else None,
                "request": row[2],
                "route_type": row[3],
                "capability_id": row[4],
                "pipeline_id": row[5],
                "status": row[6],
                "resolved_slots": row[8] or {},
                "missing_slots": row[9] or [],
                "source_event_ids": [str(item) for item in (row[12] or [])],
                "conversation_id": str(row[13]) if row[13] else None,
                "suggestion_id": str(row[14]) if row[14] else None,
                "agenda_item_ids": [str(item) for item in (row[15] or [])],
                "result": row[16] or {},
                "inclusion_reason": "Recent pipeline execution result relevant to current conversation or query.",
            }
        )
    return items[:limit]


def collect_context_ids(items: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in items:
        event_id = item.get("event_id")
        if event_id:
            ids.append(str(event_id))
        for source_id in item.get("source_event_ids") or []:
            ids.append(str(source_id))
    return list(dict.fromkeys(ids))


def build_context_pack(
    message: str,
    base_context: list[dict[str, Any]],
    assistant_context: Optional[list[dict[str, Any]]] = None,
    conversation_id: Optional[str] = None,
    agenda_context: Optional[list[dict[str, Any]]] = None,
    source_context: Optional[list[dict[str, Any]]] = None,
    task_context: Optional[list[dict[str, Any]]] = None,
    max_dialogue_items: int = 64,
    context_budget: Optional[dict[str, Any]] = None,
    request_scope: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    budget = resolve_context_budget(context_budget)
    assistant_context = assistant_context or []
    agenda_context = agenda_context or []
    source_context = source_context or []
    task_context = task_context or []
    request_scope = request_scope or {}
    selected_dialogue = relevant_assistant_dialogue_items(
        message,
        assistant_context,
        conversation_id=conversation_id,
        limit=max_dialogue_items,
    )
    session_search = build_session_search_context(
        current_message=message,
        conversation_id=str(conversation_id) if conversation_id else None,
        turns=assistant_context,
        active_tasks=task_context,
        token_budget=section_token_cap(budget, "same_conversation"),
        token_estimator=estimate_context_tokens,
    )
    if session_search["short_reply_resolution"]["resolved"]:
        selected_by_id = {str(item.get("turn_id") or item.get("event_id")): item for item in selected_dialogue}
        for item in session_search.get("included_turns", []):
            key = str(item.get("turn_id") or item.get("event_id"))
            if key not in selected_by_id:
                selected_dialogue.append({**item, "layer": "assistant_dialogue", "source": "session_search"})
                selected_by_id[key] = item
    selected_agenda = relevant_agenda_items(message, agenda_context, limit=6)
    excluded: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    scoped_memory: list[dict[str, Any]] = []
    for index, item in enumerate(base_context):
        source_id = source_id_for_context_item(item, f"memory-{index}")
        exclusion_reason = context_item_scope_exclusion(item, request_scope)
        if exclusion_reason:
            excluded.append({"source_id": source_id, "section": "memory_context", "reason": exclusion_reason})
            continue
        scoped_memory.append(item)

    current_request_item = {
        "source_id": "current-request",
        "layer": "current_request",
        "role": "user",
        "content": truncate_text_by_token_budget(message, min(16000, budget["single_item_token_limit"])),
        "inclusion_reason": "Always included as the active user request.",
    }
    packed_request, request_section = pack_context_section(
        "current_request",
        score_context_candidates(message, [current_request_item], "current_request", request_scope),
        budget,
        warnings,
        excluded,
    )
    packed_dialogue, dialogue_section = pack_context_section(
        "same_conversation",
        score_context_candidates(message, selected_dialogue, "same_conversation", request_scope, sort_items=False),
        budget,
        warnings,
        excluded,
    )
    packed_source, source_section = pack_context_section(
        "source_context",
        score_context_candidates(message, source_context, "source_context", request_scope),
        budget,
        warnings,
        excluded,
    )
    packed_task, task_section = pack_context_section(
        "task_context",
        score_context_candidates(message, task_context, "task_context", request_scope),
        budget,
        warnings,
        excluded,
    )
    packed_agenda, agenda_section = pack_context_section(
        "agenda_context",
        score_context_candidates(message, selected_agenda, "agenda_context", request_scope),
        budget,
        warnings,
        excluded,
    )
    memory_sections: list[dict[str, Any]] = []
    packed_memory: list[dict[str, Any]] = []
    for section_name in ["kv_profile", "knowledge_graph_context", "rag_event_memory", "memory_context"]:
        section_items = [item for item in scoped_memory if context_section_name_for_memory_item(item) == section_name]
        section_items = score_context_candidates(message, section_items, section_name, request_scope)
        packed_items, section = pack_context_section(section_name, section_items, budget, warnings, excluded)
        packed_memory.extend(packed_items)
        memory_sections.append(section)
    sections = [request_section, dialogue_section, source_section, task_section, agenda_section] + memory_sections
    input_used = sum(int(section.get("tokens_used") or 0) for section in sections)
    included_event_ids = (
        collect_context_ids(packed_request)
        + collect_context_ids(packed_dialogue)
        + collect_context_ids(packed_source)
        + collect_context_ids(packed_task)
        + collect_context_ids(packed_memory)
        + collect_context_ids(packed_agenda)
    )
    included_event_ids = list(dict.fromkeys(included_event_ids))
    included_memory_ids = [
        source_id_for_context_item(item, f"memory-{index}") for index, item in enumerate(packed_memory)
    ]
    included_agenda_ids = [str(item.get("id")) for item in packed_agenda if item.get("id")]
    return {
        "query": message,
        "context_pack_id": f"ctx_{uuid.uuid4().hex}",
        "conversation_id": conversation_id,
        "request_scope": request_scope,
        "current_request": packed_request,
        "memory_context": packed_memory,
        "assistant_dialogue": packed_dialogue,
        "source_context": packed_source,
        "task_context": packed_task,
        "agenda_context": packed_agenda,
        "included_event_ids": included_event_ids,
        "included_memory_ids": list(dict.fromkeys(included_memory_ids)),
        "included_agenda_ids": list(dict.fromkeys(included_agenda_ids)),
        "token_budget": {**budget, "input_used": input_used},
        "sections": sections,
        "excluded": excluded,
        "warnings": warnings,
        "retrieval_modes": retrieval_modes_for_pack(sections),
        "scope_filters_applied": request_scope,
        "session_search": session_search,
        "fallback_modes": {
            "tokenizer": "conservative_char_estimator"
            if str(budget.get("tokenizer_backend")) == "conservative_char_estimator"
            else None
        },
        "reason": "bounded context pack: active conversation, relevant assistant dialogue, active agenda, scoped memory, and source ids",
    }


def retrieve_assistant_dialogue_context(
    query: str,
    conversation_id: Optional[str] = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    patterns = token_patterns(query, max_tokens=4)
    conditions = []
    params: list[Any] = []
    if conversation_id:
        try:
            conversation_uuid = uuid.UUID(str(conversation_id))
            conditions.append("t.conversation_id = %s")
            params.append(conversation_uuid)
        except ValueError:
            pass
    for pattern in patterns:
        conditions.append("t.content ILIKE %s")
        params.append(pattern)
    where = f"WHERE {' OR '.join(conditions)}" if conditions else ""
    try:
        with db() as conn:
            rows = conn.execute(
                f"""
                SELECT t.event_id, t.conversation_id, t.role, t.content, t.created_at, e.raw_data
                FROM assistant_turns t
                LEFT JOIN events e ON e.event_id = t.event_id
                {where}
                ORDER BY t.created_at DESC
                LIMIT %s
                """,
                (*params, limit),
            ).fetchall()
    except psycopg.Error:
        return []
    return [
        {
            "layer": "assistant_dialogue",
            "event_id": str(row[0]),
            "conversation_id": str(row[1]),
            "role": row[2],
            "content": row[3],
            "created_at": row[4].isoformat() if hasattr(row[4], "isoformat") else row[4],
            "raw_data": row[5] or {},
        }
        for row in rows
    ]


def transient_assistant_turn(role: str, conversation_id: Optional[str] = None) -> dict[str, str]:
    conversation_uuid = parse_uuid_or_new(conversation_id)
    return {
        "conversation_id": str(conversation_uuid),
        "turn_id": str(uuid.uuid4()),
        "event_id": str(uuid.uuid4()),
        "role": role,
        "persisted": "false",
    }


def persist_context_snapshot(
    conn: psycopg.Connection,
    event_id: str,
    context_type: str,
    context_pack: dict[str, Any],
) -> None:
    conn.execute(
        """
        INSERT INTO context_snapshots
          (id, event_id, context_type, included_event_ids, included_memory_ids, included_agenda_ids, reason, payload)
        VALUES (%s, %s, %s, %s::TEXT[], %s::TEXT[], %s::TEXT[], %s, %s)
        """,
        (
            uuid.uuid4(),
            event_id,
            context_type,
            [str(item) for item in context_pack.get("included_event_ids") or []],
            [str(item) for item in context_pack.get("included_memory_ids") or []],
            [str(item) for item in context_pack.get("included_agenda_ids") or []],
            str(context_pack.get("reason") or ""),
            json.dumps(context_pack, ensure_ascii=False, default=str),
        ),
    )


def retrieve_context(query: str, limit: int, request_scope: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
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
    policy = infer_memory_access_policy(query, explicit_context=request_scope or {})
    scoped_context = filter_context_by_memory_access_policy(context, policy)
    return rerank_context(query, scoped_context)[: max(limit, 1)]


@app.post("/api/chat")
async def chat(body: ChatIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    redis_obj = redis_client()
    with db() as conn:
        user_turn = persist_assistant_turn(
            conn,
            redis_obj,
            role="user",
            content=body.message,
            conversation_id=body.conversation_id,
            client_type=body.client_type,
        )
    request_scope = infer_request_scope(body.message, body.ui_state)
    source_context = dedupe_context_items(
        normalize_ui_state_source_context(body.ui_state, request_scope)
        + retrieve_current_source_context(body.message, request_scope, limit=6)
    )
    context_candidate_limit = max(body.limit, 80)
    context = retrieve_context(body.message, context_candidate_limit, request_scope=request_scope)
    assistant_context = retrieve_assistant_dialogue_context(
        body.message,
        conversation_id=user_turn["conversation_id"],
        limit=64,
    )
    raw_client_delta = body.client_context_delta or body.client_context
    client_dialogue_context = normalize_client_dialogue_context(
        raw_client_delta,
        user_turn["conversation_id"],
        current_message=body.message,
        token_budget=8000,
    )
    agenda_context = retrieve_active_agenda_context(
        body.message,
        conversation_id=user_turn["conversation_id"],
        limit=6,
    )
    task_context = retrieve_active_task_context(
        body.message,
        conversation_id=user_turn["conversation_id"],
        limit=8,
    )
    context_pack = build_context_pack(
        body.message,
        context,
        assistant_context=client_dialogue_context + assistant_context,
        conversation_id=user_turn["conversation_id"],
        agenda_context=agenda_context,
        source_context=source_context,
        task_context=task_context,
        request_scope=request_scope,
        context_budget={"input_target": CONTEXT_INPUT_TARGET_TOKENS, "hard_input_ceiling": CONTEXT_HARD_INPUT_CEILING_TOKENS},
    )
    messages = build_chat_messages(body.message, context_pack)
    try:
        answer_result = await model_gateway().chat(messages)
        answer = answer_result.text
        context_pack["model_provider_id"] = answer_result.provider_id
        context_pack["model_trace"] = answer_result.trace
    except ModelGatewayError as exc:
        try:
            with db() as conn:
                safe_persist_model_request_trace(
                    conn,
                    task_class="chat",
                    selected_provider_id="",
                    status="failed",
                    error_type="model_unavailable",
                    user_visible_message=exc.to_payload()["message"],
                    context_snapshot_id=context_pack.get("context_pack_id"),
                    input_token_estimate=(context_pack.get("token_budget") or {}).get("input_used"),
                    payload=exc.to_payload(),
                )
        except psycopg.Error:
            pass
        raise HTTPException(
            status_code=503,
            detail=exc.to_payload(),
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "model_timeout",
                "message": "The model endpoint did not respond before the configured timeout.",
            },
        ) from exc
    with db() as conn:
        assistant_turn = persist_assistant_turn(
            conn,
            redis_obj,
            role="assistant",
            content=answer,
            conversation_id=user_turn["conversation_id"],
            client_type=body.client_type,
        )
        safe_persist_model_request_trace(
            conn,
            task_class="chat",
            selected_provider_id=answer_result.provider_id,
            status="succeeded",
            fallback_provider_ids=model_trace_fallbacks(answer_result.trace),
            context_snapshot_id=context_pack.get("context_pack_id"),
            input_token_estimate=(context_pack.get("token_budget") or {}).get("input_used"),
            output_token_estimate=estimate_context_tokens(answer),
            payload={"trace": answer_result.trace, "conversation_id": user_turn["conversation_id"]},
        )
    context_pack["final_model_answer_event_id"] = assistant_turn["event_id"]
    context_pack["final_model_answer_turn_id"] = assistant_turn["turn_id"]
    with db() as conn:
        persist_context_snapshot(conn, user_turn["event_id"], "chat_response", context_pack)
    return {
        "answer": answer,
        "sources": decorate_context_sources(context),
        "conversation_id": user_turn["conversation_id"],
        "context_pack": {
            "included_event_ids": context_pack["included_event_ids"],
            "included_memory_ids": context_pack.get("included_memory_ids", []),
            "included_agenda_ids": context_pack.get("included_agenda_ids", []),
            "assistant_dialogue_count": len(context_pack.get("assistant_dialogue", [])),
            "agenda_context_count": len(context_pack.get("agenda_context", [])),
            "memory_context_count": len(context_pack.get("memory_context", [])),
            "source_context_count": len(context_pack.get("source_context", [])),
            "task_context_count": len(context_pack.get("task_context", [])),
            "token_budget": context_pack.get("token_budget", {}),
            "sections": [
                {
                    "name": section.get("name"),
                    "tokens_used": section.get("tokens_used", 0),
                    "item_count": len(section.get("items") or []),
                }
                for section in context_pack.get("sections", [])
            ],
            "excluded": context_pack.get("excluded", []),
            "warnings": context_pack.get("warnings", []),
            "context_pack_id": context_pack.get("context_pack_id"),
            "retrieval_modes": context_pack.get("retrieval_modes", {}),
            "scope_filters_applied": context_pack.get("scope_filters_applied", {}),
            "reason": context_pack["reason"],
        },
    }


@app.post("/api/chat/messages")
async def chat_messages(body: ChatIn, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    return await chat(body, x_par_password=x_par_password)


@app.get("/api/chat/history")
def chat_history(
    x_par_password: Optional[str] = Header(default=None),
    conversation_id: Optional[str] = None,
    limit: int = Query(default=80, ge=1, le=200),
) -> dict[str, Any]:
    require_password(x_par_password)
    conversation_uuid: Optional[uuid.UUID] = None
    if conversation_id:
        try:
            conversation_uuid = uuid.UUID(str(conversation_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid conversation_id") from exc
    with db() as conn:
        if conversation_uuid is None:
            latest_row = conn.execute(
                """
                SELECT conversation_id FROM assistant_turns
                WHERE role IN ('user', 'assistant')
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (1,),
            ).fetchone()
            if not latest_row:
                return {"conversation_id": None, "messages": []}
            conversation_uuid = latest_row[0]
        rows = conn.execute(
            """
            SELECT id, conversation_id, role, content, event_id, suggestion_id, tool_call_id,
                   created_at, finalized_at
            FROM (
                SELECT id, conversation_id, role, content, event_id, suggestion_id, tool_call_id,
                       created_at, finalized_at
                FROM assistant_turns
                WHERE conversation_id = %s
                  AND role IN ('user', 'assistant')
                ORDER BY created_at DESC
                LIMIT %s
            ) recent_turns
            ORDER BY created_at ASC
            """,
            (conversation_uuid, limit),
        ).fetchall()
    return {
        "conversation_id": str(conversation_uuid),
        "messages": [row_to_assistant_turn(row) for row in rows],
    }


def build_chat_messages(message: str, context: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, str]]:
    context_text = json.dumps(context, ensure_ascii=False, default=str)
    return [
        {
            "role": "system",
            "content": (
                "你是用户的私有个人助理。你只能基于给定的个人上下文和用户消息回答。"
                "如果证据不足，明确说明不确定。不要编造私人事实。回答要简洁、可执行。"
                "当用户要回复某个联系人、发消息或写邮件时，不能泄露第三方私下评价、抱怨、负面观点或敏感信息。"
                "如果某条上下文只适合用户私下分析，不要把它写进对外回复草稿。"
                "上下文可能包含 bounded context pack；优先使用相关的 Nomi 对话纠正、用户偏好和当前任务，但不要使用无关对话。"
                "当用户只回复“需要、可以、好的、确认、yes、ok”等短句时，必须结合 assistant_dialogue 中最近的 Nomi 提问判断指代。"
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
                await stream_chat_to_websocket(
                    websocket,
                    str(data.get("message") or ""),
                    int(data.get("limit") or 12),
                    conversation_id=data.get("conversation_id"),
                    client_type=str(data.get("client_type") or "realtime"),
                )
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "error", "message": "unsupported realtime message type"})
    except WebSocketDisconnect:
        return
    finally:
        redis_task.cancel()


@app.websocket("/ws/voice")
async def websocket_voice(websocket: WebSocket, password: Optional[str] = None):
    await handle_voice_websocket(websocket, password)


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


async def stream_chat_to_websocket(
    websocket: WebSocket,
    message: str,
    limit: int,
    conversation_id: Optional[str] = None,
    client_type: str = "realtime",
) -> None:
    if not message.strip():
        await websocket.send_json({"type": "error", "message": "message is required"})
        return
    redis_obj = redis_client()
    try:
        with db() as conn:
            user_turn = persist_assistant_turn(
                conn,
                redis_obj,
                role="user",
                content=message,
                conversation_id=conversation_id,
                client_type=client_type,
            )
    except psycopg.Error:
        user_turn = transient_assistant_turn("user", conversation_id)
    request_scope = infer_request_scope(message, {})
    source_context = retrieve_current_source_context(message, request_scope, limit=6)
    context = retrieve_context(message, max(80, min(limit, 50)), request_scope=request_scope)
    assistant_context = retrieve_assistant_dialogue_context(message, conversation_id=user_turn["conversation_id"], limit=64)
    agenda_context = retrieve_active_agenda_context(message, conversation_id=user_turn["conversation_id"], limit=6)
    task_context = retrieve_active_task_context(message, conversation_id=user_turn["conversation_id"], limit=8)
    context_pack = build_context_pack(
        message,
        context,
        assistant_context=assistant_context,
        conversation_id=user_turn["conversation_id"],
        agenda_context=agenda_context,
        source_context=source_context,
        task_context=task_context,
        request_scope=request_scope,
        context_budget={"input_target": CONTEXT_INPUT_TARGET_TOKENS, "hard_input_ceiling": CONTEXT_HARD_INPUT_CEILING_TOKENS},
    )
    messages = build_chat_messages(message, context_pack)
    answer_parts: list[str] = []
    try:
        provider_id = ""
        model_trace: dict[str, Any] = {}
        async for chunk in model_gateway().stream_chat(messages):
            delta = chunk.delta
            provider_id = chunk.provider_id
            model_trace = chunk.trace
            if not delta:
                continue
            answer_parts.append(delta)
            await websocket.send_json({"type": "chat_delta", "delta": delta})
        if provider_id:
            context_pack["model_provider_id"] = provider_id
            context_pack["model_trace"] = model_trace
    except ModelGatewayError as exc:
        payload = exc.to_payload()
        try:
            with db() as conn:
                safe_persist_model_request_trace(
                    conn,
                    task_class="websocket_chat",
                    selected_provider_id="",
                    status="failed",
                    error_type="model_unavailable",
                    user_visible_message=payload["message"],
                    context_snapshot_id=context_pack.get("context_pack_id"),
                    input_token_estimate=(context_pack.get("token_budget") or {}).get("input_used"),
                    payload=payload,
                )
        except psycopg.Error:
            pass
        await websocket.send_json({"type": "error", "message": payload["message"], "detail": payload})
        return
    except Exception:
        await websocket.send_json({"type": "error", "message": "模型服务暂时不可用，请稍后重试。"})
        return
    answer = "".join(answer_parts)
    if not answer.strip():
        await websocket.send_json({"type": "error", "message": "模型没有返回内容，请稍后重试。"})
        return
    try:
        with db() as conn:
            assistant_turn = persist_assistant_turn(
                conn,
                redis_obj,
                role="assistant",
                content=answer,
                conversation_id=user_turn["conversation_id"],
                client_type=client_type,
            )
            context_pack["final_model_answer_event_id"] = assistant_turn["event_id"]
            context_pack["final_model_answer_turn_id"] = assistant_turn["turn_id"]
            persist_context_snapshot(conn, user_turn["event_id"], "websocket_chat_response", context_pack)
            safe_persist_model_request_trace(
                conn,
                task_class="websocket_chat",
                selected_provider_id=context_pack.get("model_provider_id") or "",
                status="succeeded",
                fallback_provider_ids=model_trace_fallbacks(context_pack.get("model_trace") or {}),
                context_snapshot_id=context_pack.get("context_pack_id"),
                input_token_estimate=(context_pack.get("token_budget") or {}).get("input_used"),
                output_token_estimate=estimate_context_tokens(answer),
                payload={"trace": context_pack.get("model_trace") or {}, "conversation_id": user_turn["conversation_id"]},
            )
    except psycopg.Error:
        pass
    await websocket.send_json(
        {
            "type": "chat_done",
            "answer": answer,
            "conversation_id": user_turn["conversation_id"],
            "sources": decorate_context_sources(context),
            "context_pack": {
                "included_event_ids": context_pack["included_event_ids"],
                "included_memory_ids": context_pack.get("included_memory_ids", []),
                "included_agenda_ids": context_pack.get("included_agenda_ids", []),
                "assistant_dialogue_count": len(context_pack.get("assistant_dialogue", [])),
                "agenda_context_count": len(context_pack.get("agenda_context", [])),
                "memory_context_count": len(context_pack.get("memory_context", [])),
                "source_context_count": len(context_pack.get("source_context", [])),
                "task_context_count": len(context_pack.get("task_context", [])),
                "token_budget": context_pack.get("token_budget", {}),
                "sections": [
                    {
                        "name": section.get("name"),
                        "tokens_used": section.get("tokens_used", 0),
                        "item_count": len(section.get("items") or []),
                    }
                    for section in context_pack.get("sections", [])
                ],
                "excluded": context_pack.get("excluded", []),
                "warnings": context_pack.get("warnings", []),
                "context_pack_id": context_pack.get("context_pack_id"),
                "retrieval_modes": context_pack.get("retrieval_modes", {}),
                "scope_filters_applied": context_pack.get("scope_filters_applied", {}),
                "reason": context_pack["reason"],
            },
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


@app.get("/api/agenda")
def agenda_items(
    x_par_password: Optional[str] = Header(default=None),
    status: Optional[str] = None,
    certainty: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
) -> dict[str, Any]:
    require_password(x_par_password)
    bounded_limit = max(1, min(limit, 100))
    with db() as conn:
        items = fetch_agenda_items(
            conn,
            status=status,
            certainty=certainty,
            source=source,
            limit=bounded_limit,
        )
    return {
        "filters": {"status": status, "certainty": certainty, "source": source, "limit": bounded_limit},
        "items": items,
    }


@app.patch("/api/agenda/{agenda_id}")
def patch_agenda_item(
    agenda_id: str,
    body: AgendaPatchIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        return update_agenda_item_with_version(conn, agenda_id, body)


@app.post("/api/agenda/{agenda_id}/snooze")
def snooze_agenda_item(
    agenda_id: str,
    body: AgendaSnoozeIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        return snooze_agenda_item_with_version(conn, agenda_id, body)


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


@app.get("/api/proactive/suggestions")
def proactive_suggestions(x_par_password: Optional[str] = Header(default=None), limit: int = 20) -> dict[str, Any]:
    return {"items": suggestions(x_par_password=x_par_password, limit=limit)}


@app.post("/api/proactive/suggestions/{suggestion_id}/action")
def proactive_suggestion_action(
    suggestion_id: str,
    body: SuggestionActionIn,
    x_par_password: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    require_password(x_par_password)
    with db() as conn:
        suggestion = fetch_suggestion_for_action(conn, suggestion_id)
        if not suggestion:
            raise HTTPException(status_code=404, detail="suggestion not found")
        feedback_id = record_user_feedback(
            conn,
            suggestion_id=suggestion_id,
            action=body.action_id,
            reason=body.reason,
            rating=body.rating,
            metadata={
                **body.metadata,
                "source_event_id": suggestion.get("source_event_id"),
                "suggestion_title": suggestion.get("title"),
            },
        )
        route_request = build_suggestion_action_route_request(suggestion, body.action_id)
        response: dict[str, Any] = {
            "suggestion_id": suggestion_id,
            "action_id": body.action_id,
            "feedback_id": feedback_id,
            "feedback_recorded": True,
        }
        if route_request:
            route_result = route_tool_request(
                route_request,
                {
                    "suggestion_id": suggestion_id,
                    "source_event_ids": [suggestion["source_event_id"]] if suggestion.get("source_event_id") else [],
                    "action_id": body.action_id,
                    "suggestion": {
                        "title": suggestion.get("title"),
                        "body": suggestion.get("body"),
                        "metadata": suggestion.get("metadata") or {},
                    },
                },
            )
            persist_task_route_trace(conn, route_result)
            response["route_result"] = route_result
        else:
            response["local_result"] = apply_suggestion_local_action(conn, suggestion_id, body)
        return response


@app.get("/api/events/{event_id}/trace")
def event_trace(event_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    pattern = f"%{event_id}%"
    with db() as conn:
        event_row = conn.execute(
            """
            SELECT event_id, source, event_type, raw_data, timestamp
            FROM events
            WHERE event_id = %s
            """,
            (event_id,),
        ).fetchone()
        if not event_row:
            raise HTTPException(status_code=404, detail="event not found")
        semantic_row = conn.execute(
            """
            SELECT id, intent, entities, importance, summary, model_version
            FROM semantic_events
            WHERE event_id = %s
            """,
            (event_id,),
        ).fetchone()
        memory_rows = conn.execute(
            """
            SELECT id, content, metadata
            FROM memory_vectors
            WHERE event_id = %s
            """,
            (event_id,),
        ).fetchall()
        fact_rows = conn.execute(
            """
            SELECT id, subject, predicate, object, confidence, source_event_ids, metadata
            FROM facts
            WHERE %s = ANY(source_event_ids)
            ORDER BY confidence DESC, updated_at DESC
            """,
            (event_id,),
        ).fetchall()
        agenda_rows = conn.execute(
            """
            SELECT a.id, a.type, a.title, a.status, a.certainty, a.time_window, a.place, a.participants,
                   a.missing_fields, a.needs_clarification, a.confidence, a.source_event_ids,
                   a.metadata, a.created_at, a.updated_at,
                   latest.operation, latest.reason, latest.created_at
            FROM agenda_items a
            LEFT JOIN LATERAL (
              SELECT operation, reason, created_at
              FROM agenda_item_versions
              WHERE agenda_item_id = a.id
              ORDER BY created_at DESC
              LIMIT 1
            ) latest ON TRUE
            WHERE %s = ANY(a.source_event_ids)
            ORDER BY a.updated_at DESC
            """,
            (event_id,),
        ).fetchall()
        agenda_version_rows = conn.execute(
            """
            SELECT id, agenda_item_id, operation, previous_value, new_value, reason,
                   source_event_ids, confidence, created_at
            FROM agenda_item_versions
            WHERE %s = ANY(source_event_ids)
            ORDER BY created_at DESC
            """,
            (event_id,),
        ).fetchall()
        suggestion_rows = conn.execute(
            """
            SELECT id, source_event_id, title, body, priority, status, metadata, created_at, updated_at
            FROM proactive_suggestions
            WHERE source_event_id = %s
            ORDER BY created_at DESC
            """,
            (event_id,),
        ).fetchall()
        route_rows = conn.execute(
            """
            SELECT id, request, route_type, capability_id, pipeline_id, risk_permission,
                   confirmation_required, task_route_decision, openclaw_task_packet,
                   clarification, context_summary, created_at,
                   source_event_ids, conversation_id, suggestion_id, agenda_item_ids
            FROM task_route_traces
            WHERE %s = ANY(source_event_ids)
               OR context_summary::text ILIKE %s
               OR task_route_decision::text ILIKE %s
               OR COALESCE(openclaw_task_packet::text, '') ILIKE %s
            ORDER BY created_at DESC
            """,
            (event_id, pattern, pattern, pattern),
        ).fetchall()
        pipeline_execution_rows = conn.execute(
            """
            SELECT id, task_trace_id, request, route_type, capability_id, pipeline_id, status,
                   required_slots, resolved_slots, missing_slots, risk, execution_guard,
                   source_event_ids, conversation_id, suggestion_id, agenda_item_ids, result, created_at
            FROM pipeline_execution_results
            WHERE %s = ANY(source_event_ids)
               OR result::text ILIKE %s
            ORDER BY created_at DESC
            """,
            (event_id, pattern),
        ).fetchall()
    return {
        "event": row_to_event_trace(event_row),
        "semantic_event": row_to_semantic_event(semantic_row) if semantic_row else None,
        "memory_vectors": [row_to_memory_vector(row) for row in memory_rows],
        "facts": [row_to_fact_trace(row) for row in fact_rows],
        "agenda_items": [agenda_item_from_row(row) for row in agenda_rows],
        "agenda_versions": [row_to_agenda_version(row) for row in agenda_version_rows],
        "suggestions": [row_to_suggestion_item(row) for row in suggestion_rows],
        "route_traces": [row_to_task_route_trace(row) for row in route_rows],
        "pipeline_executions": [row_to_pipeline_execution_result(row) for row in pipeline_execution_rows],
    }


@app.get("/api/chat/conversations/{conversation_id}/trace")
def conversation_trace(conversation_id: str, x_par_password: Optional[str] = Header(default=None)) -> dict[str, Any]:
    require_password(x_par_password)
    pattern = f"%{conversation_id}%"
    with db() as conn:
        conversation_row = conn.execute(
            """
            SELECT id, client_type, started_at, last_active_at, active_task_id, scope, status
            FROM assistant_conversations
            WHERE id = %s
            """,
            (conversation_id,),
        ).fetchone()
        if not conversation_row:
            raise HTTPException(status_code=404, detail="conversation not found")
        turn_rows = conn.execute(
            """
            SELECT id, conversation_id, role, content, event_id, suggestion_id, tool_call_id,
                   created_at, finalized_at
            FROM assistant_turns
            WHERE conversation_id = %s
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        ).fetchall()
        event_ids = [str(row[4]) for row in turn_rows if row[4]]
        context_rows = conn.execute(
            """
            SELECT id, event_id, context_type, included_event_ids, included_memory_ids,
                   included_agenda_ids, reason, payload, created_at
            FROM context_snapshots
            WHERE event_id = ANY(%s::UUID[])
            ORDER BY created_at ASC
            """,
            (event_ids,),
        ).fetchall()
        suggestion_rows = conn.execute(
            """
            SELECT id, source_event_id, title, body, priority, status, metadata, created_at, updated_at
            FROM proactive_suggestions
            WHERE source_event_id = ANY(%s::UUID[])
               OR id = ANY(%s::UUID[])
            ORDER BY created_at DESC
            """,
            (event_ids, [str(row[5]) for row in turn_rows if row[5]]),
        ).fetchall()
        route_rows = conn.execute(
            """
            SELECT id, request, route_type, capability_id, pipeline_id, risk_permission,
                   confirmation_required, task_route_decision, openclaw_task_packet,
                   clarification, context_summary, created_at,
                   source_event_ids, conversation_id, suggestion_id, agenda_item_ids
            FROM task_route_traces
            WHERE conversation_id = %s
               OR context_summary::text ILIKE %s
            ORDER BY created_at DESC
            """,
            (conversation_id, pattern),
        ).fetchall()
        pipeline_execution_rows = conn.execute(
            """
            SELECT id, task_trace_id, request, route_type, capability_id, pipeline_id, status,
                   required_slots, resolved_slots, missing_slots, risk, execution_guard,
                   source_event_ids, conversation_id, suggestion_id, agenda_item_ids, result, created_at
            FROM pipeline_execution_results
            WHERE conversation_id = %s
               OR result::text ILIKE %s
            ORDER BY created_at DESC
            """,
            (conversation_id, pattern),
        ).fetchall()
    return {
        "conversation": row_to_conversation(conversation_row),
        "turns": [row_to_assistant_turn(row) for row in turn_rows],
        "context_snapshots": [row_to_context_snapshot(row) for row in context_rows],
        "suggestions": [row_to_suggestion_item(row) for row in suggestion_rows],
        "route_traces": [row_to_task_route_trace(row) for row in route_rows],
        "pipeline_executions": [row_to_pipeline_execution_result(row) for row in pipeline_execution_rows],
    }


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
    actions = metadata.get("actions") if isinstance(metadata.get("actions"), list) else []
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
        "actions": actions,
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
    if not body.memory_id and not body.source and not body.state_key:
        raise HTTPException(status_code=400, detail="memory_id, source, or state_key is required")
    deleted = 0
    with db() as conn:
        if body.memory_id:
            cur = conn.execute("DELETE FROM semantic_memory WHERE id = %s", (body.memory_id,))
            deleted += cur.rowcount or 0
            if cur.rowcount:
                conn.execute(
                    """
                    INSERT INTO memory_audit_log (id, action, target_type, target_id, reason, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        uuid.uuid4(),
                        "delete",
                        "semantic_memory",
                        body.memory_id,
                        "deleted from governance API",
                        json.dumps({}, ensure_ascii=False),
                    ),
                )
        if body.source:
            cur = conn.execute("DELETE FROM events WHERE source = %s", (body.source,))
            deleted += cur.rowcount or 0
            if cur.rowcount:
                conn.execute(
                    """
                    INSERT INTO memory_audit_log (id, action, target_type, target_id, reason, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        uuid.uuid4(),
                        "delete",
                        "events",
                        body.source,
                        "deleted source events from governance API",
                        json.dumps({"deleted": cur.rowcount}, ensure_ascii=False),
                    ),
                )
        if body.state_key:
            cur = conn.execute("DELETE FROM memory_states WHERE key = %s", (body.state_key,))
            deleted += cur.rowcount or 0
            if cur.rowcount:
                conn.execute(
                    """
                    INSERT INTO memory_audit_log (id, action, target_type, target_id, reason, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now())
                    """,
                    (
                        uuid.uuid4(),
                        "delete",
                        "memory_state",
                        body.state_key,
                        "deleted from governance API",
                        json.dumps({}, ensure_ascii=False),
                    ),
                )
    return {"deleted": deleted}


@app.post("/model/route")
def model_route(task: str = "semantic_extraction") -> dict[str, str]:
    return {"mode": os.getenv("MODEL_MODE", "standard"), "task": task}
