# RepoMind MCP Integration

RepoMind MCP exposes the existing local RepoMind index and retrieval APIs to coding agents through the standard Model Context Protocol. It is a thin adapter over RepoMind's Python APIs; it does not shell out to the `repomind` CLI and does not replace the retrieval engine.

## Transport

RepoMind uses the standard local MCP stdio transport. This is the simplest transport for local coding-agent usage because the agent launches `repomind mcp` as a child process and communicates over stdin/stdout. RepoMind does not define a custom protocol.

## Server command

Install a release wheel as described in [Installation and lifecycle](INSTALLATION.md). Configure
clients with the absolute Python interpreter from that environment:

```powershell
& "C:\path\to\repomind-venv\Scripts\python.exe" -m repomind mcp
```

Using `python -m repomind mcp` binds the server to a known installation and avoids a stale
`repomind` command shim elsewhere on `PATH`. The server reserves stdout for JSON-RPC protocol
messages; diagnostics belong on stderr.

## Codex CLI and IDE extension — verified

The installed Codex CLI's current syntax for a local stdio server is:

```powershell
$repomindPython = (Resolve-Path "C:\path\to\repomind-venv\Scripts\python.exe").Path
codex mcp list
codex mcp get repomind  # run only if the name is already listed
codex mcp add repomind -- $repomindPython -m repomind mcp
codex mcp list
codex mcp get repomind
```

Choose another server name, such as `repomind-dev`, rather than overwriting an existing entry
that points to a different installation. Codex stores MCP configuration in its `config.toml`;
the Codex CLI, Codex IDE extension, and ChatGPT desktop app share it on the same Codex host.
Restart the current CLI/app/extension session if a newly added server is not in that session's
already-discovered tool catalog. Depending on local policy, the client can prompt before MCP tool
calls.

This configuration and RepoMind's initialization, tool discovery, status call, and functional
retrieval were exercised through Codex during Days 6 and 7. The commands above were rechecked
against Codex CLI 0.141.0 on Day 8. See the
[official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp.md) for current client
configuration behavior. A client error saying its configured model needs a newer client is a
Codex upgrade issue, not a reason to lower the model as part of normal RepoMind setup.

## GitHub Copilot CLI — configuration guidance; functional validation pending

Current GitHub documentation defines the stdio form below:

```powershell
$repomindPython = (Resolve-Path "C:\path\to\repomind-venv\Scripts\python.exe").Path
copilot mcp add repomind -- $repomindPython -m repomind mcp
copilot mcp list --json
copilot mcp get repomind --json
```

`copilot mcp add` writes user configuration under `~/.copilot/mcp-config.json`. Copilot CLI also
loads project configuration from repository-root `.mcp.json` or `.github/mcp.json` after folder
trust is granted. A project-local example is:

```json
{
  "mcpServers": {
    "repomind": {
      "type": "local",
      "command": "C:\\path\\to\\repomind-venv\\Scripts\\python.exe",
      "args": ["-m", "repomind", "mcp"],
      "tools": ["*"]
    }
  }
}
```

Review project MCP files before trusting a repository. Copilot CLI can require approval for MCP
tool calls. Its configuration is distinct from VS Code's `.vscode/mcp.json`; Copilot CLI does not
read that VS Code-specific `servers` shape directly. See GitHub's
[Copilot CLI MCP instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers).

RepoMind's MCP protocol was validated with Codex and direct MCP clients, but Copilot CLI was not
installed in the Day 6 or Day 8 environment. These commands therefore document the current
supported Copilot interface; a RepoMind-through-Copilot functional transcript remains pending.

## VS Code Copilot Chat — configuration guidance; functional validation pending

For a workspace-specific VS Code configuration, create `.vscode/mcp.json`:

```json
{
  "servers": {
    "repomind": {
      "type": "stdio",
      "command": "${workspaceFolder}\\.venv\\Scripts\\python.exe",
      "args": ["-m", "repomind", "mcp"]
    }
  }
}
```

This example assumes RepoMind is installed in the workspace's `.venv`. Otherwise replace
`command` with the user's own absolute environment interpreter path. VS Code's file uses the
`servers` top-level key; portable/Copilot CLI project files use `mcpServers`. Workspace MCP servers
are blocked in Restricted Mode, and local MCP processes can execute code with the user's access,
so review the file before granting Workspace Trust or tool approval. Use **MCP: List Servers** to
start, inspect, or troubleshoot the server. See the
[official VS Code MCP guide](https://code.visualstudio.com/docs/agent-customization/mcp-servers).

The configuration shape is current official guidance. A RepoMind-through-VS Code Copilot Chat
functional run was not performed during Days 6–8.

## Claude Code — documented only

Claude Code was available locally and its installed help matched the current official stdio form,
but RepoMind was not registered or functionally queried through Claude during Day 8:

```powershell
$repomindPython = (Resolve-Path "C:\path\to\repomind-venv\Scripts\python.exe").Path
claude mcp add --transport stdio --scope local repomind -- $repomindPython -m repomind mcp
claude mcp list
claude mcp get repomind
```

Use `--scope project` only when a shared project configuration is intended and reviewed. Project
servers require workspace trust/approval. See Anthropic's
[Claude Code MCP documentation](https://code.claude.com/docs/en/mcp). This section is setup
guidance, not a claim of completed RepoMind+Claude compatibility testing.

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
4. Query `repomind_symbol`, `repomind_dependencies`, `repomind_callers`, or `repomind_impact` only when deeper structural detail is needed.
5. Use `repomind_test_impact` before choosing tests for changed or explicitly selected files; review its evidence and commands rather than executing recommendations blindly.
6. Query `repomind_memory` when the agent needs durable repository facts without a full context pack.
7. Use `repomind_snippets` for bounded snippets when helpful.
8. After significant edits, call `repomind_context` or another read tool normally; read tools refresh stale saved changes before reading the index. Use `repomind_refresh` when you want an explicit refresh result.

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
- RepoMind evidence is not a security certification, and test-impact recommendations are evidence-based suggestions rather than guaranteed exhaustive coverage.
- Treat truncation and lower-bound metadata as part of the result; a bounded result must not be presented as a complete repository census.
- Confidence labels are retrieval/static-analysis signals, not calibrated probabilities.
