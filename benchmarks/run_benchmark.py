from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from repomind.database import IndexDatabase
from repomind.formatters import render_context
from repomind.indexer import Indexer
from repomind.retrieval import ContextRetriever, fit_context_to_budget
from repomind.utils import approximate_tokens

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TASKS_PATH = Path(__file__).with_name("tasks.json")


def run_benchmarks(budget: int = 2000) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    repositories = sorted({str(task["repository"]) for task in tasks})
    repository_metrics: dict[str, dict[str, Any]] = {}
    task_metrics: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="repomind-benchmark-") as temporary:
        temporary_root = Path(temporary)
        working: dict[str, Path] = {}
        for name in repositories:
            destination = temporary_root / name
            shutil.copytree(FIXTURES / name, destination)
            working[name] = destination
            initial = Indexer(destination).initialize()
            # Change one indexed source file to measure a real one-file incremental parse.
            with IndexDatabase(destination) as database:
                changed_row = database.connection.execute(
                    "SELECT path FROM files WHERE purpose='source' ORDER BY path LIMIT 1"
                ).fetchone()
            if changed_row is None:
                raise RuntimeError(f"Fixture {name} has no indexed source file")
            changed_path = destination / str(changed_row["path"])
            changed_path.write_text(
                changed_path.read_text(encoding="utf-8") + "\n# benchmark incremental change\n",
                encoding="utf-8",
            )
            incremental = Indexer(destination).refresh()
            repository_metrics[name] = {
                "indexed_files": initial.indexed_files,
                "index_bytes": incremental.index_bytes,
                "initial_index_seconds": initial.duration_seconds,
                "incremental_index_seconds": incremental.duration_seconds,
                "incremental_files_parsed": incremental.parsed_files,
            }

        for specification in tasks:
            repository = working[str(specification["repository"])]
            task = str(specification["task"])
            expected = {str(path) for path in specification["expected_files"]}
            with IndexDatabase(repository) as database:
                retriever = ContextRetriever(database)
                started = time.perf_counter()
                package = retriever.build_context(task, budget, level=1)
                fitted, output = fit_context_to_budget(
                    package,
                    lambda value: render_context(value, "markdown"),
                    budget,
                )
                latency = time.perf_counter() - started
            retrieved = [str(item["path"]) for item in fitted["relevant_files"]]
            source_bytes = sum(
                (repository / path).stat().st_size
                for path in retrieved
                if (repository / path).is_file()
            )
            snippets = fitted.get("snippets", [])
            source_context_bytes = (
                sum(
                    len(str(item.get("code", "")).encode("utf-8"))
                    for item in snippets
                    if isinstance(item, dict)
                )
                if isinstance(snippets, list)
                else 0
            )
            found = expected & set(retrieved)
            task_metrics.append(
                {
                    "repository": specification["repository"],
                    "task": task,
                    "files_inspected": len(retrieved),
                    "source_context_bytes_retrieved": source_context_bytes,
                    "selected_files_total_bytes": source_bytes,
                    "context_output_bytes": len(output.encode("utf-8")),
                    "approximate_tokens": approximate_tokens(output),
                    "retrieval_latency_seconds": latency,
                    "expected_files": sorted(expected),
                    "retrieved_expected_files": sorted(found),
                    "expected_file_recall": len(found) / len(expected) if expected else 1.0,
                }
            )
    recalls = [float(item["expected_file_recall"]) for item in task_metrics]
    latencies = [float(item["retrieval_latency_seconds"]) for item in task_metrics]
    return {
        "measured_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "budget_tokens": budget,
        },
        "repositories": repository_metrics,
        "tasks": task_metrics,
        "summary": {
            "task_count": len(task_metrics),
            "mean_expected_file_recall": statistics.fmean(recalls),
            "median_retrieval_latency_seconds": statistics.median(latencies),
            "mean_approximate_tokens": statistics.fmean(
                float(item["approximate_tokens"]) for item in task_metrics
            ),
            "total_expected_files": sum(len(item["expected_files"]) for item in task_metrics),
            "total_expected_files_retrieved": sum(
                len(item["retrieved_expected_files"]) for item in task_metrics
            ),
        },
    }


def render_markdown(results: dict[str, Any]) -> str:
    lines = [
        "# RepoMind measured benchmark run",
        "",
        f"Measured at: {results['measured_at']}",
        f"Python: {results['environment']['python']}",
        f"Platform: {results['environment']['platform']}",
        f"Context budget: {results['environment']['budget_tokens']} approximate tokens",
        "",
        "## Repository indexing",
        "",
        "| Fixture | Files | Initial (s) | Incremental (s) | Parsed incrementally | Index bytes |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, item in results["repositories"].items():
        lines.append(
            f"| {name} | {item['indexed_files']} | {item['initial_index_seconds']:.6f} | "
            f"{item['incremental_index_seconds']:.6f} | {item['incremental_files_parsed']} | {item['index_bytes']} |"
        )
    lines.extend(
        [
            "",
            "## Task retrieval",
            "",
            "| Task | Files | Source context bytes | Selected files total bytes | Output bytes | Approx. tokens | Latency (s) | Expected recall |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in results["tasks"]:
        lines.append(
            f"| {item['task']} | {item['files_inspected']} | {item['source_context_bytes_retrieved']} | "
            f"{item['selected_files_total_bytes']} | {item['context_output_bytes']} | "
            f"{item['approximate_tokens']} | {item['retrieval_latency_seconds']:.6f} | "
            f"{item['expected_file_recall']:.3f} |"
        )
    summary = results["summary"]
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Tasks: {summary['task_count']}",
            f"- Expected files retrieved: {summary['total_expected_files_retrieved']}/{summary['total_expected_files']}",
            f"- Mean expected-file recall: {summary['mean_expected_file_recall']:.3f}",
            f"- Median retrieval latency: {summary['median_retrieval_latency_seconds']:.6f} seconds",
            f"- Mean approximate tokens: {summary['mean_approximate_tokens']:.1f}",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RepoMind's synthetic retrieval benchmarks")
    parser.add_argument("--budget", type=int, default=2000)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = run_benchmarks(args.budget)
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
