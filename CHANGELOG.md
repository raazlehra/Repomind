# Changelog

## 2.0.0a1 - Unreleased

- Added an initial `repomind audit` command that generates deterministic Markdown and JSON repository audit reports from the local index.
- The audit report summarizes repository structure, detected architecture, important files, API routes, test files, likely test commands, risk notes, and a suggested AI context pack.
- Added structured local risk findings for paid-audit-style review, including SQLite-only month filters, weak production secrets, unsafe CORS, provisioning token exposure, frontend `localStorage` bearer tokens, parent provisioning email mismatch hotspots, and missing frontend flow coverage.

## 1.0.1

Hotfix release for UTF-8 BOM Python parsing.

- Fixed Python parsing for files encoded with a leading UTF-8 BOM (`EF BB BF`), preventing `SyntaxError: invalid non-printable character U+FEFF` parse errors during indexing.
- Preserved existing raw-file hashing and incremental change detection behavior.
- Added regression coverage for normal UTF-8 files, UTF-8 BOM files, import extraction, FastAPI route extraction, incremental refresh, and modified BOM files.

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
