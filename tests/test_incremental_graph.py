from __future__ import annotations

from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer


def read_deps(db: IndexDatabase) -> set[tuple[str, str]]:
    rows = db.connection.execute(
        "SELECT f1.path as src, f2.path as tgt FROM dependencies d JOIN files f1 ON d.source_file_id=f1.id JOIN files f2 ON d.target_file_id=f2.id"
    ).fetchall()
    return {(r["src"], r["tgt"]) for r in rows}


def test_incremental_dependency_updates(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    # A -> B -> C
    (repo / "A.py").write_text("import B\n")
    (repo / "B.py").write_text("import C\n")
    (repo / "C.py").write_text("# leaf\n")

    idx = Indexer(repo)
    idx.initialize(force=True)

    with IndexDatabase(repo) as db:
        deps = read_deps(db)
        assert ("A.py", "B.py") in deps
        assert ("B.py", "C.py") in deps

    # Modify B so B -> D
    (repo / "D.py").write_text("# new\n")
    (repo / "B.py").write_text("import D\n")
    # Refresh indexer
    changes = idx.refresh()
    assert changes.changes.total >= 1

    with IndexDatabase(repo) as db:
        deps = read_deps(db)
        assert ("A.py", "B.py") in deps
        assert ("B.py", "C.py") not in deps
        assert ("B.py", "D.py") in deps

    # Delete D
    (repo / "D.py").unlink()
    idx.refresh()
    with IndexDatabase(repo) as db:
        deps = read_deps(db)
        assert ("B.py", "D.py") not in deps

    # Rename C to C2.py and update B to import C2
    (repo / "C.py").rename(repo / "C2.py")
    (repo / "B.py").write_text("import C2\n")
    idx.refresh()
    with IndexDatabase(repo) as db:
        deps = read_deps(db)
        assert ("B.py", "C2.py") in deps
