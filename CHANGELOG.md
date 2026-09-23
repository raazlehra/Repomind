# Changelog

## 2.0.0-beta.10 - Unreleased

- Added bounded, change-aware `test-impact` analysis with per-test framework ownership,
  migration and cross-stack route/API evidence, deterministic commands, and visible truncation metadata.
- Kept test-impact strictly analysis-only across CLI and MCP: it returns bounded command
  recommendations as data and never executes repository code.

## 2.0.0-beta.9 - 2026-08-31

- Suppressed `.agents/skills/**` noise for normal application-code retrieval while preserving explicit skill-query retrieval.
- Improved universe, symbols, tickers, stocks, watchlist, and scanner-symbol retrieval through bounded lexical aliases and dependency/import expansion.
- Added a lexical/token-based content fallback for snippets when exact symbol matching returns no results.
- Added bounded TypeScript/React UI display-path traversal across hooks, API clients, models, pages, and result-display components.
- Added finance/full-stack retrieval regression fixtures covering scanner universe loading, generated analysis display, conceptual snippet queries, and irrelevant agent-skill overlap.
- Isolated the progressive agent workflow test so simulated edits run against a temporary fixture copy instead of tracked test fixtures.

## 2.0.0-beta.8 - Unreleased

- Added local Repository Memory for durable, evidence-backed repository facts.
- Added schema v2 migration that preserves existing beta.7 index data and adds the `memory` table.
- Added manual memory CRUD commands: `repomind memory add/list/show/remove/validate/stale`.
- Added conservative automatic memory extraction from indexed manifests, configuration, layouts, and strong source markers.
- Added evidence hashing, staleness states, validation behavior, ContextPack memory inclusion, and bounded memory relevance in ranking explanations.
- Added bounded MCP memory access through `repomind_memory`.
- Extended stats/status, tests, evaluators, benchmarks, and docs for Repository Memory.

## 2.0.0-beta.6 - Unreleased

- Added automatic retrieval-time index freshness so context, map, symbol, caller, dependency, impact, and snippet reads reflect saved working-tree changes without a manual refresh.
- Added release-gate coverage for concurrent retrieval freshness, watch/retrieval overlap, atomic refresh visibility, parser failure, and recovery after fixing parser errors.
- Added structured freshness status values for read paths: already fresh, refreshed, and partial when indexed files currently have parser errors.
- Promoted the v2 repository audit work from alpha to beta metadata (`2.0.0b6`) for release validation.
- Added `repomind audit` for deterministic local Markdown and JSON repository audit reports from the RepoMind index.
- The audit report summarizes repository structure, detected architecture, important files, API routes, test files, likely test commands, risk notes, and a suggested AI context pack.
- Added structured local risk findings for paid-audit-style review, including SQLite-only month filters, weak production secrets, unsafe CORS, provisioning token exposure, frontend `localStorage` bearer tokens, parent provisioning email mismatch hotspots, and missing frontend flow coverage.
- Refined runtime secret, CORS, and parent provisioning checks so test-only or validated evidence is not promoted to production runtime findings.
- Reformatted Markdown audit output with executive summary, architecture, release risk, readiness, context pack, and next-action sections while keeping the JSON artifact deterministic.

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
