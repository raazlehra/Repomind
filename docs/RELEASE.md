# Release Candidate Process

This process prepares a RepoMind candidate without publishing it. The current candidate version
is `2.0.0b11`; the current authoritative public artifact remains the exact `v2.0.0b10` wheel on
GitHub Releases until a later release is explicitly approved and published.

## Required CI checks

The `CI` workflow has read-only repository permission and does not receive publishing credentials.
It does not deploy, create a GitHub Release, or upload to PyPI. Its expected checks are:

- `CI / tests (3.11)`
- `CI / tests (3.12)`
- `CI / tests (3.13)`
- `CI / quality`
- `CI / windows-wheel-smoke`

RepoMind requires Python 3.11+. The current b11 release matrix explicitly validates Python
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
python scripts/verify_release_artifacts.py --dist-dir dist --expected-version 2.0.0b11
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

Download the authoritative b10 wheel from its GitHub Release, verify its published SHA-256, then
run the lifecycle smoke with the locally built candidate:

```text
python scripts/release_lifecycle_smoke.py \
  --baseline-wheel <repomind-2.0.0b10-py3-none-any.whl> \
  --candidate-wheel <repomind-2.0.0b11-py3-none-any.whl>
```

The lifecycle uses only disposable environments and repositories. It initializes with b10, adds
manual memory, exercises status/context/test-impact, upgrades to the candidate, reopens the same
index, runs doctor and the queries again, uninstalls/reinstalls, and verifies retained repository
data. A separate disposable repository verifies the documented fact that `init --force` rebuilds
the database and removes manual memory stored only there. Recommended test commands returned by
RepoMind are never executed by these smokes.

## Publication gate

Before publishing b11, require all of the following for the exact candidate commit:

- all required GitHub CI checks green;
- source and package metadata agree on `2.0.0b11`;
- clean tracked working tree and reviewed release notes;
- local build, artifact inspection, Windows installed-wheel smoke, and b10 lifecycle evidence;
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
