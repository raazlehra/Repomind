# RepoMind security and privacy

## Security model

RepoMind treats every repository as untrusted input. Indexing is static analysis only.

RepoMind does not:

- execute, import, evaluate, compile, or build repository source;
- use `eval`, `exec`, dynamic repository imports, or shell interpolation;
- make network requests, upload source, emit telemetry, or call an AI API;
- modify Git state;
- follow repository symlinks during scanning.

Git inspection uses fixed executable arguments with `shell=False` and a timeout.

## Default exclusions

The scanner excludes common generated/heavy trees and hard-excludes `.git` and `.repomind`. It skips binary-like files and files larger than the configured maximum.

Default secret patterns include:

```text
.env
.env.*
*.pem
*.key
credentials*
secrets*
*credential*.json
id_rsa*
id_ed25519*
```

These are defense-in-depth heuristics, not a complete secret detector. Do not rely on RepoMind as a secrets scanner. Repository operators should add project-specific patterns to `.repomindignore` or `secret_patterns`.

`include` rules never bypass secret, binary, size, symlink, `.git`, or `.repomind` protections.

## Local data

The SQLite index is stored in `.repomind/index.sqlite3` in the repository and may contain:

- relative paths and file metadata;
- symbol names, signatures, and short docstrings;
- imports, routes, relationship evidence, and architecture facts;
- repository memory facts with source paths, optional source symbols, evidence hashes, timestamps, category, confidence, source type, and status;
- Git branch/HEAD/change paths.

It does not intentionally store entire source files, whole ASTs, or large evidence payloads. Source snippets are read from the working tree on demand and are not persisted by the snippet command.

Repository Memory is local and evidence-backed. Automatic memory extraction only uses indexed non-secret files and refuses automatic facts without source evidence. Manual memory must be added explicitly and is marked `manual`.

Protect the index with the same local access controls as the repository. Normally add `.repomind/` to `.gitignore`; do not commit it if paths or structural metadata are sensitive.

## Configuration risks

`.repomind.toml` changes what is indexed. `generated_directories` and `secret_patterns` replace default tuples, so preserve security entries when overriding. Malformed configuration causes an actionable error rather than falling back silently.

Ignore handling implements common Git-style patterns and negation but is not a replacement for Git's own security model. Verify with `repomind map --json` when handling unusually complex ignore rules.

## Database safety

SQLite foreign keys and integrity checks are enabled. Schema versions are validated before reads. Normal commands do not execute SQL from repository input. Values are passed as bound parameters; dynamically generated placeholder counts derive only from in-memory integer IDs.

The index is a rebuildable cache. If corruption is detected:

```bash
repomind doctor
repomind init --force
```

`--force` removes RepoMind's SQLite database files only, not arbitrary repository files.

## Repository Memory privacy

Automatic memory must not capture secret values. Evidence paths are checked against secret-like names including `.env`, `.env.*`, `*.pem`, `*.key`, credential files, secret files, and private-key names. Included files do not bypass those protections.

Evidence hashes are computed from indexed file hashes so validation can detect changed evidence without rereading the whole repository. If evidence changes, automatic memory is marked `needs_validation`; if evidence disappears, it is marked `stale`. RepoMind marks uncertainty instead of keeping automatic facts silently valid.

## Reporting vulnerabilities

Do not include private repository contents, secrets, or a real index in a public report. Provide a minimal synthetic reproduction, RepoMind version, Python version, platform, and command used.
