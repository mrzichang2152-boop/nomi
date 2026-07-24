# Web Search Provider Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a single-user private Nomi instance securely configure Exa, Tavily, and Bocha keys in Settings and dynamically route searches across the configured providers.

**Architecture:** Store provider keys in PostgreSQL as Fernet envelopes, expose only configuration state and key hints, and preserve environment variables as fallback. A version-aware runtime manager rebuilds provider instances after configuration changes; a deterministic smart router selects among eligible providers by query category while preserving the existing Web Evidence normalization, safety, caching, citation, and audit layers.

**Tech Stack:** FastAPI, Pydantic, PostgreSQL/psycopg, Redis, cryptography/Fernet, vanilla HTML/CSS/JavaScript, pytest, Android WebView real-device acceptance.

---

## File Map

- Create `runtime_api/app/web_search/config.py`: schemas, encryption, database/environment resolution, redaction, connection-test result normalization.
- Create `runtime_api/app/web_search/router.py`: category-to-provider selection and fallback plans.
- Modify `runtime_api/app/web_search/runtime.py`: version-aware runtime manager and provider construction from resolved settings.
- Modify `runtime_api/app/main.py`: schema bootstrap and authenticated settings endpoints.
- Modify `runtime_api/app/static/index.html`: Web Search settings entry, list view, provider detail view.
- Modify `runtime_api/app/static/app.js`: load/save/test/enable/delete/routing interactions without client-side key persistence.
- Modify `runtime_api/app/static/styles.css`: responsive compact-list and provider-detail styles.
- Modify `db/init.sql`: provider and routing config tables.
- Create `runtime_api/tests/test_web_search_settings.py`: encryption, persistence, API and dynamic runtime tests.
- Create `runtime_api/tests/test_static_web_search_settings.py`: static UI contract tests.
- Modify `runtime_api/tests/test_web_search_runtime.py`: smart routing and provider composition tests.
- Create `docs/superpowers/reports/2026-07-12-web-search-provider-settings-gaps.md`: implementation and real-environment gaps.

### Task 1: Encrypted Provider Configuration Domain

**Files:**
- Create: `runtime_api/app/web_search/config.py`
- Test: `runtime_api/tests/test_web_search_settings.py`

- [x] **Step 1: Write failing encryption and redaction tests**

```python
def test_provider_key_envelope_round_trip_without_plaintext(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET", "unit-test-secret")
    envelope = encrypt_provider_api_key("sk-private-1234")
    assert "sk-private-1234" not in json.dumps(envelope)
    assert decrypt_provider_api_key(envelope) == "sk-private-1234"

def test_public_provider_setting_only_exposes_hint():
    public = public_provider_setting("exa", api_key="sk-private-1234", source="database")
    assert public["configured"] is True
    assert public["key_hint"] == "1234"
    assert "api_key" not in public
```

- [x] **Step 2: Run tests and confirm missing-module failure**

Run: `python3 -m pytest -q runtime_api/tests/test_web_search_settings.py -k 'envelope or public_provider'`
Expected: FAIL because `app.web_search.config` does not exist.

- [x] **Step 3: Implement config types and Fernet domain separation**

Implement:

```python
SUPPORTED_PROVIDER_SLUGS = ("exa", "tavily", "bocha")

def web_search_config_fernet() -> Fernet:
    secret = (
        os.getenv("WEB_SEARCH_CONFIG_ENCRYPTION_SECRET")
        or os.getenv("RAW_DATA_ENCRYPTION_KEY")
        or os.getenv("APP_PASSWORD")
        or "par-dev-web-search-config"
    )
    digest = hashlib.sha256(f"nomi:web-search-provider-key:v1:{secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
```

Add `encrypt_provider_api_key`, `decrypt_provider_api_key`, `key_hint`, `ProviderConfigRecord`, `ResolvedProviderConfig`, and response serializers that never return ciphertext or plaintext.

- [x] **Step 4: Run focused tests**

Run: `python3 -m pytest -q runtime_api/tests/test_web_search_settings.py -k 'envelope or public_provider'`
Expected: PASS.

### Task 2: PostgreSQL Schema and Environment Fallback

**Files:**
- Modify: `runtime_api/app/web_search/config.py`
- Modify: `runtime_api/app/main.py`
- Modify: `db/init.sql`
- Test: `runtime_api/tests/test_web_search_settings.py`

- [x] **Step 1: Write failing schema and resolution tests**

Cover:

```python
def test_database_key_overrides_environment_key(monkeypatch): ...
def test_environment_key_is_used_when_database_key_is_absent(monkeypatch): ...
def test_delete_database_key_reveals_environment_fallback(monkeypatch): ...
def test_schema_contains_provider_and_routing_tables(): ...
```

Use a fake psycopg connection that records SQL and returns database rows. Assert `config_source` is exactly `database`, `environment`, or `none`.

- [x] **Step 2: Run tests and confirm missing schema/resolver failures**

Run: `python3 -m pytest -q runtime_api/tests/test_web_search_settings.py -k 'environment or schema or database_key'`
Expected: FAIL because schema/resolution functions are missing.

- [x] **Step 3: Implement schema and resolution**

Add `web_search_provider_config_schema_sql()`, `load_provider_config_records(conn)`, `resolve_provider_configs(conn)`, and `load_routing_config(conn)`. Add the exact two tables from the approved spec to `db/init.sql` and call schema bootstrap from FastAPI lifespan.

- [x] **Step 4: Run focused tests**

Run: `python3 -m pytest -q runtime_api/tests/test_web_search_settings.py -k 'environment or schema or database_key'`
Expected: PASS.

### Task 3: Authenticated Settings API and Atomic Save/Test

**Files:**
- Modify: `runtime_api/app/web_search/config.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_web_search_settings.py`

- [x] **Step 1: Write failing API tests**

Add TestClient tests for:

```python
def test_settings_list_never_returns_plaintext_or_ciphertext(): ...
def test_save_tests_candidate_before_replacing_old_key(): ...
def test_invalid_candidate_does_not_replace_old_key(): ...
def test_test_saved_provider_updates_health_without_changing_key(): ...
def test_enable_requires_effective_key(): ...
def test_delete_database_key_falls_back_to_environment(): ...
def test_routing_order_requires_all_three_unique_slugs(): ...
```

Patch provider connectivity probes, not the persistence behavior. Assert error codes and that candidate keys do not appear in response text.

- [x] **Step 2: Run API tests and verify 404/missing-symbol failures**

Run: `python3 -m pytest -q runtime_api/tests/test_web_search_settings.py -k 'settings_list or candidate or enable_requires or routing_order'`
Expected: FAIL because endpoints are absent.

- [x] **Step 3: Implement connectivity probes**

Add `build_provider_from_key(provider, api_key)`, `test_provider_connection(...)`, and normalized outcomes: `healthy`, `invalid_key`, `rate_limited`, `timeout`, `provider_error`. Use one public query and one result; bypass production cache.

- [x] **Step 4: Implement settings endpoints**

Add:

```text
GET    /api/web-search/settings
PUT    /api/web-search/settings/{provider}
POST   /api/web-search/settings/{provider}/test
PATCH  /api/web-search/settings/{provider}
PATCH  /api/web-search/settings/routing
DELETE /api/web-search/settings/{provider}/key
```

Use transactions for test-then-save. Sanitize all provider errors before returning or persisting. Increment the routing config version only after successful writes.

- [x] **Step 5: Run API tests**

Run: `python3 -m pytest -q runtime_api/tests/test_web_search_settings.py`
Expected: PASS.

### Task 4: Version-Aware Runtime and Smart Routing

**Files:**
- Create: `runtime_api/app/web_search/router.py`
- Modify: `runtime_api/app/web_search/runtime.py`
- Modify: `runtime_api/app/web_search/service.py`
- Modify: `runtime_api/app/main.py`
- Test: `runtime_api/tests/test_web_search_runtime.py`
- Test: `runtime_api/tests/test_web_search_settings.py`

- [x] **Step 1: Write failing single-provider and routing-matrix tests**

```python
@pytest.mark.parametrize("provider", ["exa", "tavily", "bocha"])
def test_single_configured_provider_handles_every_category(provider): ...

@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("technical_docs", ["exa", "tavily", "bocha"]),
        ("fresh_news", ["tavily", "bocha", "exa"]),
        ("china_general", ["bocha", "tavily", "exa"]),
        ("jobs_company", ["exa", "tavily", "bocha"]),
        ("high_stakes_facts", ["exa", "tavily", "bocha"]),
    ],
)
def test_smart_route_order(category, expected): ...
```

Also assert disabled, unconfigured, and `invalid_key` providers are excluded.

- [x] **Step 2: Run routing tests and verify missing-router failure**

Run: `python3 -m pytest -q runtime_api/tests/test_web_search_runtime.py -k 'single_configured or smart_route'`
Expected: FAIL because smart router is absent.

- [x] **Step 3: Implement router**

Create `WebSearchRoutePlan` with category, selected provider names, parallel flag, cross-provider verification requirement, selection reason, and eligible provider list. Implement the approved matrix and single-provider fast path.

- [x] **Step 4: Write failing runtime version tests**

```python
def test_runtime_manager_reuses_service_for_same_version(): ...
def test_runtime_manager_rebuilds_after_redis_version_changes(): ...
def test_runtime_manager_checks_database_when_redis_is_unavailable(): ...
```

- [x] **Step 5: Run tests and verify manager failure**

Run: `python3 -m pytest -q runtime_api/tests/test_web_search_settings.py -k runtime_manager`
Expected: FAIL because `WebSearchRuntimeManager` is absent.

- [x] **Step 6: Implement version-aware runtime manager**

The manager must atomically swap services, preserve in-flight references, reuse Provider rate limiters while version is unchanged, and expose `invalidate(config_version)` after successful settings writes.

- [x] **Step 7: Integrate the manager and route trace**

Replace the static provider singleton path with runtime-manager lookup. Store category, configured/eligible/selected providers, selection reason and fallback events in search response trace/persistence without secrets.

- [x] **Step 8: Run runtime and API tests**

Run: `python3 -m pytest -q runtime_api/tests/test_web_search_runtime.py runtime_api/tests/test_web_search_settings.py`
Expected: PASS.

### Task 5: Settings UI, Compact List, and Provider Detail

**Files:**
- Modify: `runtime_api/app/static/index.html`
- Modify: `runtime_api/app/static/app.js`
- Modify: `runtime_api/app/static/styles.css`
- Create: `runtime_api/tests/test_static_web_search_settings.py`

- [x] **Step 1: Write failing static UI contract tests**

Assert the DOM contains:

```text
assistant settings item -> webSearchSettingsView
webSearchProviderList
webSearchProviderDetail
webSearchKeyInput[type=password]
webSearchSaveAndTest
webSearchTestStored
webSearchDeleteKey
webSearchEnabledToggle
```

Assert JavaScript calls only the settings endpoints and never writes `api_key` to localStorage/sessionStorage.

- [x] **Step 2: Run static tests and verify missing DOM failure**

Run: `python3 -m pytest -q runtime_api/tests/test_static_web_search_settings.py`
Expected: FAIL because the settings UI is absent.

- [x] **Step 3: Implement compact list and detail DOM**

Follow approved option B. Keep Web Search at the same settings hierarchy as Account Connections and Career Board. Do not add controls to the floating window.

- [x] **Step 4: Implement UI state transitions**

Implement load, open detail, save-and-test, test stored, toggle enabled, delete with confirmation, routing-order save, progress state and sanitized error messages. Clear the input on success, close, back, page hide and navigation.

- [x] **Step 5: Add responsive styles**

Use existing industrial visual language, full-width rows, 44px minimum touch targets, no nested cards, masked monospace hint, stable status labels and keyboard-safe vertical scrolling.

- [x] **Step 6: Run static tests**

Run: `python3 -m pytest -q runtime_api/tests/test_static_web_search_settings.py runtime_api/tests/test_static_workbench_agenda_tab.py`
Expected: PASS.

### Task 6: Full Regression, Real Provider Acceptance, and Gap Report

**Files:**
- Modify: `docs/superpowers/specs/2026-07-12-web-search-provider-settings-design.md`
- Create: `docs/superpowers/reports/2026-07-12-web-search-provider-settings-gaps.md`
- Test: `runtime_api/tests/`

- [x] **Step 1: Run full local regression**

Run:

```bash
python3 -m pytest -q runtime_api/tests
python3 -m compileall -q runtime_api/app runtime_api/scripts
docker compose config --quiet
git diff --check
```

Expected: all commands exit 0.

- [x] **Step 2: Scan for secret leakage**

Read the configured test Key from ignored `.env`, scan all committable files, and assert no plaintext match. Also inspect API payload fixtures and generated benchmark summaries for credentials.

- [x] **Step 3: Run available real Provider tests**

- Bocha: save/test, single-provider chat search, benchmark smoke.
- Exa: record blocked if no real Key is configured.
- Tavily: record blocked if no real Key is configured.
- Multi-provider intelligent routing: record blocked until at least two real Provider keys exist.

Do not replace missing real credentials with fake success.

- [x] **Step 4: Update spec implementation status and gap report**

For every requirement, record `completed`, `partially verified`, or `blocked`, with command/trace evidence. Explicitly separate local unit/API tests from cloud and Android real-device verification.

- [ ] **Step 5: Commit implementation slices only after their tests pass**

Use focused commits; never stage unrelated pre-existing workspace changes.
