from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from repomind.cli import main
from repomind.indexer import Indexer
from repomind.mcp import create_server


async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with Client(create_server()) as client:
        result = await client.call_tool(name, arguments)
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    return result.structured_content


@pytest.mark.anyio
async def test_mcp_server_startup_and_status(python_repo: Path) -> None:
    Indexer(python_repo).initialize(force=True)

    async with Client(create_server()) as client:
        tools_result = await client.list_tools()
        tools = tools_result.tools
        tool_names = {tool.name for tool in tools}
        status = await client.call_tool("repomind_status", {"repository": str(python_repo)})

    assert {
        "repomind_status",
        "repomind_context",
        "repomind_symbol",
        "repomind_callers",
        "repomind_dependencies",
        "repomind_impact",
        "repomind_snippets",
        "repomind_refresh",
        "repomind_map",
    }.issubset(tool_names)
    assert status.structured_content["initialized"] is True
    assert status.structured_content["index_health"] == "ok"
    assert status.structured_content["indexed_file_count"] > 0


@pytest.mark.anyio
async def test_mcp_context_and_cli_equivalence(mixed_repo: Path, capsys: Any) -> None:
    Indexer(mixed_repo).initialize(force=True)
    task = "Change dashboard API response"

    mcp_data = await call_tool(
        "repomind_context",
        {"repository": str(mixed_repo), "task": task, "budget": 1000, "level": 1},
    )

    assert main(
        [
            "context",
            task,
            "-C",
            str(mixed_repo),
            "--budget",
            "1000",
            "--level",
            "1",
            "--format",
            "json",
        ]
    ) == 0
    cli_data = json.loads(capsys.readouterr().out)
    mcp_paths = [item["path"] for item in mcp_data["context"]["relevant_files"]]
    cli_paths = [item["path"] for item in cli_data["relevant_files"]]
    assert mcp_paths == cli_paths
    assert mcp_data["context"]["budget"]["requested_tokens"] == 1000


@pytest.mark.anyio
async def test_mcp_symbol_callers_dependencies_impact_and_equivalence(
    python_repo: Path, capsys: Any
) -> None:
    Indexer(python_repo).initialize(force=True)
    repository = str(python_repo)

    symbol = await call_tool(
        "repomind_symbol", {"repository": repository, "symbol": "AuthService.login"}
    )
    callers = await call_tool(
        "repomind_callers", {"repository": repository, "symbol": "AuthService.login"}
    )
    dependencies = await call_tool(
        "repomind_dependencies", {"repository": repository, "target": "app/routes.py"}
    )
    impact = await call_tool(
        "repomind_impact", {"repository": repository, "target": "AuthService.login"}
    )

    assert symbol["matches"][0]["file"] == "app/auth.py"
    assert symbol["ambiguous"] is False
    assert any(item["file"] == "app/routes.py" for item in callers["callers"])
    assert any(item["file"] == "app/auth.py" for item in dependencies["dependencies"])
    assert "direct_dependents" in impact

    for command, target, mcp_result, key in (
        ("symbol", "AuthService.login", symbol, "matches"),
        ("dependencies", "app/routes.py", dependencies, "dependencies"),
        ("impact", "AuthService.login", impact, "direct_dependents"),
    ):
        assert main([command, target, "-C", repository, "--format", "json"]) == 0
        cli_data = json.loads(capsys.readouterr().out)
        if command == "symbol":
            normalized = [
                {k: v for k, v in item.items() if k != "relationships"}
                for item in mcp_result[key]
            ]
            assert normalized == cli_data[key]
        else:
            assert mcp_result[key] == cli_data[key]


@pytest.mark.anyio
async def test_mcp_snippets_are_bounded_and_do_not_expose_whole_files(python_repo: Path) -> None:
    Indexer(python_repo).initialize(force=True)
    data = await call_tool(
        "repomind_snippets",
        {
            "repository": str(python_repo),
            "target": "app/auth.py",
            "line_bound": 3,
            "token_bound": 80,
        },
    )

    assert data["snippets"]
    code = data["snippets"][0]["code"]
    assert len(code.splitlines()) <= 3
    assert "Source read from the working tree" not in code


@pytest.mark.anyio
async def test_mcp_refresh_reports_incremental_changes(python_repo: Path) -> None:
    Indexer(python_repo).initialize(force=True)
    target = python_repo / "app" / "email.py"
    target.write_text(target.read_text() + "\n\ndef notify_refresh() -> None:\n    return None\n")

    data = await call_tool("repomind_refresh", {"repository": str(python_repo)})

    assert "app/email.py" in data["modified_files"]
    assert data["parsed_file_count"] >= 1
    assert data["index_health"] == "ok"


@pytest.mark.anyio
async def test_mcp_uninitialized_invalid_ambiguous_and_malformed_errors(
    tmp_path: Path, python_repo: Path
) -> None:
    uninitialized = await call_tool("repomind_status", {"repository": str(tmp_path)})
    assert uninitialized["initialized"] is False

    not_indexed = await call_tool(
        "repomind_context", {"repository": str(tmp_path), "task": "fix login"}
    )
    assert not_indexed["error"] == "repository_not_indexed"

    invalid = await call_tool(
        "repomind_status", {"repository": str(tmp_path / "missing")}
    )
    assert invalid["error"] == "repomind_error"

    ambiguous_repo = tmp_path / "ambiguous"
    shutil.copytree(python_repo, ambiguous_repo)
    (ambiguous_repo / "app" / "extra.py").write_text(
        "class AuthService:\n    def login(self) -> None:\n        pass\n"
    )
    Indexer(ambiguous_repo).initialize(force=True)
    ambiguous = await call_tool(
        "repomind_symbol", {"repository": str(ambiguous_repo), "symbol": "login"}
    )
    assert ambiguous["ambiguous"] is True
    assert len(ambiguous["matches"]) > 1

    malformed = await call_tool(
        "repomind_context",
        {"repository": str(ambiguous_repo), "task": "x", "budget": 10},
    )
    assert malformed["error"] == "invalid_arguments"


@pytest.mark.anyio
async def test_mcp_map_returns_compact_repository_map(python_repo: Path) -> None:
    Indexer(python_repo).initialize(force=True)
    data = await call_tool(
        "repomind_map",
        {"repository": str(python_repo), "depth": 2, "include_symbols": True},
    )

    assert data["files"]
    assert any(item.get("symbols") for item in data["files"])
