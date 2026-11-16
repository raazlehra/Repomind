# Lehraz Atlas Free — Phase 1 compatibility candidate

Lehraz Atlas Free is the existing Apache-2.0 RepoMind product under the Lehraz brand.
This branch is an **unpublished compatibility implementation**. Its inherited
`2.0.0b14` metadata remains unchanged during interface review; it is not an approved
branding-only release. b14 retains the agreed Go language intelligence scope.
This change adds display branding and a `lehraz-atlas` interface. It does not add language support or Pro features,
rename the GitHub repository, change the separate `repomind-site`, or publish a package.

## Existing users

No reinstall, config edit, client re-registration or index rebuild is required for
branding. The following remain supported with no scheduled deprecation:

| Contract | Retained identity |
| --- | --- |
| Distribution and import namespace | `repomind` |
| Existing executable / module invocation | `repomind`, `python -m repomind` |
| Candidate interface | `lehraz-atlas` via `repomind.cli:atlas_main`; legacy entry stays `repomind.cli:main` |
| Legacy MCP launches | `repomind mcp`, `python -m repomind mcp`: server `repomind`, exactly 12 `repomind_*` IDs |
| Opt-in Atlas MCP launch | `lehraz-atlas mcp`: server `lehraz-atlas`, exactly 12 `atlas_*` IDs |
| Index / config / ignore | `.repomind/index.sqlite3`, `.repomind.toml`, `[repomind]`, `.repomindignore` |
| JSON contracts | `repomind.test-impact.v1`, `repomind_version`, `repomind_error`, existing fields |
| Codex integration | `.codex/skills/repomind/SKILL.md`, existing `REPOMIND-*` markers |

Help uses the selected executable name; `lehraz-atlas --help` describes Lehraz Atlas Free.
Both MCP modes share the same handlers and analysis services, input/output schemas,
strict argument validation, structured errors and local storage. Neither default
server exposes the other namespace. Switching a client to Atlas requires an
explicit user-selected command and updates to any tool allowlist or prompt names.
Existing registrations continue to use legacy names; no automatic migration occurs.
Version, human-facing report titles and MCP display title use Lehraz Atlas Free.
No client configuration is automatically edited. Existing marked AGENTS sections
remain unchanged; skill updates preserve user content outside the managed markers.
All Free functionality and Apache-2.0 contributor attribution remain available.

The published b13 wheel still reports RepoMind and has no alias. Its SHA-256 remains
`6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9`.
Install only exact checksum-verified wheels from the existing
[GitHub Releases](https://github.com/raazlehra/Repomind/releases).
Do not use plain `pip install repomind`: that PyPI name belongs to another project.
No new PyPI installation method is offered. Optional dependencies must be requested
from the verified local wheel, following [installation instructions](INSTALLATION.md#optional-dependencies).

## Candidate qualification

Use a fresh disposable checkout. Some existing tests rebuild indexes under their
source-relative fixture paths. Never use an original development worktree or a
historical compatibility lab as the test working directory. Preserve all old
artifacts and user indexes before testing an upgrade.

```text
python -m pytest -ra
python -m ruff check .
python -m mypy repomind
python -m build
python scripts/verify_release_artifacts.py --dist-dir dist --expected-version 2.0.0b14
python scripts/installed_wheel_smoke.py --wheel dist
python scripts/installed_wheel_smoke.py --wheel dist --treesitter
python scripts/installed_wheel_smoke.py --wheel dist --watch
python scripts/source_install_smoke.py --sdist dist/repomind-2.0.0b14.tar.gz
python scripts/compatibility_lifecycle_smoke.py --candidate-wheel dist/repomind-2.0.0b14-py3-none-any.whl --candidate-version 2.0.0b14
```

The lifecycle gate authenticates b13 before installing it into a new environment
with spaces in its path. It preserves the same database, creation metadata, manual
memory, config, ignore rules and Git state across upgrade, explicit rollback to b13,
uninstall and candidate reinstall. No `init --force` is used on that upgrade index.
A separate synthetic fixture retains the existing force-rebuild behavior check.
The installed-wheel gate rejects source import leakage, exercises both executables,
initializes all three MCP launch modes over stdio, and discovers and calls all 12
tools per mode. It checks exact server/tool identities, matching input schemas,
strict rejection of booleans, strings and execution arguments, bounded-error
behavior and the old test-impact schema. Unit tests freeze input and output schemas
captured from the qualified `55468b5` installed wheel. Recommendations remain data;
upstream tests are not run.

For other baseline/candidate versions, the lower-level lifecycle script requires
explicit `--baseline-version`, `--candidate-version` and authenticated
`--baseline-sha256` alongside the two wheel paths. The artifact verifier requires
both commands by default; `--require-cli repomind` permits inspection of a historical
wheel without claiming that it shipped the new alias.

## Release and rollback plan

Implementation review, release approval and repository-rename approval are separate.
All applicable local gates, exact-commit Linux/Windows CI, Python 3.11–3.13 coverage,
pinned real-PR regressions and artifact hashes must be recorded before release.
The release recommendation is to integrate this compatibility work into the
planned b14 alongside Go language intelligence. Do not publish this branding-only
branch as b14 or move the agreed b14–b17 language roadmap to make room for it.
The current `2.0.0b14` strings identify disposable development artifacts only.
Publication is NO_GO until the owner explicitly approves version/scope and the
combined b14 language and compatibility gates pass.

If a separate preview is necessary before Go is ready, request explicit approval
for a distinct, monotonically increasing development version such as
`2.0.0b14.dev1`, distributed through an explicitly identified GitHub preview rather
than a new public package index identity. It orders after b13 and before b14 under
the [Python version specification](https://packaging.python.org/en/latest/specifications/version-specifiers/#developmental-releases).
This is a proposal only: no version, tag, published artifact or roadmap is changed
here. Once approved, update version strings and CI artifact paths together, rebuild
fresh artifacts, rerun all release gates and issue new checksums. Never relabel the
current unpublished wheel or reuse b13 assets. Development releases of prereleases
are discouraged for general public indexes; the preferred path remains the agreed
b14 with Go scope.

Never replace b13 tags, release notes, assets or checksums. Never change package
identity in this phase. A future repository rename must preserve the existing
repository and history, verify integrations and old URLs, and keep the old slug
unused. That operation remains NO_GO in Phase 1.

To roll back code, revert the dedicated compatibility change through review. To
roll back an installed candidate, stop writers, preserve repository-local data,
and install the authentic b13 wheel into the dedicated environment. Verify old
CLI/MCP access and manual memory without rebuilding the index. A GitHub rename,
if separately authorized later, needs its own administrative rollback and URL checks.

Historical release docs, benchmark measurements, LICENSE attribution and sample
output keep RepoMind provenance. The legacy `docs/index.html` and existing demo
assets are unchanged; the separate site will need its own reviewed rebranding task.
Lehraz Atlas Pro is future work and is not part of the Apache-2.0 Free release.
