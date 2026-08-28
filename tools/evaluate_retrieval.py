import json
import sys
import time
from pathlib import Path

from repomind.database import IndexDatabase
from repomind.formatters import render_context
from repomind.indexer import Indexer
from repomind.retrieval import ContextRetriever, fit_context_to_budget


def index_repo(root: Path) -> None:
    idx = Indexer(root)
    idx.initialize(force=True)


def evaluate(root: Path, tasks: list[dict]):
    with IndexDatabase(root) as db:
        retriever = ContextRetriever(db)
        results = []
        for task in tasks:
            for budget in (500, 1000, 2000, 5000):
                for level in (1, 2, 3):
                    start = time.time()
                    package = retriever.build_context(task["query"], budget, level)
                    _, rendered = fit_context_to_budget(
                        package, lambda v: render_context(v, "json"), budget
                    )
                    approx = package.get("budget", {}).get("approximate_tokens", None)
                    selected = [f["path"] for f in package.get("relevant_files", [])]
                    context_metrics = package.get("metrics", {})
                    task_context = (
                        context_metrics.get("task_context", {})
                        if isinstance(context_metrics, dict)
                        else {}
                    )
                    results.append(
                        {
                            "repo": str(root),
                            "task": task["query"],
                            "budget": budget,
                            "level": level,
                            "approx_tokens": approx,
                            "files_returned": len(selected),
                            "context_bytes": task_context.get("context_output_bytes", 0),
                            "estimated_context_tokens": task_context.get(
                                "estimated_context_tokens", approx
                            ),
                            "selected_files": selected,
                            "elapsed_ms": int((time.time() - start) * 1000),
                        }
                    )
        return results


if __name__ == "__main__":
    fixtures = [
        (Path("tests/fixtures/realistic_a_backend"), [{"query": "fix authentication refresh token"}]),
        (Path("tests/fixtures/realistic_b_frontend"), [{"query": "Fix dashboard showing stale data"}]),
        (Path("tests/fixtures/realistic_c_fullstack"), [{"query": "Change dashboard API response"}]),
    ]
    all_results = []
    for root, tasks in fixtures:
        print("Indexing:", root, file=sys.stderr)
        try:
            index_repo(root)
        except Exception as exc:
            print("Index failed:", exc, file=sys.stderr)
            continue
        all_results.extend(evaluate(root, tasks))
    print(json.dumps(all_results, indent=2))
