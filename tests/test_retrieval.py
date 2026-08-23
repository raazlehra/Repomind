from __future__ import annotations

import json
from pathlib import Path

from repomind.database import IndexDatabase
from repomind.formatters import render_context
from repomind.indexer import Indexer
from repomind.map import build_repository_map, render_repository_map
from repomind.retrieval import ContextRetriever, fit_context_to_budget
from repomind.utils import approximate_tokens


def test_task_ranking_prefers_auth_files(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    with IndexDatabase(python_repo) as database:
        ranked = ContextRetriever(database).rank_files("fix login refresh token bug")
    top_paths = {item.path for item in ranked[:4]}
    assert "app/auth.py" in top_paths
    assert "app/routes.py" in top_paths


def test_context_budget_drops_records_not_text(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    with IndexDatabase(python_repo) as database:
        package = ContextRetriever(database).build_context(
            "add password reset functionality", 500, 3
        )
        fitted, rendered = fit_context_to_budget(
            package, lambda data: render_context(data, "markdown"), 500
        )
    assert approximate_tokens(rendered) <= 500
    assert fitted["relevant_files"]
    assert "Source authority" in rendered
    assert not rendered.endswith("...")


def test_context_json_and_progressive_levels(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    with IndexDatabase(python_repo) as database:
        level_one = ContextRetriever(database).build_context("login", 2000, 1)
        level_two = ContextRetriever(database).build_context("login", 2000, 2)
        level_three = ContextRetriever(database).build_context("login", 5000, 3)
    assert "imports" not in level_one
    assert "imports" in level_two
    assert "snippets" in level_three
    assert json.loads(render_context(level_one, "json"))["task"] == "login"


def test_repository_map_depth_symbols_and_json(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    with IndexDatabase(python_repo) as database:
        shallow = build_repository_map(database, depth=1, symbols=False)
        deep = build_repository_map(database, symbols=True)
    assert all("/" not in item["path"] for item in shallow)
    assert any(item.get("symbols") for item in deep)
    assert "files" in json.loads(render_repository_map(deep, "json"))
