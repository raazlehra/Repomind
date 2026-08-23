from __future__ import annotations

import os
from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer


def test_initial_index_persists_files_symbols_and_architecture(python_repo: Path) -> None:
    result = Indexer(python_repo).initialize()
    assert result.indexed_files >= 6
    assert result.parse_errors == 0
    with IndexDatabase(python_repo) as database:
        counts = database.counts()
        assert counts["symbols"] >= 8
        facts = {
            (row["category"], row["name"])
            for row in database.connection.execute("SELECT * FROM architecture")
        }
        assert ("backend", "FastAPI") in facts
        assert ("testing", "Pytest") in facts
        assert database.integrity_check() == "ok"


def test_incremental_create_modify_delete(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    (python_repo / "app" / "auth.py").write_text(
        "class AuthService:\n    def logout(self) -> None: pass\n"
    )
    (python_repo / "app" / "new_module.py").write_text("def created() -> bool: return True\n")
    (python_repo / "app" / "email.py").unlink()
    result = Indexer(python_repo).refresh()
    assert result.parsed_files == 2
    assert result.changes.modified == ("app/auth.py",)
    assert result.changes.created == ("app/new_module.py",)
    assert result.changes.deleted == ("app/email.py",)
    with IndexDatabase(python_repo) as database:
        assert database.file_by_path("app/email.py") is None
        assert database.connection.execute("SELECT 1 FROM symbols WHERE name='logout'").fetchone()


def test_rename_detected_by_hash_without_reparse(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    source = python_repo / "app" / "email.py"
    destination = python_repo / "app" / "mailer.py"
    source.rename(destination)
    result = Indexer(python_repo).refresh()
    assert result.changes.renamed == (("app/email.py", "app/mailer.py"),)
    assert result.parsed_files == 0
    with IndexDatabase(python_repo) as database:
        assert database.file_by_path("app/mailer.py") is not None
        assert database.file_by_path("app/email.py") is None


def test_mtime_only_change_not_reparsed(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    path = python_repo / "app" / "auth.py"
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    result = Indexer(python_repo).refresh()
    assert result.parsed_files == 0
    assert result.changes.total == 0


def test_only_modified_file_gets_new_index_timestamp(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    with IndexDatabase(python_repo) as database:
        before = {path: row["indexed_at"] for path, row in database.all_files().items()}
    path = python_repo / "app" / "models.py"
    path.write_text(path.read_text() + "\nACTIVE = True\n")
    Indexer(python_repo).refresh()
    with IndexDatabase(python_repo) as database:
        after = {path: row["indexed_at"] for path, row in database.all_files().items()}
    assert after["app/models.py"] != before["app/models.py"]
    assert after["app/auth.py"] == before["app/auth.py"]
