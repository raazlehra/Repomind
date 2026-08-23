from __future__ import annotations

from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer


def test_import_call_route_and_test_edges(python_repo: Path) -> None:
    Indexer(python_repo).initialize()
    with IndexDatabase(python_repo) as database:
        edges = list(
            database.connection.execute(
                """SELECT sf.path source, tf.path target, d.kind
                   FROM dependencies d JOIN files sf ON sf.id=d.source_file_id
                   LEFT JOIN files tf ON tf.id=d.target_file_id"""
            )
        )
        triples = {(row["source"], row["target"], row["kind"]) for row in edges}
        assert ("app/auth.py", "app/models.py", "imports") in triples
        assert ("tests/test_auth.py", "app/auth.py", "test-target") in triples
        assert any(row["kind"] == "calls" for row in edges)
        routes = list(database.connection.execute("SELECT method, path, handler FROM routes"))
        assert ("POST", "/login", "login") in {
            (row["method"], row["path"], row["handler"]) for row in routes
        }


def test_uncertain_ambiguous_call_is_not_resolved(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def same(): pass\n")
    (tmp_path / "b.py").write_text("def same(): pass\n")
    (tmp_path / "caller.py").write_text("def run():\n    same()\n")
    Indexer(tmp_path).initialize()
    with IndexDatabase(tmp_path) as database:
        resolved = database.connection.execute(
            """SELECT 1 FROM dependencies d JOIN symbols s ON s.id=d.target_symbol_id
               JOIN files f ON f.id=d.source_file_id
               WHERE f.path='caller.py' AND s.name='same' AND d.kind='calls'"""
        ).fetchone()
        assert resolved is None
