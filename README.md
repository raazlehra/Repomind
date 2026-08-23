# RepoMind

RepoMind is a local-first persistent code context engine for AI coding agents. It indexes repository structure once, updates changed files incrementally, and retrieves a compact, task-specific package instead of dumping a repository into an agent prompt.

```text
Repository -> RepoMind persistent index -> task context -> coding agent
```

The guiding idea is **index once, update incrementally, retrieve only what is relevant**.

RepoMind is not a coding agent and does not replace Codex or source inspection. Its summaries guide file discovery; actual source is always authoritative. RepoMind does **not** promise or guarantee reductions in OpenAI/Codex account credits or usage limits. Its measurable goals are fewer unnecessary context tokens, scans, file reads, repeated architecture discovery steps, and irrelevant files supplied to agents.

## Features

- Recursive scanner honoring `.gitignore` and `.repomindignore`
- Default exclusion of generated trees, binaries, oversized files, environment files, keys, and obvious credentials
- Versioned SQLite index in `.repomind/index.sqlite3`
- Hash-based create/modify/delete/rename detection; unchanged files are not reparsed
- Python AST extraction and deterministic JS/TS/JSX/TSX structural extraction
- Conservative fallback extraction for Java, Go, Rust, C#, C, and C++
- Imports, calls, inheritance, routes, test-targets, and confidence-scored dependency edges
- Deterministic architecture detection from manifests and configuration
- Task ranking using paths, symbols, lexical overlap, graph proximity, tests, purpose, and Git changes
- Explicit approximate-token budgets and progressive context levels
- Git-aware status without changing Git state
- Event-driven optional watch mode with debouncing
- Codex skill and idempotent `AGENTS.md` integration
- No network, telemetry, cloud upload, external AI, or repository code execution

## Requirements and installation

Python 3.11 or newer is required.

From a checkout:

```bash
python -m pip install .
# Development installation:
python -m pip install -e '.[dev]'
```

The base package includes the local MCP server dependency. For efficient event-driven watch mode
and optional Tree-sitter-backed JS/TS declarations:

```bash
python -m pip install 'repomind[watch]'
python -m pip install 'repomind[treesitter]'
```

Without `watchdog`, `repomind watch` uses a low-frequency polling fallback. Without compatible Tree-sitter grammars, built-in deterministic parsers remain active.

## Quick start

```bash
cd existing-repository
repomind init
repomind status
repomind map --depth 3 --symbols
repomind context "fix authentication refresh token bug"
```

Example focused workflow:

```bash
repomind context "add password reset functionality" --mode minimal --format markdown
repomind symbol AuthService.login --format json
repomind callers AuthService.login
repomind dependencies backend/auth.py
repomind impact AuthService.login
repomind snippets AuthService.login
```

RepoMind does not print whole files for normal context retrieval. `snippets` and context level 3 read bounded snippets explicitly.

## CLI

| Command | Purpose |
|---|---|
| `repomind init [path]` | Create and populate an index |
| `repomind refresh` | Hash and reparse only created/modified files; remove deleted files |
| `repomind watch` | Debounce filesystem changes and refresh automatically |
| `repomind status` | Show indexed, changed, deleted, new, rename, and health counts |
| `repomind map` | Compact file map, optionally with symbols or JSON |
| `repomind context "task"` | Retrieve budgeted task context |
| `repomind symbol SYMBOL` | Show symbol signatures and locations |
| `repomind callers SYMBOL` | Show resolvable incoming symbol edges |
| `repomind dependencies TARGET` | Show outgoing dependencies |
| `repomind impact TARGET` | Classify direct, indirect, test, route, and UI impact |
| `repomind snippets SYMBOL` | Read bounded working-tree source around symbols |
| `repomind doctor` | Check DB, schema, access, config, parsers, watcher, and Git |
| `repomind install-codex` | Install/update RepoMind's Codex integration safely |

Most read commands accept `--format text`, `--format markdown`, or `--format json`. Use `-C PATH`/`--repository PATH` from outside a repository.

### Context budgets

```bash
repomind context "fix login bug" --budget 1000
repomind context "fix login bug" --mode minimal   # about 750
repomind context "fix login bug" --mode balanced  # about 2000
repomind context "fix login bug" --mode deep      # about 5000
```

Token counts are local approximations, not billing-token counts. RepoMind ranks complete records and removes lower-value records first; it does not blindly slice the final text.

Progressive disclosure:

- **Level 1**: architecture, files, symbols, relationships, likely modification area
- **Level 2**: signatures, imports, and nearby dependency details
- **Level 3**: selected bounded source snippets

Use `--level 1`, `--level 2`, or `--level 3`.

## Configuration

Most repositories need no configuration. Optional `.repomind.toml`:

```toml
[repomind]
exclude = ["examples/legacy/**"]
include = ["docs/architecture.custom"]
context_budget = 2000
watch = false
languages = ["python", "typescript", "tsx"]
max_file_size = 1000000
generated_directories = [".git", ".repomind", "node_modules", "dist", "build", "target"]
secret_patterns = [".env", ".env.*", "*.pem", "*.key", "credentials*", "secrets*"]
```

`generated_directories` and `secret_patterns` replace their default lists when configured; retain entries you still want excluded. `.git` and `.repomind` remain hard exclusions. Included files do not bypass secret, size, binary, or hard safety exclusions.

## Supported languages

First-class:

- Python: AST-backed classes, functions, methods, decorators, signatures, constants, imports, calls, inheritance, and common decorator routes
- JavaScript, TypeScript, JSX, TSX: imports, exported declarations, functions, classes, interfaces, types, enums, arrow functions/components, inheritance/implementation, lexical calls, and common router calls. With the `treesitter` extra, Tree-sitter supplies declaration spans while deterministic extraction retains relationship evidence.

Conservative fallback:

- Java, Go, Rust, C#, C, C++
- Additional basic file recognition for Ruby, PHP, Swift, Kotlin, Scala, shell, and SQL

The parser registry is deliberately replaceable so Tree-sitter adapters can be added without changing the indexer. V1 does not store whole ASTs.

## Codex integration

This repository includes `.codex/skills/repomind/SKILL.md`. Install integration into another project with:

```bash
cd project
repomind install-codex
```

This creates the project-local skill and creates or appends a delimited RepoMind section to `AGENTS.md`. Existing content is preserved. Repeated runs are idempotent.

The skill instructs Codex to query RepoMind before broad scanning, use the result for file discovery, inspect actual source before edits, request deeper detail only when needed, and refresh after significant changes if watch mode is inactive.

## MCP integration

RepoMind can run as a local MCP server for coding agents:

```bash
pip install -e .
repomind mcp
```

The MCP server uses standard stdio transport and exposes status, context, symbol, callers, dependencies, impact, snippets, refresh, and map tools. Start with `repomind_status`, then request `repomind_context` at level 1 for the task. RepoMind is a discovery accelerator; agents should still inspect actual source files before edits. See [docs/MCP.md](docs/MCP.md).

## Privacy and security model

Default operation is entirely local:

- no network requests
- no cloud uploads
- no telemetry
- no external AI APIs
- no source code leaving the machine

Indexing is static. RepoMind does not import, evaluate, build, or execute repository source. See [SECURITY.md](SECURITY.md).

## Benchmarks

Run deterministic fixture benchmarks:

```bash
python -m benchmarks.run_benchmark --format markdown
python -m benchmarks.run_benchmark --format json --output benchmark.json
```

The harness measures files selected, represented source bytes, emitted output bytes, approximate tokens, retrieval latency, index size, initial index duration, one-file incremental duration, and expected-file recall. See [BENCHMARKS.md](BENCHMARKS.md). Results are measurements on tiny synthetic fixtures, not universal savings claims.

## Limitations

- Static call resolution is conservative; dynamic dispatch, reflection, runtime-generated imports, aliases, framework magic, and dependency injection can remain unresolved.
- JS/TS extraction is deterministic lexical analysis rather than a complete compiler frontend; complex multiline syntax can be missed.
- Fallback-language extraction is intentionally shallow.
- Import resolution covers common relative, package, and source-root layouts but not every monorepo alias configuration.
- Rename detection requires an unambiguous delete/create content-hash match.
- Watch mode requires the optional `watchdog` extra; RepoMind does not fall back to continuous whole-tree polling.
- Architecture detection reports only manifest/config evidence and can be incomplete.
- Approximate token counts are not provider tokenizer or billing values.
- SQLite indexes are local caches and should not normally be committed.

## Development

See [ARCHITECTURE.md](ARCHITECTURE.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

```bash
python -m pytest
ruff check .
mypy repomind
python -m build
```
