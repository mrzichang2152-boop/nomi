#!/usr/bin/env python3
"""Static inspection for external memory-system repositories.

The goal is not to judge quality from keyword counts alone. This script creates
a reproducible first-pass map: commits, manifests, language hints, and concrete
files likely to contain memory/retrieval/graph/cache lifecycle logic.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOS = ROOT / "repos"
RESULTS = ROOT / "results"
OUT = RESULTS / "static_inspection.json"

KEYWORDS = [
    "memory",
    "memories",
    "retrieve",
    "retrieval",
    "retriever",
    "graph",
    "cache",
    "rerank",
    "hybrid",
    "embed",
    "embedding",
    "forget",
    "namespace",
    "scope",
    "temporal",
    "episode",
    "entity",
    "relationship",
]

TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".kt",
    ".md",
    ".mdx",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".txt",
}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    ".ruff_cache",
    "target",
}

MANIFESTS = [
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "package.json",
    "pnpm-lock.yaml",
    "Cargo.toml",
    "go.mod",
    "uv.lock",
    "poetry.lock",
]


@dataclass
class Finding:
    path: str
    keyword_hits: dict[str, int]
    first_lines: dict[str, list[int]]


def run_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES


def iter_files(repo: Path):
    for path in repo.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and is_text_file(path):
            yield path


def language_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "javascript",
        ".jsx": "javascript",
        ".rs": "rust",
        ".go": "go",
        ".java": "java",
        ".kt": "kotlin",
        ".md": "markdown",
        ".mdx": "markdown",
        ".toml": "toml",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
    }.get(suffix, "text")


def inspect_file(repo: Path, path: Path) -> Finding | None:
    rel = path.relative_to(repo).as_posix()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    lowered = text.lower()
    hits = {kw: lowered.count(kw) for kw in KEYWORDS if lowered.count(kw)}
    if not hits:
        return None
    first_lines: dict[str, list[int]] = {}
    lines = text.splitlines()
    for kw in hits:
        found: list[int] = []
        needle = kw.lower()
        for idx, line in enumerate(lines, start=1):
            if needle in line.lower():
                found.append(idx)
                if len(found) >= 5:
                    break
        first_lines[kw] = found
    return Finding(path=rel, keyword_hits=hits, first_lines=first_lines)


def inspect_repo(repo: Path) -> dict:
    files = list(iter_files(repo))
    language_counts = Counter(language_for(path) for path in files)
    manifest_files = [m for m in MANIFESTS if (repo / m).exists()]
    findings: list[Finding] = []
    keyword_totals: Counter[str] = Counter()
    keyword_files: defaultdict[str, list[str]] = defaultdict(list)

    for path in files:
        finding = inspect_file(repo, path)
        if finding is None:
            continue
        findings.append(finding)
        for keyword, count in finding.keyword_hits.items():
            keyword_totals[keyword] += count
            keyword_files[keyword].append(finding.path)

    findings.sort(key=lambda item: sum(item.keyword_hits.values()), reverse=True)
    top_findings = [
        {
            "path": item.path,
            "keyword_hits": item.keyword_hits,
            "first_lines": item.first_lines,
        }
        for item in findings[:40]
    ]

    return {
        "name": repo.name,
        "path": str(repo.relative_to(ROOT)),
        "commit": run_git(repo, "rev-parse", "--short", "HEAD"),
        "remote": run_git(repo, "remote", "get-url", "origin"),
        "manifests": manifest_files,
        "language_counts": dict(language_counts.most_common()),
        "keyword_totals": dict(keyword_totals.most_common()),
        "keyword_files": {kw: files[:20] for kw, files in keyword_files.items()},
        "top_findings": top_findings,
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    repos = sorted(path for path in REPOS.iterdir() if (path / ".git").exists())
    result = {
        "repos": [inspect_repo(repo) for repo in repos],
        "keywords": KEYWORDS,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    for repo in result["repos"]:
        print(
            f"{repo['name']}: commit={repo['commit']} "
            f"manifests={','.join(repo['manifests']) or '-'} "
            f"top_keywords={list(repo['keyword_totals'])[:5]}"
        )


if __name__ == "__main__":
    main()
