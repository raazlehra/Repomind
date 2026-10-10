from __future__ import annotations

import os
import stat
import subprocess
import sys
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

def _git_shell_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if os.name == "nt" and len(value) > 2 and value[1] == ":":
        return f"/{value[0].lower()}{value[2:]}"
    return value


def _python_command(script: Path) -> str:
    return f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"'



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


@pytest.mark.parametrize("entrypoint", ["inspect", "bounded"])
def test_passive_git_does_not_execute_fsmonitor(tmp_path: Path, entrypoint: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    marker = tmp_path / "marker"
    hook = tmp_path / "hook"
    hook.write_text(
        f"#!/bin/sh\nprintf invoked > '{_git_shell_path(marker)}'\n", encoding="utf-8"
    )
    hook.chmod(0o700)
    subprocess.run(["git", "-C", str(root), "config", "core.fsmonitor", hook.resolve().as_posix()], check=True)
    (root / "file.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(root), "status", "--short"], check=True)
    assert marker.exists()
    marker.unlink()

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


def test_passive_git_preserves_benign_config_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "repo"
    root.mkdir()
    global_config = home / ".gitconfig"
    global_config.write_text(
        "[core]\n"
        "\tautocrlf = true\n"
        "\tprecomposeunicode = true\n"
        "[safe]\n"
        f"\tdirectory = {root.as_posix()}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "core.ignorecase", "false"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "core.filemode", "false"], check=True)

    for key in (
        "core.autocrlf", "core.ignorecase", "core.filemode",
        "core.precomposeunicode", "safe.directory",
    ):
        normal = subprocess.run(
            ["git", "-C", str(root), "config", "--get-all", key],
            check=True, capture_output=True, text=True,
        )
        passive = _run_git(root, ["config", "--get-all", key])
        assert passive.returncode == 0
        assert passive.stdout == normal.stdout


@pytest.mark.parametrize("entrypoint", ["inspect", "bounded"])
def test_passive_git_does_not_execute_clean_filter(
    tmp_path: Path, entrypoint: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    marker = tmp_path / "filter-marker"
    script = tmp_path / "filter.py"
    script.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('invoked')\n"
        "sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    source = root / "data.txt"
    source.write_text("one\n", encoding="utf-8")
    (root / ".gitattributes").write_text("*.txt filter=probe\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "tests@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "RepoMind Tests"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    command = f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"'
    subprocess.run(
        ["git", "-C", str(root), "config", "filter.probe.clean", command], check=True
    )
    source.write_text("two\n", encoding="utf-8")

    subprocess.run(["git", "-C", str(root), "status", "--short"], check=True)
    assert marker.exists()
    marker.unlink()

    if entrypoint == "inspect":
        info = inspect_git(root)
        assert info.available
        assert "data.txt" in info.changed_files
    else:
        limits = ImpactLimits()
        result = _bounded_git_changes(
            root, ["status", "--porcelain=v1", "-z"], "status",
            limits, _AnalysisBudget.start(limits),
        )
        assert "data.txt" in result.paths
    assert not marker.exists()


def test_passive_git_does_not_execute_configured_hook(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "tests@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "RepoMind Tests"], check=True)
    tracked = root / "file.py"
    tracked.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    marker = tmp_path / "hook-marker"
    hook = hooks / "post-index-change"
    hook.write_text(
        f"#!{Path(sys.executable).as_posix()}\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('invoked')\n",
        encoding="utf-8",
    )
    hook.chmod(0o700)
    subprocess.run(
        ["git", "-C", str(root), "config", "core.hooksPath", hooks.resolve().as_posix()],
        check=True,
    )
    metadata = tracked.stat()
    os.utime(tracked, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 5_000_000_000))

    subprocess.run(["git", "-C", str(root), "status", "--short"], check=True)
    assert marker.exists()
    marker.unlink()

    assert inspect_git(root).available
    assert not marker.exists()


@pytest.mark.parametrize("mechanism", ["external", "textconv"])
def test_passive_diff_does_not_execute_configured_program(
    tmp_path: Path, mechanism: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / ("data.bin" if mechanism == "textconv" else "data.txt")
    source.write_text("one\n", encoding="utf-8")
    if mechanism == "textconv":
        (root / ".gitattributes").write_text("*.bin diff=probe\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "tests@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "RepoMind Tests"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    marker = tmp_path / f"{mechanism}-marker"
    script = tmp_path / f"{mechanism}.py"
    script.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('invoked')\n"
        "paths = [pathlib.Path(value) for value in sys.argv[1:]]\n"
        "source = next((path for path in reversed(paths) if path.is_file()), None)\n"
        "sys.stdout.buffer.write(source.read_bytes() if source else b'')\n",
        encoding="utf-8",
    )
    key = "diff.external" if mechanism == "external" else "diff.probe.textconv"
    subprocess.run(
        ["git", "-C", str(root), "config", key, _python_command(script)], check=True
    )
    source.write_text("two\n", encoding="utf-8")

    subprocess.run(["git", "-C", str(root), "diff"], check=True, capture_output=True)
    assert marker.exists()
    marker.unlink()

    result = _run_git(root, ["diff"])
    assert result.returncode == 0
    assert not marker.exists()


def test_git_ignores_inherited_configuration_and_external_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    marker = tmp_path / "marker"
    script = tmp_path / "external.py"
    script.write_text(
        "import pathlib\n"
        f"pathlib.Path({str(marker)!r}).write_text('invoked')\n",
        encoding="utf-8",
    )
    command = _python_command(script)
    path = root / "a.py"
    path.write_text("x = 1\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    path.write_text("x = 2\n")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "diff.external")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", command)

    subprocess.run(["git", "-C", str(root), "diff"], check=True, capture_output=True)
    assert marker.exists()
    marker.unlink()

    diff = _run_git(root, ["diff"])
    assert diff.returncode == 0
    assert "+x = 2" in diff.stdout
    assert not marker.exists()

    monkeypatch.delenv("GIT_CONFIG_COUNT")
    monkeypatch.delenv("GIT_CONFIG_KEY_0")
    monkeypatch.delenv("GIT_CONFIG_VALUE_0")
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", command)
    subprocess.run(["git", "-C", str(root), "diff"], check=True, capture_output=True)
    assert marker.exists()
    marker.unlink()

    diff = _run_git(root, ["diff"])
    assert diff.returncode == 0
    assert "+x = 2" in diff.stdout
    assert not marker.exists()

    monkeypatch.setenv("GIT_DIR", str(tmp_path / "missing-git-dir"))
    assert "a.py" in inspect_git(root).changed_files


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

    controlled = {"GIT_OPTIONAL_LOCKS", "GIT_TERMINAL_PROMPT", "GIT_PAGER"}
    inherited = {key for key in environment if key.upper().startswith("GIT_")}
    assert inherited == controlled
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GIT_OPTIONAL_LOCKS"] == "0"
