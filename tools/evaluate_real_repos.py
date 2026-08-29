"""Run privacy-preserving real-repository validation.

The input spec must define expected files before measuring RepoMind output. Results contain
paths and metrics only; source code and snippets are never written to the report.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repomind import __version__
from repomind.context_pack import TOKEN_ESTIMATION_METHOD, estimate_tokens_from_bytes
from repomind.database import IndexDatabase
from repomind.formatters import render_context
from repomind.indexer import Indexer
from repomind.memory import memory_counts
from repomind.retrieval import ContextRetriever, fit_context_to_budget


def load_spec(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("validation spec must be a JSON object")
    if not data.get("repository"):
        raise ValueError("validation spec requires repository")
    if not data.get("repository_id"):
        raise ValueError("validation spec requires anonymous repository_id")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("validation spec requires at least one task")
    for index, task in enumerate(tasks, start=1):
        if not isinstance(task, dict):
            raise ValueError(f"task {index} must be an object")
        if not task.get("query"):
            raise ValueError(f"task {index} requires query")
        expected = task.get("expected_files")
        if (
            not isinstance(expected, list)
            or not expected
            or not all(isinstance(item, str) for item in expected)
        ):
            raise ValueError(f"task {index} requires expected_files as a non-empty list of strings")
    return data


def run_validation(spec: dict[str, Any]) -> dict[str, Any]:
    repository = Path(str(spec["repository"])).expanduser().resolve()
    budget = int(spec.get("budget", 2000))
    level = int(spec.get("level", 1))
    if level not in (1, 2, 3):
        raise ValueError("level must be 1, 2, or 3")

    start_index = time.perf_counter()
    index_result = Indexer(repository).initialize(force=bool(spec.get("force_reindex", True)))
    indexing_seconds = time.perf_counter() - start_index

    with IndexDatabase(repository) as database:
        repository_metrics = _repository_metrics(database, spec, index_result.indexed_files)
        retriever = ContextRetriever(database)
        task_results = [
            _measure_task(database, retriever, task, budget=budget, level=level)
            for task in spec["tasks"]
        ]

    recalls = [float(item["expected_file_recall"]) for item in task_results]
    latencies = [float(item["retrieval_latency_seconds"]) for item in task_results]
    total_expected = sum(len(item["expected_important_files"]) for item in task_results)
    total_hits = sum(len(item["expected_file_hits"]) for item in task_results)
    return {
        "schema_version": 1,
        "privacy": {
            "source_code_stored": False,
            "secrets_stored": False,
            "automatic_upload": False,
            "token_counts_are_estimates": True,
            "provider_credit_savings_claimed": False,
        },
        "measured_at": datetime.now(UTC).isoformat(),
        "repository": repository_metrics,
        "run": {
            "budget": budget,
            "level": level,
            "indexing_seconds": indexing_seconds,
        },
        "tasks": task_results,
        "summary": {
            "task_count": len(task_results),
            "total_expected_files": total_expected,
            "total_expected_file_hits": total_hits,
            "mean_expected_file_recall": statistics.fmean(recalls) if recalls else 1.0,
            "median_retrieval_latency_seconds": statistics.median(latencies) if latencies else 0.0,
        },
    }


def render_markdown(results: dict[str, Any]) -> str:
    repo = results["repository"]
    summary = results["summary"]
    lines = [
        "# RepoMind real-world validation",
        "",
        "This report is sanitized by design. It records repository metadata, file paths, and",
        "provider-neutral estimates, but not repository source code, snippets, secrets, or uploads.",
        "",
        "## Repository",
        "",
        f"- Anonymous repository ID: `{repo['repository_id']}`",
        f"- Language/framework: {repo['language_framework']}",
        f"- Indexed files: {repo['indexed_file_count']}",
        f"- Indexed text bytes: {repo['indexed_text_bytes']}",
        f"- Approximate repository tokens: {repo['approximate_repository_tokens']}",
        f"- Token estimation method: {repo['token_estimation_method']}",
        f"- RepoMind version: {repo['repomind_version']}",
        f"- OS: {repo['os']}",
        f"- Python: {repo['python_version']}",
        "",
        "## Tasks",
        "",
        "| Task | Expected | Returned | Hits | Recall | Approx. context tokens | Represented-context reduction | Latency (s) | Memory facts | Notes/noise |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for task in results["tasks"]:
        lines.append(
            f"| {task['task_query']} | {len(task['expected_important_files'])} | "
            f"{task['files_returned_count']} | {len(task['expected_file_hits'])} | "
            f"{task['expected_file_recall']:.3f} | {task['approximate_context_tokens']} | "
            f"{task['represented_context_reduction_percent']:.2f}% | "
            f"{task['retrieval_latency_seconds']:.6f} | {task['memory_facts_included_count']} | "
            f"{_markdown_cell(str(task.get('notes_noise', '')))} |"
        )
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Tasks: {summary['task_count']}",
            f"- Expected files retrieved: {summary['total_expected_file_hits']}/{summary['total_expected_files']}",
            f"- Mean expected-file recall: {summary['mean_expected_file_recall']:.3f}",
            f"- Median retrieval latency: {summary['median_retrieval_latency_seconds']:.6f} seconds",
            "",
            "## Per-task file lists",
            "",
        ]
    )
    for task in results["tasks"]:
        lines.extend(
            [
                f"### {task['task_query']}",
                "",
                "Expected important files:",
                "",
                *[f"- `{path}`" for path in task["expected_important_files"]],
                "",
                "Files returned by RepoMind:",
                "",
                *[f"- `{path}`" for path in task["files_returned_by_repomind"]],
                "",
                "Expected-file hits:",
                "",
                *[f"- `{path}`" for path in task["expected_file_hits"]],
                "",
            ]
        )
    return "\n".join(lines)


def _repository_metrics(
    database: IndexDatabase, spec: dict[str, Any], indexed_files: int
) -> dict[str, Any]:
    row = database.connection.execute(
        "SELECT COALESCE(SUM(size), 0) AS indexed_text_bytes FROM files"
    ).fetchone()
    indexed_text_bytes = int(row["indexed_text_bytes"]) if row else 0
    return {
        "repository_id": str(spec["repository_id"]),
        "language_framework": str(spec.get("language_framework", "unspecified")),
        "indexed_file_count": indexed_files,
        "indexed_text_bytes": indexed_text_bytes,
        "approximate_repository_tokens": estimate_tokens_from_bytes(indexed_text_bytes),
        "token_estimation_method": TOKEN_ESTIMATION_METHOD,
        "repomind_version": __version__,
        "os": platform.platform(),
        "python_version": platform.python_version(),
    }


def _measure_task(
    database: IndexDatabase,
    retriever: ContextRetriever,
    task: dict[str, Any],
    *,
    budget: int,
    level: int,
) -> dict[str, Any]:
    query = str(task["query"])
    expected = [str(path).replace("\\", "/") for path in task["expected_files"]]
    started = time.perf_counter()
    package = retriever.build_context(query, budget, level=level, explain=True)
    fitted, rendered = fit_context_to_budget(package, lambda value: render_context(value, "json"), budget)
    latency = time.perf_counter() - started
    returned = [str(item["path"]) for item in fitted.get("relevant_files", [])]
    hits = sorted(set(expected) & set(returned))
    context_metrics = fitted.get("metrics", {})
    task_context = context_metrics.get("task_context", {}) if isinstance(context_metrics, dict) else {}
    reduction = context_metrics.get("reduction", {}) if isinstance(context_metrics, dict) else {}
    memory = fitted.get("memory", [])
    counts = memory_counts(database)
    return {
        "task_query": query,
        "expected_important_files": expected,
        "files_returned_by_repomind": returned,
        "expected_file_hits": hits,
        "expected_file_recall": len(hits) / len(expected) if expected else 1.0,
        "files_returned_count": len(returned),
        "approximate_context_tokens": task_context.get(
            "estimated_context_tokens", _approximate_tokens_from_rendered(rendered)
        ),
        "approximate_repository_tokens": estimate_tokens_from_bytes(
            int(
                database.connection.execute(
                    "SELECT COALESCE(SUM(size), 0) AS indexed_text_bytes FROM files"
                ).fetchone()["indexed_text_bytes"]
            )
        ),
        "represented_context_reduction_percent": float(
            reduction.get("context_volume_reduction_percent", 0.0)
        ),
        "retrieval_latency_seconds": latency,
        "memory_facts_included_count": len(memory) if isinstance(memory, list) else 0,
        "memory_facts_total_count": counts["total"],
        "notes_noise": str(task.get("notes", "")),
    }


def _approximate_tokens_from_rendered(rendered: str) -> int:
    return max(1, len(rendered) // 4)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run privacy-preserving RepoMind validation on a real repository"
    )
    parser.add_argument("--spec", required=True, type=Path, help="validation spec JSON")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path, help="write report to this path")
    args = parser.parse_args()

    results = run_validation(load_spec(args.spec))
    rendered = (
        json.dumps(results, indent=2) + "\n" if args.format == "json" else render_markdown(results)
    )
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
