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


def test_fixture_references_resolve_to_exact_indexed_files_only(tmp_path: Path) -> None:
    test_dir = tmp_path / "test"
    corpus_dir = tmp_path / "corpus" / "redstamp"
    source_dir = tmp_path / "src"
    test_dir.mkdir()
    corpus_dir.mkdir(parents=True)
    source_dir.mkdir()
    (source_dir / "reader.mjs").write_text(
        "export async function readRedstampAudit() {}\n", encoding="utf-8"
    )
    (corpus_dir / "audit.jsonl").write_text("# not strict JSON Lines\nnot-json\n", encoding="utf-8")
    (corpus_dir / "checkpoint.json").write_text("{}", encoding="utf-8")
    (corpus_dir / "unrelated.jsonl").write_text("{}\n", encoding="utf-8")
    (corpus_dir / "method-fake.jsonl").write_text("{}\n", encoding="utf-8")
    (corpus_dir / "regex-fake.jsonl").write_text("{}\n", encoding="utf-8")
    (corpus_dir / "conditional.jsonl").write_text("{}\n", encoding="utf-8")
    (corpus_dir / "object-shadow-fake.jsonl").write_text("{}\n", encoding="utf-8")
    (corpus_dir / "array-shadow-fake.jsonl").write_text("{}\n", encoding="utf-8")
    (corpus_dir / "comma-shadow-fake.jsonl").write_text("{}\n", encoding="utf-8")
    (corpus_dir / "catch-shadow-fake.jsonl").write_text("{}\n", encoding="utf-8")
    (corpus_dir / "anonymous.jsonl").write_text("{}\n", encoding="utf-8")
    (test_dir / "fixture.test.mjs").write_text(
        """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readRedstampAudit } from '../src/reader.mjs';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus', 'redstamp');
readFileSync(join(CORPUS, 'checkpoint.json'), 'utf8');
readRedstampAudit(join(CORPUS, 'audit.jsonl'));
readFileSync(join(CORPUS, 'missing.jsonl'), 'utf8');
const obj = { readFileSync() { return null; } };
obj.readFileSync(join(CORPUS, 'method-fake.jsonl'));
const pattern = /[/]readFileSync(join(CORPUS, 'regex-fake.jsonl'))/;
if (CORPUS) {
  readFileSync(join(CORPUS, 'conditional.jsonl'), 'utf8');
}
const anonymous = function () {
  if (CORPUS) {
    readFileSync(join(CORPUS, 'anonymous.jsonl'), 'utf8');
  }
};
""",
        encoding="utf-8",
    )

    (test_dir / "shadowed.test.mjs").write_text(
        """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus', 'redstamp');
function objectRun() {
  const { readFileSync } = { readFileSync: () => null };
  readFileSync(join(CORPUS, 'object-shadow-fake.jsonl'));
}
function arrayRun() {
  const [readFileSync] = [() => null];
  readFileSync(join(CORPUS, 'array-shadow-fake.jsonl'));
}
function commaRun(source) {
  const marker = 1, { readFileSync } = source;
  readFileSync(join(CORPUS, 'comma-shadow-fake.jsonl'));
}
try {
  throw {};
} catch ({ readFileSync }) {
  readFileSync(join(CORPUS, 'catch-shadow-fake.jsonl'));
}
""",
        encoding="utf-8",
    )

    Indexer(tmp_path).initialize()

    with IndexDatabase(tmp_path) as database:
        files = {
            str(row["path"]): (str(row["language"]), str(row["purpose"]), str(row["summary"]))
            for row in database.connection.execute(
                "SELECT path, language, purpose, summary FROM files WHERE path LIKE 'corpus/%'"
            )
        }
        references = {
            str(row["target"])
            for row in database.connection.execute(
                """SELECT r.target FROM "references" r
                   JOIN files f ON f.id=r.file_id
                   WHERE f.path='test/fixture.test.mjs' AND r.kind='fixture-reference'"""
            )
        }
        dependencies = {
            (str(row["target"]), str(row["kind"]), float(row["confidence"]))
            for row in database.connection.execute(
                """SELECT tf.path target, d.kind, d.confidence FROM dependencies d
                   JOIN files sf ON sf.id=d.source_file_id
                   LEFT JOIN files tf ON tf.id=d.target_file_id
                   WHERE sf.path='test/fixture.test.mjs' AND tf.path LIKE 'corpus/%'"""
            )
        }
        shadowed_references = {
            str(row["target"])
            for row in database.connection.execute(
                """SELECT r.target FROM "references" r
                   JOIN files f ON f.id=r.file_id
                   WHERE f.path='test/shadowed.test.mjs' AND r.kind='fixture-reference'"""
            )
        }
        shadowed_dependencies = {
            str(row["target"])
            for row in database.connection.execute(
                """SELECT tf.path target FROM dependencies d
                   JOIN files sf ON sf.id=d.source_file_id
                   LEFT JOIN files tf ON tf.id=d.target_file_id
                   WHERE sf.path='test/shadowed.test.mjs' AND tf.path LIKE 'corpus/%'"""
            )
        }

    assert files["corpus/redstamp/audit.jsonl"] == (
        "config",
        "configuration",
        "configuration",
    )
    assert references == {
        "corpus/redstamp/audit.jsonl",
        "corpus/redstamp/conditional.jsonl",
        "corpus/redstamp/anonymous.jsonl",
        "corpus/redstamp/checkpoint.json",
        "corpus/redstamp/missing.jsonl",
    }
    assert dependencies == {
        ("corpus/redstamp/audit.jsonl", "fixture-reference", 0.9),
        ("corpus/redstamp/conditional.jsonl", "fixture-reference", 1.0),
        ("corpus/redstamp/anonymous.jsonl", "fixture-reference", 1.0),
        ("corpus/redstamp/checkpoint.json", "fixture-reference", 1.0),
    }
    assert shadowed_references == set()
    assert shadowed_dependencies == set()
