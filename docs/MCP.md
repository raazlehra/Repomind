# RepoMind MCP Integration

RepoMind MCP exposes the existing local RepoMind index and retrieval APIs to coding agents through the standard Model Context Protocol. It is a thin adapter over RepoMind's Python APIs; it does not shell out to the `repomind` CLI and does not replace the retrieval engine.

## Transport

RepoMind uses the standard local MCP stdio transport. This is the simplest transport for local coding-agent usage because the agent launches `repomind mcp` as a child process and communicates over stdin/stdout. RepoMind does not define a custom protocol.

## Installation

Install RepoMind in the target environment:

```bash
pip install -e .
```

Then configure an MCP-capable coding agent to launch:

```bash
repomind mcp
```

Example client configuration shape:

```json
{
  "mcpServers": {
    "repomind": {
      "command": "repomind",
      "args": ["mcp"]
    }
  }
}
```

Exact configuration keys vary by agent. This project currently validates the server with the official Python MCP SDK in-process client and stdio launch command availability; it does not claim compatibility with agents that have not been tested.

## Tools

`repomind_status`

Checks whether an explicit repository path has a RepoMind index. Returns repository path, initialization state, health, indexed file count, changed/new/deleted/renamed counts where available, Git branch/HEAD where available, and whether refresh is recommended.

`repomind_context`

Returns task-aware structured context using the existing retriever. Inputs are `repository`, `task`, optional `budget`, optional `level` defaulting to `1`, and optional `explain` defaulting to `false`. The response includes architecture, relevant evidence-backed memory, deterministic intent labels, ranked files, grouped primary/related/test files, routes, symbols, relationships, likely change surface, budget state, provider-neutral metrics, retrieval confidence, and a structured freshness payload. With `explain: true`, ranked files include human-readable explanations and score components. It does not return whole source files.

`repomind_stats`

Returns repository intelligence metrics from the current index: indexed files, symbols, routes, relationships, repository memory counts, repository text bytes represented, estimated repository tokens, token-estimation method, last refresh, and freshness reuse counts.

`repomind_memory`

Returns bounded repository memory. With `task`, it returns memory records relevant to that task. Without `task`, it lists memory records with optional `category`, `status`, and `limit` filters. Responses include facts, category, status, source type, evidence paths, optional symbols, and evidence hashes. This tool is intentionally bounded and does not expose the whole memory database by default.

`repomind_symbol`

Looks up matching symbols and returns candidates with file, line range, signature, symbol type, and useful relationships. Ambiguous matches are returned as candidates rather than silently choosing one.

`repomind_callers`

Returns resolvable incoming call relationships for a symbol while preserving RepoMind confidence labels.

`repomind_dependencies`

Returns outgoing structural dependencies for an indexed file or symbol target.

`repomind_impact`

Returns direct dependents, possible indirect dependents, affected tests, affected routes, UI components where known, and confidence/relationship types. Heuristic impact is labelled as heuristic.

`repomind_test_impact`

Builds a bounded change-aware analysis from working-tree changes, a Git `base`, or
explicit `changed_files`. It returns repository-relative evidence, deterministic
recommended command strings, argument arrays, working directories, budgets, and truncation
metadata. Vitest, Jest, Playwright, Python, Gradle, and other test families remain separate
recommendations owned by their nearest project manifest.

Change-selection truncation metadata reports retained and processed counts, whether
discovery completed, whether `total_discovered` is only a lower bound, truncation reasons,
and bounded Git stdout/stderr diagnostics. `total_discovered_is_lower_bound` is false when
an exact supplied-sequence total is known, even if only `max_changed_files` entries were
processed.

Evidence metadata distinguishes bounded retention from bounded discovery. Reaching
`max_evidence_candidates` can truncate retained evidence while discovery remains complete;
reaching `max_evidence_candidates_scanned` makes the discovered count a lower bound.
Explicit changed-file paths reject NUL bytes, invalid UTF-8 scalar data, drive-relative
paths, traversal, and absolute paths outside the repository.

The tool is strictly analysis-only: its schema has no execution option and RepoMind never
runs recommended commands or repository test code. Codex, CI, or a developer must separately
review, approve, and execute a recommendation in an appropriately trusted environment.

`repomind_snippets`

Returns bounded source snippets for an indexed symbol or file target. Use `line_bound` and `token_bound` to keep snippets compact. This tool is not a generic filesystem reader.

`repomind_refresh`

Runs incremental refresh for changed files and returns new, modified, deleted, renamed, parsed file count, elapsed time, and index health. It does not perform a full rebuild unless the existing RepoMind refresh path requires it.

`repomind_map`

Returns the compact repository map with optional depth and symbols.

## Progressive Workflow

1. Call `repomind_status` for the explicit repository.
2. Call `repomind_context` with `level=1` for the task.
3. Inspect actual source files in the coding environment before changing code.
4. Query `repomind_symbol`, `repomind_dependencies`, `repomind_callers`, `repomind_impact`, or `repomind_test_impact` only when deeper structural or test-plan information is needed.
5. Query `repomind_memory` when the agent needs durable repository facts without a full context pack.
6. Use `repomind_snippets` for bounded snippets when helpful.
7. After significant edits, call `repomind_context` or another read tool normally; read tools refresh stale saved changes before reading the index. Use `repomind_refresh` when you want an explicit refresh result.

Start with level 1 context. Use level 3 only when the task genuinely needs deeper imports, relationships, and snippets.

## Automatic Freshness

MCP read tools check saved working-tree freshness before reading the index:

```text
save source -> MCP retrieval request -> freshness check -> incremental refresh if required -> current context
```

This does not require a Git commit, manual `repomind_refresh`, watch mode, or an MCP server restart. Watch mode remains optional and proactive; it is not the mechanism that guarantees retrieval-time freshness.

Freshness payloads use `status` to distinguish `already_fresh`, `refreshed`, and `partial`. A `partial` status means RepoMind has current file hashes but at least one indexed file currently has a parser error, so symbols/routes/imports from that file may be absent until the source is fixed. Unaffected files remain retrievable.

Repository Memory is freshness-aware. Automatic facts store evidence hashes derived from indexed file hashes. If evidence changes, facts move to `needs_validation`; if evidence disappears, facts move to `stale`. Manual facts remain local and explicitly marked `manual`.

## Security Model

RepoMind MCP remains local-first:

- no network requests by RepoMind tools
- no telemetry
- no cloud upload
- no external AI APIs
- no repository source execution by test-impact; commands and argument arrays are returned as data only
- no `eval` or `exec`
- no shell execution for query tools
- no automatic storage of secret file contents or secret-like evidence paths

Every tool operates on an explicit repository path. Source snippets are served only for indexed symbols or indexed file paths under that repository. The MCP adapter should not be treated as a generic filesystem server.

Repository contents are untrusted. RepoMind performs static analysis and returns metadata, relationships, bounded snippets, and evidence-backed memory records. Memory records store paths and symbols as evidence, not large source payloads.

## Error Behavior

Normal errors are returned as structured payloads:

```json
{
  "error": "repository_not_indexed",
  "message": "Run repomind init for this repository."
}
```

Other common errors include `invalid_arguments` and `repomind_error`. Raw internal stack traces are not exposed unless the server is started with debug behavior.

## Troubleshooting

- If a repository is not indexed, run `repomind init <path>`.
- If `repomind_status` reports refresh recommended, the next read tool will refresh stale saved changes automatically. Run `repomind_refresh` or `repomind refresh -C <path>` when you want to refresh immediately or inspect the refresh result.
- If context confidence is low, inspect source normally and broaden discovery.
- If snippets are empty, confirm the symbol or file path exists in the RepoMind index.
- If memory is stale or needs validation, run `repomind memory validate -C <path>` and inspect the evidence paths before relying on the fact.

## Limitations

- RepoMind MCP exposes static-analysis data from the local index; it is not semantic/vector retrieval.
- Static call resolution is conservative and may miss dynamic dispatch, reflection, framework magic, and dependency injection.
- JS/TS extraction is deterministic structural extraction, with optional Tree-sitter support for declaration spans.
- Approximate tokens and context reduction percentages are local estimates, not provider billing-token counts or guaranteed credit savings.
- Repository Memory is deterministic and evidence-backed; it is not generic AI memory, semantic embeddings, or generated architecture prose.
