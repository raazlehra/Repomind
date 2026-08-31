from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from repomind.context_pack import ContextBudget, ContextMetrics, ContextPack
from repomind.database import IndexDatabase
from repomind.intent import classify_task_intent
from repomind.memory import relevant_memory_for_task
from repomind.models import RankedFile
from repomind.utils import approximate_tokens, tokenize

_MODE_BUDGETS = {"minimal": 750, "balanced": 2000, "deep": 5000}
RANKING_WEIGHTS = {
    "path_term": 4.0,
    "path_specific_term": 4.0,
    "filename": 5.0,
    "path_phrase": 8.0,
    "symbol_base": 5.0,
    "symbol_term": 3.0,
    "symbol_name": 4.0,
    "test_relevance": 2.5,
    "configuration_relevance": 10.0,
    "content_term": 10.0,
    "migration_relevance": 4.0,
    "git_changed": 1.5,
    "intent": 3.0,
    "memory": 2.0,
}
_TERM_ALIASES = {
    "api": {"route", "routes"},
    "auth": {"authentication"},
    "authentication": {"auth"},
    "card": {"cards"},
    "cards": {"card"},
    "component": {"components"},
    "components": {"component"},
    "dependencies": {"dependency"},
    "dependency": {"dependencies"},
    "display": {"render", "view"},
    "displayed": {"display", "rendered", "shown"},
    "displaying": {"display", "rendering", "showing"},
    "generated": {"generate", "generates", "generation"},
    "generate": {"generated", "generates", "generation"},
    "hook": {"hooks"},
    "hooks": {"hook"},
    "load": {"loaded", "loading", "loads"},
    "loaded": {"load", "loading", "loads"},
    "model": {"models"},
    "models": {"model"},
    "page": {"pages"},
    "pages": {"page"},
    "render": {"display", "rendered", "rendering", "view"},
    "rendered": {"displayed", "render"},
    "rendering": {"displaying", "render"},
    "result": {"results"},
    "results": {"result"},
    "route": {"api", "routes"},
    "routes": {"api", "route"},
    "scanner": {"scan", "symbols"},
    "selected": {"select", "selection"},
    "stock": {"stocks", "symbols", "ticker", "tickers", "universe", "watchlist"},
    "stocks": {"stock", "symbols", "ticker", "tickers", "universe", "watchlist"},
    "symbol": {"symbols"},
    "symbols": {"symbol"},
    "ticker": {"stock", "stocks", "symbols", "tickers", "universe", "watchlist"},
    "tickers": {"stock", "stocks", "symbols", "ticker", "universe", "watchlist"},
    "universe": {"stock", "stocks", "symbols", "ticker", "tickers", "watchlist"},
    "view": {"display", "render"},
    "watchlist": {"stock", "stocks", "symbol", "symbols", "ticker", "tickers", "universe"},
    "websocket": {"websockets"},
    "websockets": {"websocket"},
}
_STRUCTURAL_GRAPH_KINDS = {"imports"}
_AGENT_SKILL_PREFIX = ".agents/skills/"
_AGENT_QUERY_TERMS = {"agent", "agents", "codex", "instruction", "instructions", "skill", "skills"}
_APPLICATION_CODE_TERMS = {
    "analysis",
    "api",
    "backend",
    "card",
    "cards",
    "client",
    "code",
    "component",
    "components",
    "display",
    "displaying",
    "engine",
    "frontend",
    "hook",
    "hooks",
    "model",
    "models",
    "page",
    "pages",
    "render",
    "result",
    "results",
    "route",
    "routes",
    "scanner",
    "service",
    "src",
    "stock",
    "stocks",
    "symbol",
    "symbols",
    "ticker",
    "tickers",
    "universe",
    "watchlist",
}
_UI_DISPLAY_TERMS = {
    "card",
    "cards",
    "component",
    "components",
    "display",
    "displaying",
    "frontend",
    "hook",
    "hooks",
    "model",
    "models",
    "page",
    "pages",
    "render",
    "result",
    "results",
    "tsx",
    "jsx",
    "view",
}
_UI_IMPORT_TRAVERSAL_TERMS = (_UI_DISPLAY_TERMS - {"result", "results"}) | {"api", "client"}
_UI_ENTRYPOINT_PATH_TERMS = {
    "card",
    "cards",
    "component",
    "components",
    "hook",
    "hooks",
    "model",
    "models",
    "page",
    "pages",
    "tsx",
    "jsx",
}
_LOW_SIGNAL_QUERY_TERMS = {
    "backend",
    "code",
    "display",
    "displayed",
    "displaying",
    "find",
    "frontend",
    "involved",
    "result",
    "results",
    "render",
    "rendered",
    "rendering",
    "showing",
    "view",
}
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
_SYMBOL_NOISE_TERMS = {"bug", "fix", "result", "results", "test", "tests"}


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

    def rank_files(
        self, task: str, limit: int = 30, intent: list[str] | None = None
    ) -> list[RankedFile]:
        task_lower = task.lower().strip()
        intent_labels = intent or classify_task_intent(task)
        raw_terms = tokenize(task) - _STOPWORDS
        terms = _expand_terms(raw_terms)
        application_code_query = _is_application_code_query(raw_terms, terms, intent_labels)
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
        memory_by_path = self._memory_relevance_by_path(task)
        ranked: dict[int, RankedFile] = {}
        for row in files:
            file_id = int(row["id"])
            path = str(row["path"])
            if _is_agent_skill_path(path) and application_code_query:
                continue
            path_lower = path.lower()
            path_terms = tokenize(path)
            overlap = terms & path_terms
            score = float(len(overlap) * RANKING_WEIGHTS["path_term"])
            reasons: list[str] = []
            components: dict[str, float] = {}
            if overlap:
                reasons.append("path:" + ",".join(sorted(overlap)))
                _add_component(
                    components, "path", len(overlap) * RANKING_WEIGHTS["path_term"]
                )
                specific_path_terms = {term for term in overlap if len(term) >= 5}
                if specific_path_terms:
                    amount = len(specific_path_terms) * RANKING_WEIGHTS["path_specific_term"]
                    score += amount
                    _add_component(components, "path", amount)
                    reasons.append("path-specific:" + ",".join(sorted(specific_path_terms)))
            stem = Path(path).stem.lower()
            if stem in terms:
                score += RANKING_WEIGHTS["filename"]
                _add_component(components, "path", RANKING_WEIGHTS["filename"])
                reasons.append("filename")
            if task_lower and task_lower in path_lower:
                score += RANKING_WEIGHTS["path_phrase"]
                _add_component(components, "path", RANKING_WEIGHTS["path_phrase"])
                reasons.append("path phrase")
            content_overlap = self._ui_entrypoint_content_overlap(
                path, str(row["purpose"]), terms
            )
            if content_overlap:
                amount = min(10.0, len(content_overlap) * RANKING_WEIGHTS["content_term"])
                score += amount
                _add_component(components, "content", amount)
                reasons.append("content:" + ",".join(sorted(content_overlap)))
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
                    symbol_score = RANKING_WEIGHTS["symbol_base"] + len(
                        symbol_overlap
                    ) * RANKING_WEIGHTS["symbol_term"]
                    if str(symbol["name"]).lower() in terms:
                        symbol_score += RANKING_WEIGHTS["symbol_name"]
                    capped = min(symbol_score, 14)
                    allowed = max(0.0, 28.0 - symbol_score_total)
                    if allowed <= 0:
                        continue
                    amount = min(capped, allowed)
                    score += amount
                    symbol_score_total += amount
                    _add_component(components, "symbol", amount)
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
                score += RANKING_WEIGHTS["test_relevance"]
                _add_component(components, "test", RANKING_WEIGHTS["test_relevance"])
                reasons.append("test relevance")
            if purpose == "configuration" and terms & _CONFIG_TERMS:
                score += RANKING_WEIGHTS["configuration_relevance"]
                _add_component(
                    components, "configuration", RANKING_WEIGHTS["configuration_relevance"]
                )
                reasons.append("configuration relevance")
            if purpose == "migration" and terms & {"database", "schema", "model", "migration"}:
                score += RANKING_WEIGHTS["migration_relevance"]
                _add_component(components, "database", RANKING_WEIGHTS["migration_relevance"])
                reasons.append("migration relevance")
            if path in changed:
                score += RANKING_WEIGHTS["git_changed"]
                _add_component(components, "freshness", RANKING_WEIGHTS["git_changed"])
                reasons.append("git changed")
            memory_boost = memory_by_path.get(path, 0.0)
            if memory_boost:
                score += memory_boost
                _add_component(components, "memory", memory_boost)
                reasons.append("memory relevance")
            intent_boost = self._intent_boost(intent_labels, purpose, path)
            if intent_boost:
                score += intent_boost
                _add_component(components, "intent", intent_boost)
                reasons.append("task-intent boost:" + ",".join(intent_labels))
            if score > 0:
                ranked[file_id] = RankedFile(
                    path,
                    score,
                    reasons,
                    purpose,
                    str(row["language"]),
                    matched_symbols,
                    components,
                    _ranking_explanations(reasons),
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
                        {"lexical": 0.5},
                        ["repository entry point selected because no lexical match was found"],
                    )

        self._expand_graph(ranked, files, terms)
        return sorted(ranked.values(), key=lambda item: (-item.score, item.path))[:limit]

    def build_context(
        self, task: str, budget: int, level: int = 1, explain: bool = False
    ) -> dict[str, Any]:
        return self.build_context_pack(task, budget, level).as_dict(explain=explain)

    def build_context_pack(self, task: str, budget: int, level: int = 1) -> ContextPack:
        started = time.perf_counter()
        level = min(3, max(1, level))
        intent = classify_task_intent(task)
        ranked = self.rank_files(task, intent=intent)
        selected = ranked[: min(15, max(4, budget // 180))]
        selected_paths = {item.path for item in selected}
        relevant_files = [
            {
                "path": item.path,
                "score": round(item.score, 2),
                "purpose": item.purpose,
                "language": item.language,
                "reasons": item.reasons[:3],
                "explanations": item.explanations,
                "score_breakdown": {
                    key: round(value, 3) for key, value in item.score_components.items()
                },
            }
            for item in selected
        ]
        pack = ContextPack(
            task=task,
            context_level=level,
            intent=intent,
            architecture=self._architecture(),
            memory=relevant_memory_for_task(
                self.database, task, limit=max(2, min(6, budget // 400))
            ),
            relevant_files=relevant_files,
            primary_files=[
                item.path
                for item in selected
                if item.purpose not in {"documentation", "configuration", "test"}
            ][:8],
            related_files=[
                item.path
                for item in selected
                if item.purpose in {"documentation", "configuration"}
            ][:8],
            relevant_tests=[item.path for item in selected if item.purpose == "test"][:8],
            routes=self._routes(selected_paths, max_items=max(6, budget // 240)),
            important_symbols=self._important_symbols(selected, include_signatures=level >= 2),
            relationships=self._relationships(selected_paths, max_items=max(8, budget // 130)),
            likely_modification_area=[
                item.path
                for item in selected
                if item.purpose not in {"documentation", "configuration", "test"}
            ][:6],
            budget=ContextBudget(requested_tokens=budget),
            metrics=self._metrics_base(selected, len(ranked), 0.0),
        )
        if level >= 2:
            pack.imports = self._imports(selected_paths, max_items=max(8, budget // 140))
            pack.nearby_dependencies = self._nearby_dependencies(
                selected_paths, max_items=max(8, budget // 140)
            )
        if level >= 3:
            pack.snippets = self._snippets(selected, max_items=max(2, budget // 600))
        pack.metrics.retrieval_latency_seconds = time.perf_counter() - started
        return pack

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

    def _routes(self, paths: set[str], max_items: int) -> list[dict[str, Any]]:
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        query = f"""SELECT f.path AS file, r.method, r.path, r.handler, r.line, r.confidence
                    FROM routes r JOIN files f ON f.id=r.file_id
                    WHERE f.path IN ({placeholders})
                    ORDER BY r.confidence DESC, f.path, r.line LIMIT ?"""
        return [
            {
                "file": str(row["file"]),
                "method": str(row["method"]),
                "path": str(row["path"]),
                "handler": row["handler"],
                "line": int(row["line"]),
                "confidence": _confidence_label(float(row["confidence"])),
            }
            for row in self.connection.execute(query, [*paths, max_items])
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
        seeds = sorted(ranked, key=lambda item: (-ranked[item].score, ranked[item].path))[:8]
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
                {"graph": added},
                _ranking_explanations(
                    [
                        f"graph:{edge['kind']}:{ranked[origin].path}",
                        "graph terms:" + ",".join(sorted(neighbor_overlap)),
                    ]
                ),
            )
        self._expand_structural_dependencies(ranked, by_id, terms)

    def _expand_structural_dependencies(
        self, ranked: dict[int, RankedFile], by_id: dict[int, sqlite3.Row], terms: set[str]
    ) -> None:
        frontier = sorted(ranked, key=lambda item: (-ranked[item].score, ranked[item].path))[:8]
        seen = set(frontier)
        for _ in range(2):
            if not frontier:
                break
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
                ceiling = 6.0 if origin_file.score >= 10.0 else 3.0
                score = max(1.25, min(ceiling, origin_file.score * 0.18 * confidence))
                ranked[neighbor] = RankedFile(
                    str(row["path"]),
                    score,
                    [f"graph-structural:{edge['kind']}:{origin_file.path}"],
                    str(row["purpose"]),
                    str(row["language"]),
                    [],
                    {"graph": score},
                    _ranking_explanations(
                        [f"graph-structural:{edge['kind']}:{origin_file.path}"]
                    ),
                )
                seen.add(neighbor)
                next_frontier.append(neighbor)
            frontier = next_frontier
        self._expand_ui_import_neighborhood(ranked, by_id, terms)

    def _expand_ui_import_neighborhood(
        self, ranked: dict[int, RankedFile], by_id: dict[int, sqlite3.Row], terms: set[str]
    ) -> None:
        if not (terms & _UI_DISPLAY_TERMS):
            return
        traversal_terms = (terms - _LOW_SIGNAL_QUERY_TERMS) | _UI_IMPORT_TRAVERSAL_TERMS
        ranked_ids = sorted(ranked, key=lambda item: (-ranked[item].score, ranked[item].path))
        frontier: list[int] = []
        for file_id in ranked_ids:
            row = by_id[file_id]
            if str(row["purpose"]) in {"test", "documentation", "configuration"}:
                continue
            path_terms = tokenize(str(row["path"]))
            is_ui_source = "src" in path_terms and bool(path_terms & _UI_ENTRYPOINT_PATH_TERMS)
            if not is_ui_source:
                continue
            frontier.append(file_id)
            if len(frontier) >= 8:
                break
        seen = set(ranked)
        added = 0
        for _ in range(3):
            if not frontier or added >= 8:
                return
            placeholders = ",".join("?" for _ in frontier)
            query = f"""SELECT source_file_id, target_file_id, kind, confidence FROM dependencies
                        WHERE (source_file_id IN ({placeholders})
                           OR target_file_id IN ({placeholders}))
                          AND target_file_id IS NOT NULL
                          AND kind='imports'
                        ORDER BY confidence DESC"""
            next_frontier: list[int] = []
            candidates: list[
                tuple[float, str, int, int, sqlite3.Row, sqlite3.Row, set[str]]
            ] = []
            for edge in self.connection.execute(query, [*frontier, *frontier]):
                source = int(edge["source_file_id"])
                target = int(edge["target_file_id"])
                if source in frontier and target != source:
                    origin, neighbor = source, target
                elif target in frontier and source != target:
                    origin, neighbor = target, source
                else:
                    continue
                origin_file = ranked[origin]
                reverse_import = target in frontier and source == neighbor
                origin_path_terms = tokenize(origin_file.path)
                if reverse_import and (
                    origin_file.score < 8.0
                    or not (origin_path_terms & {"component", "components", "page", "pages"})
                ):
                    continue
                neighbor_row = by_id.get(neighbor)
                if neighbor_row is None:
                    continue
                path = str(neighbor_row["path"])
                if "src" not in tokenize(path):
                    continue
                if _is_agent_skill_path(path):
                    continue
                if str(neighbor_row["purpose"]) in {"test", "documentation", "configuration"}:
                    continue
                neighbor_overlap = self._neighbor_overlap(neighbor, path, traversal_terms)
                if not neighbor_overlap:
                    continue
                confidence = float(edge["confidence"])
                score = max(
                    2.0,
                    min(9.0, origin_file.score * 0.80 * confidence + len(neighbor_overlap)),
                )
                current = ranked.get(neighbor)
                if current is not None and current.score >= score:
                    continue
                candidates.append(
                    (score, path, origin, neighbor, neighbor_row, edge, neighbor_overlap)
                )
            for score, path, origin, neighbor, row, edge, neighbor_overlap in sorted(
                candidates, key=lambda item: (-item[0], item[1])
            ):
                if added >= 8:
                    break
                current = ranked.get(neighbor)
                if current is not None and current.score >= score:
                    continue
                origin_file = ranked[origin]
                ranked[neighbor] = RankedFile(
                    path,
                    score,
                    [
                        f"graph-ui-import:{edge['kind']}:{origin_file.path}",
                        "graph terms:" + ",".join(sorted(neighbor_overlap)),
                    ],
                    str(row["purpose"]),
                    str(row["language"]),
                    [],
                    {"graph": score},
                    _ranking_explanations(
                        [
                            f"graph-ui-import:{edge['kind']}:{origin_file.path}",
                            "graph terms:" + ",".join(sorted(neighbor_overlap)),
                        ]
                    ),
                )
                seen.add(neighbor)
                next_frontier.append(neighbor)
                added += 1
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

    def _ui_entrypoint_content_overlap(
        self, path: str, purpose: str, terms: set[str]
    ) -> set[str]:
        if purpose != "source" or not (terms & _UI_DISPLAY_TERMS):
            return set()
        path_terms = tokenize(path)
        if "src" not in path_terms or not (path_terms & _UI_ENTRYPOINT_PATH_TERMS):
            return set()
        content_terms = terms - _LOW_SIGNAL_QUERY_TERMS - _UI_ENTRYPOINT_PATH_TERMS
        if not content_terms:
            return set()
        try:
            source = (self.database.root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return set()
        overlap = tokenize(source) & content_terms
        return {term for term in overlap if len(term) >= 5}

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

    def _memory_relevance_by_path(self, task: str) -> dict[str, float]:
        output: dict[str, float] = {}
        for item in relevant_memory_for_task(self.database, task, limit=8):
            paths = item.get("source_paths", ())
            if not isinstance(paths, (list, tuple)):
                continue
            for path in paths:
                output[str(path)] = min(
                    RANKING_WEIGHTS["memory"],
                    output.get(str(path), 0.0) + 0.75,
                )
        return output

    def _intent_boost(self, intent: list[str], purpose: str, path: str) -> float:
        path_terms = tokenize(path)
        boost = 0.0
        if "test" in intent and purpose == "test":
            boost += RANKING_WEIGHTS["intent"]
        if "documentation" in intent and purpose == "documentation":
            boost += RANKING_WEIGHTS["intent"]
        if "dependency_change" in intent and purpose == "configuration":
            boost += RANKING_WEIGHTS["intent"]
        if "database_change" in intent and (
            purpose == "migration" or path_terms & {"model", "models", "schema", "migration"}
        ):
            boost += RANKING_WEIGHTS["intent"]
        if "api_change" in intent and path_terms & {"api", "route", "routes", "handler"}:
            boost += RANKING_WEIGHTS["intent"]
        if "security" in intent and path_terms & {"auth", "security", "token", "permission"}:
            boost += RANKING_WEIGHTS["intent"]
        if "performance" in intent and path_terms & {"benchmark", "cache", "perf", "performance"}:
            boost += RANKING_WEIGHTS["intent"]
        return min(boost, RANKING_WEIGHTS["intent"] * 2)

    def _metrics_base(
        self, selected: list[RankedFile], candidate_count: int, latency_seconds: float
    ) -> ContextMetrics:
        row = self.connection.execute(
            "SELECT COUNT(*) AS file_count, COALESCE(SUM(size), 0) AS total_bytes FROM files"
        ).fetchone()
        indexed_files = int(row["file_count"]) if row else 0
        repository_text_bytes = int(row["total_bytes"]) if row else 0
        selected_bytes = 0
        for item in selected:
            file_row = self.connection.execute(
                "SELECT size FROM files WHERE path=?", (item.path,)
            ).fetchone()
            if file_row:
                selected_bytes += int(file_row["size"])
        return ContextMetrics(
            indexed_files=indexed_files,
            repository_text_bytes=repository_text_bytes,
            candidate_files_considered=candidate_count,
            files_returned=len(selected),
            selected_file_bytes=selected_bytes,
            retrieval_latency_seconds=latency_seconds,
        )


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
        "memory",
        "relevant_files",
        "architecture",
    )
    minimum = {
        "relevant_files": 1,
        "important_symbols": 0,
        "relationships": 0,
        "memory": 0,
        "architecture": 1,
        "snippets": 0,
        "nearby_dependencies": 0,
        "imports": 0,
    }
    truncated = False
    while True:
        rendered, tokens = _stabilize_render_state(package, renderer, budget, truncated)
        if tokens <= budget:
            return package, rendered
        removed = False
        for key in removal_order:
            values = package.get(key)
            if isinstance(values, list) and len(values) > minimum.get(key, 0):
                values.pop()
                removed = True
                truncated = True
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


def _add_component(components: dict[str, float], name: str, amount: float) -> None:
    components[name] = components.get(name, 0.0) + amount


def _ranking_explanations(reasons: list[str]) -> list[str]:
    output: list[str] = []
    for reason in reasons:
        if reason.startswith("symbol:"):
            output.append(f"exact symbol match: {reason.removeprefix('symbol:')}")
        elif reason.startswith("path:") or reason.startswith("path-specific:"):
            output.append(f"path match: {reason.split(':', 1)[1]}")
        elif reason == "filename":
            output.append("filename matches a task term")
        elif reason == "path phrase":
            output.append("full task phrase appears in the file path")
        elif reason == "test relevance":
            output.append("relevant test file for a fix/test task")
        elif reason == "configuration relevance":
            output.append("configuration file matches dependency/configuration task terms")
        elif reason.startswith("content:"):
            output.append(f"content match: {reason.split(':', 1)[1]}")
        elif reason == "migration relevance":
            output.append("database migration relevance")
        elif reason == "git changed":
            output.append("recent-change relevance from saved Git working-tree state")
        elif reason == "memory relevance":
            output.append("bounded repository-memory relevance from evidence-backed facts")
        elif (
            reason.startswith("graph:")
            or reason.startswith("graph-structural:")
            or reason.startswith("graph-ui-import:")
        ):
            output.append("graph proximity through " + reason.split(":", 1)[1])
        elif reason.startswith("task-intent boost:"):
            output.append("task-intent boost: " + reason.split(":", 1)[1])
        else:
            output.append(reason)
    return output


def _update_render_metrics(
    package: dict[str, Any], rendered: str, requested_budget: int, truncated: bool
) -> None:
    metrics = package.get("metrics")
    if not isinstance(metrics, dict):
        return
    task_context = metrics.get("task_context")
    if isinstance(task_context, dict):
        task_context["files_returned"] = len(package.get("relevant_files", []))
        task_context["context_output_bytes"] = len(rendered.encode("utf-8"))
        task_context["estimated_context_tokens"] = approximate_tokens(rendered)
        task_context["budget_used_percent"] = _bounded_percent(
            int(task_context["estimated_context_tokens"]), requested_budget
        )
        task_context["truncated"] = truncated
    reduction = metrics.get("reduction")
    repository = metrics.get("repository")
    if isinstance(reduction, dict) and isinstance(repository, dict):
        indexed_files = int(repository.get("indexed_files", 0))
        repository_bytes = int(repository.get("repository_text_bytes", 0))
        reduction["file_reduction_percent"] = _bounded_reduction(
            indexed_files, len(package.get("relevant_files", []))
        )
        reduction["context_volume_reduction_percent"] = _bounded_reduction(
            repository_bytes, len(rendered.encode("utf-8"))
        )


def _stabilize_render_state(
    package: dict[str, Any],
    renderer: Callable[[dict[str, Any]], str],
    budget: int,
    truncated: bool,
) -> tuple[str, int]:
    rendered = renderer(package)
    for _ in range(5):
        tokens = approximate_tokens(rendered)
        budget_info = package.get("budget")
        if isinstance(budget_info, dict):
            budget_info["approximate_tokens"] = tokens
            budget_info["truncated"] = truncated
        _update_render_metrics(package, rendered, budget, truncated)
        next_rendered = renderer(package)
        if next_rendered == rendered:
            return rendered, tokens
        rendered = next_rendered
    tokens = approximate_tokens(rendered)
    budget_info = package.get("budget")
    if isinstance(budget_info, dict):
        budget_info["approximate_tokens"] = tokens
        budget_info["truncated"] = truncated
    _update_render_metrics(package, rendered, budget, truncated)
    return rendered, tokens


def _bounded_percent(numerator: int | float, denominator: int | float) -> float:
    if denominator <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (float(numerator) / float(denominator)) * 100.0)), 2)


def _bounded_reduction(total: int | float, selected: int | float) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (1.0 - float(selected) / float(total)) * 100.0)), 2)


def _is_agent_skill_path(path: str) -> bool:
    return path.replace("\\", "/").startswith(_AGENT_SKILL_PREFIX)


def _is_application_code_query(
    raw_terms: set[str], expanded_terms: set[str], intent: list[str]
) -> bool:
    if raw_terms & _AGENT_QUERY_TERMS:
        return False
    if expanded_terms & _APPLICATION_CODE_TERMS:
        return True
    return bool(set(intent) & {"api_change", "database_change", "security", "performance"})
