# Nomi Memory Systems Research Report

Date: 2026-07-03

## Executive Summary

I cloned six mature memory/retrieval-related open-source projects into an isolated research workspace and ran a Nomi-focused static benchmark against the real failure modes we have seen: missing WhatsApp facts, relative dates not becoming absolute dates, cancelled events staying active, weak job-context retrieval, repeated slow retrieval, and cross-contact privacy leakage.

The strongest references are:

1. **Graphiti** for temporal relationship graph memory.
2. **mem0** for memory write/update/delete lifecycle and scoped semantic memory.
3. **LangMem** for background memory extraction, namespace design, and memory management patterns.
4. **Qdrant Alloy** for a unified hybrid retrieval substrate, not for memory semantics.
5. **GPTCache** for repeated-answer/model-call caching, not for long-term memory.
6. **GraphRAG** for offline document/job-corpus graph indexing, not for realtime WhatsApp/Gmail hot-path memory.

The recommendation is **not** to fork or heavily modify these projects. Nomi should borrow their designs behind adapter boundaries and build its own `Memory Runtime` because Nomi's hardest requirements are product-specific: private-account scope isolation, per-contact evidence, event-state transitions, proactive suggestions, and realtime Android chat latency.

## Scope And Research Artifacts

Created:

- `research/memory-systems/README.md`
- `research/memory-systems/fixtures/nomi_memory_cases.json`
- `research/memory-systems/scripts/inspect_repos.py`
- `research/memory-systems/scripts/run_static_benchmark.py`
- `research/memory-systems/results/static_inspection.json`
- `research/memory-systems/results/nomi_static_benchmark.json`

Cloned repositories:

| Project | Repository | Commit |
|---|---|---:|
| Graphiti | `https://github.com/getzep/graphiti.git` | `f4330dc` |
| mem0 | `https://github.com/mem0ai/mem0.git` | `cd79fa8` |
| LangMem | `https://github.com/langchain-ai/langmem.git` | `c01e273` |
| GPTCache | `https://github.com/zilliztech/gptcache.git` | `c59fb3a` |
| GraphRAG | `https://github.com/microsoft/graphrag.git` | `6d02c23` |
| Qdrant Alloy | `https://github.com/qdrant/qdrant-alloy.git` | `a5cad5c` |

Important limitation: this pass is a **static and fixture-fit benchmark**, not a full runtime benchmark of each third-party project. I deliberately did not install all their dependency stacks into Nomi's workspace. The next step should be a small runtime spike only for the top candidates, not all six.

## Nomi Benchmark Fixtures

The benchmark cases are based on current Nomi failures and desired behavior:

| Fixture | Purpose |
|---|---|
| `contact_family_fact` | `王超他儿子叫张红` must answer `张红是王超的儿子`, not `用户的儿子`. |
| `insurance_preference` | WhatsApp insurance intent should become retrievable memory instead of returning no record. |
| `relative_event_absolute_date` | `明天下午3点半` must be stored/answered as an absolute date and time. |
| `cancellation` | Cancelled events must not remain active in schedule answers or suggestions. |
| `deadline_quote_sheet` | Deadline task must preserve deliverable plus constraints: quote sheet, cost, profit margin. |
| `job_intent` | Job search must retrieve resume/profile and enter the job pipeline, not generic chat. |
| `cross_contact_isolation` | One contact's private opinion must not leak into another contact's context. |

## Static Score Table

Scale: `0=not present`, `1=limited/reference only`, `2=usable with adaptation`, `3=strong direct reference`.

| Project | Total | Best Use In Nomi | Main Caveat |
|---|---:|---|---|
| Graphiti | 20 | Temporal relationship graph, event validity, evidence-backed graph search. | Likely requires graph DB/runtime adapter; not a drop-in 2C/4G hot path. |
| mem0 | 18 | Memory lifecycle, scoped semantic memory, CRUD, search/rerank patterns. | Its generic memory semantics do not fully solve Nomi's event/contact policy. |
| LangMem | 17 | Background memory extraction, namespace/scoping, memory management tools. | More aligned with LangGraph architecture than Nomi's current stack. |
| GPTCache | 10 | Stable-answer cache and repeated model-call cache. | Does not solve memory extraction, graph, or temporal correctness. |
| GraphRAG | 10 | Offline graph indexing over resumes, JD corpora, documents. | Batch/indexing oriented; not suitable for realtime message ingestion. |
| Qdrant Alloy | 8 | Hybrid retrieval substrate: dense + sparse + late-interaction rerank. | Retrieval only; no memory lifecycle, no relationship semantics. |

## Project Findings

### Graphiti

Best fit: temporal graph memory.

Evidence:

- `graphiti_core/graph_queries.py` defines indexes over `group_id`, `created_at`, `valid_at`, `invalid_at`, and `expired_at`.
- `graphiti_core/driver/kuzu_driver.py` includes schema fields for `group_id`, `valid_at`, and `invalid_at`.
- `README.md` describes querying across time, meaning, and relationships with hybrid retrieval.
- `graphiti_core/decorators.py` handles multiple `group_ids`, which maps well to Nomi's account/contact/user partitioning idea.

Why it matters for Nomi:

- `王超 -> 儿子 -> 张红` is naturally a graph edge with evidence and source contact.
- `明天人民广场见` and `取消了` need event validity transitions, not just appending new text memories.
- `A 说 B 坏话` must be scoped by contact/context; Graphiti's `group_id` is a useful model.

What to borrow:

- Entity/relationship/event graph model.
- Temporal validity fields: `valid_at`, `invalid_at`, `expired_at`.
- Group/scope partitioning.
- Hybrid graph search shape.

What not to borrow directly:

- Do not make Graphiti the synchronous chat hot path immediately.
- Do not require all Nomi memory to live only inside Graphiti before we prove operational cost.

### mem0

Best fit: memory lifecycle and scoped semantic memory.

Evidence:

- `mem0/memory/main.py` requires scope-like identifiers such as `user_id`, `agent_id`, and `run_id`.
- `mem0/memory/main.py` contains `add`, `search`, update/delete cleanup logic, `created_at`, `updated_at`, rerank, hybrid search references, and entity extraction code.
- The project has tests and docs around memory add/search/update behavior.

Why it matters for Nomi:

- Current Nomi memory still behaves too much like "store and retrieve text." mem0 is a stronger reference for "new input updates or replaces older beliefs."
- It offers useful patterns for scoped search filters; Nomi needs stricter scope: user, account, channel, contact, conversation, and source message.

What to borrow:

- Memory CRUD lifecycle.
- Session-scoped metadata and mandatory filters.
- Search/rerank payload structure.
- History of memory changes.

What not to borrow directly:

- Do not let mem0's generic memory model define Nomi's product semantics.
- It does not by itself solve schedule cancellation, proactive reminders, or cross-contact leak policy.

### LangMem

Best fit: memory extraction architecture and namespace model.

Evidence:

- `docs/docs/concepts/conceptual_guide.md` describes semantic/profile/episodic/procedural memory.
- The same guide explicitly discusses collection memory update, delete/invalidate, consolidation, recency/frequency/importance, and hot-path vs background memory formation.
- `docs/docs/hot_path_quickstart.md` documents `create_manage_memory_tool`, `create_search_memory_tool`, and namespace usage.
- `src/langmem/knowledge/extraction.py` and `src/langmem/knowledge/tools.py` show extraction/tool-oriented memory APIs.

Why it matters for Nomi:

- Nomi should not write every memory synchronously during chat; LangMem's hot-path/background split supports the user's earlier idea: receive messages quickly, then batch/consolidate memory.
- Namespaces map well to Nomi's multi-account and per-contact isolation.

What to borrow:

- Background memory extraction and consolidation.
- Memory namespace templates.
- Distinction among semantic, episodic, procedural, and profile memory.

What not to borrow directly:

- Do not force Nomi into LangGraph just to use LangMem concepts.
- Do not expose memory tools to a free-running agent without Nomi's policy gates.

### Qdrant Alloy

Best fit: retrieval substrate.

Evidence:

- `README.md` describes a hybrid search pipeline fusing dense, sparse, and late-interaction embeddings.
- `src/alloy/alloy.py` implements a hybrid approach with dense embeddings, sparse embeddings, and late interaction.
- Config examples include BM25 and Qwen-related embedding/rerank combinations.

Why it matters for Nomi:

- Current Nomi retrieval has scattered KV/graph/RAG/BM25/vector paths. The right end-state is a single `HybridRetriever` interface, even if implemented locally first.
- Job search and resume/JD matching need stronger hybrid retrieval than pure vector recall.

What to borrow:

- Unified retrieve-and-rerank flow.
- Dense + sparse + late-interaction architecture.
- Query-time candidate fusion.

What not to borrow directly:

- It is not a memory system.
- It does not decide whether `张红` is a person, whose son he is, or whether a cancelled meeting is active.

### GPTCache

Best fit: stable-answer and model-call cache.

Evidence:

- `README.md` frames GPTCache as semantic cache for LLM responses.
- It supports exact and similar cache lookup, embeddings, vector stores, similarity evaluation, and cache latency metrics.
- `gptcache/adapter/adapter.py` and manager modules show the cache adapter pattern.

Why it matters for Nomi:

- Repeated stable questions like `张红是谁？`, `人民广场会面是几月几号几点？`, and `明天我有哪些安排？` should not always pay full retrieval + model cost if source evidence has not changed.

What to borrow:

- Semantic cache shape.
- Cache keys that include source evidence version, user id, scope, and policy flags.
- Cache hit/miss latency metrics.

What not to borrow directly:

- Do not cache high-risk or stale-prone answers without evidence-version invalidation.
- It cannot fix extraction errors or missing memories.

### GraphRAG

Best fit: offline corpus graph processing.

Evidence:

- README warns indexing can be expensive.
- `packages/graphrag/graphrag/data_model` includes entity and relationship data models.
- `packages/graphrag/graphrag/query/structured_search/local_search` builds graph-aware local context.
- `prompt_tune` and indexing APIs are oriented toward corpus processing.

Why it matters for Nomi:

- Good reference for batch processing resumes, job descriptions, company pages, and long document folders.
- Less suitable for WhatsApp/Gmail per-message realtime ingestion.

What to borrow:

- Offline graph-building concepts for large document/job corpora.
- Local/global graph search separation.

What not to borrow directly:

- Do not put GraphRAG indexing in the chat hot path.
- Do not use it for every private message event.

## What This Means For Nomi's Current Failures

### Failure: `张红是谁？` sometimes says no record

Root design issue: family/person facts are not consistently promoted into a relationship graph with source contact and evidence.

Borrow:

- Graphiti-style entity/relationship edge with `source_message_id`, `contact_id`, `valid_at`.
- mem0/LangMem-style memory lifecycle to update rather than append.

### Failure: `明天` remains ambiguous

Root design issue: relative-time resolution is not treated as a write-time invariant.

Borrow:

- Graphiti-style temporal fields.
- Nomi-specific rule: every agenda/task event stores `observed_at`, `event_start_at`, `timezone`, `original_time_text`, `resolution_confidence`.

### Failure: cancelled events remain active

Root design issue: schedule memory is append-only instead of stateful.

Borrow:

- Temporal validity (`invalid_at`) and event-state transitions.
- Nomi-specific canonical event table remains the source of truth for active/cancelled/postponed.

### Failure: stable fact questions are slow

Root design issue: repeated retrieval/model work is not cached by evidence version.

Borrow:

- GPTCache-style semantic cache, but with Nomi-specific invalidation by source version.

### Failure: job search says no profile despite resume

Root design issue: career profile/resume/JD retrieval is not a first-class namespace and pipeline context.

Borrow:

- LangMem namespace design for `career/profile`, `career/resumes`, `career/jobs`.
- Qdrant Alloy-style hybrid retrieval for JD/resume matching.
- GraphRAG only for offline indexing of larger job/resume corpora.

### Failure: one contact's context may leak into another

Root design issue: retrieval scope is not strict enough.

Borrow:

- Graphiti `group_id` and LangMem namespace thinking.
- mem0 mandatory filter pattern.

Nomi-specific rule:

- Every memory query must carry a `scope_policy`: `user_private`, `contact_private`, `conversation_private`, `shareable_summary`, or `assistant_operational`.

## Recommended Nomi Memory Runtime Direction

Build Nomi's own `Memory Runtime` with these modules:

1. `MemoryWriteBuffer`
   - Accepts Gmail/WhatsApp/Telegram/LinkedIn/user-chat events quickly.
   - Batches writes and runs extraction asynchronously.
   - Uses priority path for agenda/deadline/urgent facts.

2. `MemoryExtractor`
   - Produces structured candidates: facts, events, tasks, preferences, relationships, cancellations, job signals.
   - Uses rules first for obvious time/task patterns; model only when ambiguous.

3. `TemporalGraphStore`
   - Stores people, organizations, events, relationships, evidence, and validity windows.
   - The first implementation can be Postgres tables; Graphiti-style service can be a later adapter spike.

4. `HybridRetriever`
   - One retrieval entry point.
   - Runs KV/profile lookup, graph lookup, BM25/vector retrieval, agenda lookup, and optional cache lookup behind one interface.
   - Returns a typed evidence bundle, not raw snippets.

5. `MemoryQueryPlanner`
   - Decides whether the query needs memory.
   - Selects namespaces and layers.
   - Carries strict scope policy.

6. `AnswerCache`
   - Caches stable, evidence-backed answers.
   - Invalidates by source event version, memory version, agenda version, and contact scope.

7. `MemoryGovernance`
   - Explains why an answer used or did not use memory.
   - Provides trace ids, source message ids, confidence, and privacy gates.

## Dependency Recommendation

Do not import any of these projects into production immediately.

Use this sequence:

1. **Design Nomi Memory Runtime v2** from the above modules.
2. **Implement a small local Postgres-backed version first** because Nomi already has DB/runtime infrastructure.
3. **Run a two-candidate runtime spike**:
   - Graphiti spike for temporal graph memory.
   - mem0 or LangMem spike for memory lifecycle/background extraction.
4. **Only adopt a dependency through an adapter** if it beats the local implementation on correctness and latency.

## Remaining Research Gaps

These are not done yet:

- Runtime benchmark of Graphiti/mem0/LangMem on the Nomi fixture cases.
- Latency benchmark on a 2C/4G or 4C/8G private server.
- Storage size and migration estimate for existing Nomi memories.
- Security review of external dependency transitive packages.
- Direct comparison against current Nomi `/api/chat` traces after a prototype is implemented.

## Next Step

The next step should be a **Nomi Memory Runtime v2 design document**, not direct code changes.

That design should specify:

- tables/entities,
- write pipeline,
- event-state transitions,
- query planner,
- hybrid retrieval contract,
- cache invalidation,
- privacy scopes,
- trace format,
- acceptance tests using `research/memory-systems/fixtures/nomi_memory_cases.json`.

After the design is approved, implement it in small slices:

1. strict memory scopes,
2. relationship fact extraction,
3. relative-time agenda canonicalization,
4. cancellation state transitions,
5. single retrieval planner,
6. answer cache,
7. Graphiti/mem0/LangMem runtime spike behind adapters.
