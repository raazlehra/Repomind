from __future__ import annotations

import json
from pathlib import Path

from repomind.cli import main
from repomind.context_pack import bounded_reduction
from repomind.database import IndexDatabase
from repomind.formatters import render_context
from repomind.freshness import ensure_index_fresh
from repomind.indexer import Indexer
from repomind.intent import classify_task_intent
from repomind.retrieval import ContextRetriever, fit_context_to_budget


def test_intent_classification_broad_signals() -> None:
    assert classify_task_intent("fix refresh token bug") == ["bug_fix", "security"]
    assert classify_task_intent("add invoice export endpoint") == ["feature", "api_change"]
    assert classify_task_intent("add migration for user table") == [
        "feature",
        "database_change",
    ]
    assert classify_task_intent("write tests for auth") == ["security", "test"]
    assert classify_task_intent("trace obscure behavior") == ["unknown"]


def test_context_pack_groups_budget_and_metrics(python_repo: Path) -> None:
    Indexer(python_repo).initialize()

    with IndexDatabase(python_repo) as database:
        package = ContextRetriever(database).build_context(
            "fix login refresh token bug", 1000, 1
        )

    assert package["intent"]["labels"] == ["bug_fix", "security"]
    assert package["primary_files"]
    assert package["budget"]["requested_tokens"] == 1000
    assert "method" in package["budget"]
    assert package["metrics"]["repository"]["indexed_files"] > 0
    assert package["metrics"]["task_context"]["candidate_files_considered"] > 0
    assert 0 <= package["metrics"]["reduction"]["file_reduction_percent"] <= 100
    assert all("explanations" not in item for item in package["relevant_files"])
    assert all("score_breakdown" not in item for item in package["relevant_files"])


def test_context_explanations_are_opt_in_and_structured(python_repo: Path) -> None:
    Indexer(python_repo).initialize()

    with IndexDatabase(python_repo) as database:
        retriever = ContextRetriever(database)
        normal = retriever.build_context("fix login refresh token bug", 2000, 1)
        explained = retriever.build_context(
            "fix login refresh token bug", 2000, 1, explain=True
        )

    assert "explanations" not in normal["relevant_files"][0]
    top = explained["relevant_files"][0]
    assert top["explanations"]
    assert top["score_breakdown"]
    rendered = render_context(explained, "markdown")
    assert "score breakdown:" in rendered


def test_fit_context_updates_render_metrics_and_truncation(python_repo: Path) -> None:
    Indexer(python_repo).initialize()

    with IndexDatabase(python_repo) as database:
        package = ContextRetriever(database).build_context(
            "add password reset functionality", 500, 3, explain=True
        )
        fitted, rendered = fit_context_to_budget(
            package, lambda data: render_context(data, "markdown"), 500
        )

    assert fitted["metrics"]["task_context"]["context_output_bytes"] == len(
        rendered.encode("utf-8")
    )
    assert fitted["metrics"]["task_context"]["estimated_context_tokens"] <= 500
    assert isinstance(fitted["budget"]["truncated"], bool)


def test_fit_context_metrics_are_present_when_first_render_fits(python_repo: Path) -> None:
    Indexer(python_repo).initialize()

    with IndexDatabase(python_repo) as database:
        package = ContextRetriever(database).build_context("login", 2000, 1)
        _, rendered = fit_context_to_budget(
            package, lambda data: render_context(data, "json"), 2000
        )

    data = json.loads(rendered)
    assert data["metrics"]["task_context"]["context_output_bytes"] > 0
    assert data["metrics"]["task_context"]["estimated_context_tokens"] > 0


def test_metrics_handle_zero_denominator_without_negative_values() -> None:
    assert bounded_reduction(0, 10) == 0.0
    assert bounded_reduction(10, 20) == 0.0


def test_incremental_reuse_metrics_for_unchanged_and_modified_files(python_repo: Path) -> None:
    Indexer(python_repo).initialize()

    fresh = ensure_index_fresh(python_repo).as_dict()
    assert fresh["files_reparsed"] == 0
    assert fresh["files_reused"] == fresh["files_scanned"]

    target = python_repo / "app" / "auth.py"
    target.write_text(
        target.read_text(encoding="utf-8") + "\ndef reuse_metric_probe() -> None:\n    pass\n",
        encoding="utf-8",
    )
    changed = ensure_index_fresh(python_repo).as_dict()

    assert changed["files_reparsed"] == 1
    assert changed["files_reused"] == changed["files_scanned"] - 1


def test_cli_context_explain_and_stats_json(python_repo: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["init", str(python_repo), "--format", "json"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "context",
                "fix login refresh token bug",
                "-C",
                str(python_repo),
                "--explain",
                "--format",
                "json",
            ]
        )
        == 0
    )
    explained = json.loads(capsys.readouterr().out)
    assert explained["relevant_files"][0]["explanations"]
    assert explained["metrics"]["task_context"]["estimated_context_tokens"] > 0

    assert main(["stats", "-C", str(python_repo), "--format", "json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["title"] == "RepoMind Repository Intelligence"
    assert stats["estimated_repository_tokens"] > 0
