#!/usr/bin/env python3
"""Nomi-fit static benchmark for candidate memory projects.

This is intentionally conservative: scores are not a claim that a project works
for Nomi out of the box. They identify which ideas are worth borrowing or
spiking behind an adapter.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSPECTION = ROOT / "results" / "static_inspection.json"
FIXTURES = ROOT / "fixtures" / "nomi_memory_cases.json"
OUT = ROOT / "results" / "nomi_static_benchmark.json"

CRITERIA = [
    "memory_write_lifecycle",
    "temporal_correctness",
    "relationship_graph",
    "hybrid_retrieval",
    "routing_planning",
    "caching",
    "privacy_scope_isolation",
    "realtime_suitability",
    "operational_fit",
]

PROJECT_PROFILES = {
    "mem0": {
        "scores": {
            "memory_write_lifecycle": 3,
            "temporal_correctness": 2,
            "relationship_graph": 2,
            "hybrid_retrieval": 2,
            "routing_planning": 2,
            "caching": 1,
            "privacy_scope_isolation": 2,
            "realtime_suitability": 2,
            "operational_fit": 2,
        },
        "evidence_terms": {
            "memory_write_lifecycle": ["add", "update", "delete", "history", "memory"],
            "temporal_correctness": ["temporal", "created_at", "updated_at"],
            "relationship_graph": ["graph", "entity", "relationship"],
            "hybrid_retrieval": ["hybrid", "rerank", "embedding"],
            "routing_planning": ["retrieve", "retrieval", "memory"],
            "caching": ["cache"],
            "privacy_scope_isolation": ["scope", "user_id", "agent_id", "run_id"],
            "realtime_suitability": ["search", "add", "memory"],
            "operational_fit": ["pyproject", "memory"],
        },
        "nomi_fit": "Strong reference for memory CRUD/lifecycle and user-scoped semantic memory, but should be wrapped instead of embedded wholesale.",
    },
    "graphiti": {
        "scores": {
            "memory_write_lifecycle": 3,
            "temporal_correctness": 3,
            "relationship_graph": 3,
            "hybrid_retrieval": 3,
            "routing_planning": 2,
            "caching": 1,
            "privacy_scope_isolation": 2,
            "realtime_suitability": 2,
            "operational_fit": 1,
        },
        "evidence_terms": {
            "memory_write_lifecycle": ["add_episode", "episode", "invalidate", "edge"],
            "temporal_correctness": ["temporal", "valid_at", "invalid_at", "reference_time"],
            "relationship_graph": ["entity", "relationship", "edge", "node"],
            "hybrid_retrieval": ["hybrid", "rerank", "search"],
            "routing_planning": ["search", "query", "center_node"],
            "caching": ["cache"],
            "privacy_scope_isolation": ["group_id", "namespace", "scope"],
            "realtime_suitability": ["add_episode", "search"],
            "operational_fit": ["neo4j", "falkor", "graph"],
        },
        "nomi_fit": "Best conceptual match for temporal relationship memory and evidence-backed graph search; operational cost needs an adapter/spike.",
    },
    "langmem": {
        "scores": {
            "memory_write_lifecycle": 3,
            "temporal_correctness": 1,
            "relationship_graph": 2,
            "hybrid_retrieval": 1,
            "routing_planning": 2,
            "caching": 1,
            "privacy_scope_isolation": 3,
            "realtime_suitability": 2,
            "operational_fit": 2,
        },
        "evidence_terms": {
            "memory_write_lifecycle": ["memory", "extract", "update", "delete"],
            "temporal_correctness": ["episode", "time", "temporal"],
            "relationship_graph": ["knowledge", "graph", "relationship"],
            "hybrid_retrieval": ["retrieve", "embedding"],
            "routing_planning": ["reflection", "tool", "extract"],
            "caching": ["cache"],
            "privacy_scope_isolation": ["namespace", "scope"],
            "realtime_suitability": ["hot_path", "tool", "memory"],
            "operational_fit": ["pyproject", "langgraph"],
        },
        "nomi_fit": "Good reference for extraction/reflection and namespace-scoped memory tools, especially if Nomi later aligns with LangGraph patterns.",
    },
    "qdrant-alloy": {
        "scores": {
            "memory_write_lifecycle": 0,
            "temporal_correctness": 0,
            "relationship_graph": 0,
            "hybrid_retrieval": 3,
            "routing_planning": 1,
            "caching": 0,
            "privacy_scope_isolation": 0,
            "realtime_suitability": 2,
            "operational_fit": 2,
        },
        "evidence_terms": {
            "hybrid_retrieval": ["hybrid", "rerank", "embedding"],
            "routing_planning": ["retrieve", "retrieval"],
            "realtime_suitability": ["retrieve", "hybrid"],
            "operational_fit": ["qdrant", "config"],
        },
        "nomi_fit": "Useful as a retrieval substrate reference only; it does not solve memory lifecycle or graph semantics.",
    },
    "gptcache": {
        "scores": {
            "memory_write_lifecycle": 0,
            "temporal_correctness": 0,
            "relationship_graph": 0,
            "hybrid_retrieval": 1,
            "routing_planning": 0,
            "caching": 3,
            "privacy_scope_isolation": 1,
            "realtime_suitability": 3,
            "operational_fit": 2,
        },
        "evidence_terms": {
            "hybrid_retrieval": ["embedding", "similarity", "rerank"],
            "caching": ["cache", "adapter", "manager"],
            "privacy_scope_isolation": ["namespace"],
            "realtime_suitability": ["cache", "adapter"],
            "operational_fit": ["requirements", "cache"],
        },
        "nomi_fit": "Good reference for repeated-answer and model-call caching; not a memory system for facts, schedules, or relationships.",
    },
    "graphrag": {
        "scores": {
            "memory_write_lifecycle": 1,
            "temporal_correctness": 0,
            "relationship_graph": 3,
            "hybrid_retrieval": 2,
            "routing_planning": 1,
            "caching": 1,
            "privacy_scope_isolation": 1,
            "realtime_suitability": 0,
            "operational_fit": 1,
        },
        "evidence_terms": {
            "memory_write_lifecycle": ["indexing", "operation"],
            "relationship_graph": ["entity", "relationship", "graph"],
            "hybrid_retrieval": ["local_search", "context", "embedding"],
            "routing_planning": ["query", "search"],
            "caching": ["cache"],
            "privacy_scope_isolation": ["scope"],
            "operational_fit": ["indexing", "pipeline"],
        },
        "nomi_fit": "Valuable for offline corpus graph construction and query composition; too batch-oriented for Nomi's hot chat path.",
    },
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_snippet(repo_root: Path, rel_path: str, line: int, radius: int = 1) -> str:
    path = repo_root / rel_path
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    snippet_lines = []
    for idx in range(start, end + 1):
        text = lines[idx - 1].strip()
        if text:
            snippet_lines.append(f"L{idx}: {text[:220]}")
    return " | ".join(snippet_lines)


def find_evidence(repo: dict, criterion: str, terms: list[str]) -> list[dict]:
    root = ROOT / repo["path"]
    evidence = []
    for finding in repo["top_findings"]:
        matched_terms = []
        line_candidates = []
        for term in terms:
            for keyword, lines in finding.get("first_lines", {}).items():
                if term.lower() in keyword.lower() or keyword.lower() in term.lower():
                    matched_terms.append(keyword)
                    line_candidates.extend(lines[:1])
        if not matched_terms:
            path_l = finding["path"].lower()
            matched_terms = [term for term in terms if term.lower() in path_l]
        if matched_terms:
            line = line_candidates[0] if line_candidates else 1
            evidence.append(
                {
                    "path": finding["path"],
                    "line": line,
                    "matched_terms": sorted(set(matched_terms))[:6],
                    "snippet": read_snippet(root, finding["path"], line),
                }
            )
        if len(evidence) >= 3:
            break
    return evidence


def fixture_coverage(project: str) -> dict[str, str]:
    if project == "graphiti":
        return {
            "strong": "contact_family_fact, relative_event_absolute_date, cancellation, cross_contact_isolation",
            "weak": "answer caching and lightweight operation on 2C/4G",
        }
    if project == "mem0":
        return {
            "strong": "contact_family_fact, insurance_preference, deadline_quote_sheet",
            "weak": "strict temporal event state and cross-contact leakage need Nomi-side policy",
        }
    if project == "langmem":
        return {
            "strong": "namespace-scoped extraction and memory update workflows",
            "weak": "less direct support for temporal graph/event cancellation",
        }
    if project == "qdrant-alloy":
        return {
            "strong": "single hybrid retrieval substrate for job_intent and semantic facts",
            "weak": "does not decide memory lifecycle or relationship semantics",
        }
    if project == "gptcache":
        return {
            "strong": "repeated stable questions after the first correct answer",
            "weak": "cannot fix extraction or missing memory by itself",
        }
    if project == "graphrag":
        return {
            "strong": "offline graph summaries over documents/resumes/job corpora",
            "weak": "not suitable for per-message realtime WhatsApp/Gmail ingestion",
        }
    return {"strong": "", "weak": ""}


def main() -> None:
    inspection = load_json(INSPECTION)
    fixtures = load_json(FIXTURES)
    results = []
    for repo in inspection["repos"]:
        profile = PROJECT_PROFILES[repo["name"]]
        criteria = {}
        for criterion in CRITERIA:
            score = profile["scores"].get(criterion, 0)
            criteria[criterion] = {
                "score": score,
                "evidence": find_evidence(
                    repo,
                    criterion,
                    profile.get("evidence_terms", {}).get(criterion, []),
                )
                if score
                else [],
            }
        total = sum(item["score"] for item in criteria.values())
        results.append(
            {
                "name": repo["name"],
                "commit": repo["commit"],
                "remote": repo["remote"],
                "total_score": total,
                "criteria": criteria,
                "nomi_fit": profile["nomi_fit"],
                "fixture_coverage": fixture_coverage(repo["name"]),
            }
        )

    results.sort(key=lambda item: item["total_score"], reverse=True)
    output = {
        "criteria_scale": "0=not present, 1=limited/reference only, 2=usable with adaptation, 3=strong direct reference",
        "fixture_count": len(fixtures["cases"]),
        "fixtures": [case["id"] for case in fixtures["cases"]],
        "results": results,
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    for item in results:
        print(f"{item['name']}: total={item['total_score']} commit={item['commit']}")


if __name__ == "__main__":
    main()
