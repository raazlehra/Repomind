# Changelog

## 1.0.0

Initial V1 release.

- Added persistent local repository indexing with a versioned SQLite cache in `.repomind/`.
- Added incremental refresh for created, modified, deleted, and unambiguous renamed files.
- Added structural parsing for Python and deterministic JavaScript/TypeScript/JSX/TSX extraction, with conservative fallback extraction for additional languages.
- Added dependency graph generation for imports, calls, inheritance, routes, tests, and confidence-scored relationships.
- Added task-aware retrieval using paths, symbols, lexical relevance, graph proximity, file purpose, tests, and Git state.
- Added explicit context budgets, local approximate token accounting, and progressive disclosure levels.
- Added symbol lookup, callers, dependencies, impact analysis, and bounded source snippets.
- Added the `repomind` CLI for indexing, refresh, status, map, context, graph queries, doctor checks, watch mode, Codex installation, and MCP startup.
- Added a local stdio MCP server exposing status, context, symbol, callers, dependencies, impact, snippets, refresh, and map tools.
- Added Codex skill and project integration helpers for local-first agent workflows.
- Added deterministic benchmarks, retrieval evaluations, weighted quality metrics, and real-project validation reports.
- Documented local-first privacy and security behavior: no telemetry, no cloud upload, no external AI APIs, and no execution of repository source during indexing.
