from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from repomind.database import IndexDatabase
from repomind.models import RankedFile
from repomind.utils import approximate_tokens, tokenize

_MODE_BUDGETS = {"minimal": 750, "balanced": 2000, "deep": 5000}
_TERM_ALIASES = {
    "api": {"route", "routes"},
    "auth": {"authentication"},
    "authentication": {"auth"},
    "dependencies": {"dependency"},
    "dependency": {"dependencies"},
    "route": {"api", "routes"},
    "routes": {"api", "route"},
    "websocket": {"websockets"},
    "websockets": {"websocket"},
}
_STRUCTURAL_GRAPH_KINDS = {"imports"}
_STOPWORDS = {
    "a",
    "an",
    "and",
    "after",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_CONFIG_TERMS = {
    "build",
    "config",
    "configuration",
    "dependencies",
    "dependency",
    "deploy",
    "extra",
    "install",
    "optional",
    "package",
    "pyproject",
}
_SYMBOL_NOISE_TERMS = {"bug", "fix", "test", "tests"}


class ContextRetriever:
    def __init__(self, database: IndexDatabase) -> None:
        self.database = database
        self.connection = database.connection

    @staticmethod
    def resolve_budget(mode: str, budget: int | None, configured: int = 2000) -> int:
        if budget is not None:
            if budget < 100:
                raise ValueError("Context budget must be at least 100 tokens")
            return budget
        return _MODE_BUDGETS.get(mode, configured)

    def rank_files(self, task: str, limit: int = 30) -> list[RankedFile]:
        task_lower = task.lower().strip()
        terms = _expand_terms(tokenize(task) - _STOPWORDS)
        files = list(self.connection.execute("SELECT * FROM files"))
        symbols = list(
            self.connection.execute(
                "SELECT id, file_id, name, qualified_name, kind, signature FROM symbols"
            )
        )
        symbols_by_file: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for symbol in symbols:
            symbols_by_file[int(symbol["file_id"])].append(symbol)
        changed = self._git_changed_files()
        ranked: dict[int, RankedFile] = {}
        for row in files:
            file_id = int(row["id"])
            path = str(row["path"])
            path_lower = path.lower()
            path_terms = tokenize(path)
            overlap = terms & path_terms
            score = float(len(overlap) * 4)
            reasons: list[str] = []
            if overlap:
                reasons.append("path:" + ",".join(sorted(overlap)))
                specific_path_terms = {term for term in overlap if len(term) >= 5}
                if specific_path_terms:
                    score += len(specific_path_terms) * 4
                    reasons.append("path-specific:" + ",".join(sorted(specific_path_terms)))
            stem = Path(path).stem.lower()
            if stem in terms:
                score += 5
                reasons.append("filename")
            if task_lower and task_lower in path_lower:
                score += 8
                reasons.append("path phrase")
            matched_symbols: list[dict[str, Any]] = []
            symbol_score_total = 0.0
            seen_symbol_overlaps: set[tuple[str, ...]] = set()
            for symbol in symbols_by_file.get(file_id, []):
                symbol_text = f"{symbol['name']} {symbol['qualified_name']} {symbol['signature']}"
                symbol_terms = tokenize(symbol_text)
                symbol_overlap = (terms & symbol_terms) - _SYMBOL_NOISE_TERMS
                if symbol_overlap:
                    overlap_key = tuple(sorted(symbol_overlap))
                    if overlap_key in seen_symbol_overlaps:
                        continue
                    seen_symbol_overlaps.add(overlap_key)
                    symbol_score = 5 + len(symbol_overlap) * 3
                    if str(symbol["name"]).lower() in terms:
                        symbol_score += 4
                    capped = min(symbol_score, 14)
                    allowed = max(0.0, 28.0 - symbol_score_total)
                    if allowed <= 0:
                        continue
                    score += min(capped, allowed)
                    symbol_score_total += min(capped, allowed)
                    reasons.append(f"symbol:{symbol['qualified_name']}")
                    matched_symbols.append(
                        {
                            "id": int(symbol["id"]),
                            "name": str(symbol["name"]),
                            "qualified_name": str(symbol["qualified_name"]),
                            "kind": str(symbol["kind"]),
                            "signature": str(symbol["signature"]),
                        }
                    )
            purpose = str(row["purpose"])
            if purpose == "test" and terms & {"test", "tests", "spec", "bug", "fix"}:
                score += 2.5
                reasons.append("test relevance")
            if purpose == "configuration" and terms & _CONFIG_TERMS:
                score += 10
                reasons.append("configuration relevance")
            if purpose == "migration" and terms & {"database", "schema", "model", "migration"}:
                score += 4
                reasons.append("migration relevance")
            if path in changed:
                score += 1.5
                reasons.append("git changed")
            if score > 0:
                ranked[file_id] = RankedFile(
                    path,
                    score,
                    reasons,
                    purpose,
                    str(row["language"]),
                    matched_symbols,
                )

        if not ranked:
            # A task with no lexical match still receives a compact architecture entry point.
            for row in files:
                if str(row["purpose"]) in {"configuration", "source"}:
                    ranked[int(row["id"])] = RankedFile(
                        str(row["path"]),
                        0.5,
                        ["repository entry point"],
                        str(row["purpose"]),
                        str(row["language"]),
                        [],
                    )

        self._expand_graph(ranked, files, terms)
        return sorted(ranked.values(), key=lambda item: (-item.score, item.path))[:limit]

    def build_context(self, task: str, budget: int, level: int = 1) -> dict[str, Any]:
        level = min(3, max(1, level))
        ranked = self.rank_files(task)
        selected = ranked[: min(15, max(4, budget // 180))]
        selected_paths = {item.path for item in selected}
        package: dict[str, Any] = {
            "task": task,
            "context_level": level,
            "architecture": self._architecture(),
            "relevant_files": [
                {
                    "path": item.path,
                    "score": round(item.score, 2),
                    "purpose": item.purpose,
                    "language": item.language,
                    "reasons": item.reasons[:3],
                }
                for item in selected
            ],
            "important_symbols": self._important_symbols(selected, include_signatures=level >= 2),
            "relationships": self._relationships(selected_paths, max_items=max(8, budget // 130)),
            "likely_modification_area": [
                item.path
                for item in selected
                if item.purpose not in {"documentation", "configuration", "test"}
            ][:6],
            "source_authority": "RepoMind summaries guide discovery; inspect actual source before modification.",
        }
        if level >= 2:
            package["imports"] = self._imports(selected_paths, max_items=max(8, budget // 140))
            package["nearby_dependencies"] = self._nearby_dependencies(
                selected_paths, max_items=max(8, budget // 140)
            )
        if level >= 3:
            package["snippets"] = self._snippets(selected, max_items=max(2, budget // 600))
        package["budget"] = {"requested_tokens": budget, "approximate_tokens": 0}
        return package

    def _architecture(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT category, name, evidence, confidence FROM architecture ORDER BY category, name"
        )
        return [
            {
                "category": str(row["category"]),
                "name": str(row["name"]),
                "evidence": str(row["evidence"]),
                "confidence": float(row["confidence"]),
            }
            for row in rows
        ][:30]

    def _important_symbols(
        self, selected: list[RankedFile], include_signatures: bool
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for item in selected:
            symbols = item.symbols
            if not symbols:
                row = self.connection.execute(
                    "SELECT id FROM files WHERE path=?", (item.path,)
                ).fetchone()
                if row:
                    symbols = [
                        dict(symbol)
                        for symbol in self.connection.execute(
                            """SELECT id, name, qualified_name, kind, signature FROM symbols
                               WHERE file_id=? ORDER BY exported DESC, line_start LIMIT 3""",
                            (int(row["id"]),),
                        )
                    ]
            for symbol in symbols[:4]:
                value = {
                    "file": item.path,
                    "name": str(symbol["qualified_name"]),
                    "kind": str(symbol["kind"]),
                }
                if include_signatures:
                    value["signature"] = str(symbol["signature"])
                output.append(value)
        return output[:24]

    def _relationships(self, paths: set[str], max_items: int) -> list[dict[str, Any]]:
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        query = f"""
            SELECT sf.path AS source_file, tf.path AS target_file,
                   ss.qualified_name AS source_symbol, ts.qualified_name AS target_symbol,
                   d.kind, d.confidence, d.source
            FROM dependencies d
            JOIN files sf ON sf.id=d.source_file_id
            LEFT JOIN files tf ON tf.id=d.target_file_id
            LEFT JOIN symbols ss ON ss.id=d.source_symbol_id
            LEFT JOIN symbols ts ON ts.id=d.target_symbol_id
            WHERE sf.path IN ({placeholders}) OR tf.path IN ({placeholders})
            ORDER BY d.confidence DESC, d.kind, sf.path
            LIMIT ?
        """
        values = [*paths, *paths, max_items]
        return [
            {
                "from": str(row["source_symbol"] or row["source_file"]),
                "type": str(row["kind"]),
                "to": str(row["target_symbol"] or row["target_file"] or "unresolved"),
                "confidence": _confidence_label(float(row["confidence"])),
                "source": str(row["source"]),
            }
            for row in self.connection.execute(query, values)
        ]

    def _imports(self, paths: set[str], max_items: int) -> list[dict[str, Any]]:
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        query = f"""SELECT f.path, i.module, i.imported_name, i.alias, i.line, rf.path AS resolved
                    FROM imports i JOIN files f ON f.id=i.file_id
                    LEFT JOIN files rf ON rf.id=i.resolved_file_id
                    WHERE f.path IN ({placeholders}) ORDER BY f.path, i.line LIMIT ?"""
        return [
            {
                "file": str(row["path"]),
                "module": str(row["module"]),
                "name": row["imported_name"],
                "alias": row["alias"],
                "resolved_file": row["resolved"],
                "line": int(row["line"]),
            }
            for row in self.connection.execute(query, [*paths, max_items])
        ]

    def _nearby_dependencies(self, paths: set[str], max_items: int) -> list[dict[str, Any]]:
        relationships = self._relationships(paths, max_items)
        return [
            item for item in relationships if item["type"] in {"imports", "calls", "test-target"}
        ]

    def _snippets(self, selected: list[RankedFile], max_items: int) -> list[dict[str, Any]]:
        snippets: list[dict[str, Any]] = []
        for item in selected:
            if len(snippets) >= max_items:
                break
            file_row = self.connection.execute(
                "SELECT id FROM files WHERE path=?", (item.path,)
            ).fetchone()
            if not file_row:
                continue
            symbol = self.connection.execute(
                """SELECT qualified_name, line_start, line_end FROM symbols WHERE file_id=?
                   ORDER BY exported DESC, line_start LIMIT 1""",
                (int(file_row["id"]),),
            ).fetchone()
            if not symbol:
                continue
            source_path = self.database.root / item.path
            try:
                lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            start = max(1, int(symbol["line_start"]) - 2)
            end = min(len(lines), int(symbol["line_end"]) + 2, start + 39)
            text = "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))
            snippets.append(
                {
                    "file": item.path,
                    "symbol": str(symbol["qualified_name"]),
                    "lines": f"{start}-{end}",
                    "code": text,
                }
            )
        return snippets

    def _expand_graph(
        self, ranked: dict[int, RankedFile], files: list[sqlite3.Row], terms: set[str]
    ) -> None:
        if not ranked:
            return
        by_id = {int(row["id"]): row for row in files}
        seeds = sorted(ranked, key=lambda item: ranked[item].score, reverse=True)[:8]
        placeholders = ",".join("?" for _ in seeds)
        query = f"""SELECT source_file_id, target_file_id, kind, confidence FROM dependencies
                    WHERE source_file_id IN ({placeholders}) OR target_file_id IN ({placeholders})"""
        for edge in self.connection.execute(query, [*seeds, *seeds]):
            source = int(edge["source_file_id"])
            target = int(edge["target_file_id"]) if edge["target_file_id"] is not None else None
            if target is None:
                continue
            if source in seeds and target not in ranked:
                origin, neighbor = source, target
            elif target in seeds and source not in ranked:
                origin, neighbor = target, source
            else:
                continue
            row = by_id.get(neighbor)
            if row is None:
                continue
            neighbor_overlap = self._neighbor_overlap(neighbor, str(row["path"]), terms)
            if not neighbor_overlap:
                continue
            added = min(
                4.0,
                ranked[origin].score * 0.18 * float(edge["confidence"])
                + min(2.0, len(neighbor_overlap) * 0.75),
            )
            ranked[neighbor] = RankedFile(
                str(row["path"]),
                added,
                [
                    f"graph:{edge['kind']}:{ranked[origin].path}",
                    "graph terms:" + ",".join(sorted(neighbor_overlap)),
                ],
                str(row["purpose"]),
                str(row["language"]),
                [],
            )
        self._expand_structural_dependencies(ranked, by_id)

    def _expand_structural_dependencies(
        self, ranked: dict[int, RankedFile], by_id: dict[int, sqlite3.Row]
    ) -> None:
        frontier = sorted(ranked, key=lambda item: ranked[item].score, reverse=True)[:8]
        seen = set(frontier)
        for _ in range(2):
            if not frontier:
                return
            placeholders = ",".join("?" for _ in frontier)
            query = f"""SELECT source_file_id, target_file_id, kind, confidence FROM dependencies
                        WHERE source_file_id IN ({placeholders})
                          AND target_file_id IS NOT NULL
                          AND kind IN ({",".join("?" for _ in _STRUCTURAL_GRAPH_KINDS)})"""
            next_frontier: list[int] = []
            for edge in self.connection.execute(query, [*frontier, *_STRUCTURAL_GRAPH_KINDS]):
                origin = int(edge["source_file_id"])
                neighbor = int(edge["target_file_id"])
                if neighbor in ranked or neighbor in seen:
                    continue
                origin_file = ranked[origin]
                if origin_file.purpose in {"test", "documentation", "configuration"}:
                    continue
                confidence = float(edge["confidence"])
                if confidence < 0.95:
                    continue
                row = by_id.get(neighbor)
                if row is None:
                    continue
                score = max(1.25, min(3.0, origin_file.score * 0.10 * confidence))
                ranked[neighbor] = RankedFile(
                    str(row["path"]),
                    score,
                    [f"graph-structural:{edge['kind']}:{origin_file.path}"],
                    str(row["purpose"]),
                    str(row["language"]),
                    [],
                )
                seen.add(neighbor)
                next_frontier.append(neighbor)
            frontier = next_frontier

    def _neighbor_overlap(self, file_id: int, path: str, terms: set[str]) -> set[str]:
        overlap = terms & tokenize(path)
        if overlap:
            return overlap
        rows = self.connection.execute(
            "SELECT name, qualified_name, signature FROM symbols WHERE file_id=?", (file_id,)
        )
        for row in rows:
            text = f"{row['name']} {row['qualified_name']} {row['signature']}"
            overlap |= terms & tokenize(text)
        return overlap

    def _git_changed_files(self) -> set[str]:
        row = self.connection.execute(
            "SELECT value FROM git_state WHERE key='changed_files'"
        ).fetchone()
        if not row:
            return set()
        try:
            value = json.loads(str(row["value"]))
        except json.JSONDecodeError:
            return set()
        return {str(item) for item in value} if isinstance(value, list) else set()


def fit_context_to_budget(
    package: dict[str, Any],
    renderer: Callable[[dict[str, Any]], str],
    budget: int,
) -> tuple[dict[str, Any], str]:
    """Drop complete low-value records until output fits; never cut arbitrary text."""
    removal_order = (
        "snippets",
        "nearby_dependencies",
        "imports",
        "relationships",
        "important_symbols",
        "relevant_files",
        "architecture",
    )
    minimum = {
        "relevant_files": 1,
        "important_symbols": 0,
        "relationships": 0,
        "architecture": 1,
        "snippets": 0,
        "nearby_dependencies": 0,
        "imports": 0,
    }
    while True:
        rendered = renderer(package)
        tokens = approximate_tokens(rendered)
        budget_info = package.get("budget")
        if isinstance(budget_info, dict):
            budget_info["approximate_tokens"] = tokens
            rendered = renderer(package)
            tokens = approximate_tokens(rendered)
            budget_info["approximate_tokens"] = tokens
        if tokens <= budget:
            return package, rendered
        removed = False
        for key in removal_order:
            values = package.get(key)
            if isinstance(values, list) and len(values) > minimum.get(key, 0):
                values.pop()
                removed = True
                break
        if not removed:
            # Only fixed high-signal fields remain. This can happen with a very long task string.
            return package, rendered


def _confidence_label(value: float) -> str:
    if value >= 0.85:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"


def _expand_terms(terms: set[str]) -> set[str]:
    expanded = set(terms)
    for term in terms:
        expanded.update(_TERM_ALIASES.get(term, set()))
    return expanded
