from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from repomind.config import Config
from repomind.context_pack import TOKEN_ESTIMATION_METHOD, estimate_tokens_from_bytes
from repomind.database import INDEX_DIRECTORY, INDEX_FILENAME, IndexDatabase
from repomind.errors import NotIndexedError, RepoMindError
from repomind.formatters import render_context
from repomind.freshness import ensure_index_fresh
from repomind.git import inspect_git
from repomind.indexer import Indexer
from repomind.map import build_repository_map
from repomind.memory import (
    add_manual_memory,
    list_memory,
    memory_counts,
    relevant_memory_for_task,
    remove_memory,
    show_memory,
    stale_memory,
    validate_memory,
)
from repomind.queries import callers, dependencies, impact, snippets, symbol_details
from repomind.repository import resolve_repository
from repomind.retrieval import ContextRetriever, fit_context_to_budget
from repomind.test_impact import TestImpactLimits, analyze_test_impact


def status(repository: str) -> dict[str, Any]:
    root = _canonical_repository(repository, require_index=False)
    git = inspect_git(root)
    index_path = root / INDEX_DIRECTORY / INDEX_FILENAME
    if not index_path.is_file():
        return {
            "repository": str(root),
            "initialized": False,
            "index_health": "missing",
            "indexed_file_count": 0,
            "changed": None,
            "new": None,
            "deleted": None,
            "renamed": [],
            "git": _git_payload(git),
            "refresh_recommended": False,
        }
    config = Config.load(root)
    with IndexDatabase(root) as database:
        detection = Indexer(root, config).detect_changes(database)
        counts = database.counts()
        integrity = database.integrity_check()
        changed = len(detection.changes.modified) + len(detection.changes.renamed)
        new = len(detection.changes.created)
        deleted = len(detection.changes.deleted)
        return {
            "repository": str(root),
            "initialized": True,
            "index_health": "ok" if integrity == "ok" else integrity,
            "indexed_file_count": counts["files"],
            "changed": changed,
            "new": new,
            "deleted": deleted,
            "renamed": [
                {"from": old, "to": new_path} for old, new_path in detection.changes.renamed
            ],
            "git": _git_payload(git),
            "refresh_recommended": bool(changed or new or deleted),
            "symbols": counts["symbols"],
            "dependencies": counts["dependencies"],
            "memory": memory_counts(database),
            "last_refresh": database.get_meta("last_refresh_at"),
        }


def context(
    repository: str,
    task: str,
    budget: int | None = None,
    level: int = 1,
    explain: bool = False,
) -> dict[str, Any]:
    root = _canonical_repository(repository)
    config = Config.load(root)
    freshness = ensure_index_fresh(root, config)
    with IndexDatabase(root) as database:
        retriever = ContextRetriever(database)
        resolved_budget = retriever.resolve_budget("balanced", budget, config.context_budget)
        package = retriever.build_context(task, resolved_budget, level, explain=explain)
        fitted, _ = fit_context_to_budget(
            package, lambda value: render_context(value, "json"), resolved_budget
        )
    return {
        "repository": str(root),
        "task": task,
        "context": fitted,
        "freshness": freshness.as_dict(),
        "retrieval_confidence": _retrieval_confidence(fitted),
    }


def stats(repository: str) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        counts = database.counts()
        total_row = database.connection.execute(
            "SELECT COALESCE(SUM(size), 0) AS total_bytes FROM files"
        ).fetchone()
        route_row = database.connection.execute("SELECT COUNT(*) FROM routes").fetchone()
        repository_text_bytes = int(total_row["total_bytes"]) if total_row else 0
        return {
            "title": "RepoMind Repository Intelligence",
            "repository": str(root),
            "indexed_files": counts["files"],
            "symbols": counts["symbols"],
            "routes": int(route_row[0]) if route_row else 0,
            "relationships": counts["dependencies"],
            "repository_text_bytes": repository_text_bytes,
            "estimated_repository_tokens": estimate_tokens_from_bytes(repository_text_bytes),
            "token_estimation_method": TOKEN_ESTIMATION_METHOD,
            "last_refresh": database.get_meta("last_refresh_at"),
            "freshness": freshness.as_dict(),
            "memory": memory_counts(database),
        }


def symbol(repository: str, target: str) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        data = symbol_details(database, target)
        for item in data.get("matches", []):
            item["relationships"] = _symbol_relationships(database, str(item["name"]))
        data["repository"] = str(root)
        data["freshness"] = freshness.as_dict()
        data["ambiguous"] = len(data.get("matches", [])) > 1
        return data


def symbol_callers(repository: str, target: str) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        data = callers(database, target)
        data["repository"] = str(root)
        data["freshness"] = freshness.as_dict()
        return data


def structural_dependencies(repository: str, target: str) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        data = dependencies(database, target)
        data["repository"] = str(root)
        data["freshness"] = freshness.as_dict()
        return data


def change_impact(repository: str, target: str) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        data = impact(database, target)
        data["repository"] = str(root)
        data["freshness"] = freshness.as_dict()
        return data



def test_impact(
    repository: str,
    changed_files: list[str] | None = None,
    base: str | None = None,
    *,
    limits: TestImpactLimits | None = None,
    output_mode: str = "compact_json",
) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        return analyze_test_impact(
            database,
            changed_files,
            base=base,
            limits=limits,
            output_mode=output_mode,  # type: ignore[arg-type]
            additional_metadata={"freshness": freshness.as_dict()},
        )


def bounded_snippets(
    repository: str,
    target: str,
    line_bound: int | None = None,
    token_bound: int | None = None,
) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        data = snippets(database, target)
        if not data.get("snippets"):
            file_row = database.file_by_path(target.replace("\\", "/").removeprefix("./"))
            if file_row is not None:
                data["snippets"] = [_file_snippet(database, str(file_row["path"]), line_bound)]
        if line_bound is not None or token_bound is not None:
            for item in data.get("snippets", []):
                item["code"] = _bound_code(str(item["code"]), line_bound, token_bound)
        data["repository"] = str(root)
        data["freshness"] = freshness.as_dict()
        return data


def refresh(repository: str) -> dict[str, Any]:
    root = _canonical_repository(repository)
    start = time.perf_counter()
    result = Indexer(root).refresh()
    health = status(str(root))
    return {
        "repository": str(root),
        "new_files": list(result.changes.created),
        "modified_files": list(result.changes.modified),
        "deleted_files": list(result.changes.deleted),
        "renamed_files": [
            {"from": old, "to": new_path} for old, new_path in result.changes.renamed
        ],
        "parsed_file_count": result.parsed_files,
        "elapsed_seconds": round(time.perf_counter() - start, 4),
        "index_health": health["index_health"],
        "indexed_file_count": health["indexed_file_count"],
        "memory": health.get("memory", {}),
    }


def memory_add(
    repository: str,
    value: str,
    category: str,
    key: str | None = None,
    source_paths: list[str] | None = None,
    source_symbols: list[str] | None = None,
) -> dict[str, Any]:
    root = _canonical_repository(repository)
    with IndexDatabase(root) as database:
        record = add_manual_memory(
            database,
            value,
            category,
            key,
            tuple(source_paths or ()),
            tuple(source_symbols or ()),
        )
    return {"repository": str(root), "memory": record}


def memory_list(
    repository: str,
    category: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        return {
            "repository": str(root),
            "freshness": freshness.as_dict(),
            "memory": list_memory(database, category, status_filter, limit),
            "counts": memory_counts(database),
        }


def memory_show(repository: str, identifier: str) -> dict[str, Any]:
    root = _canonical_repository(repository)
    with IndexDatabase(root) as database:
        return {"repository": str(root), "memory": show_memory(database, identifier)}


def memory_remove(repository: str, identifier: str) -> dict[str, Any]:
    root = _canonical_repository(repository)
    with IndexDatabase(root) as database:
        result = remove_memory(database, identifier)
    return {"repository": str(root), **result}


def memory_validate(repository: str, identifier: str | None = None) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        result = validate_memory(database, identifier)
        result["counts"] = memory_counts(database)
        result["freshness"] = freshness.as_dict()
    return {"repository": str(root), **result}


def memory_stale(repository: str, limit: int = 50) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        return {
            "repository": str(root),
            "freshness": freshness.as_dict(),
            "memory": stale_memory(database, limit),
            "counts": memory_counts(database),
        }


def memory_for_task(repository: str, task: str, limit: int = 10) -> dict[str, Any]:
    root = _canonical_repository(repository)
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        return {
            "repository": str(root),
            "task": task,
            "freshness": freshness.as_dict(),
            "memory": relevant_memory_for_task(database, task, limit),
            "counts": memory_counts(database),
        }


def repository_map(
    repository: str,
    depth: int | None = None,
    include_symbols: bool = False,
) -> dict[str, Any]:
    root = _canonical_repository(repository)
    if depth is not None and depth < 1:
        raise ValueError("depth must be at least 1")
    freshness = ensure_index_fresh(root)
    with IndexDatabase(root) as database:
        return {
            "repository": str(root),
            "freshness": freshness.as_dict(),
            "files": build_repository_map(database, depth, include_symbols),
        }


def error_payload(exc: Exception, debug: bool = False) -> dict[str, Any]:
    if isinstance(exc, NotIndexedError):
        payload: dict[str, Any] = {
            "error": "repository_not_indexed",
            "message": "Run repomind init for this repository.",
        }
    elif isinstance(exc, ValueError):
        payload = {"error": "invalid_arguments", "message": str(exc)}
    elif isinstance(exc, RepoMindError):
        payload = {"error": "repomind_error", "message": str(exc)}
    else:
        payload = {"error": "internal_error", "message": "RepoMind MCP request failed."}
    if debug:
        payload["debug"] = repr(exc)
    return payload


def _canonical_repository(repository: str, require_index: bool = True) -> Path:
    if not repository:
        raise ValueError("repository is required")
    return resolve_repository(Path(repository), require_index=require_index)


def _git_payload(git: Any) -> dict[str, Any]:
    return {
        "available": git.available,
        "branch": git.branch,
        "head": git.head,
        "changed_files": list(git.changed_files),
        "error": git.error,
    }


def _retrieval_confidence(package: dict[str, Any]) -> str:
    files = package.get("relevant_files", [])
    if not files:
        return "low"
    scores = [float(item.get("score", 0.0)) for item in files if isinstance(item, dict)]
    if scores and max(scores) >= 12:
        return "high"
    if scores and max(scores) >= 5:
        return "medium"
    return "low"


def _symbol_relationships(database: IndexDatabase, name: str) -> dict[str, Any]:
    return {
        "callers": callers(database, name).get("callers", [])[:10],
        "dependencies": dependencies(database, name).get("dependencies", [])[:10],
    }


def _file_snippet(
    database: IndexDatabase, relative_path: str, line_bound: int | None
) -> dict[str, Any]:
    path = database.root / relative_path
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    max_lines = min(max(line_bound or 40, 1), 120)
    end = min(len(lines), max_lines)
    code = "\n".join(f"{line}: {lines[line - 1]}" for line in range(1, end + 1))
    return {
        "symbol": None,
        "file": relative_path,
        "lines": f"1-{end}",
        "complete_symbol": False,
        "code": code,
    }


def _bound_code(code: str, line_bound: int | None, token_bound: int | None) -> str:
    lines = code.splitlines()
    if line_bound is not None:
        lines = lines[: max(line_bound, 1)]
    if token_bound is None:
        return "\n".join(lines)
    output: list[str] = []
    total = 0
    for line in lines:
        estimated = max(1, len(line) // 4)
        if output and total + estimated > token_bound:
            break
        output.append(line)
        total += estimated
    return "\n".join(output)
