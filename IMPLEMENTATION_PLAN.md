# RepoMind implementation plan

## Stack and decisions

- Python 3.11+ with an `argparse` CLI to keep runtime dependencies at zero.
- SQLite (WAL mode, foreign keys, versioned migrations) under `.repomind/index.sqlite3`.
- Python's `ast` for high-confidence Python structure; deterministic lexical parsers for JS/TS/JSX/TSX and fallback languages. A parser protocol and registry leave room for optional Tree-sitter adapters.
- Static analysis only. Repository code is never imported or executed.
- Event-driven watching through optional `watchdog`; no continuous whole-tree polling fallback.
- Deterministic lexical/structural ranking; no network, telemetry, embeddings, or AI API.

## Milestones

1. Package skeleton, configuration, scanner, ignore/security rules, schema, and CLI.
2. Parser abstraction plus Python and JS/TS/fallback structural extractors.
3. Import resolution and typed/confidence-scored dependency graph.
4. Architecture detection, deterministic task ranking, bounded context builder, and progressive lookup commands.
5. Hash-based incremental create/modify/delete/rename handling and debounced watcher.
6. Git metadata, impact analysis, diagnostics, Codex skill, and idempotent `AGENTS.md` integration.
7. Unit/integration fixtures, benchmark harness, documentation, packaging, and quality gates.

## Validation

Run pytest, mypy, Ruff, package build/install validation, benchmark fixtures, and CLI smoke tests. Record only measured benchmark outputs and document incomplete or heuristic behavior explicitly.
