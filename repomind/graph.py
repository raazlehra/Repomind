from __future__ import annotations

import posixpath
import sqlite3
from collections.abc import Iterable
from pathlib import PurePosixPath

from repomind.database import IndexDatabase

_CODE_EXTENSIONS = (
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".java",
    ".go",
    ".rs",
    ".cs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
)


def rebuild_dependency_graph(database: IndexDatabase) -> None:
    connection = database.connection
    files = list(connection.execute("SELECT id, path, language, is_test FROM files"))
    path_to_id = {str(row["path"]): int(row["id"]) for row in files}
    file_by_id = {int(row["id"]): row for row in files}
    connection.execute("DELETE FROM dependencies")
    connection.execute("UPDATE imports SET resolved_file_id = NULL")

    imports_by_source: dict[int, set[int]] = {}
    for imported in connection.execute(
        """SELECT imports.*, files.path AS source_path, files.language AS source_language
           FROM imports JOIN files ON files.id = imports.file_id"""
    ):
        source_id = int(imported["file_id"])
        target_id = _resolve_module(
            str(imported["module"]),
            str(imported["source_path"]),
            str(imported["source_language"]),
            path_to_id,
            str(imported["imported_name"]) if imported["imported_name"] else None,
        )
        if target_id is None or target_id == source_id:
            continue
        connection.execute(
            "UPDATE imports SET resolved_file_id = ? WHERE id = ?", (target_id, int(imported["id"]))
        )
        imports_by_source.setdefault(source_id, set()).add(target_id)
        _insert_dependency(
            connection,
            source_id,
            target_id,
            None,
            None,
            "imports",
            1.0,
            f"import:{imported['module']}",
        )
        source_file = file_by_id[source_id]
        target_file = file_by_id[target_id]
        if bool(source_file["is_test"]) and not bool(target_file["is_test"]):
            _insert_dependency(
                connection,
                source_id,
                target_id,
                None,
                None,
                "test-target",
                0.95,
                f"test import:{imported['module']}",
            )

    symbols = list(connection.execute("SELECT id, file_id, name, qualified_name FROM symbols"))
    by_exact: dict[str, list[sqlite3.Row]] = {}
    by_name: dict[str, list[sqlite3.Row]] = {}
    for symbol in symbols:
        by_exact.setdefault(str(symbol["qualified_name"]), []).append(symbol)
        by_name.setdefault(str(symbol["name"]), []).append(symbol)

    for reference in connection.execute('SELECT * FROM "references"'):
        source_file_id = int(reference["file_id"])
        target_text = str(reference["target"])
        candidates = _symbol_candidates(target_text, by_exact, by_name)
        prefer_imported = "." in target_text and not target_text.startswith(("self.", "this."))
        chosen = _choose_symbol(
            candidates,
            source_file_id,
            imports_by_source.get(source_file_id, set()),
            prefer_imported=prefer_imported,
        )
        if chosen is None:
            continue
        source_symbol_id: int | None = None
        if reference["source_symbol"]:
            source_candidates = [
                row
                for row in by_exact.get(str(reference["source_symbol"]), [])
                if int(row["file_id"]) == source_file_id
            ]
            if len(source_candidates) == 1:
                source_symbol_id = int(source_candidates[0]["id"])
        target_file_id = int(chosen["file_id"])
        target_symbol_id = int(chosen["id"])
        confidence = float(reference["confidence"])
        if len(candidates) > 1:
            confidence = min(confidence, 0.6)
        _insert_dependency(
            connection,
            source_file_id,
            target_file_id,
            source_symbol_id,
            target_symbol_id,
            str(reference["kind"]),
            confidence,
            f"static:{reference['evidence']}",
        )


def _resolve_module(
    module: str,
    source_path: str,
    language: str,
    path_to_id: dict[str, int],
    imported_name: str | None,
) -> int | None:
    source = PurePosixPath(source_path)
    base: PurePosixPath
    raw_module = module
    if language == "python":
        dots = len(module) - len(module.lstrip("."))
        tail = module[dots:].replace(".", "/")
        if dots:
            base = source.parent
            for _ in range(max(0, dots - 1)):
                base = base.parent
            stem = posixpath.normpath((base / tail).as_posix())
        else:
            stem = tail
        candidates = [f"{stem}.py", f"{stem}/__init__.py", f"{stem}.pyi"]
        if imported_name and imported_name not in {"*", "default"}:
            candidates.extend((f"{stem}/{imported_name}.py", f"{stem}/{imported_name}/__init__.py"))
    elif raw_module.startswith("."):
        stem = posixpath.normpath((source.parent / raw_module).as_posix())
        candidates = [
            stem,
            *(f"{stem}{extension}" for extension in _CODE_EXTENSIONS),
            *(f"{stem}/index{extension}" for extension in _CODE_EXTENSIONS),
        ]
    else:
        stem = raw_module.replace(".", "/").replace("::", "/")
        candidates = [f"{stem}{extension}" for extension in _CODE_EXTENSIONS]
        candidates.extend(f"{stem}/index{extension}" for extension in _CODE_EXTENSIONS)
        candidates.extend((f"{stem}/__init__.py", stem))

    for candidate in candidates:
        clean = candidate.lstrip("./")
        if clean in path_to_id:
            return path_to_id[clean]
    # Account for common source roots (src/, backend/, app/) without guessing between duplicates.
    suffix_matches = {
        file_id
        for path, file_id in path_to_id.items()
        for candidate in candidates
        if path.endswith("/" + candidate.lstrip("./"))
    }
    if len(suffix_matches) == 1:
        return next(iter(suffix_matches))
    return None


def _symbol_candidates(
    target: str,
    by_exact: dict[str, list[sqlite3.Row]],
    by_name: dict[str, list[sqlite3.Row]],
) -> list[sqlite3.Row]:
    clean = target.strip().removeprefix("self.").removeprefix("this.")
    candidates: list[sqlite3.Row] = []
    candidates.extend(by_exact.get(clean, []))
    if "." in clean:
        candidates.extend(by_name.get(clean.rsplit(".", 1)[-1], []))
        for qualified, rows in by_exact.items():
            if qualified.endswith("." + clean):
                candidates.extend(rows)
    else:
        candidates.extend(by_name.get(clean, []))
    seen: set[int] = set()
    unique: list[sqlite3.Row] = []
    for row in candidates:
        symbol_id = int(row["id"])
        if symbol_id not in seen:
            seen.add(symbol_id)
            unique.append(row)
    return unique


def _choose_symbol(
    candidates: list[sqlite3.Row],
    source_file_id: int,
    imported_files: Iterable[int],
    *,
    prefer_imported: bool = False,
) -> sqlite3.Row | None:
    if not candidates:
        return None
    same_file = [row for row in candidates if int(row["file_id"]) == source_file_id]
    imported = set(imported_files)
    from_import = [row for row in candidates if int(row["file_id"]) in imported]
    if prefer_imported and len(from_import) == 1:
        return from_import[0]
    if len(same_file) == 1:
        return same_file[0]
    if len(from_import) == 1:
        return from_import[0]
    unique_ids = {int(row["id"]): row for row in candidates}
    if len(unique_ids) == 1:
        return next(iter(unique_ids.values()))
    return None


def _insert_dependency(
    connection: sqlite3.Connection,
    source_file_id: int,
    target_file_id: int | None,
    source_symbol_id: int | None,
    target_symbol_id: int | None,
    kind: str,
    confidence: float,
    source: str,
) -> None:
    # SQLite UNIQUE constraints treat NULL values as distinct, so explicitly avoid duplicates.
    exists = connection.execute(
        """SELECT 1 FROM dependencies
           WHERE source_file_id=? AND target_file_id IS ? AND source_symbol_id IS ?
             AND target_symbol_id IS ? AND kind=? AND source=?""",
        (source_file_id, target_file_id, source_symbol_id, target_symbol_id, kind, source),
    ).fetchone()
    if exists:
        return
    connection.execute(
        """INSERT INTO dependencies(source_file_id, target_file_id, source_symbol_id, target_symbol_id,
                                    kind, confidence, source)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            source_file_id,
            target_file_id,
            source_symbol_id,
            target_symbol_id,
            kind,
            confidence,
            source,
        ),
    )
