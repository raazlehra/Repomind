# Contributing to RepoMind

## Principles

Changes should preserve these constraints:

1. Index once and reparse only changed source.
2. Prefer compact retrieval to repository dumping.
3. Prefer deterministic structure before optional semantics.
4. Keep default operation local and network-free.
5. Treat source as authoritative and summaries as navigation aids.
6. Do not invent relationships; retain evidence and confidence.
7. Enforce context budgets by dropping complete low-value records.
8. Measure claims.

## Setup

```bash
git clone <repository>
cd repomind
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Checks

Run all gates before submitting:

```bash
python -m pytest
ruff check .
mypy repomind
python -m build
python -m repomind --version
```

Do not disable type checking or add suppression comments merely to hide errors. A narrow suppression is acceptable only when an optional untyped dependency requires it and the reason is evident.

## Test fixtures

Fixtures live under `tests/fixtures` and must be synthetic. Never copy proprietary source, live credentials, `.env` values, or private keys. Add tests for:

- scanner/ignore/security behavior;
- parser structure and malformed input;
- create/modify/delete/rename refreshes;
- conservative graph resolution;
- ranking and budget boundaries;
- output formats and CLI error behavior;
- agent integration idempotency.

## Parser contributions

Implement the `StructuralParser` protocol and return compact `ParseResult` records. Do not store whole ASTs or execute source. Every relationship candidate needs a kind, confidence, line when known, and human-auditable evidence.

Parser tests should include valid structure, malformed source, imports, symbols, and at least one relationship. Avoid asserting relationships that cannot be determined statically.

## Schema changes

Increment `SCHEMA_VERSION`, provide an explicit migration or actionable rebuild path, update `ARCHITECTURE.md`, and test old/new behavior. The index is a cache, but silent schema drift is not acceptable.

## Benchmarks

Run:

```bash
python -m benchmarks.run_benchmark --format json --output benchmark.json
```

Report raw environment and measured values. Do not generalize tiny fixture results into token, billing, credit, or productivity guarantees.
