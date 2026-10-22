# Release Process

The current public prerelease is
[`v2.0.0b11`](https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b11), published on
2026-10-10 as a public hardening beta. It is not stable v2.0.0. GitHub Release artifacts are the
authoritative public distribution:

- `repomind-2.0.0b11-py3-none-any.whl` — SHA-256
  `3202f593084a5f13cbe68c21bc7a2bc3c6207671a28e10303267bf0b0594ba9f`
- `repomind-2.0.0b11.tar.gz` — SHA-256
  `8814e9ab9ca134fc7b34ae8b1f91030490411a29c39c8af5c660bb8dacb24938`

The repository is preparing an unpublished `2.0.0b12` candidate from verified main commit
`d3a9659d16c8f9cd23e77c753ffab739cce19ff4`. The candidate contains the merged scope from
PRs #8, #9, and #10: Node.js built-in `.mjs` test recognition and broad existing npm test-script
recommendation, bounded multiline JavaScript static imports, `.jsonl` configuration indexing,
and optional Tree-sitter-backed source-anchored `.json`/`.jsonl` fixture references. It remains
static analysis: no recommended repository commands are executed, coverage is unknown, and
wrapper-based fixture data flow remains unsupported. This candidate is not a tag, published
release, or replacement for the b11 download links above.

The process below prepares a future candidate without publishing it. Replace placeholders with
the candidate version and a suitable baseline release; do not infer that a later release exists.

## Required CI checks

The `CI` workflow has read-only repository permission and does not receive publishing credentials.
It does not deploy, create a GitHub Release, or upload to PyPI. Its expected checks are:

- `CI / tests (3.11)`
- `CI / tests (3.12)`
- `CI / tests (3.13)`
- `CI / quality`
- `CI / windows-wheel-smoke`

RepoMind requires Python 3.11+. The b11 release matrix explicitly validates Python
3.11–3.13. Other Python versions are not claimed as release-tested unless listed in the release
notes. The quality job runs Ruff, mypy, wheel/sdist build and inspection, and an installed-wheel
CLI/MCP smoke test on Linux. The Windows job independently builds, inspects, and installs the
wheel into a disposable environment whose path contains spaces.

## Local candidate gates

Run from the repository root containing `pyproject.toml`:

```text
python -m pytest
python -m ruff check repomind tests tools benchmarks scripts
python -m mypy repomind
python -m build
python scripts/verify_release_artifacts.py --dist-dir dist --expected-version 2.0.0b12
python scripts/installed_wheel_smoke.py --wheel dist
git diff --check
```

The canonical local Ruff command names the tracked Python project areas. CI also runs
`python -m ruff check .` in a clean checkout, where unrelated local untracked directories do not
exist. Do not add broad lint exclusions to accommodate unrelated local files.

The artifact verifier requires the full Apache-2.0 license, package modules, candidate metadata,
console entrypoint, and MCP module. It rejects generated/private archive paths and tests in the
wheel. Tests are intentionally retained in the source distribution so downstream source-build
verification can run them.

## Upgrade lifecycle gate

Download the selected baseline wheel from its GitHub Release, verify its published SHA-256, then
run the lifecycle smoke with the locally built future candidate:

```text
python scripts/release_lifecycle_smoke.py \
  --baseline-wheel <baseline-wheel> \
  --candidate-wheel <candidate-wheel>
```

The lifecycle uses only disposable environments and repositories. It initializes with the
baseline, adds manual memory, exercises status/context/test-impact, upgrades to the candidate,
reopens the same index, runs doctor and the queries again, uninstalls/reinstalls, and verifies
retained repository data. A separate disposable repository verifies the documented fact that
`init --force` rebuilds the database and removes manual memory stored only there. Recommended
test commands returned by RepoMind are never executed by these smokes.

For the b12 candidate, use the authentic b11 GitHub Release wheel as the baseline and first
verify SHA-256
`3202f593084a5f13cbe68c21bc7a2bc3c6207671a28e10303267bf0b0594ba9f`.

For b11, pre-release validation exercised the b10-to-b11 lifecycle against the local b11
candidate built from the release code. The final public b11 wheel was later rebuilt from the same
release commit and independently downloaded, checksum-verified, installed, and smoke-tested. The
full lifecycle sequence was not repeated against that final downloaded wheel; do not broaden the
historical evidence beyond those two validations.

## b12 candidate validation record

On 2026-10-23, the unpublished b12 candidate was validated locally on Windows with Python
`3.12.14` from verified base commit `d3a9659d16c8f9cd23e77c753ffab739cce19ff4`:

- `python -m pytest`: 326 passed and 16 skipped in 91.73 seconds. Every skip was a
  Windows symlink-creation check blocked by `WinError 1314`; the required Linux CI test jobs
  remain responsible for executing those paths.
- Ruff over `repomind tests tools benchmarks scripts`, strict mypy over `repomind`, the
  wheel/sdist build, artifact inspection for `2.0.0b12`, and `git diff --check` passed.
- Base and `[treesitter]` installed-wheel smokes passed outside the source checkout. Both
  reported Python 3.12.14 and confirmed that recommended commands were not executed.
- The authentic b11 baseline wheel was downloaded from its GitHub Release and matched SHA-256
  `3202f593084a5f13cbe68c21bc7a2bc3c6207671a28e10303267bf0b0594ba9f` before the
  b11-to-b12 lifecycle smoke preserved schema 2, repository identity, creation metadata, manual
  memory, uninstall/reinstall behavior, and documented `init --force` semantics.
- The candidate artifacts were `repomind-2.0.0b12-py3-none-any.whl` with SHA-256
  `f5e0b1fc095f870f8d0bef5f6ca7344f68df6b82ab6279032a02607e2e5a9b2a` and
  `repomind-2.0.0b12.tar.gz` with SHA-256
  `f1a7575ee07ac9df232ceaa53cd3047c180f20b31978c56359acd4897ffe2be8`.
- The installed `[treesitter]` wheel validated pinned Plumbline PR #98 commit
  `c7adfffe55c41cdb6aeab8a1e09d233b89bc47ab`: 123 indexed files, 19 JSONL files,
  zero parse errors, the three expected redstamp fixture edges at lines 409/410/416 with
  confidences 1.0/1.0/0.9, three structurally related test-impact reports with unknown
  coverage, a negative control excluding the redstamp test, and unsupported wrapper flow
  remaining unsupported. No Plumbline npm script was executed.

These are candidate artifacts, not published release assets. Exact candidate-commit CI and owner
approval are still required before any tag, release, asset upload, or website update.

## Future publication gate

Before publishing any future candidate, require all of the following for the exact candidate
commit:

- all required GitHub CI checks green;
- source and package metadata agree on the candidate version;
- clean tracked working tree and reviewed release notes;
- local build, artifact inspection, Windows installed-wheel smoke, and suitable baseline lifecycle
  evidence;
- Linux installed-wheel evidence from the actual GitHub Actions run;
- recorded wheel and sdist SHA-256 hashes;
- no unresolved P0 blocker or release-critical security/documentation ambiguity.

Tag creation, GitHub Release creation, asset upload, and any publishing action require separate
owner authorization. A green local run alone is not permission to push or publish.

## Recommended `main` protection

After the workflow has run and GitHub has established the check names, require pull requests and
all five checks listed above, block force pushes and branch deletion, and require branches to be
up to date before merge. Decide and document whether administrators may bypass these rules;
security-sensitive release branches should normally avoid an unreviewed admin bypass.
