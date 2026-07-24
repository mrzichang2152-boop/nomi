import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "postgresql://test")
os.environ.setdefault("REDIS_URL", "redis://test")


def test_web_search_api_returns_citable_sources_and_persists_audit(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.web_search.schema import SearchResponse, WebSource

    class FakeService:
        def search(self, request):
            assert request.query == "Qwen 最新版本"
            return SearchResponse(
                run_id="webrun_api",
                status="completed",
                query=request.query,
                query_hash="query-hash",
                mode=request.mode,
                providers_attempted=["exa"],
                sources=[
                    WebSource(
                        source_id="websrc_api",
                        run_id="webrun_api",
                        provider="exa",
                        title="Official release",
                        url="https://qwenlm.github.io/blog/release/",
                        canonical_url="https://qwenlm.github.io/blog/release",
                        snippet="Official details",
                        trust_tier="primary",
                    )
                ],
            )

    persisted = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(main, "web_search_service", lambda: FakeService())
    monkeypatch.setattr(
        main,
        "current_web_search_provider_status",
        lambda: {"enabled": True, "provider_order": ["exa"], "configured_providers": ["exa"]},
    )
    monkeypatch.setattr(main, "db", lambda: Conn())
    monkeypatch.setattr(main, "persist_search_run", lambda conn, **kwargs: persisted.append(kwargs))

    response = TestClient(main.app).post(
        "/api/web-search/search",
        headers={"x-par-password": "secret"},
        json={"query": "Qwen 最新版本", "mode": "quick", "max_results": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["sources"][0]["source_id"] == "websrc_api"
    assert payload["sources"][0]["url"] == "https://qwenlm.github.io/blog/release/"
    assert persisted[0]["response"].run_id == "webrun_api"


def test_web_search_audit_persists_routing_trace():
    from app.web_search.persistence import persist_search_run, web_search_schema_sql
    from app.web_search.schema import SearchRequest, SearchResponse

    class Conn:
        def __init__(self):
            self.executed = []

        def execute(self, sql, params=()):
            self.executed.append((" ".join(sql.split()), params))

    conn = Conn()
    request = SearchRequest(query="latest release")
    response = SearchResponse(
        run_id="webrun_route",
        status="completed",
        query="latest release",
        query_hash="hash",
        mode="quick",
        routing_trace={
            "category": "fresh_news",
            "provider_order": ["tavily", "bocha", "exa"],
            "reason": "smart_route:fresh_news",
        },
    )

    persist_search_run(conn, request=request, response=response, original_query_hash="original")

    schema = " ".join(web_search_schema_sql())
    insert_sql, params = conn.executed[0]
    assert "routing_trace JSONB" in schema
    assert "routing_trace" in insert_sql
    assert any(
        isinstance(value, str) and '"category": "fresh_news"' in value
        for value in params
    )


def test_web_search_provider_status_does_not_expose_credentials(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    monkeypatch.setattr(
        main,
        "current_web_search_provider_status",
        lambda: {"enabled": True, "provider_order": ["exa"], "configured_providers": ["exa"]},
    )

    response = TestClient(main.app).get(
        "/api/web-search/providers",
        headers={"x-par-password": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "provider_order": ["exa"],
        "configured_providers": ["exa"],
    }
    assert "key" not in response.text.lower()


def test_chat_web_fetcher_returns_citable_context_and_honors_route_plan(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.chat_router import ChatContextRoute
    from app.web_search.schema import SearchResponse, WebSource

    requests = []

    class FakeService:
        def search(self, request):
            requests.append(request)
            return SearchResponse(
                run_id="webrun_chat",
                status="completed",
                query=request.query,
                query_hash="hash",
                mode=request.mode,
                sources=[
                    WebSource(
                        source_id="websrc_chat",
                        run_id="webrun_chat",
                        provider="exa",
                        title="Official docs",
                        url="https://example.com/docs",
                        canonical_url="https://example.com/docs",
                        snippet="Current release details.",
                    )
                ],
            )

    monkeypatch.setattr(main, "web_search_service", lambda: FakeService())
    monkeypatch.setattr(
        main,
        "current_web_search_provider_status",
        lambda: {"enabled": True, "provider_order": ["exa"], "configured_providers": ["exa"]},
    )
    monkeypatch.setattr(main, "persist_web_search_response", lambda *args, **kwargs: None)
    route = ChatContextRoute(
        intent="web_query",
        needs_web=True,
        web_mode="balanced",
        web_freshness="month",
        web_max_sources=8,
    )

    context = main.fetch_web_search_context("Qwen 最新版本", route, trace_context={"conversation_id": "conv-1"})

    assert requests[0].mode == "balanced"
    assert requests[0].freshness == "month"
    assert requests[0].max_results == 8
    assert context[0]["source_id"] == "websrc_chat"
    assert context[0]["layer"] == "web_evidence"


def test_chat_web_fetcher_degrades_to_explicit_status_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.chat_router import ChatContextRoute

    class BrokenService:
        def search(self, request):
            raise RuntimeError("provider timed out")

    monkeypatch.setattr(main, "web_search_service", lambda: BrokenService())
    monkeypatch.setattr(
        main,
        "current_web_search_provider_status",
        lambda: {"enabled": True, "provider_order": ["exa"], "configured_providers": ["exa"]},
    )
    route = ChatContextRoute(intent="web_query", needs_web=True)

    context = main.fetch_web_search_context("current release", route)

    assert context == [
        {
            "source_id": "web-search-status",
            "layer": "web_search_status",
            "status": "failed",
            "error": "provider timed out",
            "inclusion_reason": "Web search failed; expose the limitation instead of inventing current facts.",
        }
    ]


def test_chat_web_fetcher_honors_global_disabled_switch(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.chat_router import ChatContextRoute

    monkeypatch.setattr(
        main,
        "current_web_search_provider_status",
        lambda: {"enabled": False, "provider_order": ["exa"], "configured_providers": ["exa"]},
    )
    monkeypatch.setattr(
        main,
        "web_search_service",
        lambda: (_ for _ in ()).throw(AssertionError("disabled search must not call a provider")),
    )

    context = main.fetch_web_search_context(
        "current release",
        ChatContextRoute(intent="web_query", needs_web=True),
    )

    assert context[0]["layer"] == "web_search_status"
    assert context[0]["status"] == "disabled"
    assert context[0]["error"] == "web_search_disabled"


def test_public_web_query_stops_before_model_when_search_is_disabled():
    from app import main
    from app.chat_router import ChatContextRoute

    answer = main.required_web_evidence_failure_answer(
        ChatContextRoute(intent="web_query", needs_web=True),
        [
            {
                "source_id": "web-search-status",
                "layer": "web_search_status",
                "status": "disabled",
                "error": "web_search_disabled",
            }
        ],
    )

    assert answer is not None
    assert "联网搜索尚未配置" in answer
    assert "博查、Tavily 或 Exa" in answer
    assert "不使用旧知识猜测" in answer


def test_public_web_query_stops_before_model_when_provider_fails():
    from app import main
    from app.chat_router import ChatContextRoute

    answer = main.required_web_evidence_failure_answer(
        ChatContextRoute(intent="web_query", needs_web=True),
        [
            {
                "source_id": "web-search-status",
                "layer": "web_search_status",
                "status": "failed",
                "error": "provider timed out",
            }
        ],
    )

    assert answer is not None
    assert "联网搜索暂时失败" in answer
    assert "provider timed out" in answer
    assert "不使用旧知识猜测" in answer


def test_public_web_query_continues_when_citable_evidence_exists():
    from app import main
    from app.chat_router import ChatContextRoute

    answer = main.required_web_evidence_failure_answer(
        ChatContextRoute(intent="web_query", needs_web=True),
        [
            {
                "source_id": "websrc_weather",
                "layer": "web_evidence",
                "title": "北京天气",
                "url": "https://weather.example/beijing",
            }
        ],
    )

    assert answer is None


def test_web_fetch_api_returns_sanitized_document(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    from app.web_search.schema import FetchResponse, WebSource

    monkeypatch.setattr(
        main,
        "fetch_public_page",
        lambda request: FetchResponse(
            status="completed",
            source=WebSource(
                source_id="websrc_fetch",
                provider="direct_fetch",
                title="Docs",
                url=request.url,
                canonical_url=request.url,
                content="Readable documentation text.",
                content_status="fetched",
            ),
        ),
    )
    monkeypatch.setattr(
        main,
        "current_web_search_provider_status",
        lambda: {"enabled": True, "provider_order": ["exa"], "configured_providers": ["exa"]},
    )

    response = TestClient(main.app).post(
        "/api/web-search/fetch",
        headers={"x-par-password": "secret"},
        json={"url": "https://example.com/docs", "max_chars": 5000},
    )

    assert response.status_code == 200
    assert response.json()["source"]["source_id"] == "websrc_fetch"
    assert response.json()["source"]["content"] == "Readable documentation text."


def test_web_search_schema_bootstrap_creates_audit_tables(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main

    executed = []

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def execute(self, sql, params=()):
            executed.append(" ".join(sql.split()))
            return self

        def fetchall(self):
            return []

    monkeypatch.setattr(main, "db", lambda: Conn())

    main.ensure_web_search_schema()

    combined = "\n".join(executed)
    assert "CREATE TABLE IF NOT EXISTS web_search_runs" in combined
    assert "CREATE TABLE IF NOT EXISTS web_search_sources" in combined
    assert "CREATE TABLE IF NOT EXISTS web_claim_citations" in combined
    assert "CREATE TABLE IF NOT EXISTS web_search_provider_configs" in combined
    assert "CREATE TABLE IF NOT EXISTS web_search_routing_config" in combined
    assert "web_search_runs_created_idx" in combined
    assert "web_search_sources_run_idx" in combined
    assert "web_claim_citations_event_idx" in combined


def test_web_search_service_is_resolved_through_runtime_manager(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "secret")
    from app import main
    sentinel_service = object()

    class Manager:
        def get_service(self):
            return sentinel_service

    monkeypatch.setattr(main, "web_search_runtime_manager", lambda: Manager())

    service = main.web_search_service()

    assert service is sentinel_service
