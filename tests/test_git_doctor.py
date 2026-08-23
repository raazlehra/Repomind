from __future__ import annotations

import subprocess
from pathlib import Path

from repomind.database import IndexDatabase
from repomind.doctor import run_doctor
from repomind.git import inspect_git
from repomind.indexer import Indexer


def test_git_awareness_records_branch_head_and_changes(python_repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(python_repo)], check=True)
    subprocess.run(
        ["git", "-C", str(python_repo), "config", "user.email", "fixture@example.com"], check=True
    )
    subprocess.run(["git", "-C", str(python_repo), "config", "user.name", "Fixture"], check=True)
    subprocess.run(["git", "-C", str(python_repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(python_repo), "commit", "-qm", "fixture"], check=True)
    (python_repo / "app" / "auth.py").write_text(
        (python_repo / "app" / "auth.py").read_text() + "\n"
    )
    info = inspect_git(python_repo)
    assert info.available
    assert info.head
    assert "app/auth.py" in info.changed_files
    Indexer(python_repo).initialize()
    with IndexDatabase(python_repo) as database:
        changed = database.connection.execute(
            "SELECT value FROM git_state WHERE key='changed_files'"
        ).fetchone()
        assert changed and "app/auth.py" in changed["value"]


def test_doctor_reports_integrity_parsers_watcher_git(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    result = run_doctor(python_repo)
    names = {item["check"] for item in result["checks"]}
    assert result["index_health"] == "healthy"
    assert {
        "database integrity",
        "index schema",
        "parsers",
        "watcher",
        "git",
        "configuration",
    } <= names
