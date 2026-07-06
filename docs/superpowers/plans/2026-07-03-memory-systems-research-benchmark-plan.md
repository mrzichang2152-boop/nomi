# Memory Systems Research Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evaluate mature open-source agent memory projects against Nomi's real memory failures and produce an evidence-backed Nomi Memory Runtime redesign direction.

**Architecture:** Keep all third-party code in an isolated `research/memory-systems/` directory and do not import it into Nomi production code. Use a common benchmark fixture set representing Nomi's WhatsApp/Gmail/Telegram/LinkedIn memory needs, then inspect each project's data model, retrieval strategy, write lifecycle, cache strategy, scope isolation, and latency posture.

**Tech Stack:** Git shallow clones, Python inspection scripts, Markdown reports, Nomi runtime API probes where needed.

---

## File Structure

- Create: `research/memory-systems/README.md`
  - Explains why these repositories are vendored only for research and must not be imported into runtime code.
- Create: `research/memory-systems/fixtures/nomi_memory_cases.json`
  - Shared Nomi benchmark cases covering identity facts, relative-time agendas, preference memory, cancellation, job intent, and cross-contact isolation.
- Create: `research/memory-systems/scripts/inspect_repos.py`
  - Collects repository metadata and searches for memory, retrieval, graph, cache, and lifecycle implementation files.
- Create: `research/memory-systems/scripts/run_static_benchmark.py`
  - Scores each cloned project against Nomi criteria from static code/docs inspection and fixture suitability.
- Create: `docs/superpowers/reports/2026-07-03-memory-systems-research-report.md`
  - Final evidence report: project-by-project findings, small benchmark results, what to borrow, what not to borrow, and recommended next design step.

## Evaluation Criteria

Each candidate project is scored from 0-3 on:

- **Memory write lifecycle:** Can it extract, merge, update, invalidate, or forget memories instead of only appending text?
- **Temporal correctness:** Can it preserve created time, event time, relative-time resolution, and fact validity windows?
- **Relationship graph:** Can it represent people, relationships, evidence, relation changes, and source-contact scope?
- **Hybrid retrieval:** Can it combine exact/KV, graph, vector, keyword, recency, and rerank in one query path?
- **Routing/planning:** Can it decide whether memory is needed and which memory layer should be queried?
- **Caching:** Does it provide a clear cache layer for repeated stable answers or repeated retrieval.
- **Privacy/scope isolation:** Can it prevent one contact's private facts from leaking into another contact's context?
- **Realtime suitability:** Is it reasonable for sub-second to low-second online chat, or mainly offline/batch?
- **Operational fit:** Can it run on Nomi's private-cloud 4C/8G or 2C/4G target without dragging in a heavy stack?

## Benchmark Fixtures

The benchmark uses these Nomi-style examples:

- Contact-scoped fact: `王超他儿子叫张红`; query `张红是谁？`; expected answer says `张红是王超的儿子` with source contact `王超`.
- User preference: `我想买个你之前说的那个保险`; query `我买保险最关心什么？`; expected answer should mention insurance intent and ask/recall missing preference only if absent.
- Relative event: `明天下午3点半在人民广场见，带合同`; query `人民广场会面是几月几号几点？`; expected answer must use absolute date.
- Cancellation: `明天人民广场那个见面取消了`; query `明天我有哪些安排？`; expected answer must not include cancelled event as active.
- Deadline: `周五18点前把报价单发我，记得核对成本和利润率`; query `周五18点前我要做什么？`; expected answer must mention quote sheet plus cost/profit check.
- Job intent: `帮我找适合我的工作机会`; expected retrieval should include resume/profile/JD context and use LinkedIn/job pipeline rather than generic chat.
- Cross-contact isolation: Contact A says Contact B is unreliable; query while talking to B should not reveal A's private statement.

## Tasks

### Task 1: Create Isolated Research Workspace

**Files:**
- Create: `research/memory-systems/README.md`
- Create: `research/memory-systems/fixtures/nomi_memory_cases.json`

- [ ] **Step 1: Create research directory and README**

Expected README content:

```markdown
# Nomi Memory Systems Research

This directory contains shallow clones and benchmark fixtures for evaluating external memory projects.

Rules:
- Do not import these repositories into Nomi runtime code.
- Do not modify third-party repositories unless explicitly creating a local experiment branch.
- Keep benchmark fixtures Nomi-specific so results map to current production failures.
- Treat benchmark results as evidence for design, not as a direct dependency decision.
```

- [ ] **Step 2: Create Nomi memory fixture JSON**

Expected fixture fields:

```json
{
  "cases": [
    {
      "id": "contact_family_fact",
      "source": "whatsapp",
      "contact": "王超",
      "observed_at": "2026-07-03T14:47:00+08:00",
      "messages": ["王超他儿子叫张红"],
      "query": "张红是谁？",
      "expected": ["张红", "王超", "儿子"],
      "must_not_include": ["用户的儿子"]
    }
  ]
}
```

### Task 2: Clone Candidate Repositories

**Files:**
- Create directories under: `research/memory-systems/repos/`

- [ ] **Step 1: Shallow clone repositories**

Run:

```bash
mkdir -p research/memory-systems/repos
git clone --depth=1 https://github.com/mem0ai/mem0.git research/memory-systems/repos/mem0
git clone --depth=1 https://github.com/getzep/graphiti.git research/memory-systems/repos/graphiti
git clone --depth=1 https://github.com/langchain-ai/langmem.git research/memory-systems/repos/langmem
git clone --depth=1 https://github.com/qdrant/qdrant-alloy.git research/memory-systems/repos/qdrant-alloy
git clone --depth=1 https://github.com/zilliztech/gptcache.git research/memory-systems/repos/gptcache
git clone --depth=1 https://github.com/microsoft/graphrag.git research/memory-systems/repos/graphrag
```

Expected: each directory has a `.git` folder and README.

### Task 3: Static Repository Inspection

**Files:**
- Create: `research/memory-systems/scripts/inspect_repos.py`

- [ ] **Step 1: Write inspection script**

The script must:
- list each repo's current commit,
- detect languages/package manifests,
- search for implementation files containing `memory`, `retrieve`, `graph`, `cache`, `rerank`, `hybrid`, `embed`, `forget`, `namespace`, `scope`, and `temporal`,
- output JSON to `research/memory-systems/results/static_inspection.json`.

- [ ] **Step 2: Run inspection**

Run:

```bash
python3 research/memory-systems/scripts/inspect_repos.py
```

Expected: `static_inspection.json` exists and every cloned repo has non-empty findings.

### Task 4: Nomi-Focused Static Benchmark

**Files:**
- Create: `research/memory-systems/scripts/run_static_benchmark.py`
- Create: `research/memory-systems/results/nomi_static_benchmark.json`

- [ ] **Step 1: Write scoring script**

The script must score each repository from 0-3 for the evaluation criteria and include concrete evidence file paths/snippets for every non-zero score.

- [ ] **Step 2: Run benchmark**

Run:

```bash
python3 research/memory-systems/scripts/run_static_benchmark.py
```

Expected: JSON includes scores, evidence, and Nomi-fit notes for every repository.

### Task 5: Evidence Report

**Files:**
- Create: `docs/superpowers/reports/2026-07-03-memory-systems-research-report.md`

- [ ] **Step 1: Write report**

The report must include:
- source repositories and clone commits,
- project-by-project findings,
- benchmark score table,
- direct applicability to current Nomi failures,
- what to borrow,
- what not to borrow,
- risks and unknowns,
- recommendation for whether the next step is a Nomi Memory Runtime redesign doc or a small code spike.

- [ ] **Step 2: Self-review report**

Check:
- Every recommendation cites evidence from a cloned repo, doc, or benchmark result.
- The report does not recommend importing a large framework without adapter boundaries.
- The report explicitly answers whether to clone/fork/modify these projects or only borrow designs.

## Completion Criteria

- The research workspace exists and is isolated from production imports.
- Candidate repositories are cloned shallowly or marked with a clear clone failure reason.
- Benchmark fixtures are Nomi-specific and cover known failures.
- Static inspection and benchmark results are generated.
- Final report gives a concrete next step backed by evidence.
