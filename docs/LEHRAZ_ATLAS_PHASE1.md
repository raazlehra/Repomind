# Lehraz Atlas Free — Phase 1 compatibility candidate

Lehraz Atlas Free is the existing Apache-2.0 RepoMind product under the Lehraz brand.
This branch prepares **2.0.0b14, unpublished**. It adds display branding and an
equivalent `lehraz-atlas` command. It does not add language support or Pro features,
rename the GitHub repository, change the separate `repomind-site`, or publish a package.

## Existing users

No reinstall, config edit, client re-registration or index rebuild is required for
branding. The following remain supported with no scheduled deprecation:

| Contract | Retained identity |
| --- | --- |
| Distribution and import namespace | `repomind` |
| Existing executable / module invocation | `repomind`, `python -m repomind` |
| Candidate alias | `lehraz-atlas`, pointing to the same `repomind.cli:main` |
| MCP server name and all 12 tool IDs | `repomind`, existing `repomind_*` IDs |
| Index / config / ignore | `.repomind/index.sqlite3`, `.repomind.toml`, `[repomind]`, `.repomindignore` |
| JSON contracts | `repomind.test-impact.v1`, `repomind_version`, `repomind_error`, existing fields |
| Codex integration | `.codex/skills/repomind/SKILL.md`, existing `REPOMIND-*` markers |

Help continues to use the legacy `repomind` program name under either executable.
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
initializes MCP over stdio, discovers and calls all 12 legacy tool IDs, and verifies
the old test-impact schema. Recommendations remain data; upstream tests are not run.

For other baseline/candidate versions, the lower-level lifecycle script requires
explicit `--baseline-version`, `--candidate-version` and authenticated
`--baseline-sha256` alongside the two wheel paths. The artifact verifier requires
both commands by default; `--require-cli repomind` permits inspection of a historical
wheel without claiming that it shipped the new alias.

## Release and rollback plan

Implementation review, release approval and repository-rename approval are separate.
All applicable local gates, exact-commit Linux/Windows CI, Python 3.11–3.13 coverage,
pinned real-PR regressions and artifact hashes must be recorded before release.
The candidate version does not reserve or broaden the proposed b14 language roadmap.
Its final release scope/version must be reviewed before any publication.

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
