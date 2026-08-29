from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from repomind.cli import main
from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.mcp import create_server
from repomind.memory import add_manual_memory, memory_counts, relevant_memory_for_task
from repomind.retrieval import ContextRetriever


def _pyproject(dependencies: list[str]) -> str:
    return json.dumps(dependencies)


def _write_memory_repo(root: Path, dependencies: list[str] | None = None) -> None:
    deps = dependencies or ["mcp>=2,<3", "pytest>=8.2", "ruff>=0.6", "mypy>=1.11"]
    (root / "repomind").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "memory-app"',
                'version = "0.1.0"',
                "dependencies = [" + ", ".join(f'"{item}"' for item in deps) + "]",
                "",
                "[project.optional-dependencies]",
                'dev = ["build>=1.2"]',
            ]
        ),
        encoding="utf-8",
    )
    (root / "repomind" / "__init__.py").write_text("", encoding="utf-8")
    (root / "repomind" / "database.py").write_text(
        "import sqlite3\n\nclass IndexDatabase:\n    pass\n", encoding="utf-8"
    )
    (root / "repomind" / "mcp.py").write_text(
        "def run_stdio() -> None:\n    pass\n", encoding="utf-8"
    )
    (root / "tests" / "test_memory_app.py").write_text(
        "def test_app() -> None:\n    assert True\n", encoding="utf-8"
    )


def test_manual_memory_crud_cli(tmp_path: Path, capsys: Any) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    assert main(["init", str(repo), "--format", "json"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "memory",
                "add",
                "-C",
                str(repo),
                "--category",
                "architecture",
                "--source",
                "repomind/database.py",
                "All index writes go through IndexDatabase.",
                "--format",
                "json",
            ]
        )
        == 0
    )
    added = json.loads(capsys.readouterr().out)["memory"]
    assert added["status"] == "manual"
    assert added["source_type"] == "manual"
    assert added["source_paths"] == ["repomind/database.py"]

    assert main(["memory", "list", "-C", str(repo), "--format", "json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert any(item["key"] == added["key"] for item in listed["memory"])

    assert main(["memory", "show", "-C", str(repo), added["key"], "--format", "json"]) == 0
    shown = json.loads(capsys.readouterr().out)["memory"]
    assert shown["value"] == "All index writes go through IndexDatabase."

    assert main(["memory", "remove", "-C", str(repo), added["key"], "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["removed"] == added["key"]


def test_automatic_memory_requires_indexed_evidence_and_deterministic_hash(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    Indexer(repo).initialize()

    with IndexDatabase(repo) as database:
        memories = relevant_memory_for_task(database, "pytest mcp sqlite", limit=10)
        assert memories
        assert all(item["source_paths"] for item in memories)
        assert all(item["evidence_hash"] for item in memories)
        first = memories[0]
        again = relevant_memory_for_task(database, str(first["value"]), limit=1)[0]

    assert first["evidence_hash"] == again["evidence_hash"]


def test_automatic_memory_marks_changed_and_deleted_evidence_uncertain(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    Indexer(repo).initialize()

    (repo / "pyproject.toml").write_text(
        (repo / "pyproject.toml").read_text(encoding="utf-8").replace("pytest>=8.2", "pytest>=8.3"),
        encoding="utf-8",
    )
    Indexer(repo).refresh()
    with IndexDatabase(repo) as database:
        pytest_memory = database.memory_by_id_or_key("auto:testing:pytest")
        assert pytest_memory is not None
        assert pytest_memory["status"] == "needs_validation"

    (repo / "pyproject.toml").unlink()
    Indexer(repo).refresh()
    with IndexDatabase(repo) as database:
        pytest_memory = database.memory_by_id_or_key("auto:testing:pytest")
        assert pytest_memory is not None
        assert pytest_memory["status"] == "stale"


def test_memory_validation_confirms_deterministic_fact_after_evidence_change(
    tmp_path: Path, capsys: Any
) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    Indexer(repo).initialize()
    (repo / "pyproject.toml").write_text(
        (repo / "pyproject.toml").read_text(encoding="utf-8").replace("pytest>=8.2", "pytest>=8.3"),
        encoding="utf-8",
    )
    Indexer(repo).refresh()

    assert main(["memory", "validate", "-C", str(repo), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["outcomes"]["updated"] >= 1
    with IndexDatabase(repo) as database:
        assert database.memory_by_id_or_key("auto:testing:pytest")["status"] == "valid"


def test_manual_memory_survives_refresh_and_secret_paths_are_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    (repo / ".env").write_text("API_KEY=secret-value\n", encoding="utf-8")
    Indexer(repo).initialize()

    with IndexDatabase(repo) as database:
        add_manual_memory(database, "Manual deployment note.", "workflow")
        with pytest.raises(ValueError, match="secret-like"):
            add_manual_memory(database, "Secret location.", "security", source_paths=(".env",))

    (repo / "repomind" / "database.py").write_text(
        "import sqlite3\n\nclass IndexDatabase:\n    pass\n\ndef changed() -> None:\n    pass\n",
        encoding="utf-8",
    )
    Indexer(repo).refresh()
    with IndexDatabase(repo) as database:
        counts = memory_counts(database)
        memories = relevant_memory_for_task(database, "deployment note", limit=5)
    assert counts["manual"] == 1
    assert memories[0]["status"] == "manual"


def test_weak_readme_prose_and_secret_contents_are_not_auto_stored(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    (repo / "README.md").write_text(
        "Maybe the product has a magical payment gateway using API_KEY=secret-value.\n",
        encoding="utf-8",
    )
    (repo / ".env").write_text("PASSWORD=secret-value\n", encoding="utf-8")
    Indexer(repo).initialize()

    with IndexDatabase(repo) as database:
        memories = database.connection.execute("SELECT value FROM memory").fetchall()

    values = "\n".join(str(row["value"]) for row in memories)
    assert "magical payment gateway" not in values
    assert "secret-value" not in values


def test_android_room_memory_uses_gradle_and_manifest_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "android"
    (repo / "app" / "src" / "main").mkdir(parents=True)
    (repo / "app").mkdir(exist_ok=True)
    (repo / "app" / "build.gradle.kts").write_text(
        """
plugins { id("com.android.application") }
dependencies {
    implementation("androidx.room:room-runtime:2.6.1")
}
android {
    defaultConfig {
        javaCompileOptions {
            annotationProcessorOptions {
                argument("room.schemaLocation", "$projectDir/schemas")
            }
        }
    }
}
""",
        encoding="utf-8",
    )
    (repo / "app" / "src" / "main" / "AndroidManifest.xml").write_text(
        "<manifest xmlns:android=\"http://schemas.android.com/apk/res/android\" />",
        encoding="utf-8",
    )
    Indexer(repo).initialize()

    with IndexDatabase(repo) as database:
        values = {row["value"] for row in database.connection.execute("SELECT value FROM memory")}
        assert database.file_by_path("app/build.gradle.kts")["purpose"] == "configuration"

    assert "Android app uses Room." in values
    assert "Room schema export is configured." in values
    assert "Android manifest does not request Internet permission." in values


def test_context_pack_includes_relevant_memory_and_excludes_stale(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    Indexer(repo).initialize()

    with IndexDatabase(repo) as database:
        add_manual_memory(
            database,
            "Refresh token handling must stay in AuthService.",
            "security",
            source_paths=("repomind/database.py",),
        )
        package = ContextRetriever(database).build_context(
            "fix refresh token handling", 1200, 1, explain=True
        )
        assert any("Refresh token" in item["value"] for item in package["memory"])
        top = next(item for item in package["relevant_files"] if item["path"] == "repomind/database.py")
        assert "memory" in top["score_breakdown"]
        database.connection.execute(
            "UPDATE memory SET status='stale' WHERE source_type='manual'"
        )
        package = ContextRetriever(database).build_context("fix refresh token handling", 1200, 1)

    assert not any("Refresh token" in item["value"] for item in package["memory"])


def test_context_memory_cap_is_enforced(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    Indexer(repo).initialize()

    with IndexDatabase(repo) as database:
        for index in range(10):
            add_manual_memory(database, f"Payment workflow note {index}.", "workflow")
        package = ContextRetriever(database).build_context("payment workflow", 800, 1)

    assert len(package["memory"]) <= 2


def test_schema_v1_index_upgrades_without_losing_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    Indexer(repo).initialize()
    with IndexDatabase(repo) as database:
        before = database.counts()["files"]
        with database.transaction():
            database.connection.execute("DROP TABLE memory")
            database.connection.execute("DROP INDEX IF EXISTS idx_memory_category")
            database.connection.execute("DROP INDEX IF EXISTS idx_memory_status")
            database.connection.execute("DROP INDEX IF EXISTS idx_memory_source_type")
            database.set_meta("schema_version", "1")

    with IndexDatabase(repo) as database:
        assert database.get_meta("schema_version") == "2"
        assert database.counts()["files"] == before
        assert database.counts()["memory"] >= 0


@pytest.mark.anyio
async def test_mcp_memory_is_bounded_and_task_relevant(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    Indexer(repo).initialize()

    async with Client(create_server()) as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        result = await client.call_tool(
            "repomind_memory",
            {"repository": str(repo), "task": "pytest testing", "limit": 2},
        )

    assert "repomind_memory" in tools
    assert result.is_error is False
    assert isinstance(result.structured_content, dict)
    assert len(result.structured_content["memory"]) <= 2
    assert any("pytest" in item["value"].lower() for item in result.structured_content["memory"])


def test_beta7_index_copy_migrates_and_populates_memory_once(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_memory_repo(repo)
    Indexer(repo).initialize()
    source = repo / ".repomind" / "index.sqlite3"
    migrated_repo = tmp_path / "migrated"
    shutil.copytree(repo, migrated_repo)
    target = migrated_repo / ".repomind" / "index.sqlite3"
    shutil.copyfile(source, target)
    with sqlite3.connect(target) as connection:
        connection.execute("DROP TABLE memory")
        connection.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
        connection.execute("DELETE FROM meta WHERE key='memory_last_sync_at'")

    assert main(["stats", "-C", str(migrated_repo), "--format", "json"]) == 0
    with IndexDatabase(migrated_repo) as database:
        assert database.get_meta("schema_version") == "2"
        assert database.get_meta("memory_last_sync_at") is not None
        assert memory_counts(database)["valid"] > 0
