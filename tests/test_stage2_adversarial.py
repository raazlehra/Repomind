from __future__ import annotations

from pathlib import Path

import pytest

from repomind.config import Config
from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.scanner import is_executable_test_path
from repomind.test_impact import (
    _read_test_source,
    analyze_test_impact,
)


def _create_sqlite_repo(root: Path, files: dict[str, str]) -> IndexDatabase:
    for rel_path, content in files.items():
        p = root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    indexer = Indexer(root, Config.load(root))
    indexer.initialize()
    return IndexDatabase(root)


def test_adv1_facade_reexport_direct_symbol_call_vs_passive_import(tmp_path: Path) -> None:
    """Assess R4: Direct symbol call via facade is preserved (medium); passive facade import is demoted (low)."""
    files = {
        "pkg/__init__.py": "from pkg.worker import calculate\n",
        "pkg/worker.py": "def calculate(): return 42\n",
        "tests/test_caller.py": "import pkg\ndef test_calc(): assert pkg.calculate() == 42\n",
        "tests/test_passive.py": "import pkg\ndef test_other(): pass\n",
    }
    db = _create_sqlite_repo(tmp_path, files)

    report = analyze_test_impact(db, changed_files=["pkg/worker.py"])
    commands = report["recommended_commands"]
    existing_tests = report["existing_tests"]

    caller_test = next(t for t in existing_tests if t["file"] == "tests/test_caller.py")
    assert caller_test["confidence"] == "medium"
    assert caller_test["structurally_related"] is True
    assert caller_test["evidence"][0]["kind"] == "dependency"

    passive_test = next(t for t in existing_tests if t["file"] == "tests/test_passive.py")
    assert passive_test["confidence"] == "low"
    assert passive_test["evidence"][0]["kind"] == "facade-reachability"

    targeted_cmd = next(c for c in commands if c.get("scope") == "targeted")
    assert "tests/test_caller.py" in targeted_cmd["argv"]
    assert "tests/test_passive.py" not in targeted_cmd["argv"]

    broad_cmd = next(c for c in commands if c.get("scope") == "broad")
    assert broad_cmd["argv"] == ["python", "-m", "pytest"]


def test_adv2_directly_changed_facade_preserves_targeted_dependents(tmp_path: Path) -> None:
    """When the facade module itself is modified in the PR, direct dependents ARE targeted."""
    files = {
        "pkg/__init__.py": "VERSION = '1.0.0'\n",
        "tests/test_version.py": "import pkg\ndef test_ver(): assert pkg.VERSION == '1.0.0'\n",
    }
    db = _create_sqlite_repo(tmp_path, files)

    report = analyze_test_impact(db, changed_files=["pkg/__init__.py"])
    commands = report["recommended_commands"]
    targeted_cmd = next(c for c in commands if c.get("scope") == "targeted")
    assert "tests/test_version.py" in targeted_cmd["argv"]


def test_adv3_alias_import_resolution(tmp_path: Path) -> None:
    """Aliased imports (from worker import process as my_proc) resolve directly."""
    files = {
        "pkg/worker.py": "def process(): return 1\n",
        "tests/test_worker.py": "from pkg.worker import process as my_proc\ndef test_p(): assert my_proc() == 1\n",
    }
    db = _create_sqlite_repo(tmp_path, files)

    report = analyze_test_impact(db, changed_files=["pkg/worker.py"])
    commands = report["recommended_commands"]
    targeted_cmd = next(c for c in commands if c.get("scope") == "targeted")
    assert "tests/test_worker.py" in targeted_cmd["argv"]


def test_adv4_distinctive_same_stem_nested_dirs(tmp_path: Path) -> None:
    """Stem matcher isolates auth/token.py vs billing/token.py."""
    files = {
        "src/auth/token.py": "def auth_token(): return 'a'\n",
        "src/billing/token.py": "def bill_token(): return 'b'\n",
        "tests/auth/test_token.py": "def test_a(): pass\n",
        "tests/billing/test_token.py": "def test_b(): pass\n",
    }
    db = _create_sqlite_repo(tmp_path, files)

    report = analyze_test_impact(db, changed_files=["src/auth/token.py"])
    commands = report["recommended_commands"]
    targeted_cmd = next((c for c in commands if c.get("scope") == "targeted"), None)
    if targeted_cmd:
        assert "tests/auth/test_token.py" in targeted_cmd["argv"]
        assert "tests/billing/test_token.py" not in targeted_cmd["argv"]


def test_adv5_runnable_vs_non_runnable_case_test(tmp_path: Path) -> None:
    """Helper .case.test.* files without runner invocation are not executable test paths."""
    helper = tmp_path / "src" / "router" / "common.case.test.ts"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("export const commonCases = [{ path: '/' }];\n", encoding="utf-8")

    runnable = tmp_path / "src" / "router" / "router.test.ts"
    runnable.write_text("describe('router', () => { it('works', () => {}); });\n", encoding="utf-8")

    assert not is_executable_test_path("src/router/common.case.test.ts", root=tmp_path)
    assert is_executable_test_path("src/router/router.test.ts", root=tmp_path)


def test_adv6_mixed_python_and_go_unaffected(tmp_path: Path) -> None:
    """Mixed Python and Go changes report truthful Go status and preserve Python commands."""
    files = {
        "src/service.py": "def run(): return 1\n",
        "tests/test_service.py": "from service import run\ndef test_s(): assert run() == 1\n",
        "pkg/writer.go": "package pkg\nfunc Write() {}\n",
        "pkg/writer_test.go": "package pkg\nfunc TestWrite(t *testing.T) {}\n",
    }
    db = _create_sqlite_repo(tmp_path, files)

    report = analyze_test_impact(db, changed_files=["src/service.py", "pkg/writer_test.go"])
    caps = report["capabilities"]
    assert caps["runner_supported"] is False
    assert caps["by_language"]["go"]["runner_supported"] is False
    assert caps["by_language"]["python"]["runner_supported"] is True
    cmds = report["recommended_commands"]
    assert any("pytest" in c.get("argv", []) for c in cmds)
    assert not any(u.get("file") == "pkg/writer_test.go" for u in report["uncovered_areas"])


def test_adv7_go_testdata_exclusion(tmp_path: Path) -> None:
    """Go testdata directories are excluded from test classification."""
    files = {
        "pkg/helper.go": "package pkg\n",
        "pkg/testdata/fixture_test.go": "package testdata\n",
    }
    db = _create_sqlite_repo(tmp_path, files)

    row = db.connection.execute("SELECT is_test FROM files WHERE path=?", ("pkg/testdata/fixture_test.go",)).fetchone()
    assert row is not None
    assert row["is_test"] == 0


def test_adv8_symlink_traversal_guard(tmp_path: Path) -> None:
    """_read_test_source guards against symlinks pointing outside root."""
    target_outside = tmp_path / "outside.txt"
    target_outside.write_text("describe('secret', () => {});", encoding="utf-8")

    inside_dir = tmp_path / "repo"
    inside_dir.mkdir(parents=True, exist_ok=True)
    symlink_file = inside_dir / "link.test.ts"

    try:
        symlink_file.symlink_to(target_outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation requires elevation or Developer Mode on Windows")
    assert symlink_file.is_symlink()
    content = _read_test_source(symlink_file)
    assert content == ""
