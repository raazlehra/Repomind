from __future__ import annotations

import sqlite3
from collections import deque
from typing import Any

from repomind.database import IndexDatabase
from repomind.intent import classify_task_intent
from repomind.retrieval import (
    _STOPWORDS,
    _expand_terms,
    _is_agent_skill_path,
    _is_application_code_query,
)
from repomind.utils import tokenize


def symbol_details(database: IndexDatabase, target: str) -> dict[str, Any]:
    rows = _find_symbols(database, target)
    return {
        "query": target,
        "matches": [
            {
                "name": str(row["qualified_name"]),
                "kind": str(row["kind"]),
                "signature": str(row["signature"]),
                "file": str(row["path"]),
                "lines": f"{row['line_start']}-{row['line_end']}",
                "exported": bool(row["exported"]),
                "documentation": row["documentation"],
            }
            for row in rows
        ],
        "source_authority": "Inspect actual source before modification.",
    }


def callers(database: IndexDatabase, target: str) -> dict[str, Any]:
    symbols = _find_symbols(database, target)
    if not symbols:
        return {"query": target, "callers": []}
    ids = [int(row["id"]) for row in symbols]
    placeholders = ",".join("?" for _ in ids)
    rows = database.connection.execute(
        f"""SELECT sf.path AS source_file, ss.qualified_name AS source_symbol,
                   tf.path AS target_file, ts.qualified_name AS target_symbol,
                   d.kind, d.confidence, d.source
            FROM dependencies d
            JOIN files sf ON sf.id=d.source_file_id
            LEFT JOIN files tf ON tf.id=d.target_file_id
            LEFT JOIN symbols ss ON ss.id=d.source_symbol_id
            LEFT JOIN symbols ts ON ts.id=d.target_symbol_id
            WHERE d.target_symbol_id IN ({placeholders})
            ORDER BY d.confidence DESC, sf.path""",
        ids,
    )
    return {
        "query": target,
        "callers": [
            {
                "from": str(row["source_symbol"] or row["source_file"]),
                "file": str(row["source_file"]),
                "relationship": str(row["kind"]),
                "target": str(row["target_symbol"]),
                "confidence": _confidence(float(row["confidence"])),
                "evidence": str(row["source"]),
            }
            for row in rows
        ],
    }


def dependencies(database: IndexDatabase, target: str) -> dict[str, Any]:
    files, symbols = _resolve_target(database, target)
    if not files and not symbols:
        return {"query": target, "dependencies": []}
    conditions: list[str] = []
    values: list[int] = []
    if files:
        ids = [int(row["id"]) for row in files]
        conditions.append(f"d.source_file_id IN ({','.join('?' for _ in ids)})")
        values.extend(ids)
    if symbols:
        ids = [int(row["id"]) for row in symbols]
        conditions.append(f"d.source_symbol_id IN ({','.join('?' for _ in ids)})")
        values.extend(ids)
    rows = database.connection.execute(
        f"""SELECT sf.path AS source_file, tf.path AS target_file,
                   ss.qualified_name AS source_symbol, ts.qualified_name AS target_symbol,
                   d.kind, d.confidence, d.source
            FROM dependencies d
            JOIN files sf ON sf.id=d.source_file_id
            LEFT JOIN files tf ON tf.id=d.target_file_id
            LEFT JOIN symbols ss ON ss.id=d.source_symbol_id
            LEFT JOIN symbols ts ON ts.id=d.target_symbol_id
            WHERE {" OR ".join(conditions)}
            ORDER BY d.confidence DESC, d.kind, target_file""",
        values,
    )
    return {
        "query": target,
        "dependencies": [
            {
                "from": str(row["source_symbol"] or row["source_file"]),
                "type": str(row["kind"]),
                "to": str(row["target_symbol"] or row["target_file"] or "unresolved"),
                "file": row["target_file"],
                "confidence": _confidence(float(row["confidence"])),
                "evidence": str(row["source"]),
            }
            for row in rows
        ],
    }


def impact(database: IndexDatabase, target: str) -> dict[str, Any]:
    files, symbols = _resolve_target(database, target)
    if not files and not symbols:
        return {
            "query": target,
            "direct_dependents": [],
            "possible_indirect_dependents": [],
            "tests_likely_affected": [],
            "routes_likely_affected": [],
            "ui_components_possibly_affected": [],
        }
    explicit_file_ids = {int(row["id"]) for row in files}
    containing_file_ids = {int(row["file_id"]) for row in symbols}
    target_file_ids = explicit_file_ids | containing_file_ids
    target_symbol_ids = {int(row["id"]) for row in symbols}
    conditions: list[str] = []
    values: list[int] = []
    if explicit_file_ids:
        conditions.append(f"d.target_file_id IN ({','.join('?' for _ in explicit_file_ids)})")
        values.extend(sorted(explicit_file_ids))
    if target_symbol_ids:
        conditions.append(f"d.target_symbol_id IN ({','.join('?' for _ in target_symbol_ids)})")
        values.extend(sorted(target_symbol_ids))
    if containing_file_ids:
        conditions.append(
            f"(d.target_file_id IN ({','.join('?' for _ in containing_file_ids)}) "
            "AND d.kind IN ('imports', 'test-target'))"
        )
        values.extend(sorted(containing_file_ids))
    direct_rows = list(
        database.connection.execute(
            f"""SELECT DISTINCT sf.id AS source_id, sf.path AS source_file, sf.is_test,
                       ss.qualified_name AS source_symbol, d.kind, d.confidence, d.source
                FROM dependencies d JOIN files sf ON sf.id=d.source_file_id
                LEFT JOIN symbols ss ON ss.id=d.source_symbol_id
                WHERE {" OR ".join(conditions)}
                ORDER BY d.confidence DESC, sf.path""",
            values,
        )
    )
    direct_ids = {int(row["source_id"]) for row in direct_rows}
    direct_symbols = {
        str(row["source_symbol"]) for row in direct_rows if row["source_symbol"] is not None
    }
    indirect_ids: set[int] = set()
    frontier = deque((file_id, 0) for file_id in direct_ids)
    visited = set(target_file_ids) | direct_ids
    while frontier:
        file_id, distance = frontier.popleft()
        if distance >= 2:
            continue
        for row in database.connection.execute(
            "SELECT DISTINCT source_file_id FROM dependencies WHERE target_file_id=?",
            (file_id,),
        ):
            dependent = int(row["source_file_id"])
            if dependent not in visited:
                visited.add(dependent)
                indirect_ids.add(dependent)
                frontier.append((dependent, distance + 1))
    indirect = _files_by_ids(database, indirect_ids)
    affected_ids = direct_ids | indirect_ids
    tests = [row for row in _files_by_ids(database, affected_ids) if bool(row["is_test"])]
    route_rows: list[sqlite3.Row] = []
    if affected_ids | target_file_ids:
        ids = sorted(affected_ids | target_file_ids)
        route_rows = list(
            database.connection.execute(
                f"""SELECT f.path, r.method, r.path AS route_path, r.handler, r.confidence
                    FROM routes r JOIN files f ON f.id=r.file_id
                    WHERE f.id IN ({",".join("?" for _ in ids)}) ORDER BY f.path, r.line""",
                ids,
            )
        )
    components: list[sqlite3.Row] = []
    if affected_ids:
        ids = sorted(affected_ids)
        components = list(
            database.connection.execute(
                f"""SELECT f.path, s.qualified_name FROM symbols s JOIN files f ON f.id=s.file_id
                    WHERE s.kind='component' AND f.id IN ({",".join("?" for _ in ids)})""",
                ids,
            )
        )
    return {
        "query": target,
        "direct_dependents": [
            {
                "file": str(row["source_file"]),
                "symbol": row["source_symbol"],
                "relationship": str(row["kind"]),
                "confidence": _confidence(float(row["confidence"])),
                "evidence": str(row["source"]),
            }
            for row in direct_rows
        ],
        "possible_indirect_dependents": [
            {"file": str(row["path"]), "classification": "indirect", "confidence": "heuristic"}
            for row in indirect
            if not bool(row["is_test"])
        ],
        "tests_likely_affected": [
            {
                "file": str(row["path"]),
                "classification": "direct" if int(row["id"]) in direct_ids else "indirect",
            }
            for row in tests
        ],
        "routes_likely_affected": [
            {
                "file": str(row["path"]),
                "route": f"{row['method']} {row['route_path']}",
                "handler": row["handler"],
                "classification": (
                    "direct" if str(row["handler"]) in direct_symbols else "heuristic"
                ),
                "confidence": (
                    _confidence(float(row["confidence"]))
                    if str(row["handler"]) in direct_symbols
                    else "heuristic"
                ),
            }
            for row in route_rows
        ],
        "ui_components_possibly_affected": [
            {
                "file": str(row["path"]),
                "component": str(row["qualified_name"]),
                "confidence": "heuristic",
            }
            for row in components
        ],
    }


def snippets(database: IndexDatabase, target: str) -> dict[str, Any]:
    symbols = _find_symbols(database, target)
    output: list[dict[str, Any]] = []
    for symbol in symbols[:10]:
        path = database.root / str(symbol["path"])
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        actual_start = int(symbol["line_start"])
        actual_end = int(symbol["line_end"])
        start = max(1, actual_start - 2)
        end = min(len(lines), actual_end + 2, start + 119)
        code = "\n".join(f"{line}: {lines[line - 1]}" for line in range(start, end + 1))
        output.append(
            {
                "symbol": str(symbol["qualified_name"]),
                "file": str(symbol["path"]),
                "lines": f"{start}-{end}",
                "complete_symbol": end >= actual_end,
                "code": code,
            }
        )
    if not output:
        output = _content_snippet_fallback(database, target)
    return {
        "query": target,
        "snippets": output,
        "source_authority": "Source read from the working tree at command time.",
    }


def _content_snippet_fallback(database: IndexDatabase, target: str) -> list[dict[str, Any]]:
    raw_terms = tokenize(target) - _STOPWORDS
    terms = _expand_terms(raw_terms)
    if not terms:
        return []
    app_code_query = _is_application_code_query(raw_terms, terms, classify_task_intent(target))
    rows = list(
        database.connection.execute(
            "SELECT id, path, purpose FROM files ORDER BY path"
        )
    )
    matches: list[tuple[float, int, str, int, list[str]]] = []
    for row in rows:
        file_id = int(row["id"])
        path = str(row["path"])
        purpose = str(row["purpose"])
        if app_code_query and (
            _is_agent_skill_path(path) or purpose in {"configuration", "documentation"}
        ):
            continue
        try:
            lines = (database.root / path).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            continue
        best = _best_matching_line(lines, raw_terms, terms, target)
        if best is None:
            continue
        score, line_number = best
        path_overlap = terms & tokenize(path)
        score += len(path_overlap) * 1.5
        if score < 3.0:
            continue
        matches.append((score, file_id, path, line_number, lines))

    matches.sort(key=lambda item: (-item[0], item[2]))
    return [
        _format_content_snippet(database, file_id, path, line_number, lines)
        for _, file_id, path, line_number, lines in matches[:10]
    ]


def _best_matching_line(
    lines: list[str], raw_terms: set[str], terms: set[str], target: str
) -> tuple[float, int] | None:
    best_score = 0.0
    best_line = 0
    target_lower = target.lower().strip()
    for index, line in enumerate(lines, start=1):
        line_terms = tokenize(line)
        if not line_terms:
            continue
        overlap = terms & line_terms
        exact_overlap = raw_terms & line_terms
        if not overlap:
            continue
        score = float(len(overlap) + len(exact_overlap))
        if target_lower and target_lower in line.lower():
            score += 6.0
        if score > best_score:
            best_score = score
            best_line = index
    if best_line == 0:
        return None
    return best_score, best_line


def _format_content_snippet(
    database: IndexDatabase, file_id: int, path: str, line_number: int, lines: list[str]
) -> dict[str, Any]:
    symbol = database.connection.execute(
        """SELECT qualified_name, line_start, line_end FROM symbols
           WHERE file_id=? AND line_start <= ? AND line_end >= ?
           ORDER BY line_start DESC LIMIT 1""",
        (file_id, line_number, line_number),
    ).fetchone()
    if symbol is None:
        symbol = database.connection.execute(
            """SELECT qualified_name, line_start, line_end FROM symbols
               WHERE file_id=? ORDER BY exported DESC, line_start LIMIT 1""",
            (file_id,),
        ).fetchone()
    start = max(1, line_number - 3)
    end = min(len(lines), line_number + 6, start + 119)
    code = "\n".join(f"{line}: {lines[line - 1]}" for line in range(start, end + 1))
    actual_end = int(symbol["line_end"]) if symbol is not None else end
    return {
        "symbol": str(symbol["qualified_name"]) if symbol is not None else "content match",
        "file": path,
        "lines": f"{start}-{end}",
        "complete_symbol": end >= actual_end,
        "code": code,
    }


def _find_symbols(database: IndexDatabase, target: str) -> list[sqlite3.Row]:
    exact = list(
        database.connection.execute(
            """SELECT s.*, f.path FROM symbols s JOIN files f ON f.id=s.file_id
               WHERE s.qualified_name=? OR s.name=? ORDER BY f.path, s.line_start""",
            (target, target),
        )
    )
    if exact:
        return exact
    escaped = target.replace("%", "\\%").replace("_", "\\_")
    return list(
        database.connection.execute(
            """SELECT s.*, f.path FROM symbols s JOIN files f ON f.id=s.file_id
               WHERE s.qualified_name LIKE ? ESCAPE '\\' ORDER BY f.path, s.line_start LIMIT 25""",
            (f"%{escaped}%",),
        )
    )


def _resolve_target(
    database: IndexDatabase, target: str
) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    normalized = target.replace("\\", "/").removeprefix("./")
    files = list(database.connection.execute("SELECT * FROM files WHERE path=?", (normalized,)))
    return files, _find_symbols(database, target)


def _files_by_ids(database: IndexDatabase, ids: set[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    return list(
        database.connection.execute(
            f"SELECT id, path, is_test, purpose FROM files WHERE id IN ({','.join('?' for _ in ids)}) ORDER BY path",
            sorted(ids),
        )
    )


def _confidence(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"
