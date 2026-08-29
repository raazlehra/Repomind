from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from repomind.errors import NotIndexedError, RepoMindError
from repomind.models import ArchitectureFact, MemoryRecord, ParseResult, ScannedFile

SCHEMA_VERSION = 2
INDEX_DIRECTORY = ".repomind"
INDEX_FILENAME = "index.sqlite3"

_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_type TEXT NOT NULL,
    source_paths TEXT NOT NULL,
    source_symbols TEXT NOT NULL DEFAULT '[]',
    evidence_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_verified_at TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_category ON memory(category);
CREATE INDEX IF NOT EXISTS idx_memory_status ON memory(status);
CREATE INDEX IF NOT EXISTS idx_memory_source_type ON memory(source_type);
"""

_SCHEMA = (
    """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS directories (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    parent_path TEXT
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    directory_id INTEGER REFERENCES directories(id) ON DELETE SET NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    language TEXT NOT NULL,
    purpose TEXT NOT NULL,
    is_test INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    parse_error TEXT,
    indexed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_language ON files(language);
CREATE INDEX IF NOT EXISTS idx_files_purpose ON files(purpose);
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    parent_symbol_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    signature TEXT NOT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL,
    exported INTEGER NOT NULL DEFAULT 0,
    documentation TEXT
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_qualified ON symbols(qualified_name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    imported_name TEXT,
    alias TEXT,
    line INTEGER NOT NULL,
    is_relative INTEGER NOT NULL DEFAULT 0,
    resolved_file_id INTEGER REFERENCES files(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_imports_file ON imports(file_id);
CREATE INDEX IF NOT EXISTS idx_imports_resolved ON imports(resolved_file_id);
CREATE TABLE IF NOT EXISTS "references" (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    source_symbol TEXT,
    target TEXT NOT NULL,
    line INTEGER,
    confidence REAL NOT NULL,
    evidence TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_references_file ON "references"(file_id);
CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    symbol_id INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    handler TEXT,
    line INTEGER NOT NULL,
    confidence REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS dependencies (
    id INTEGER PRIMARY KEY,
    source_file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    target_file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    source_symbol_id INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    target_symbol_id INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(source_file_id, target_file_id, source_symbol_id, target_symbol_id, kind, source)
);
CREATE INDEX IF NOT EXISTS idx_dependencies_source_file ON dependencies(source_file_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_target_file ON dependencies(target_file_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_source_symbol ON dependencies(source_symbol_id);
CREATE INDEX IF NOT EXISTS idx_dependencies_target_symbol ON dependencies(target_symbol_id);
CREATE TABLE IF NOT EXISTS architecture (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    evidence TEXT NOT NULL,
    confidence REAL NOT NULL,
    UNIQUE(category, name, evidence)
);
CREATE TABLE IF NOT EXISTS git_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""
    + _MEMORY_SCHEMA
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class IndexDatabase:
    def __init__(self, root: Path, create: bool = False) -> None:
        self.root = root.resolve()
        self.directory = self.root / INDEX_DIRECTORY
        self.path = self.directory / INDEX_FILENAME
        if not create and not self.path.is_file():
            raise NotIndexedError()
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        try:
            self.connection = sqlite3.connect(self.path, timeout=30)
        except sqlite3.Error as exc:
            raise RepoMindError(f"Unable to open index database: {exc}") from exc
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        if create:
            self._initialize()
        else:
            self._validate_version()

    def __enter__(self) -> IndexDatabase:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _initialize(self) -> None:
        with self.transaction():
            self.connection.executescript(_SCHEMA)
            self.set_meta("schema_version", str(SCHEMA_VERSION))
            self.set_meta("repository_root", str(self.root))
            self.set_meta("created_at", self.get_meta("created_at") or utc_now())

    def _validate_version(self) -> None:
        try:
            version = self.get_meta("schema_version")
        except sqlite3.Error as exc:
            raise RepoMindError(
                f"Index schema is invalid: {exc}. Run: repomind init --force"
            ) from exc
        if version is None:
            raise RepoMindError("Index schema version is missing. Run: repomind init --force")
        parsed_version = int(version)
        if parsed_version < SCHEMA_VERSION:
            self._migrate(parsed_version)
            return
        if parsed_version != SCHEMA_VERSION:
            raise RepoMindError(
                f"Unsupported index schema {version}; this RepoMind expects {SCHEMA_VERSION}. "
                "Run: repomind init --force"
            )

    def _migrate(self, version: int) -> None:
        if version < 1:
            raise RepoMindError("Index schema version is too old. Run: repomind init --force")
        with self.transaction():
            if version == 1:
                self.connection.executescript(_MEMORY_SCHEMA)
                self.set_meta("schema_version", str(SCHEMA_VERSION))

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            with self.connection:
                yield
        except sqlite3.Error as exc:
            raise RepoMindError(f"Index database operation failed: {exc}") from exc

    def set_meta(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def all_files(self) -> dict[str, sqlite3.Row]:
        return {str(row["path"]): row for row in self.connection.execute("SELECT * FROM files")}

    def file_by_path(self, path: str) -> sqlite3.Row | None:
        row = self.connection.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
        return cast(sqlite3.Row | None, row)

    def ensure_directory(self, relative: str) -> int:
        parent = Path(relative).parent.as_posix() if relative else None
        if parent == ".":
            parent = ""
        self.connection.execute(
            "INSERT INTO directories(path, parent_path) VALUES (?, ?) ON CONFLICT(path) DO NOTHING",
            (relative, parent),
        )
        row = self.connection.execute(
            "SELECT id FROM directories WHERE path = ?", (relative,)
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def upsert_file(self, scanned: ScannedFile, content_hash: str, result: ParseResult) -> int:
        directory = Path(scanned.path).parent.as_posix()
        if directory == ".":
            directory = ""
        directory_id = self.ensure_directory(directory)
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO files(path, directory_id, size, mtime_ns, content_hash, language, purpose,
                              is_test, summary, parse_error, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                directory_id=excluded.directory_id, size=excluded.size, mtime_ns=excluded.mtime_ns,
                content_hash=excluded.content_hash, language=excluded.language, purpose=excluded.purpose,
                is_test=excluded.is_test, summary=excluded.summary, parse_error=excluded.parse_error,
                indexed_at=excluded.indexed_at
            """,
            (
                scanned.path,
                directory_id,
                scanned.size,
                scanned.mtime_ns,
                content_hash,
                scanned.language,
                scanned.purpose,
                int(scanned.is_test),
                result.summary,
                result.parse_error,
                now,
            ),
        )
        row = self.file_by_path(scanned.path)
        assert row is not None
        file_id = int(row["id"])
        self.replace_parse_data(file_id, result)
        return file_id

    def replace_parse_data(self, file_id: int, result: ParseResult) -> None:
        self.connection.execute("DELETE FROM dependencies WHERE source_file_id = ?", (file_id,))
        self.connection.execute('DELETE FROM "references" WHERE file_id = ?', (file_id,))
        self.connection.execute("DELETE FROM imports WHERE file_id = ?", (file_id,))
        self.connection.execute("DELETE FROM routes WHERE file_id = ?", (file_id,))
        self.connection.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
        symbol_ids: dict[str, int] = {}
        pending = list(result.symbols)
        while pending:
            inserted = False
            for symbol in list(pending):
                if symbol.parent and symbol.parent not in symbol_ids:
                    continue
                cursor = self.connection.execute(
                    """
                    INSERT INTO symbols(file_id, parent_symbol_id, name, qualified_name, kind, signature,
                                        line_start, line_end, exported, documentation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        file_id,
                        symbol_ids.get(symbol.parent or ""),
                        symbol.name,
                        symbol.qualified_name,
                        symbol.kind,
                        symbol.signature,
                        symbol.line_start,
                        symbol.line_end,
                        int(symbol.exported),
                        symbol.documentation,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RepoMindError("SQLite did not return an inserted symbol id")
                symbol_ids[symbol.qualified_name] = cursor.lastrowid
                pending.remove(symbol)
                inserted = True
            if not inserted:
                # Defensive handling for parser output with a missing parent.
                symbol = pending.pop(0)
                cursor = self.connection.execute(
                    """INSERT INTO symbols(file_id, name, qualified_name, kind, signature,
                                           line_start, line_end, exported, documentation)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        file_id,
                        symbol.name,
                        symbol.qualified_name,
                        symbol.kind,
                        symbol.signature,
                        symbol.line_start,
                        symbol.line_end,
                        int(symbol.exported),
                        symbol.documentation,
                    ),
                )
                if cursor.lastrowid is None:
                    raise RepoMindError("SQLite did not return an inserted symbol id")
                symbol_ids[symbol.qualified_name] = cursor.lastrowid
        for imported in result.imports:
            self.connection.execute(
                """INSERT INTO imports(file_id, module, imported_name, alias, line, is_relative)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    imported.module,
                    imported.name,
                    imported.alias,
                    imported.line,
                    int(imported.is_relative),
                ),
            )
        for reference in result.edges:
            self.connection.execute(
                """INSERT INTO "references"(file_id, kind, source_symbol, target, line, confidence, evidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    reference.kind,
                    reference.source_symbol,
                    reference.target,
                    reference.line,
                    reference.confidence,
                    reference.evidence,
                ),
            )
        for route in result.routes:
            self.connection.execute(
                """INSERT INTO routes(file_id, symbol_id, method, path, handler, line, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    symbol_ids.get(route.handler or ""),
                    route.method,
                    route.path,
                    route.handler,
                    route.line,
                    route.confidence,
                ),
            )

    def delete_files(self, paths: Sequence[str]) -> None:
        self.connection.executemany("DELETE FROM files WHERE path = ?", ((path,) for path in paths))

    def rename_file(self, old: str, scanned: ScannedFile) -> None:
        directory = Path(scanned.path).parent.as_posix()
        if directory == ".":
            directory = ""
        directory_id = self.ensure_directory(directory)
        self.connection.execute(
            """UPDATE files SET path=?, directory_id=?, size=?, mtime_ns=?, language=?, purpose=?,
                                is_test=?, indexed_at=? WHERE path=?""",
            (
                scanned.path,
                directory_id,
                scanned.size,
                scanned.mtime_ns,
                scanned.language,
                scanned.purpose,
                int(scanned.is_test),
                utc_now(),
                old,
            ),
        )

    def replace_architecture(self, facts: Sequence[ArchitectureFact]) -> None:
        self.connection.execute("DELETE FROM architecture")
        self.connection.executemany(
            "INSERT OR IGNORE INTO architecture(category, name, evidence, confidence) VALUES (?, ?, ?, ?)",
            ((fact.category, fact.name, fact.evidence, fact.confidence) for fact in facts),
        )

    def upsert_memory(self, record: MemoryRecord) -> int:
        now = utc_now()
        created_at = record.created_at or now
        updated_at = record.updated_at or now
        verified_at = record.last_verified_at or now
        self.connection.execute(
            """
            INSERT INTO memory(key, value, category, confidence, source_type, source_paths,
                               source_symbols, evidence_hash, created_at, updated_at,
                               last_verified_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                category=excluded.category,
                confidence=excluded.confidence,
                source_type=excluded.source_type,
                source_paths=excluded.source_paths,
                source_symbols=excluded.source_symbols,
                evidence_hash=excluded.evidence_hash,
                updated_at=excluded.updated_at,
                last_verified_at=excluded.last_verified_at,
                status=excluded.status
            """,
            (
                record.key,
                record.value,
                record.category,
                record.confidence,
                record.source_type,
                json.dumps(list(record.source_paths), sort_keys=True),
                json.dumps(list(record.source_symbols), sort_keys=True),
                record.evidence_hash,
                created_at,
                updated_at,
                verified_at,
                record.status,
            ),
        )
        row = self.connection.execute(
            "SELECT id FROM memory WHERE key = ?", (record.key,)
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def memory_by_id_or_key(self, identifier: str) -> sqlite3.Row | None:
        if identifier.isdigit():
            row = self.connection.execute(
                "SELECT * FROM memory WHERE id = ?", (int(identifier),)
            ).fetchone()
            if row is not None:
                return cast(sqlite3.Row, row)
        row = self.connection.execute("SELECT * FROM memory WHERE key = ?", (identifier,)).fetchone()
        return cast(sqlite3.Row | None, row)

    def delete_memory(self, identifier: str) -> bool:
        row = self.memory_by_id_or_key(identifier)
        if row is None:
            return False
        self.connection.execute("DELETE FROM memory WHERE id = ?", (int(row["id"]),))
        return True

    def set_git_state(self, values: dict[str, Any]) -> None:
        self.connection.execute("DELETE FROM git_state")
        self.connection.executemany(
            "INSERT INTO git_state(key, value) VALUES (?, ?)",
            ((key, json.dumps(value, sort_keys=True)) for key, value in values.items()),
        )

    def integrity_check(self) -> str:
        row = self.connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0]) if row else "unknown"

    def counts(self) -> dict[str, int]:
        tables = ("files", "symbols", "imports", "references", "dependencies", "routes", "memory")
        output: dict[str, int] = {}
        for table in tables:
            escaped = '"references"' if table == "references" else table
            row = self.connection.execute(f"SELECT COUNT(*) FROM {escaped}").fetchone()
            output[table] = int(row[0]) if row else 0
        return output
