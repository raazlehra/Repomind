from __future__ import annotations

from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.queries import callers, dependencies, impact, snippets, symbol_details


def test_symbol_callers_dependencies_and_snippets(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    with IndexDatabase(python_repo) as database:
        details = symbol_details(database, "AuthService.login")
        caller_data = callers(database, "AuthService.login")
        dependency_data = dependencies(database, "app/routes.py")
        snippet_data = snippets(database, "AuthService.login")
    assert details["matches"][0]["file"] == "app/auth.py"
    assert any(item["file"] == "app/routes.py" for item in caller_data["callers"])
    assert any(item["file"] == "app/auth.py" for item in dependency_data["dependencies"])
    assert "def login" in snippet_data["snippets"][0]["code"]


def test_change_impact_distinguishes_direct_tests_and_routes(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    with IndexDatabase(python_repo) as database:
        data = impact(database, "AuthService.login")
    direct_files = {item["file"] for item in data["direct_dependents"]}
    assert "app/routes.py" in direct_files
    assert all(
        item["confidence"] in {"high", "medium", "low"} for item in data["direct_dependents"]
    )
    assert isinstance(data["possible_indirect_dependents"], list)
    assert all(
        item["classification"] in {"direct", "heuristic"} for item in data["routes_likely_affected"]
    )
