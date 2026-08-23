# RepoMind architecture

RepoMind separates repository discovery, structural extraction, persistent graph storage, deterministic ranking, and presentation. Repository content is always treated as untrusted static input.

## System flow

```text
                       .gitignore / .repomindignore / .repomind.toml
                                           |
                                           v
Working tree -> scanner -> hash/change detector -> parser registry
                                                |       |
                                                |       +-> symbols/imports/routes/references
                                                v
                                      versioned SQLite index
                                                |
                    +---------------------------+------------------------+
                    |                           |                        |
                    v                           v                        v
            dependency resolver       architecture detector       Git inspector
                    |                           |                        |
                    +---------------------------+------------------------+
                                                |
                                                v
                    task ranking -> budgeted context builder -> text/Markdown/JSON
```

No component executes repository source or needs network access.

## Scanner

`repomind.scanner.RepositoryScanner` walks with `os.walk(topdown=True)` so ignored/generated directories are pruned before traversal. It:

1. applies hard `.git` and `.repomind` exclusions;
2. applies generated-directory rules;
3. interprets root and nested `.gitignore`/`.repomindignore` patterns, including negation;
4. excludes configurable secret patterns;
5. classifies source, tests, configuration, docs, migrations, and API areas;
6. rejects symlinks, oversized content, and binary-like input.

`ScannedFile` stores only metadata; hashing streams one MiB chunks. File contents are read one file at a time during parsing.

## Parser abstraction

`StructuralParser` is a protocol:

```text
parse(path, relative_path, source) -> ParseResult
```

`ParserRegistry` maps languages to implementations. `ParseResult` is deliberately compact: symbols, imports, relationship candidates, routes, summary, and parse error. Whole ASTs and whole sources are not stored.

- Python uses the standard AST for high-confidence declarations, signatures, imports, decorators/routes, inheritance, and lexical calls.
- JS/TS/JSX/TSX uses a deterministic lexical extractor for imports, exported declarations, interfaces/types, classes, arrow functions/components, routes, and conservative calls. When the `treesitter` extra is installed, an optional adapter uses Tree-sitter for declaration names and spans while retaining deterministic relationship evidence.
- Java/Go/Rust/C#/C/C++ use a shallow fallback extractor.
- Configuration and documentation retain only file metadata and a summary.

The interface permits a future Tree-sitter adapter to replace a language parser without changing indexing or retrieval.

## Persistent index

`.repomind/index.sqlite3` uses foreign keys, WAL journaling, and an explicit schema version. Main records:

```text
directories 1 --- * files 1 --- * symbols
                          | --- * imports
                          | --- * references (unresolved parser evidence)
                          | --- * routes
                          |
                          + --- * dependencies --- files/symbols

architecture(category, name, evidence, confidence)
git_state(key, JSON value)
meta(schema version, root, timestamps)
```

Dependencies retain edge type, numeric confidence, and evidence source. Uncertain references remain unresolved rather than being turned into invented edges.

## Initial and incremental indexing

Initial indexing streams each eligible file through hashing and one parser, then resolves the compact graph.

Refresh comparison:

```text
scanner metadata
   |
   +-- same size + mtime ----------------------> unchanged
   +-- metadata differs + same content hash ---> metadata-only update
   +-- content hash differs -------------------> reparse this file
   +-- absent from index ----------------------> create
   +-- absent from tree -----------------------> delete
   +-- unique equal hash delete/create pair ---> rename
```

Only created or content-modified files are reparsed. Deletes cascade through file-owned records. Rename rows preserve identity when the hash match is unambiguous. Dependency resolution is rebuilt from stored compact imports/references; unchanged source files are not reread or reparsed.

## Dependency graph

The resolver has two phases:

1. Resolve internal imports against indexed paths using language-aware candidates and common source-root suffixes.
2. Resolve symbol relationship candidates only when a target is unique in the same file, a resolved imported file, or the complete symbol set.

Edge examples:

```text
routes.py --imports (1.0, import syntax)--> auth.py
test_auth.py --test-target (0.95, test import)--> auth.py
login_route --calls (0.6, static call expression)--> AuthService.login
AuthService --inherits (0.9, class base)--> BaseService
POST /login --route-handler (0.95, decorator)--> login_route
```

Call confidence does not imply runtime certainty. Dynamic calls may be omitted.

## Architecture detection

Manifest/config readers use `json`, `tomllib`, or bounded text markers. Evidence is stored with every fact. Inputs include package/requirements files, language module files, Docker, Compose, Vite, Next, TypeScript, Maven, and Gradle. Unsupported or malformed manifests produce no guesses.

## Deterministic ranking

Task retrieval uses no LLM or embedding by default. Ranking signals include:

- token overlap with paths and filenames;
- token overlap with symbol names/signatures;
- exact filename/symbol boosts;
- file-purpose hints (test/config/migration);
- working-tree Git changes;
- one-hop confidence-weighted graph expansion.

If no term matches, configuration/source entry points provide a small navigation result instead of a repository dump.

## Context builder and budgets

```text
ranked files
   +-> architecture evidence
   +-> symbols
   +-> relationships
   +-> likely modification area
   +-> L2 imports/signatures/neighbors
   +-> L3 bounded working-tree snippets
             |
             v
       format-specific rendering
             |
             v
  approximate local token counter
             |
      over budget? remove the lowest-ranked complete record and rerender
```

This preserves record boundaries and avoids blind string truncation. Level 3 snippets are read from the current working tree, not the database.

## Watcher

With the `watch` extra, watchdog emits file events. RepoMind ignores its own index and Git internals, debounces an event burst, and runs incremental refresh. Without watchdog, `watch` returns an actionable installation error rather than continuously rescanning the whole repository; `doctor` reports watcher availability.

## Git integration

Git calls use argument arrays (`shell=False`), a timeout, and read-only commands: `rev-parse`, `branch --show-current`, and `status --porcelain`. RepoMind never commits, pushes, checks out, resets, stashes, or changes branches.

## Agent integration

`install-codex` writes a project-local `.codex/skills/repomind/SKILL.md` with managed markers. It appends a delimited section to `AGENTS.md` without replacing existing content. Both operations are idempotent; an unmanaged existing skill is preserved.

The integration directs agents to use RepoMind for discovery, not as source authority.

## Extension seams

V1 keeps these interfaces small for future additions without implementing them now:

- parser registry: Tree-sitter and additional languages;
- retriever: optional local embeddings/semantic candidates;
- formatter/query layer: MCP or editor integrations;
- index/graph service: cross-repository or shared indexes;
- watcher/event boundary: CI hooks.

A web dashboard is intentionally outside V1.
