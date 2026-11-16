"""Owned static release fixture; never builds or runs Go source."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def create_go_fixture(repository: Path) -> None:
    (repository / "gopkg").mkdir()
    (repository / "go.mod").write_text("module example.org/release-smoke\n\ngo 1.24\n", encoding="utf-8")
    (repository / "gopkg/math.go").write_text(
        "package gopkg\nfunc Add(a, b int) int { return a + b }\n", encoding="utf-8"
    )
    (repository / "gopkg/math_test.go").write_text(
        'package gopkg\nimport "testing"\nfunc TestAdd(t *testing.T) { if Add(2, 3) != 5 { t.Fatal("sum") } }\n',
        encoding="utf-8",
    )


def assert_go_plan(payload: Any, *, supported: bool = True) -> None:
    if payload.get("schema_version") != "repomind.test-impact.v1":
        raise RuntimeError("Go fixture changed the report schema identity")
    commands = [item for item in payload["recommended_commands"] if item["framework"] == "go"]
    capability = payload["capabilities"]["by_language"]["go"]["test_selection_supported"]
    if capability is not supported:
        raise RuntimeError("Go fixture capability does not match the installed release")
    if supported:
        if len(commands) != 1 or commands[0]["argv"] != ["go", "test", "./gopkg"] or commands[0]["working_directory"] != ".":
            raise RuntimeError("Go fixture produced an unexpected package command")
        if not any(t["file"] == "gopkg/math_test.go" and t["coverage"] == "unknown" for t in payload["existing_tests"]):
            raise RuntimeError("Go fixture lost package test evidence/unknown coverage")
    elif commands:
        raise RuntimeError("Historical baseline invented Go command recommendations")
