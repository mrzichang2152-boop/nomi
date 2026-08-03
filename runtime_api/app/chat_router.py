from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import re
from urllib.parse import unquote_plus


@dataclass(frozen=True)
class ChatContextRoute:
    intent: str
    needs_dialogue: bool = True
    needs_source: bool = False
    needs_memory: bool = False
    needs_agenda: bool = False
    needs_tasks: bool = False
    needs_memory_kv: bool = False
    needs_memory_graph: bool = False
    needs_memory_rag: bool = False
    needs_timeline: bool = False
    needs_external_tool_state: bool = False
    needs_web: bool = False
    needs_attachments: bool = False
    web_mode: str = "quick"
    web_freshness: str = "none"
    web_max_queries: int = 1
    web_max_sources: int = 5
    confidence: float = 1.0
    reason: str = ""
    entities: tuple[dict[str, Any], ...] = ()
    scope: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        detailed_memory = (
            self.needs_memory_kv
            or self.needs_memory_graph
            or self.needs_memory_rag
            or self.needs_timeline
        )
        if self.needs_memory and not detailed_memory:
            object.__setattr__(self, "needs_memory_kv", True)
            object.__setattr__(self, "needs_memory_graph", True)
            object.__setattr__(self, "needs_memory_rag", True)
            object.__setattr__(self, "needs_timeline", True)
        elif detailed_memory and not self.needs_memory:
            object.__setattr__(self, "needs_memory", True)

    def to_decision(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "needs": {
                "dialogue": self.needs_dialogue,
                "source": self.needs_source,
                "memory": self.needs_memory,
                "memory_kv": self.needs_memory_kv,
                "memory_graph": self.needs_memory_graph,
                "memory_rag": self.needs_memory_rag,
                "timeline": self.needs_timeline,
                "agenda": self.needs_agenda,
                "tasks": self.needs_tasks,
                "external_tool_state": self.needs_external_tool_state,
                "web": self.needs_web,
                "attachments": self.needs_attachments,
            },
            "web": {
                "mode": self.web_mode,
                "freshness": self.web_freshness,
                "max_queries": self.web_max_queries,
                "max_sources": self.web_max_sources,
            },
            "entities": list(self.entities),
            "scope": dict(self.scope),
            "risk": dict(self.risk),
            "reason": self.reason,
        }


AGENDA_RE = re.compile(
    r"(今天|明天|后天|本周|下周|周[一二三四五六日天]|星期[一二三四五六日天]|日程|安排|会议|开会|要开的会|会面|见面|截止|"
    r"提醒|取消|几点|什么时候|之前|以前|[0-2]?\d\s*点\s*前|"
    r"\bwhen\b|\bwhere\b|\bmeet\b|\bmeeting\b|\bappointment\b|\binterview\b|\bschedule\b|\bcalendar\b)"
)
AGENDA_EVIDENCE_FALLBACK_RE = re.compile(
    r"(来源|证据|缺什么|待补充|还缺|从哪|谁说|聊天|消息|记录|"
    r"周[一二三四五六日天]\s*[0-2]?\d\s*点\s*前|星期[一二三四五六日天]\s*[0-2]?\d\s*点\s*前|"
    r"[0-2]?\d\s*点\s*前|截止|报价|成本|利润率|合同|保单|保险)"
)
MEMORY_RE = re.compile(
    r"(之前|上次|谁说|说过|聊天记录|邮件|报价|PHONE_|客户|同事|朋友|记得|历史|"
    r"请记住|帮我记住|记住的|暗号|测试暗号|口令|偏好|喜好|保险|保单|免赔|理赔|"
    r"\bremember(?:ed|ing)?\b|\bmemory\b|\bpreviously\b|\blast time\b|\bearlier\b)",
    re.I,
)
SOURCE_CONTEXT_RE = re.compile(
    r"(Gmail|邮件|email|inbox|收件箱|WhatsApp|Telegram|LinkedIn|领英|Calendar|日历)",
    re.IGNORECASE,
)
TASK_RE = re.compile(r"(帮我|替我|跟进|起草|发送|回复|投递|申请|打车|导航|购买|下单|处理)")
ANSWER_FORMAT_RE = re.compile(r"(只回复|仅回复|直接回答|简短回答|一句话回答|不要解释)")
INFO_REQUEST_RE = re.compile(r"(解释一下|解释下|介绍一下|什么是|是什么意思|\bwhat is\b|\bhow does\b)", re.IGNORECASE)
JOB_RE = re.compile(
    r"(岗位|职位|工作机会|求职机会|招聘信息|合适的工作|适合我的工作|JD|简历|HR|recruiter|hiring manager|面试官|求职|投递|offer|cover letter|自我介绍|"
    r"申请岗位|提交申请|linkedin_search_[a-z0-9_]+|job_[a-z0-9_]+|"
    r"\bjobs?\b|\bjob opportunities?\b|\bsuitable jobs?\b|\bresume\b|\bCV\b|\bcareer\b|\bpositions?\b|\bapply\b|\bsubmit application\b)",
    re.IGNORECASE,
)
WEB_EXPLICIT_RE = re.compile(
    r"(搜索一下|搜一下|帮我搜索|帮我搜|网上查|上网查|联网查|查一下最新|查查最新|"
    r"web\s*search|search\s+the\s+web|look\s+up)",
    re.IGNORECASE,
)
WEB_CURRENT_FACT_RE = re.compile(
    r"(当前最新|现在最新|最新版本|最新发布|最近发布|今日|今天的新闻|实时|截至目前|"
    r"current\s+latest|latest\s+(?:version|release|news)|as\s+of\s+today)",
    re.IGNORECASE,
)
WEB_DYNAMIC_FACT_RE = re.compile(
    r"(天气|气温|降雨|降水|空气质量|空气污染|AQI|汇率|外汇|股价|股票指数|上证指数|深证成指|"
    r"航班状态|航班动态|列车状态|列车动态|路况|交通拥堵|比赛比分|比赛结果|赛果|油价|金价|"
    r"weather|temperature|forecast|air\s+quality|exchange\s+rate|stock\s+price|market\s+index|"
    r"flight\s+status|train\s+status|traffic|match\s+score|game\s+score|oil\s+price|gold\s+price)",
    re.IGNORECASE,
)
WEB_TIME_SENSITIVE_TOPIC_RE = re.compile(
    r"(新闻|热点|政策|法规|法律|税率|利率|价格|售价|票价|多少钱|限行|限号|开放时间|营业时间|"
    r"几点(?:开放|关门|闭馆)|开放吗|营业吗|关门|闭馆|展览|演出|活动|榜单|排名|"
    r"CEO|首席执行官|现任|负责人|董事长|总裁|任职|总统|总理|首相|部长|市长|州长|议长|"
    r"news|headline|policy|regulation|law|tax\s+rate|interest\s+rate|price|opening\s+hours|"
    r"open\s+today|close(?:s|d)?\s+at|exhibition|event|ranking|chief\s+executive|"
    r"president|prime\s+minister|minister|governor|mayor|speaker|who\s+is\s+the\s+(?:current\s+)?CEO)",
    re.IGNORECASE,
)
AGENDA_SUBJECT_RE = re.compile(
    r"(日程|安排|会议|开会|要开的会|会面|见面|约会|截止|提醒|取消|"
    r"meeting|appointment|interview|schedule|calendar|reminder)",
    re.IGNORECASE,
)
WEB_FRESHNESS_RE = re.compile(
    r"(最新|最近|当前|现在|今日|今天|明天|后天|本周|这周|周末|本月|实时|"
    r"latest|current|recent|today|tomorrow|this\s+week|this\s+weekend)",
    re.IGNORECASE,
)
WEB_DAY_FRESHNESS_RE = re.compile(
    r"(当前|现在|今日|今天|明天|后天|今晚|实时|此刻|"
    r"current|today|tomorrow|tonight|real[ -]?time|right\s+now)",
    re.IGNORECASE,
)
PRIVATE_SELF_CONTEXT_RE = re.compile(
    r"(我的|我有哪些|我有什么|我收到|我发的|我(?:最近|今天|现在|明天|后天|和|跟|与)|"
    r"我们(?:的|有哪些|有什么|部门|项目|公司|团队)|咱们(?:的|有哪些|有什么|部门|项目|公司|团队)|"
    r"刚才|刚刚|之前|上次|对方|王总|客户|同事|朋友|家人|"
    r"my\s+(?:email|message|schedule|calendar|meeting|contact)|our\s+(?:schedule|meeting))",
    re.IGNORECASE,
)
JOB_DISCOVERY_RE = re.compile(
    r"(找.*(?:工作|岗位|职位|机会)|工作机会|求职机会|招聘信息|岗位推荐|职位推荐|适合我的.*(?:工作|岗位|职位)|"
    r"find.*(?:job|position|role)|job\s+opportunit|open\s+role)",
    re.IGNORECASE,
)
IMPLICIT_REFERENCE_RE = re.compile(r"(那件事|后来|刚刚|刚才|这个|那个|她|他|他们|她们|回了吗|回复了吗|还要继续|继续吗)")
RELATIONSHIP_RE = re.compile(r"(回复|联系|关系|认识|介绍|HR|客户|朋友|同事|recruiter|hiring manager)", re.IGNORECASE)
FAMILY_RELATION_RE = re.compile(
    r"(儿子|女儿|孩子|小孩|父亲|爸爸|母亲|妈妈|老婆|妻子|太太|丈夫|老公|兄弟|姐妹|哥哥|姐姐|弟弟|妹妹|家人|亲属|"
    r"son|daughter|child|father|mother|wife|husband|brother|sister)",
    re.IGNORECASE,
)
FAMILY_RELATION_QUERY_RE = re.compile(r"(谁|谁的|哪个|哪位|叫|名字|是|who|whose|name)", re.IGNORECASE)
CJK_PERSON_IDENTITY_QUERY_RE = re.compile(
    r"^[\s“”\"'`]*[\u4e00-\u9fff]{2,8}\s*(?:是谁|是什么人|是什么身份|是哪个人|是哪位|什么来头)[？?。.!！]*\s*$"
)
CJK_PERSON_IDENTITY_REFERENCE_RE = re.compile(
    r"[\u4e00-\u9fff]{2,8}\s*(?:是谁|是什么人|是什么身份|是哪个人|是哪位|什么来头)"
)
CJK_PERSON_RELATION_PAIR_QUERY_RE = re.compile(
    r"[\u4e00-\u9fff]{2,8}\s*(?:和|跟|与)\s*[\u4e00-\u9fff]{2,8}.{0,8}(?:什么关系|关系)"
)
ACTION_COMMAND_RE = re.compile(r"(帮我|替我|起草|发送|发给|回复他|回复她|回复客户|回复邮件|投递|申请|打车|导航|购买|下单|处理)")
LATIN_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9_-]{1,}\b")
VALID_ROUTE_INTENTS = {
    "simple_chat",
    "memory_query",
    "agenda_query",
    "task_request",
    "relationship_query",
    "job_query",
    "web_query",
    "source_question",
    "action_confirmation",
}
SemanticRouter = Callable[[str, Optional[dict[str, Any]], ChatContextRoute], Optional[dict[str, Any]]]
SHORT_REPLY_RE = re.compile(
    r"^\s*(需要|需要的|可以|可以的|好的|好|行|嗯|对|确认|继续|稍后|不用|不要|"
    r"yes|yep|ok|okay|sure|no|nope)\s*[。.!！?？]*\s*$",
    re.IGNORECASE,
)


def _has_pending_action(ui_state: dict[str, Any] | None) -> bool:
    if not isinstance(ui_state, dict):
        return False
    pending_keys = (
        "pending_action",
        "pending_task",
        "pending_confirmation",
        "last_assistant_action",
        "active_suggestion",
    )
    return any(bool(ui_state.get(key)) for key in pending_keys)


def _extract_latin_entities(text: str) -> tuple[dict[str, Any], ...]:
    entities = []
    for match in LATIN_ENTITY_RE.finditer(text):
        value = match.group(0)
        upper_value = value.upper()
        if upper_value in {"LINKEDIN", "GMAIL", "WHATSAPP", "TELEGRAM"}:
            entity_type = "channel"
        elif upper_value == "JD":
            entity_type = "job"
        elif upper_value == "HR":
            entity_type = "person"
        elif upper_value.startswith("PHONE"):
            entity_type = "product"
        else:
            entity_type = "person"
        entities.append({"type": entity_type, "text": value, "confidence": 0.72})
    return tuple(entities[:6])


def _route_from_semantic_decision(decision: dict[str, Any]) -> ChatContextRoute | None:
    intent = str(decision.get("intent") or "")
    if intent not in VALID_ROUTE_INTENTS:
        return None
    needs = decision.get("needs") if isinstance(decision.get("needs"), dict) else {}
    entities = decision.get("entities") if isinstance(decision.get("entities"), list) else []
    normalized_entities = tuple(item for item in entities if isinstance(item, dict))
    scope = decision.get("scope") if isinstance(decision.get("scope"), dict) else {}
    risk = decision.get("risk") if isinstance(decision.get("risk"), dict) else {}
    web = decision.get("web") if isinstance(decision.get("web"), dict) else {}
    try:
        confidence = float(decision.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence <= 0 or confidence > 1:
        return None
    return ChatContextRoute(
        intent=intent,
        needs_dialogue=bool(needs.get("dialogue", True)),
        needs_source=bool(needs.get("source", False)),
        needs_memory=bool(needs.get("memory", False)),
        needs_agenda=bool(needs.get("agenda", False)),
        needs_tasks=bool(needs.get("tasks", False)),
        needs_memory_kv=bool(needs.get("memory_kv", False)),
        needs_memory_graph=bool(needs.get("memory_graph", False)),
        needs_memory_rag=bool(needs.get("memory_rag", False)),
        needs_timeline=bool(needs.get("timeline", False)),
        needs_external_tool_state=bool(needs.get("external_tool_state", False)),
        needs_web=bool(needs.get("web", False)),
        needs_attachments=bool(needs.get("attachments", False)),
        web_mode=str(web.get("mode") or "quick"),
        web_freshness=str(web.get("freshness") or "none"),
        web_max_queries=max(1, min(int(web.get("max_queries") or 1), 5)),
        web_max_sources=max(1, min(int(web.get("max_sources") or 5), 15)),
        confidence=confidence,
        reason=str(decision.get("reason") or "semantic_router"),
        entities=normalized_entities,
        scope=scope,
        risk=risk,
    )


def _finalize_route(
    text: str,
    ui_state: dict[str, Any] | None,
    route: ChatContextRoute,
    semantic_router: SemanticRouter | None,
) -> ChatContextRoute:
    if semantic_router is None:
        return route
    if route.intent != "simple_chat" or route.reason not in {"default_simple", "informational_request"}:
        return route
    try:
        semantic_decision = semantic_router(text, ui_state, route)
    except Exception:
        return route
    if not isinstance(semantic_decision, dict):
        return route
    semantic_route = _route_from_semantic_decision(semantic_decision)
    return semantic_route or route


def route_chat_context(
    message: str,
    ui_state: dict[str, Any] | None = None,
    semantic_router: SemanticRouter | None = None,
) -> ChatContextRoute:
    text = unquote_plus(str(message or "").strip())
    has_ui_source = bool(ui_state and (ui_state.get("source_type") or ui_state.get("current_source") or ui_state.get("source")))
    has_pending_action = _has_pending_action(ui_state)

    if SHORT_REPLY_RE.search(text) and has_pending_action:
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="action_confirmation",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            needs_memory_kv=True,
            needs_memory_graph=True,
            needs_memory_rag=True,
            needs_timeline=True,
            needs_tasks=True,
            needs_external_tool_state=True,
            confidence=0.92,
            reason="pending_action_confirmation",
            entities=_extract_latin_entities(str(ui_state or "")),
            risk={"may_trigger_action": True, "requires_user_confirmation": True, "privacy_level": "high"},
        ), semantic_router)

    if (
        ANSWER_FORMAT_RE.search(text)
        and not AGENDA_RE.search(text)
        and not MEMORY_RE.search(text)
        and not re.search(r"(帮我|替我|发给|发送给|回复他|回复她|回复客户|回复邮件|起草)", text)
    ):
        return _finalize_route(text, ui_state, ChatContextRoute(intent="simple_chat", needs_dialogue=True, needs_source=has_ui_source, reason="answer_format"), semantic_router)

    if SHORT_REPLY_RE.search(text):
        return _finalize_route(text, ui_state, ChatContextRoute(intent="simple_chat", needs_dialogue=True, needs_source=has_ui_source, reason="short_reply"), semantic_router)

    explicit_web_search = bool(WEB_EXPLICIT_RE.search(text))
    current_public_fact = bool(WEB_CURRENT_FACT_RE.search(text))
    dynamic_public_fact = bool(WEB_DYNAMIC_FACT_RE.search(text))
    time_sensitive_public_topic = bool(WEB_TIME_SENSITIVE_TOPIC_RE.search(text))
    freshness_signal = bool(WEB_FRESHNESS_RE.search(text))
    private_agenda_subject = bool(AGENDA_SUBJECT_RE.search(text))
    private_source_subject = bool(SOURCE_CONTEXT_RE.search(text) or MEMORY_RE.search(text))
    private_self_context = bool(PRIVATE_SELF_CONTEXT_RE.search(text))
    private_relationship_subject = bool(
        RELATIONSHIP_RE.search(text)
        and (_extract_latin_entities(text) or private_self_context or IMPLICIT_REFERENCE_RE.search(text))
    )
    strong_public_signal = dynamic_public_fact or time_sensitive_public_topic
    freshness_public_query = bool(
        freshness_signal
        and not private_source_subject
        and not private_self_context
        and not private_relationship_subject
        and (not private_agenda_subject or strong_public_signal)
    )
    if (
        (explicit_web_search or current_public_fact or strong_public_signal or freshness_public_query)
        and not JOB_RE.search(text)
        and not private_source_subject
        and (not private_self_context or explicit_web_search)
        and (not private_relationship_subject or strong_public_signal)
        and (not private_agenda_subject or strong_public_signal)
    ):
        if dynamic_public_fact or WEB_DAY_FRESHNESS_RE.search(text):
            web_freshness = "day"
        elif WEB_FRESHNESS_RE.search(text):
            web_freshness = "month"
        else:
            web_freshness = "none"
        return ChatContextRoute(
            intent="web_query",
            needs_dialogue=True,
            needs_web=True,
            web_mode="balanced" if explicit_web_search else "quick",
            web_freshness=web_freshness,
            web_max_queries=2 if explicit_web_search else 1,
            web_max_sources=8 if explicit_web_search else 5,
            confidence=0.9,
            reason=(
                "explicit_web_search"
                if explicit_web_search
                else "dynamic_public_fact"
                if dynamic_public_fact
                else "time_sensitive_public_topic"
                if time_sensitive_public_topic
                else "current_public_fact"
                if current_public_fact
                else "freshness_public_query"
            ),
            risk={"privacy_level": "public_query_only"},
        )

    if INFO_REQUEST_RE.search(text) and not JOB_RE.search(text) and not MEMORY_RE.search(text) and not AGENDA_RE.search(text):
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="simple_chat",
            needs_dialogue=True,
            needs_source=has_ui_source,
            confidence=0.9,
            reason="informational_request",
        ), semantic_router)

    if FAMILY_RELATION_RE.search(text) and FAMILY_RELATION_QUERY_RE.search(text):
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="relationship_query",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            needs_memory_kv=True,
            needs_memory_graph=True,
            needs_memory_rag=True,
            needs_timeline=True,
            confidence=0.82,
            reason="family_relationship_reference",
            entities=_extract_latin_entities(text),
            scope={"relationship_scope": "family"},
        ), semantic_router)

    if (
        CJK_PERSON_IDENTITY_QUERY_RE.search(text)
        or CJK_PERSON_IDENTITY_REFERENCE_RE.search(text)
        or CJK_PERSON_RELATION_PAIR_QUERY_RE.search(text)
    ):
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="relationship_query",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            needs_memory_kv=True,
            needs_memory_graph=True,
            needs_memory_rag=True,
            needs_timeline=True,
            confidence=0.8,
            reason="chinese_person_relationship_reference",
            entities=_extract_latin_entities(text),
            scope={"relationship_scope": "person_identity"},
        ), semantic_router)

    if JOB_RE.search(text):
        needs_web = bool(JOB_DISCOVERY_RE.search(text) or WEB_EXPLICIT_RE.search(text))
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="job_query",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            needs_memory_kv=True,
            needs_memory_graph=True,
            needs_memory_rag=True,
            needs_timeline=False,
            needs_tasks=True,
            needs_web=needs_web,
            web_mode="balanced" if needs_web else "quick",
            web_freshness="month" if needs_web else "none",
            web_max_queries=3 if needs_web else 1,
            web_max_sources=10 if needs_web else 5,
            confidence=0.88,
            reason="job_context",
            entities=_extract_latin_entities(text),
            scope={"source_types": ["job_description", "resume", "linkedin"]},
            risk={"may_trigger_action": bool(TASK_RE.search(text)), "requires_user_confirmation": bool(TASK_RE.search(text)), "privacy_level": "high"},
        ), semantic_router)

    if RELATIONSHIP_RE.search(text) and _extract_latin_entities(text) and not ACTION_COMMAND_RE.search(text):
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="relationship_query",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            needs_memory_graph=True,
            needs_memory_rag=True,
            needs_timeline=True,
            confidence=0.78,
            reason="relationship_reference",
            entities=_extract_latin_entities(text),
            scope={"relationship_scope": "same_contact"},
        ), semantic_router)

    if TASK_RE.search(text):
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="task_request",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            needs_memory_kv=True,
            needs_memory_graph=True,
            needs_memory_rag=True,
            needs_timeline=True,
            needs_agenda=bool(AGENDA_RE.search(text)),
            needs_tasks=True,
            confidence=0.86,
            reason="task_keyword",
            entities=_extract_latin_entities(text),
            risk={"may_trigger_action": True, "requires_user_confirmation": True, "privacy_level": "high"},
        ), semantic_router)

    if MEMORY_RE.search(text):
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="memory_query",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            needs_memory_kv=True,
            needs_memory_graph=True,
            needs_memory_rag=True,
            needs_timeline=True,
            needs_agenda=bool(AGENDA_RE.search(text)),
            confidence=0.9,
            reason="memory_keyword",
            entities=_extract_latin_entities(text),
        ), semantic_router)

    if AGENDA_RE.search(text):
        needs_memory_fallback = bool(
            MEMORY_RE.search(text)
            or AGENDA_EVIDENCE_FALLBACK_RE.search(text)
        )
        needs_source_fallback = bool(
            has_ui_source
            or SOURCE_CONTEXT_RE.search(text)
            or needs_memory_fallback
        )
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="agenda_query",
            needs_dialogue=True,
            needs_source=needs_source_fallback,
            needs_memory=needs_memory_fallback,
            needs_memory_kv=needs_memory_fallback,
            needs_memory_graph=needs_memory_fallback,
            needs_memory_rag=needs_memory_fallback,
            needs_timeline=needs_memory_fallback,
            needs_agenda=True,
            confidence=0.88,
            reason="agenda_keyword_with_evidence" if needs_source_fallback else "agenda_keyword",
            entities=_extract_latin_entities(text),
        ), semantic_router)

    if SOURCE_CONTEXT_RE.search(text):
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="source_question",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            needs_memory_kv=True,
            needs_memory_graph=True,
            needs_memory_rag=True,
            needs_timeline=True,
            needs_agenda=False,
            confidence=0.88,
            reason="source_context_keyword",
            entities=_extract_latin_entities(text),
        ), semantic_router)

    if IMPLICIT_REFERENCE_RE.search(text):
        return _finalize_route(text, ui_state, ChatContextRoute(
            intent="memory_query",
            needs_dialogue=True,
            needs_source=True,
            needs_memory=True,
            needs_memory_graph=True,
            needs_memory_rag=True,
            needs_timeline=True,
            needs_agenda=False,
            needs_tasks=has_pending_action,
            confidence=0.66,
            reason="implicit_reference",
            entities=_extract_latin_entities(text),
        ), semantic_router)

    return _finalize_route(text, ui_state, ChatContextRoute(intent="simple_chat", needs_dialogue=True, needs_source=has_ui_source, reason="default_simple"), semantic_router)


def context_fetch_limits(route: ChatContextRoute, requested_limit: int = 12) -> dict[str, int]:
    requested = min(max(int(requested_limit or 12), 1), 50)

    def detailed_memory_limits(
        *,
        memory: int,
        kv: int,
        graph: int,
        rag: int,
        timeline: int,
    ) -> dict[str, int]:
        return {
            "memory": memory if route.needs_memory else 0,
            "memory_kv": kv if route.needs_memory_kv else 0,
            "memory_graph": graph if route.needs_memory_graph else 0,
            "memory_rag": rag if route.needs_memory_rag else 0,
            "timeline": timeline if route.needs_timeline else 0,
        }

    if route.intent in {"task_request", "action_confirmation"}:
        return {
            "source": 4 if route.needs_source else 0,
            **detailed_memory_limits(memory=max(requested, 12), kv=4, graph=5, rag=8, timeline=5),
            "dialogue": 40 if route.needs_dialogue else 0,
            "agenda": 3 if route.needs_agenda else 0,
            "tasks": 8 if route.needs_tasks else 0,
            "external_tool_state": 4 if route.needs_external_tool_state else 0,
            "input_target_tokens": 64000,
        }
    if route.intent == "job_query":
        return {
            "source": 6 if route.needs_source else 0,
            **detailed_memory_limits(memory=max(requested, 12), kv=5, graph=6, rag=10, timeline=0),
            "dialogue": 40 if route.needs_dialogue else 0,
            "agenda": 0,
            "tasks": 8 if route.needs_tasks else 0,
            "external_tool_state": 0,
            "web": 10 if route.needs_web else 0,
            "input_target_tokens": 96000,
        }
    if route.intent == "web_query":
        return {
            "source": 0,
            **detailed_memory_limits(memory=0, kv=0, graph=0, rag=0, timeline=0),
            "dialogue": 20 if route.needs_dialogue else 0,
            "agenda": 0,
            "tasks": 0,
            "external_tool_state": 0,
            "web": 8 if route.needs_web else 0,
            "input_target_tokens": 32000,
        }
    if route.intent == "relationship_query":
        return {
            "source": 3 if route.needs_source else 0,
            **detailed_memory_limits(memory=max(min(requested, 16), 8), kv=2, graph=8, rag=6, timeline=6),
            "dialogue": 30 if route.needs_dialogue else 0,
            "agenda": 0,
            "tasks": 0,
            "external_tool_state": 0,
            "input_target_tokens": 48000,
        }
    if route.intent == "memory_query":
        return {
            "source": 3 if route.needs_source else 0,
            **detailed_memory_limits(memory=max(min(requested, 16), 8), kv=3, graph=5, rag=8, timeline=5),
            "dialogue": 24 if route.needs_dialogue else 0,
            "agenda": 2 if route.needs_agenda else 0,
            "tasks": 0,
            "external_tool_state": 0,
            "input_target_tokens": 48000,
        }
    if route.intent == "source_question":
        return {
            "source": 6 if route.needs_source else 0,
            **detailed_memory_limits(memory=max(min(requested, 16), 8), kv=3, graph=5, rag=8, timeline=5),
            "dialogue": 24 if route.needs_dialogue else 0,
            "agenda": 2 if route.needs_agenda else 0,
            "tasks": 4 if route.needs_tasks else 0,
            "external_tool_state": 0,
            "input_target_tokens": 48000,
        }
    if route.intent == "agenda_query":
        return {
            "source": 2 if route.needs_source else 0,
            **detailed_memory_limits(memory=max(min(requested, 12), 6), kv=2, graph=4, rag=6, timeline=4),
            "dialogue": 24 if route.needs_dialogue else 0,
            "agenda": max(min(requested, 12), 8) if route.needs_agenda else 0,
            "tasks": 0,
            "external_tool_state": 0,
            "input_target_tokens": 24000,
        }
    return {
        "source": 2 if route.needs_source else 0,
        **detailed_memory_limits(memory=0, kv=0, graph=0, rag=0, timeline=0),
        "dialogue": 10 if route.reason == "answer_format" and route.needs_dialogue else (30 if route.needs_dialogue else 0),
        "agenda": 0,
        "tasks": 0,
        "external_tool_state": 0,
        "input_target_tokens": 4000 if route.reason == "answer_format" else 16000,
    }
