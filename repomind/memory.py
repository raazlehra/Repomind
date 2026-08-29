from __future__ import annotations

import hashlib
import json
import sqlite3
import tomllib
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from repomind.database import IndexDatabase, utc_now
from repomind.models import MemoryRecord
from repomind.utils import tokenize

MEMORY_CATEGORIES = {
    "architecture",
    "convention",
    "dependency",
    "workflow",
    "security",
    "testing",
    "api",
    "database",
    "configuration",
    "domain",
    "integration",
}
MEMORY_STATUSES = {"valid", "needs_validation", "stale", "invalid", "manual"}
AUTOMATIC_SOURCE_TYPE = "automatic"
MANUAL_SOURCE_TYPE = "manual"
SECRET_MEMORY_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "credentials*",
    "credential*",
    "secrets*",
    "secret*",
    "*private*key*",
    "id_rsa*",
    "id_ed25519*",
)
_MEMORY_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "the",
    "to",
    "uses",
    "with",
}
_CATEGORY_BY_ARCHITECTURE = {
    "backend": "architecture",
    "framework": "architecture",
    "frontend": "architecture",
    "database": "database",
    "database-library": "database",
    "data-store": "database",
    "testing": "testing",
    "language": "dependency",
    "build": "workflow",
    "deployment": "workflow",
}


def add_manual_memory(
    database: IndexDatabase,
    value: str,
    category: str,
    key: str | None = None,
    source_paths: tuple[str, ...] = (),
    source_symbols: tuple[str, ...] = (),
) -> dict[str, Any]:
    category = _validate_category(category)
    normalized_paths = _normalize_source_paths(database, source_paths, allow_missing=False)
    record = MemoryRecord(
        id=None,
        key=key or _manual_key(category, value),
        value=value.strip(),
        category=category,
        confidence=1.0,
        source_type=MANUAL_SOURCE_TYPE,
        source_paths=normalized_paths,
        source_symbols=tuple(sorted(source_symbols)),
        evidence_hash=_evidence_hash(database, normalized_paths)
        or _stable_hash(["manual", category, value.strip()]),
        status="manual",
    )
    if not record.value:
        raise ValueError("memory value is required")
    with database.transaction():
        memory_id = database.upsert_memory(record)
    row = database.memory_by_id_or_key(str(memory_id))
    assert row is not None
    return memory_row_to_dict(row)


def list_memory(
    database: IndexDatabase,
    category: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    values: list[Any] = []
    clauses: list[str] = []
    if category:
        clauses.append("category = ?")
        values.append(_validate_category(category))
    if status:
        clauses.append("status = ?")
        values.append(_validate_status(status))
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = database.connection.execute(
        f"""SELECT * FROM memory{where}
            ORDER BY status='manual' DESC, category, key LIMIT ?""",
        [*values, max(1, min(limit, 200))],
    )
    return [memory_row_to_dict(row) for row in rows]


def show_memory(database: IndexDatabase, identifier: str) -> dict[str, Any]:
    row = database.memory_by_id_or_key(identifier)
    if row is None:
        raise ValueError(f"Memory not found: {identifier}")
    return memory_row_to_dict(row)


def remove_memory(database: IndexDatabase, identifier: str) -> dict[str, Any]:
    with database.transaction():
        removed = database.delete_memory(identifier)
    if not removed:
        raise ValueError(f"Memory not found: {identifier}")
    return {"removed": identifier}


def stale_memory(database: IndexDatabase, limit: int = 50) -> list[dict[str, Any]]:
    rows = database.connection.execute(
        """SELECT * FROM memory
           WHERE status IN ('needs_validation', 'stale', 'invalid')
           ORDER BY updated_at DESC, category LIMIT ?""",
        (max(1, min(limit, 200)),),
    )
    return [memory_row_to_dict(row) for row in rows]


def sync_automatic_memory(
    database: IndexDatabase, *, validate_changed: bool = False
) -> dict[str, int]:
    candidates = {record.key: record for record in extract_automatic_memory(database)}
    existing_rows = database.connection.execute(
        "SELECT * FROM memory WHERE source_type = ?", (AUTOMATIC_SOURCE_TYPE,)
    ).fetchall()
    existing = {str(row["key"]): row for row in existing_rows}
    counts = {"created": 0, "updated": 0, "needs_validation": 0, "stale": 0}
    now = utc_now()
    with database.transaction():
        for key, record in candidates.items():
            previous = existing.get(key)
            status = "valid"
            evidence_hash = record.evidence_hash
            if previous is not None and str(previous["evidence_hash"]) != record.evidence_hash:
                status = "valid" if validate_changed else "needs_validation"
                if not validate_changed:
                    evidence_hash = str(previous["evidence_hash"])
            database.upsert_memory(
                MemoryRecord(
                    id=record.id,
                    key=record.key,
                    value=record.value,
                    category=record.category,
                    confidence=record.confidence,
                    source_type=record.source_type,
                    source_paths=record.source_paths,
                    source_symbols=record.source_symbols,
                    evidence_hash=evidence_hash,
                    status=status,
                )
            )
            if previous is None:
                counts["created"] += 1
            elif status == "needs_validation":
                counts["needs_validation"] += 1
            else:
                counts["updated"] += 1
        for key, row in existing.items():
            if key in candidates:
                continue
            database.connection.execute(
                "UPDATE memory SET status='stale', updated_at=?, last_verified_at=? WHERE id=?",
                (now, now, int(row["id"])),
            )
            counts["stale"] += 1
    return counts


def validate_memory(database: IndexDatabase, identifier: str | None = None) -> dict[str, Any]:
    generated = {record.key: record for record in extract_automatic_memory(database)}
    if identifier:
        rows = [database.memory_by_id_or_key(identifier)]
    else:
        rows = database.connection.execute(
            "SELECT * FROM memory WHERE source_type = ?", (AUTOMATIC_SOURCE_TYPE,)
        ).fetchall()
    outcomes: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    now = utc_now()
    with database.transaction():
        for row in rows:
            if row is None:
                continue
            if str(row["source_type"]) == MANUAL_SOURCE_TYPE:
                outcomes["manual"] += 1
                records.append(memory_row_to_dict(row))
                continue
            key = str(row["key"])
            generated_record = generated.get(key)
            if generated_record is None:
                status = "stale"
                outcome = "stale"
                evidence_hash = str(row["evidence_hash"])
            else:
                evidence_hash = generated_record.evidence_hash
                if evidence_hash == str(row["evidence_hash"]):
                    status = "valid"
                    outcome = "valid"
                else:
                    status = "valid"
                    outcome = "updated"
                database.upsert_memory(
                    MemoryRecord(
                        id=None,
                        key=generated_record.key,
                        value=generated_record.value,
                        category=generated_record.category,
                        confidence=generated_record.confidence,
                        source_type=generated_record.source_type,
                        source_paths=generated_record.source_paths,
                        source_symbols=generated_record.source_symbols,
                        evidence_hash=evidence_hash,
                        status=status,
                    )
                )
            if generated_record is None:
                database.connection.execute(
                    """UPDATE memory SET status=?, updated_at=?, last_verified_at=?
                       WHERE id=?""",
                    (status, now, now, int(row["id"])),
                )
            outcomes[outcome] += 1
            refreshed = database.memory_by_id_or_key(key)
            if refreshed is not None:
                records.append(memory_row_to_dict(refreshed))
    return {"outcomes": dict(outcomes), "records": records}


def relevant_memory_for_task(
    database: IndexDatabase,
    task: str,
    limit: int = 5,
    *,
    include_uncertain: bool = False,
) -> list[dict[str, Any]]:
    terms = tokenize(task) - _MEMORY_STOPWORDS
    if not terms:
        return []
    statuses = ("valid", "manual") if not include_uncertain else tuple(sorted(MEMORY_STATUSES))
    placeholders = ",".join("?" for _ in statuses)
    rows = database.connection.execute(
        f"SELECT * FROM memory WHERE status IN ({placeholders})", statuses
    )
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for row in rows:
        item = memory_row_to_dict(row)
        haystack = " ".join(
            [
                str(item["key"]),
                str(item["value"]),
                str(item["category"]),
                " ".join(str(path) for path in item["source_paths"]),
                " ".join(str(symbol) for symbol in item["source_symbols"]),
            ]
        )
        overlap = terms & tokenize(haystack)
        if not overlap:
            continue
        score = len(overlap) + float(item["confidence"])
        if item["status"] == "manual":
            score += 0.25
        item["matched_terms"] = sorted(overlap)
        scored.append((score, str(item["key"]), item))
    scored.sort(key=lambda value: (-value[0], value[1]))
    return [item for _, _, item in scored[: max(1, min(limit, 25))]]


def memory_counts(database: IndexDatabase) -> dict[str, int]:
    rows = database.connection.execute(
        "SELECT status, COUNT(*) AS count FROM memory GROUP BY status ORDER BY status"
    )
    counts = {str(row["status"]): int(row["count"]) for row in rows}
    return {
        "total": sum(counts.values()),
        "valid": counts.get("valid", 0),
        "needs_validation": counts.get("needs_validation", 0),
        "stale": counts.get("stale", 0),
        "invalid": counts.get("invalid", 0),
        "manual": counts.get("manual", 0),
    }


def memory_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "key": str(row["key"]),
        "value": str(row["value"]),
        "category": str(row["category"]),
        "confidence": float(row["confidence"]),
        "source_type": str(row["source_type"]),
        "source_paths": _json_list(str(row["source_paths"])),
        "source_symbols": _json_list(str(row["source_symbols"])),
        "evidence_hash": str(row["evidence_hash"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "last_verified_at": str(row["last_verified_at"]),
        "status": str(row["status"]),
    }


def extract_automatic_memory(database: IndexDatabase) -> list[MemoryRecord]:
    records: dict[str, MemoryRecord] = {}
    for record in _architecture_memory(database):
        records[record.key] = record
    for record in _pyproject_memory(database):
        records[record.key] = record
    for record in _source_marker_memory(database):
        records[record.key] = record
    for record in _android_memory(database):
        records[record.key] = record
    for record in _layout_memory(database):
        records[record.key] = record
    return sorted(records.values(), key=lambda item: item.key)


def _architecture_memory(database: IndexDatabase) -> list[MemoryRecord]:
    rows = database.connection.execute(
        "SELECT category, name, evidence, confidence FROM architecture ORDER BY category, name"
    )
    records: list[MemoryRecord] = []
    for row in rows:
        evidence = str(row["evidence"])
        if database.file_by_path(evidence) is None:
            continue
        name = str(row["name"])
        arch_category = str(row["category"])
        category = _CATEGORY_BY_ARCHITECTURE.get(arch_category, "architecture")
        records.append(
            _automatic_record(
                database,
                category=category,
                key=f"auto:{category}:{_slug(name)}:{_slug(evidence)}",
                value=f"Repository uses {name}.",
                source_paths=(evidence,),
                confidence=float(row["confidence"]),
            )
        )
    return records


def _pyproject_memory(database: IndexDatabase) -> list[MemoryRecord]:
    if database.file_by_path("pyproject.toml") is None:
        return []
    path = database.root / "pyproject.toml"
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return []
    dependencies = _pyproject_dependencies(raw)
    records: list[MemoryRecord] = []
    if "pytest" in dependencies:
        records.append(
            _automatic_record(
                database,
                category="testing",
                key="auto:testing:pytest",
                value="Repository uses pytest for tests.",
                source_paths=("pyproject.toml",),
            )
        )
    if "ruff" in dependencies:
        records.append(
            _automatic_record(
                database,
                category="workflow",
                key="auto:workflow:ruff",
                value="Repository uses Ruff for linting.",
                source_paths=("pyproject.toml",),
            )
        )
    if "mypy" in dependencies:
        records.append(
            _automatic_record(
                database,
                category="workflow",
                key="auto:workflow:mypy",
                value="Repository uses mypy for Python type checking.",
                source_paths=("pyproject.toml",),
            )
        )
    if "build" in dependencies:
        records.append(
            _automatic_record(
                database,
                category="workflow",
                key="auto:workflow:python-build",
                value="Repository uses the Python build package for packaging.",
                source_paths=("pyproject.toml",),
            )
        )
    if "mcp" in dependencies:
        records.append(
            _automatic_record(
                database,
                category="integration",
                key="auto:integration:mcp",
                value="Repository exposes MCP support through the mcp package.",
                source_paths=("pyproject.toml",),
            )
        )
    return records


def _source_marker_memory(database: IndexDatabase) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    sqlite_rows = database.connection.execute(
        """SELECT f.path FROM imports i JOIN files f ON f.id=i.file_id
           WHERE i.module='sqlite3' ORDER BY f.path LIMIT 3"""
    ).fetchall()
    sqlite_paths = tuple(str(row["path"]) for row in sqlite_rows)
    if sqlite_paths:
        records.append(
            _automatic_record(
                database,
                category="database",
                key="auto:database:sqlite-index",
                value="RepoMind stores its local index in SQLite.",
                source_paths=sqlite_paths,
                source_symbols=("IndexDatabase",),
            )
        )
    mcp_file = database.file_by_path("repomind/mcp.py")
    if mcp_file is not None:
        records.append(
            _automatic_record(
                database,
                category="integration",
                key="auto:integration:stdio-mcp-server",
                value="RepoMind provides a local stdio MCP server.",
                source_paths=("repomind/mcp.py",),
            )
        )
    return records


def _layout_memory(database: IndexDatabase) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    api_rows = database.connection.execute(
        """SELECT path FROM files
           WHERE purpose='api'
              OR path LIKE '%/routes.%'
              OR path LIKE '%/api.%'
              OR path LIKE '%/controllers/%'
           ORDER BY path LIMIT 5"""
    ).fetchall()
    if api_rows:
        paths = tuple(str(row["path"]) for row in api_rows)
        common = _common_directory(paths)
        records.append(
            _automatic_record(
                database,
                category="api",
                key=f"auto:api:route-layout:{_slug(common)}",
                value=f"API route files live under {common}.",
                source_paths=paths,
            )
        )
    test_rows = database.connection.execute(
        "SELECT path FROM files WHERE purpose='test' ORDER BY path LIMIT 5"
    ).fetchall()
    if test_rows:
        paths = tuple(str(row["path"]) for row in test_rows)
        common = _common_directory(paths)
        records.append(
            _automatic_record(
                database,
                category="testing",
                key=f"auto:testing:test-layout:{_slug(common)}",
                value=f"Tests live under {common}.",
                source_paths=paths,
            )
        )
    return records


def _android_memory(database: IndexDatabase) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    gradle_rows = database.connection.execute(
        """SELECT path FROM files
           WHERE path LIKE '%build.gradle' OR path LIKE '%build.gradle.kts'
           ORDER BY path LIMIT 5"""
    ).fetchall()
    gradle_paths = tuple(str(row["path"]) for row in gradle_rows)
    room_paths: list[str] = []
    schema_paths: list[str] = []
    for relative in gradle_paths:
        text = _read_indexed_text(database, relative).lower()
        if "androidx.room" in text or "room-" in text:
            room_paths.append(relative)
        if "schemadirectory" in text or "room.schemalocation" in text:
            schema_paths.append(relative)
    if room_paths:
        records.append(
            _automatic_record(
                database,
                category="database",
                key="auto:database:android-room",
                value="Android app uses Room.",
                source_paths=tuple(room_paths),
            )
        )
    if schema_paths:
        records.append(
            _automatic_record(
                database,
                category="database",
                key="auto:database:room-schema-export",
                value="Room schema export is configured.",
                source_paths=tuple(schema_paths),
            )
        )
    manifest_rows = database.connection.execute(
        "SELECT path FROM files WHERE path LIKE '%AndroidManifest.xml' ORDER BY path LIMIT 3"
    ).fetchall()
    for row in manifest_rows:
        relative = str(row["path"])
        text = _read_indexed_text(database, relative)
        if "android.permission.INTERNET" not in text:
            records.append(
                _automatic_record(
                    database,
                    category="security",
                    key=f"auto:security:no-internet-permission:{_slug(relative)}",
                    value="Android manifest does not request Internet permission.",
                    source_paths=(relative,),
                )
            )
    return records


def _automatic_record(
    database: IndexDatabase,
    *,
    category: str,
    key: str,
    value: str,
    source_paths: tuple[str, ...],
    source_symbols: tuple[str, ...] = (),
    confidence: float = 1.0,
) -> MemoryRecord:
    normalized_paths = _normalize_source_paths(database, source_paths, allow_missing=False)
    if not normalized_paths:
        raise ValueError("automatic memory requires indexed source evidence")
    evidence_hash = _evidence_hash(database, normalized_paths)
    if not evidence_hash:
        raise ValueError("automatic memory requires hashed source evidence")
    return MemoryRecord(
        id=None,
        key=key,
        value=value,
        category=_validate_category(category),
        confidence=confidence,
        source_type=AUTOMATIC_SOURCE_TYPE,
        source_paths=normalized_paths,
        source_symbols=tuple(sorted(source_symbols)),
        evidence_hash=evidence_hash,
        status="valid",
    )


def _evidence_hash(database: IndexDatabase, source_paths: tuple[str, ...]) -> str:
    parts: list[str] = []
    for path in sorted(source_paths):
        row = database.file_by_path(path)
        if row is None:
            return ""
        parts.append(f"{path}:{row['content_hash']}")
    return _stable_hash(parts) if parts else ""


def _normalize_source_paths(
    database: IndexDatabase, source_paths: tuple[str, ...], *, allow_missing: bool
) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in source_paths:
        path = PurePosixPath(str(raw).replace("\\", "/")).as_posix()
        if path.startswith("./"):
            path = path[2:]
        if _looks_secret(path):
            raise ValueError(f"memory evidence path is excluded as secret-like: {raw}")
        if not allow_missing and database.file_by_path(path) is None:
            raise ValueError(f"memory evidence path is not indexed: {raw}")
        normalized.append(path)
    return tuple(sorted(dict.fromkeys(normalized)))


def _manual_key(category: str, value: str) -> str:
    return f"manual:{category}:{_stable_hash([value.strip()])[:12]}"


def _stable_hash(parts: list[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _json_list(value: str) -> list[str]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [str(item) for item in data]
    return []


def _pyproject_dependencies(raw: dict[str, Any]) -> set[str]:
    values: list[str] = []
    project = raw.get("project", {})
    if isinstance(project, dict):
        dependencies = project.get("dependencies", [])
        if isinstance(dependencies, list):
            values.extend(str(item) for item in dependencies)
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    values.extend(str(item) for item in group)
    tool = raw.get("tool", {})
    poetry = tool.get("poetry", {}) if isinstance(tool, dict) else {}
    if isinstance(poetry, dict) and isinstance(poetry.get("dependencies"), dict):
        values.extend(str(item) for item in poetry["dependencies"])
    return {_dependency_name(value) for value in values if _dependency_name(value)}


def _dependency_name(value: str) -> str:
    return value.strip().split("[", 1)[0].split(">", 1)[0].split("<", 1)[0].split("=", 1)[0].lower()


def _read_indexed_text(database: IndexDatabase, relative: str) -> str:
    if database.file_by_path(relative) is None:
        return ""
    try:
        return (database.root / relative).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _common_directory(paths: tuple[str, ...]) -> str:
    if not paths:
        return "."
    directories = [Path(path).parent.as_posix() for path in paths]
    common = directories[0]
    for directory in directories[1:]:
        while common and not directory.startswith(common):
            common = Path(common).parent.as_posix()
            if common == ".":
                return "."
    return common or "."


def _slug(value: str) -> str:
    terms = tokenize(value)
    return "-".join(sorted(terms)) or "root"


def _looks_secret(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    lowered = path.lower()
    return any(PurePosixPath(lowered).match(pattern) or PurePosixPath(name).match(pattern) for pattern in SECRET_MEMORY_PATTERNS)


def _validate_category(category: str) -> str:
    normalized = category.strip().lower().replace("-", "_")
    if normalized not in MEMORY_CATEGORIES:
        raise ValueError(f"Unsupported memory category: {category}")
    return normalized


def _validate_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in MEMORY_STATUSES:
        raise ValueError(f"Unsupported memory status: {status}")
    return normalized
