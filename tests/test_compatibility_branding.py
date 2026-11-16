from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from mcp import Client

from repomind.cli import main
from repomind.database import INDEX_DIRECTORY, INDEX_FILENAME, SCHEMA_VERSION, IndexDatabase
from repomind.errors import RepoMindError
from repomind.indexer import Indexer
from repomind.mcp import create_server
from repomind.services import error_payload


def test_distribution_alias_and_legacy_contracts_are_separate() -> None:
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert metadata["name"] == "repomind"
    assert metadata["scripts"]["repomind"] == "repomind.cli:main"
    assert metadata["scripts"]["lehraz-atlas"] == "repomind.cli:atlas_main"
    assert (INDEX_DIRECTORY, INDEX_FILENAME, SCHEMA_VERSION) == (".repomind", "index.sqlite3", 2)
    assert error_payload(RepoMindError("example"))["error"] == "repomind_error"


def test_branded_audit_preserves_json_schema_and_version_key(python_repo: Path, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    report = tmp_path / "audit.json"
    markdown = tmp_path / "audit.md"
    assert main(["audit", str(python_repo), "--json", str(report), "--output", str(markdown)]) == 0
    capsys.readouterr()
    data = json.loads(report.read_text())
    assert data["schema_version"] == "1"
    assert "repomind_version" in data
    assert "# Lehraz Atlas Free Repository Audit" in markdown.read_text()


@pytest.mark.anyio
async def test_mcp_display_rebrand_keeps_internal_name_and_all_legacy_tool_ids() -> None:
    async with Client(create_server(), mode="legacy") as client:
        assert client.server_info is not None
        assert client.server_info.name == "repomind"
        assert client.server_info.title == "Lehraz Atlas Free"
        result = await client.list_tools()
    assert {tool.name for tool in result.tools} == {
        "repomind_status", "repomind_context", "repomind_symbol", "repomind_callers",
        "repomind_dependencies", "repomind_impact", "repomind_test_impact", "repomind_snippets",
        "repomind_refresh", "repomind_map", "repomind_stats", "repomind_memory",
    }


def test_existing_legacy_config_ignore_and_index_are_reused(tmp_path: Path) -> None:
    config = tmp_path / ".repomind.toml"
    ignore = tmp_path / ".repomindignore"
    config.write_text("[repomind]\ncontext_budget = 800\n")
    ignore.write_text("ignored.py\n")
    (tmp_path / "kept.py").write_text("value = 1\n")
    (tmp_path / "ignored.py").write_text("value = 2\n")
    Indexer(tmp_path).initialize()
    with IndexDatabase(tmp_path) as database:
        assert database.file_by_path("kept.py") is not None
        assert database.file_by_path("ignored.py") is None
        created = database.get_meta("created_at")
    Indexer(tmp_path).refresh()
    with IndexDatabase(tmp_path) as database:
        assert database.get_meta("created_at") == created
    assert config.read_text() == "[repomind]\ncontext_budget = 800\n"
    assert ignore.read_text() == "ignored.py\n"
