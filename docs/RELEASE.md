# Release Process

The current public prerelease is
[`v2.0.0b11`](https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b11), published on
2026-10-10 as a public hardening beta. It is not stable v2.0.0. GitHub Release artifacts are the
authoritative public distribution:

- `repomind-2.0.0b11-py3-none-any.whl` — SHA-256
  `3202f593084a5f13cbe68c21bc7a2bc3c6207671a28e10303267bf0b0594ba9f`
- `repomind-2.0.0b11.tar.gz` — SHA-256
  `8814e9ab9ca134fc7b34ae8b1f91030490411a29c39c8af5c660bb8dacb24938`

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
python scripts/verify_release_artifacts.py --dist-dir dist --expected-version <candidate-version>
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

For b11, pre-release validation exercised the b10-to-b11 lifecycle against the local b11
candidate built from the release code. The final public b11 wheel was later rebuilt from the same
release commit and independently downloaded, checksum-verified, installed, and smoke-tested. The
full lifecycle sequence was not repeated against that final downloaded wheel; do not broaden the
historical evidence beyond those two validations.

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
