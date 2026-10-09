from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from repomind.database import IndexDatabase
from repomind.errors import RepoMindError
from repomind.git import _run_git, inspect_git, passive_git_environment
from repomind.indexer import Indexer
from repomind.parsers import ParserRegistry
from repomind.parsers.python import PythonParser, _PythonVisitor
from repomind.test_impact import TestImpactLimits as ImpactLimits
from repomind.test_impact import _AnalysisBudget, _bounded_git_changes


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
@pytest.mark.parametrize("force", [False, True])
def test_windows_index_directory_junction_rejected(tmp_path: Path, force: bool) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "index.sqlite3"
    if force:
        sentinel.write_bytes(b"do not delete")
    link = root / ".repomind"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode:
        pytest.skip(f"Junction creation unavailable: {created.stderr or created.stdout}")
    metadata = link.lstat()
    assert getattr(metadata, "st_file_attributes", 0) & getattr(
        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
    )
    with pytest.raises(RepoMindError, match="Unsafe index"):
        Indexer(root).initialize(force=force)
    if force:
        assert sentinel.read_bytes() == b"do not delete"
    else:
        assert not sentinel.exists()


@pytest.mark.parametrize("force", [False, True])
def test_index_directory_escape_rejected(tmp_path: Path, force: bool) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "index.sqlite3"
    if force:
        sentinel.write_bytes(b"do not delete")
    _symlink(root / ".repomind", outside, directory=True)
    with pytest.raises(RepoMindError, match="Unsafe index"):
        Indexer(root).initialize(force=force)
    if force:
        assert sentinel.read_bytes() == b"do not delete"
    else:
        assert not sentinel.exists()


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
@pytest.mark.parametrize("operation", ["create", "open", "force"])
def test_index_file_links_rejected(tmp_path: Path, suffix: str, operation: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    Indexer(root).initialize()
    outside = tmp_path / "outside"
    outside.write_bytes(b"untouched")
    link = root / ".repomind" / f"index.sqlite3{suffix}"
    link.unlink(missing_ok=True)
    _symlink(link, outside)
    with pytest.raises(RepoMindError, match="Unsafe index"):
        if operation == "force":
            Indexer(root).initialize(force=True)
        else:
            with IndexDatabase(root, create=operation == "create"):
                pass
    assert outside.read_bytes() == b"untouched"
    assert link.is_symlink()


def test_force_preflights_all_entries_before_deleting_database(tmp_path: Path) -> None:
    Indexer(tmp_path).initialize()
    database = tmp_path / ".repomind" / "index.sqlite3"
    before = database.read_bytes()
    _symlink(Path(str(database) + "-shm"), tmp_path / "missing")
    with pytest.raises(RepoMindError, match="Unsafe index"):
        Indexer(tmp_path).initialize(force=True)
    assert database.read_bytes() == before


def test_hardlinked_database_rejected(tmp_path: Path) -> None:
    Indexer(tmp_path).initialize()
    database = tmp_path / ".repomind" / "index.sqlite3"
    outside = tmp_path / "shared.sqlite3"
    os.link(database, outside)
    before = outside.read_bytes()
    with pytest.raises(RepoMindError, match="Unsafe index"):
        Indexer(tmp_path).initialize(force=True)
    assert outside.read_bytes() == before


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_hardlinked_sidecar_rejected(tmp_path: Path, suffix: str) -> None:
    Indexer(tmp_path).initialize()
    sidecar = tmp_path / ".repomind" / f"index.sqlite3{suffix}"
    sidecar.unlink(missing_ok=True)
    outside = tmp_path / f"outside{suffix}"
    outside.write_bytes(b"untouched")
    try:
        os.link(outside, sidecar)
    except OSError as exc:
        pytest.skip(f"Hardlink creation unavailable: {exc}")
    with pytest.raises(RepoMindError, match="Unsafe index"), IndexDatabase(tmp_path):
        pass
    assert outside.read_bytes() == b"untouched"
    assert sidecar.read_bytes() == b"untouched"


def test_normal_wal_concurrent_connections_remain_supported(tmp_path: Path) -> None:
    Indexer(tmp_path).initialize()
    with IndexDatabase(tmp_path) as first:
        with first.transaction():
            first.set_meta("concurrency_probe", "ready")
        with IndexDatabase(tmp_path) as second:
            assert second.get_meta("concurrency_probe") == "ready"
            assert second.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_deep_python_file_isolated_and_recovers(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text("def good(): return 1\n")
    bad = tmp_path / "bad.py"
    bad.write_text("x = " + "+".join(["1"] * 10_000))
    result = Indexer(tmp_path).initialize()
    assert result.parse_errors == 1
    with IndexDatabase(tmp_path) as database:
        row = database.file_by_path("bad.py")
        assert row and "RecursionError" in row["parse_error"]
        assert database.connection.execute("SELECT 1 FROM symbols WHERE name='good'").fetchone()
    bad.write_text("def recovered(): return 2\n")
    assert Indexer(tmp_path).refresh().parse_errors == 0
    with IndexDatabase(tmp_path) as database:
        row = database.file_by_path("bad.py")
        assert row and row["parse_error"] is None
        assert database.connection.execute("SELECT 1 FROM symbols WHERE name='recovered'").fetchone()


@pytest.mark.parametrize("failure", [RecursionError, MemoryError])
def test_ast_construction_failure_is_file_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
) -> None:
    def interrupted(*args: object, **kwargs: object) -> None:
        raise failure("synthetic AST resource failure")

    monkeypatch.setattr("repomind.parsers.python.ast.parse", interrupted)
    result = PythonParser().parse(tmp_path / "a.py", "a.py", "def partial(): pass\n")
    assert result.parse_error and failure.__name__ in result.parse_error
    assert not result.symbols
    assert not result.imports
    assert not result.edges
    assert not result.routes


@pytest.mark.parametrize("failure", [RecursionError, MemoryError])
def test_traversal_failure_discards_partial_symbols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
) -> None:
    original = _PythonVisitor.visit_FunctionDef

    def interrupted(self: _PythonVisitor, node: object) -> None:
        original(self, node)
        raise failure("synthetic visitor resource failure")

    monkeypatch.setattr(_PythonVisitor, "visit_FunctionDef", interrupted)
    result = PythonParser().parse(tmp_path / "a.py", "a.py", "def partial(): pass\n")
    assert result.parse_error and failure.__name__ in result.parse_error
    assert not result.symbols
    assert not result.imports
    assert not result.edges
    assert not result.routes


def test_registry_does_not_hide_unexpected_parser_bug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.py"
    source.write_text("x = 1\n")

    def broken(*args: object) -> None:
        raise RuntimeError("unexpected parser bug")

    monkeypatch.setattr(PythonParser, "parse", broken)
    with pytest.raises(RuntimeError, match="unexpected parser bug"):
        ParserRegistry().parse(source, "a.py", "python")


def test_indexer_does_not_hide_unexpected_database_bug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected database bug")

    monkeypatch.setattr(IndexDatabase, "upsert_file", broken)
    with pytest.raises(RuntimeError, match="unexpected database bug"):
        Indexer(tmp_path).initialize()


@pytest.mark.skipif(os.name == "nt", reason="POSIX marker hook; Windows smoke is separate")
@pytest.mark.parametrize("entrypoint", ["inspect", "bounded"])
def test_passive_git_does_not_execute_fsmonitor(tmp_path: Path, entrypoint: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    marker = tmp_path / "marker"
    hook = tmp_path / "hook"
    hook.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\n")
    hook.chmod(0o700)
    subprocess.run(["git", "-C", str(root), "config", "core.fsmonitor", str(hook)], check=True)
    (root / "file.py").write_text("x = 1\n")
    if entrypoint == "inspect":
        info = inspect_git(root)
        assert info.available
        assert "file.py" in info.changed_files
    else:
        limits = ImpactLimits()
        _bounded_git_changes(
            root, ["status", "--porcelain=v1", "-z"], "status", limits, _AnalysisBudget.start(limits)
        )
    assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable marker")
def test_git_ignores_inherited_configuration_and_external_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    marker = tmp_path / "marker"
    hook = tmp_path / "hook"
    hook.write_text(f"#!/bin/sh\nprintf invoked > '{marker}'\n")
    hook.chmod(0o700)
    path = root / "a.py"
    path.write_text("x = 1\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    path.write_text("x = 2\n")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(hook))
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", str(hook))
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "missing-git-dir"))
    assert "a.py" in inspect_git(root).changed_files
    diff = _run_git(root, ["diff"])
    assert diff.returncode == 0
    assert "+x = 2" in diff.stdout
    assert not marker.exists()


@pytest.mark.parametrize("failed_call", [2, 3, 4])
def test_git_timeout_after_initial_probe_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_call: int
) -> None:
    calls = 0

    def timeout(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == failed_call:
            raise subprocess.TimeoutExpired("git", 5)
        return subprocess.CompletedProcess(args, 0, stdout="true\n", stderr="")

    monkeypatch.setattr("repomind.git._run_git", timeout)
    info = inspect_git(tmp_path)
    assert info.available
    assert info.error and "TimeoutExpired" in info.error


def test_git_environment_strips_inherited_names_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("gIt_Config_Count", "1")
    monkeypatch.setenv("Git_External_Diff", "untrusted")

    environment = passive_git_environment()

    controlled = {
        "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_GLOBAL",
        "GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT", "GIT_PAGER",
    }
    inherited = {key for key in environment if key.upper().startswith("GIT_")}
    assert inherited == controlled
