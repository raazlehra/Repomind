"""Evaluate retrieval with weighted recall metrics.

Outputs a JSON report per run including recall metrics and context efficiency.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from repomind.database import IndexDatabase
from repomind.formatters import render_context
from repomind.indexer import Indexer
from repomind.memory import add_manual_memory
from repomind.retrieval import ContextRetriever, fit_context_to_budget
from repomind.utils import approximate_tokens


def load_gold(path: Path) -> dict[str, dict[str, list[str]]]:
    # Gold file format: {"task_query": {"primary": [...], "secondary": [...], "tests": [...]}}
    return json.loads(path.read_text())


def compute_metrics(
    selected: list[str],
    gold: dict[str, list[str]],
    baseline_tokens: int,
    selected_tokens: int,
) -> dict[str, float]:
    sel = set(selected)
    primary = set(gold.get("primary", []))
    secondary = set(gold.get("secondary", []))
    tests = set(gold.get("tests", []))

    def frac(a: set[str], b: set[str]) -> float:
        if not b:
            return 1.0
        return len(a & b) / len(b)

    critical_recall = frac(sel, primary)
    secondary_recall = frac(sel, secondary)
    test_recall = frac(sel, tests)

    irrelevant = sel - (primary | secondary | tests)
    noise_ratio = len(irrelevant) / max(1, len(sel))

    context_efficiency = selected_tokens / max(1, baseline_tokens)

    # Composite score rewards recall while penalizing noise.
    retrieval_quality = (
        critical_recall + 0.5 * secondary_recall + 0.5 * test_recall - noise_ratio
    )

    return {
        "critical_recall": critical_recall,
        "secondary_recall": secondary_recall,
        "test_recall": test_recall,
        "noise_ratio": noise_ratio,
        "context_efficiency": context_efficiency,
        "retrieval_quality": retrieval_quality,
    }


def evaluate(
    root: Path,
    gold: dict[str, dict[str, list[str]]],
    baseline_tokens: int,
) -> list[dict[str, object]]:
    idx = Indexer(root)
    idx.initialize(force=True)

    with IndexDatabase(root) as db:
        seed_memory(db)
        retriever = ContextRetriever(db)
        results = []
        for query, labels in gold.items():
            for budget in (500, 1000, 2000, 5000, 10000):
                for level in (1, 2, 3):
                    start = time.time()
                    package = retriever.build_context(query, budget, level)
                    _, rendered = fit_context_to_budget(
                        package, lambda v: render_context(v, "json"), budget
                    )
                    approx = package.get("budget", {}).get("approximate_tokens", None)
                    selected = [f["path"] for f in package.get("relevant_files", [])]
                    selected_tokens = approximate_tokens(rendered)
                    metrics = compute_metrics(selected, labels, baseline_tokens, selected_tokens)
                    context_metrics = package.get("metrics", {})
                    task_context = (
                        context_metrics.get("task_context", {})
                        if isinstance(context_metrics, dict)
                        else {}
                    )
                    memory = package.get("memory", [])
                    results.append(
                        {
                            "repo": str(root),
                            "task": query,
                            "budget": budget,
                            "level": level,
                            "approx_tokens": approx,
                            "files_returned": len(selected),
                            "context_bytes": task_context.get("context_output_bytes", 0),
                            "selected_tokens": selected_tokens,
                            "memory_records": len(memory) if isinstance(memory, list) else 0,
                            "selected_files": selected,
                            "elapsed_ms": int((time.time() - start) * 1000),
                            "metrics": metrics,
                        }
                    )
        return results


def seed_memory(database: IndexDatabase) -> None:
    candidates = (
        (
            "security",
            "Authentication refresh-token behavior is implemented in backend services and routes.",
            ("backend/services.py", "backend/routes.py"),
        ),
        (
            "api",
            "Dashboard API response changes cross backend routes and frontend API clients.",
            ("backend/routes.py", "frontend/src/apiClient.ts", "frontend/src/api.ts"),
        ),
    )
    for category, value, paths in candidates:
        evidence = tuple(path for path in paths if database.file_by_path(path) is not None)
        if not evidence:
            continue
        add_manual_memory(database, value, category, source_paths=evidence)


if __name__ == "__main__":
    gold_dir = Path("benchmarks/gold")
    out = []
    for gold_file in sorted(gold_dir.glob("*.json")):
        repo_name = gold_file.stem
        root = Path("tests/fixtures") / repo_name
        if not root.exists():
            print("Fixture missing for", repo_name, "— skipping", file=sys.stderr)
            continue
        gold = load_gold(gold_file)
        baseline_tokens = approximate_tokens(
            "\n".join(
                [
                    p.read_text(encoding="utf-8", errors="replace")
                    for p in root.rglob("*")
                    if p.is_file()
                ]
            )
        )
        print("Evaluating", root, file=sys.stderr)
        out.extend(evaluate(root, gold, baseline_tokens))

    print(json.dumps(out, indent=2))
