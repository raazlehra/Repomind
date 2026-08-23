from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from repomind import __version__
from repomind.config import Config
from repomind.database import IndexDatabase
from repomind.doctor import run_doctor
from repomind.errors import RepoMindError
from repomind.formatters import render_context, render_records
from repomind.indexer import Indexer, IndexResult, ProgressCallback
from repomind.integration import install_codex
from repomind.map import build_repository_map, render_repository_map
from repomind.queries import callers, dependencies, impact, snippets, symbol_details
from repomind.repository import resolve_repository
from repomind.retrieval import ContextRetriever, fit_context_to_budget
from repomind.watcher import watch_repository, watchdog_available

_FORMATS = ("text", "markdown", "json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repomind",
        description="Local-first persistent code context engine for AI coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"RepoMind {__version__}")
    parser.add_argument(
        "--verbose", action="store_true", help="show tracebacks for unexpected errors"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="scan and initialize a repository index")
    init_parser.add_argument("path", nargs="?", default=".")
    init_parser.add_argument(
        "--force", action="store_true", help="replace an existing RepoMind index"
    )
    init_parser.add_argument("--format", choices=_FORMATS, default="text")

    refresh_parser = subparsers.add_parser("refresh", help="incrementally update changed files")
    _repository_argument(refresh_parser)
    refresh_parser.add_argument("--format", choices=_FORMATS, default="text")

    status_parser = subparsers.add_parser("status", help="show index and working-tree status")
    _repository_argument(status_parser)
    status_parser.add_argument("--format", choices=_FORMATS, default="text")

    watch_parser = subparsers.add_parser("watch", help="watch files and incrementally refresh")
    _repository_argument(watch_parser)
    watch_parser.add_argument("--debounce", type=float, default=0.5)

    map_parser = subparsers.add_parser("map", help="print a compact repository map")
    _repository_argument(map_parser)
    map_parser.add_argument("--depth", type=int)
    map_parser.add_argument("--symbols", action="store_true")
    map_parser.add_argument("--json", action="store_true", help="alias for --format json")
    map_parser.add_argument("--format", choices=_FORMATS, default="text")

    context_parser = subparsers.add_parser(
        "context", help="retrieve task-specific repository context"
    )
    context_parser.add_argument("task")
    _repository_argument(context_parser)
    context_parser.add_argument("--budget", type=int)
    context_parser.add_argument(
        "--mode", choices=("minimal", "balanced", "deep"), default="balanced"
    )
    context_parser.add_argument("--level", type=int, choices=(1, 2, 3), default=1)
    context_parser.add_argument("--format", choices=_FORMATS, default="text")

    for name, help_text in (
        ("symbol", "show matching symbol metadata"),
        ("callers", "show statically detected callers"),
        ("dependencies", "show outgoing file or symbol dependencies"),
        ("impact", "estimate direct, indirect, test, route, and UI impact"),
        ("snippets", "read bounded source snippets for a symbol"),
    ):
        command_parser = subparsers.add_parser(name, help=help_text)
        command_parser.add_argument("target")
        _repository_argument(command_parser)
        command_parser.add_argument("--format", choices=_FORMATS, default="text")

    doctor_parser = subparsers.add_parser("doctor", help="run actionable diagnostics")
    doctor_parser.add_argument("path", nargs="?", default=".")
    doctor_parser.add_argument("--format", choices=_FORMATS, default="text")

    install_parser = subparsers.add_parser(
        "install-codex", help="install Codex skill and AGENTS.md guidance"
    )
    install_parser.add_argument("path", nargs="?", default=".")
    install_parser.add_argument("--format", choices=_FORMATS, default="text")

    mcp_parser = subparsers.add_parser("mcp", help="run the local RepoMind MCP server")
    mcp_parser.add_argument("--debug", action="store_true", help="include debug details in MCP errors")
    return parser


def _repository_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repository", "-C", default=".", help="repository path (default: current directory)"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (RepoMindError, ValueError) as exc:
        print(f"RepoMind error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except Exception as exc:
        if bool(getattr(args, "verbose", False)):
            traceback.print_exc()
        else:
            print(f"RepoMind error: {exc}. Re-run with --verbose for details.", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    command = str(args.command)
    if command == "init":
        root = resolve_repository(Path(args.path), require_index=False)
        index_result = Indexer(root).initialize(
            force=bool(args.force), progress=_progress_callback()
        )
        _print_index_result("initialized", index_result, str(args.format))
        return 0
    if command == "refresh":
        root = resolve_repository(Path(args.repository))
        index_result = Indexer(root).refresh(progress=_progress_callback())
        _print_index_result("refreshed", index_result, str(args.format))
        return 0
    if command == "status":
        root = resolve_repository(Path(args.repository))
        config = Config.load(root)
        with IndexDatabase(root) as database:
            detection = Indexer(root, config).detect_changes(database)
            counts = database.counts()
            integrity = database.integrity_check()
            data = {
                "repository": str(root),
                "indexed_files": counts["files"],
                "changed": len(detection.changes.modified) + len(detection.changes.renamed),
                "deleted": len(detection.changes.deleted),
                "new": len(detection.changes.created),
                "renamed": [{"from": old, "to": new} for old, new in detection.changes.renamed],
                "index_healthy": integrity == "ok",
                "symbols": counts["symbols"],
                "dependencies": counts["dependencies"],
                "last_refresh": database.get_meta("last_refresh_at"),
            }
        print(render_records(data, str(args.format)), end="")
        return 0
    if command == "watch":
        root = resolve_repository(Path(args.repository))
        config = Config.load(root)
        backend = "watchdog events" if watchdog_available() else "watchdog not installed"
        print(f"Watching {root} ({backend}); press Ctrl-C to stop.", file=sys.stderr)

        def on_update(result: IndexResult) -> None:
            print(
                f"Refreshed: +{len(result.changes.created)} ~{len(result.changes.modified)} "
                f"-{len(result.changes.deleted)} renames={len(result.changes.renamed)} "
                f"parsed={result.parsed_files} ({result.duration_seconds:.3f}s)",
                flush=True,
            )

        watch_repository(root, config, on_update, float(args.debounce))
        return 0
    if command == "map":
        root = resolve_repository(Path(args.repository))
        if args.depth is not None and args.depth < 1:
            raise ValueError("--depth must be at least 1")
        with IndexDatabase(root) as database:
            items = build_repository_map(database, args.depth, bool(args.symbols))
        output_format = "json" if bool(args.json) else str(args.format)
        print(render_repository_map(items, output_format), end="")
        return 0
    if command == "context":
        root = resolve_repository(Path(args.repository))
        config = Config.load(root)
        with IndexDatabase(root) as database:
            retriever = ContextRetriever(database)
            budget = retriever.resolve_budget(str(args.mode), args.budget, config.context_budget)
            package = retriever.build_context(str(args.task), budget, int(args.level))
            _, rendered = fit_context_to_budget(
                package,
                lambda value: render_context(value, str(args.format)),
                budget,
            )
        print(rendered, end="")
        return 0
    if command in {"symbol", "callers", "dependencies", "impact", "snippets"}:
        root = resolve_repository(Path(args.repository))
        with IndexDatabase(root) as database:
            handlers = {
                "symbol": symbol_details,
                "callers": callers,
                "dependencies": dependencies,
                "impact": impact,
                "snippets": snippets,
            }
            data = handlers[command](database, str(args.target))
        print(render_records(data, str(args.format)), end="")
        return 0
    if command == "doctor":
        candidate = Path(args.path)
        try:
            root = resolve_repository(candidate)
        except RepoMindError:
            root = resolve_repository(candidate, require_index=False)
        print(render_records(run_doctor(root), str(args.format)), end="")
        return 0
    if command == "install-codex":
        root = resolve_repository(Path(args.path), require_index=False)
        install_result = install_codex(root)
        data = {
            "skill": {
                "path": install_result.skill_path,
                "action": install_result.skill_action,
            },
            "agents": {
                "path": install_result.agents_path,
                "action": install_result.agents_action,
            },
            "next_step": 'Run: repomind context "<task>" --format markdown',
        }
        print(render_records(data, str(args.format)), end="")
        return 0
    if command == "mcp":
        from repomind.mcp import run_stdio

        run_stdio(debug=bool(args.debug))
        return 0
    raise RepoMindError(f"Unknown command: {command}")


def _print_index_result(action: str, result: IndexResult, output_format: str) -> None:
    data = {
        "index": action,
        "indexed_files": result.indexed_files,
        "parsed_files": result.parsed_files,
        "created": len(result.changes.created),
        "modified": len(result.changes.modified),
        "deleted": len(result.changes.deleted),
        "renamed": len(result.changes.renamed),
        "parse_errors": result.parse_errors,
        "duration_seconds": round(result.duration_seconds, 4),
        "index_bytes": result.index_bytes,
    }
    print(render_records(data, output_format), end="")


def _progress_callback() -> ProgressCallback | None:
    if not sys.stderr.isatty():
        return None

    def progress(index: int, path: str) -> None:
        print(f"\rIndexing {index}: {path[:70]:<70}", end="", file=sys.stderr, flush=True)

    return progress


if __name__ == "__main__":
    raise SystemExit(main())
