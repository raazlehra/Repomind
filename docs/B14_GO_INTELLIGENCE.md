# b14 Stage A: local Go intelligence

This unpublished implementation builds on the merged Lehraz Atlas compatibility
work. It does not publish b14, begin Stage B configuration intelligence, introduce
Pro features, change package/storage identities or edit client registrations.

## Supported evidence

Go analysis extracts bounded package clauses, single/grouped imports (including
aliases and blank imports) and useful declarations. It resolves indexed local
module/package relationships using `go.mod`, `go.work` membership and qualified
local replacements. It respects nested-module boundaries and rejects duplicate
module identities. A package import links every qualified production file in the
target package; the single-file `imports.resolved_file_id` column stays unset for
Go packages. Package/module evidence is also retained in compact reference records.

Same-package `_test.go` files receive package-membership evidence. External `_test`
packages require an explicit import of the production package. Imported local
packages can connect dependent package tests through the existing bounded graph.
Transitive Go package tests are followed within the existing node, edge, per-file
and time budgets; Python/TypeScript traversal behavior is unchanged. Truncated
plans require broader review and never establish complete runtime coverage.
This selects packages, not individual Go test functions or measured coverage.
All `coverage` values remain `unknown`.

The [Go module reference](https://go.dev/ref/mod) defines module/package paths and
workspace/replacement ownership. The
[Go command reference](https://pkg.go.dev/cmd/go#hdr-Test_packages) defines package
test targets. This implementation uses a bounded static subset and does not invoke
the Go toolchain to validate or build the repository.

## Recommendations only

Both commands below inspect changes and return plans:

```text
lehraz-atlas test-impact pkg/service.go -C /path/to/repository --format json
repomind test-impact pkg/service.go -C /path/to/repository --format json
```

A qualified package can produce `argv: ["go", "test", "./pkg"]` with its owning
module's repository-relative working directory. Root packages use `"."`. No
workspace-root blanket `go test ./...`, manifest-supplied flags, individual test
file invocation or test-name filter is invented. No Go command, module download,
test binary or repository script is executed by analysis.

A local replacement can supply graph evidence while its directory is excluded
from the active workspace. Direct recommendations for that excluded directory are
withheld; eligible consuming workspace packages may still be recommended. Users
must separately review any plan and their Go environment before running it.

Atlas MCP and both legacy MCP launches keep their existing 12-tool interfaces,
strict arguments, wire schemas and errors. `runner_supported` refers to qualified
command planning, not execution. Aggregate capability flags remain conservative
for mixed supported/unsupported changes; per-file warnings and evidence explain
the supported subset. Go index limits are visible under `truncation.go_index`.

## Unsupported and partial cases

- Missing, malformed, excluded or ambiguous manifests; unresolved workspace members;
  escaping, ignored, symlinked or mismatched local replacements; conflicting package
  declarations and malformed/legacy header evidence do not yield qualified plans.
- Standard-library and external imports remain recorded but unresolved locally.
  No dependency solver, module cache, network lookup or global suffix guessing runs.
- Build tags, OS/architecture filenames, generated files, cgo and dot imports are
  unqualified. Other unconditional files in a proven package can still supply
  partial evidence. The report identifies limitations and keeps runtime coverage
  unknown; it does not promise which build-constrained tests a user's environment runs.
- Go bodies are checked for bounded lexical/delimiter structure, not type correctness
  or full language validity. Dynamic calls, reflection, embedding, test function
  signatures and build behavior are not proved. Test-only packages without production
  ownership and nonstandard package paths remain unsupported.
- Escaped import/manifest paths, nonqualified manifest directives (including
  exclude/retract/tool/ignore/godebug semantics), conflicting/version-ambiguous
  replacements and custom toolchains are not guessed. Qualified version-specific
  local replacements must match the indexed requirement exactly.
- Only indexed repository-local manifests are used. Parent-directory/ambient
  `GOWORK`, Go environment flags and remote requirements are not evaluated. If a
  language/ignore filter excludes the manifests, support is withheld.

## Bounds, freshness and compatibility

Each Go source/manifest is limited to 256,000 UTF-8 bytes; source token count is
40,000, delimiter depth 128, imports 256 and declarations/directives 1,024. Local
topology is capped at 5,000 files, 20,000 compact references/imports per query,
256 modules, 64 workspaces, 256 files per package, 20,000 edges and 2,000,000 bytes
of cached metadata. Exceeding a topology limit withholds qualified command plans
and visibly truncates Go analysis. Existing request-level graph/time/evidence/output
limits remain unchanged and also apply.

The resolver reads compact indexed records, not arbitrary manifest targets on disk.
The scanner rejects symlinks and Windows junctions before indexing. Existing
secret/generated exclusions remain in force. No source bodies or config values
are added to relationship evidence.

The index remains schema 2 in `.repomind/index.sqlite3`. On an existing b13 index,
normal freshness reparses only Go source/manifests with old extraction summaries
and rebuilds their graph; no forced initialization is needed. Changes to imports,
manifests, membership and file names invalidate the derived graph. A graph rebuilt
by b13 during rollback is detected and repaired on the next candidate read.
Existing file IDs, creation metadata, manual memory and non-Go parsing are retained.

Go workspace fixtures and additive pinned Chi expectations are included in the
source distribution. Historical b13 receipts remain unchanged; new Go-positive
expectations are separate from the b13 unsupported controls. HTTPX/Hono and the
existing JSON/JSONL negatives remain regression gates. Publication approval is
separate from accepting this Stage A implementation.
