# RepoMind Public Launch Readiness Checklist

This remains a conservative checklist: checked items have evidence for the stated scope, while
unchecked items still require external, manual, or broader validation. Publishing b11 does not
automatically complete the remaining launch work.

## 2026-10-23 b12 pre-publication preparation record

- [x] Verified base - canonical `main` was
  `d3a9659d16c8f9cd23e77c753ffab739cce19ff4`; PRs #8, #9, and #10 were merged.
- [x] Candidate metadata - source/runtime metadata declare `2.0.0b12`; this preparation record
  does not assert publication. Historical b11 publication records and download hashes remain
  unchanged.
- [x] Local release gates - 326 tests passed; 16 Windows symlink tests skipped for missing
  privilege and require Linux CI coverage. Ruff, mypy, build, artifact inspection, diff check,
  and base/Tree-sitter installed-wheel smokes passed on Python 3.12.14.
- [x] Upgrade lifecycle - the checksum-verified public b11 wheel upgraded to the local b12
  candidate with schema, repository metadata, manual memory, uninstall/reinstall, and forced
  rebuild behavior preserved as documented.
- [x] External static validation - the installed b12 Tree-sitter wheel passed the pinned
  Plumbline checks without executing npm scripts; this is maintainer-run evidence, not
  independent customer validation or runtime coverage.
- [x] Exact candidate CI - PASS for final candidate commit
  `ce8b16001ff9e8967bd1206ee442490c7cbde695`: [GitHub Actions run `39850116897`](https://github.com/raazlehra/Repomind/actions/runs/39850116897)
  passed `tests (3.11)`, `tests (3.12)`, `tests (3.13)`, `quality`, and
  `windows-wheel-smoke`.
- [x] Post-merge CI - PASS for main commit
  `696e3cb5d01411950474cad410494f9420800a11`: [GitHub Actions run `39851299675`](https://github.com/raazlehra/Repomind/actions/runs/39851299675)
  passed the same five required jobs.
- [ ] Publication checkpoint - at merged commit
  `696e3cb5d01411950474cad410494f9420800a11`, no b12 tag, GitHub Release, asset upload,
  website update, or outreach had occurred. Current publication state must be checked on GitHub;
  each publication action requires separate owner approval.
- [ ] Independent tester feedback - PENDING; maintainer-run Plumbline validation does not satisfy
  this launch requirement.

## 2026-10-10 b11 publication status

- [x] Version/tag/prerelease - `v2.0.0b11` is published as a GitHub prerelease, not stable v2.0.0.
- [x] Published artifacts - the wheel and sdist are attached to the
  [b11 release](https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b11) with recorded
  SHA-256 hashes.
- [x] Required release CI - tests on Python 3.11, 3.12, and 3.13, quality, and
  `windows-wheel-smoke` passed for release commit `b6dd660`.
- [x] Installation verification - the final public b11 wheel was independently downloaded,
  checksum-verified, installed, and smoke-tested.
- [x] Public website - the [RepoMind website](https://raazlehra.github.io/repomind-site/) now
  presents the public open-source beta and b11 installation path.
- [ ] Independent tester feedback - PENDING; no external independent tester feedback has been
  received yet.

## 1. Product

- [ ] Positioning clear - Likely complete from repo evidence: `README.md` opens with "Local-first repository intelligence for AI coding agents" and explains what RepoMind is and is not.
- [ ] README understandable in 30 seconds - Requires verification: run a timed read with at least one developer unfamiliar with RepoMind.
- [ ] Current beta limitations documented - Likely complete from repo evidence: `README.md` has `Limitations`; `pyproject.toml` marks beta status.
- [ ] Supported languages accurate - Requires verification: `README.md` documents language support, but confirm against parser implementations and tests before public launch.
- [ ] Roadmap accurate - Requires verification: `IMPLEMENTATION_PLAN.md` exists, but owner should confirm it reflects current priorities.

## 2. Installation

- [ ] Clean-machine install tested - Requires verification: Day 7 passed in new process-isolated Windows virtual environments, but a fresh VM or user profile is still unverified.
- [x] Windows release validation - b11 `windows-wheel-smoke` passed; pre-release lifecycle validation covered the b10-to-b11 candidate path on Windows/Python 3.12.14.
- [x] Linux installed-wheel verification - the b11 `quality` job installed and smoke-tested the wheel outside the source checkout.
- [ ] macOS tested - PENDING; no b11 macOS release run is recorded.
- [x] Python requirements documented - `README.md`, `docs/BETA_TESTING.md`, and `pyproject.toml` require Python 3.11+; b11 CI covers 3.11–3.13.
- [x] Uninstall instructions - `docs/INSTALLATION.md` documents package removal, preserved repository data, and separate MCP-client registration cleanup.
- [x] Upgrade instructions - `docs/INSTALLATION.md` documents the exact b10-to-b11 pre-release lifecycle evidence and its final-wheel limitation.
- [ ] v1/v2 index migration tested - Likely complete from repo evidence: `tests/test_memory.py` covers v1/beta.7-style migration to schema v2; `CHANGELOG.md` and `ARCHITECTURE.md` document the migration.

## 3. Functional

- [ ] `repomind init` - Likely complete from repo evidence: command is in current CLI help and covered by `tests/test_cli.py`.
- [ ] `repomind doctor` - Likely complete from repo evidence: command is in current CLI help and covered by `tests/test_git_doctor.py`.
- [ ] `repomind status` - Likely complete from repo evidence: command is in current CLI help and covered by `tests/test_cli.py`.
- [ ] `repomind stats` - Likely complete from repo evidence: command is in current CLI help and documented in `README.md`; MCP stats are covered by `tests/test_mcp.py`.
- [ ] `repomind context` - Likely complete from repo evidence: command is in current CLI help and covered by `tests/test_cli.py` and `tests/test_context_pack.py`.
- [ ] `repomind context --explain` - Likely complete from repo evidence: flag is in current CLI help and covered by MCP/context tests.
- [ ] `repomind memory` - Likely complete from repo evidence: `memory list` is in current CLI help and CRUD/validation behavior is covered by `tests/test_memory.py`.
- [ ] `repomind map` - Likely complete from repo evidence: command is in current CLI help and covered by `tests/test_cli.py` and `tests/test_mcp.py`.
- [ ] `repomind symbol` - Likely complete from repo evidence: command is in current CLI help and covered by `tests/test_mcp.py` and freshness tests.
- [ ] `repomind callers` - Likely complete from repo evidence: command is in current CLI help and covered by `tests/test_mcp.py`.
- [ ] `repomind dependencies` - Likely complete from repo evidence: command is in current CLI help and covered by `tests/test_mcp.py` and `tests/test_freshness.py`.
- [ ] `repomind impact` - Likely complete from repo evidence: command is in current CLI help and covered by `tests/test_cli.py` and `tests/test_mcp.py`.
- [ ] MCP - Likely complete from repo evidence: `docs/MCP.md` documents tools and `tests/test_mcp.py` covers startup, tools, and CLI equivalence.
- [ ] Automatic freshness - Likely complete from repo evidence: `README.md`, `docs/MCP.md`, and `tests/test_freshness.py` cover retrieval-time refresh for CLI and MCP reads.

## 4. Quality

- [x] Full pytest - b11 release-commit test jobs passed on Python 3.11, 3.12, and 3.13.
- [x] Ruff - the b11 release-commit `quality` job passed its Ruff gate.
- [x] mypy - the b11 release-commit `quality` job passed its mypy gate.
- [x] Build - the b11 release-commit `quality` job built and inspected the wheel and sdist.
- [ ] Evaluators - Requires verification: `tools/evaluate_retrieval.py`, `tools/evaluate_weighted.py`, and `tools/evaluate_real_repos.py` exist, but release results must be generated.
- [ ] Synthetic benchmark - Requires verification: `benchmarks/run_benchmark.py`, `benchmarks/tasks.json`, and `BENCHMARKS.md` exist, but rerun for the release candidate.
- [ ] Real-world validations - Requires verification: `docs/REAL_WORLD_VALIDATION.md` and `tools/evaluate_real_repos.py` exist, but public-launch evidence needs fresh sanitized runs.

## 5. Security/privacy

- [ ] Secret scan - Requires verification: run a repository secret scanner and review results before launch.
- [ ] `.env` excluded - Likely complete from repo evidence: `SECURITY.md` documents `.env` and `.env.*` exclusions.
- [ ] Private keys excluded - Likely complete from repo evidence: `SECURITY.md` documents `*.pem`, `*.key`, `id_rsa*`, and `id_ed25519*` exclusions.
- [ ] No telemetry - Likely complete from repo evidence: `README.md`, `SECURITY.md`, and `docs/MCP.md` state no telemetry.
- [ ] No source upload - Likely complete from repo evidence: `README.md`, `SECURITY.md`, and `docs/MCP.md` state no cloud/source upload.
- [ ] `SECURITY.md` current - Requires verification: file exists and documents the model, but owner should confirm disclosure/contact details before public launch.
- [ ] Responsible disclosure instructions - Requires verification: `SECURITY.md` explains vulnerability report contents, but no explicit public contact or GitHub security advisory process was confirmed.

## 6. GitHub

- [ ] About description - Requires verification: GitHub repository metadata is not represented in local files.
- [ ] Topics - Requires verification: `pyproject.toml` has suggested package keywords, but actual GitHub topics must be confirmed in repository settings.
- [ ] README - Likely complete from repo evidence: `README.md` exists.
- [ ] LICENSE - Likely complete from repo evidence: `LICENSE` exists and `pyproject.toml` declares Apache-2.0.
- [ ] CONTRIBUTING - Likely complete from repo evidence: `CONTRIBUTING.md` exists.
- [ ] SECURITY - Likely complete from repo evidence: `SECURITY.md` exists.
- [ ] Issue templates - Likely complete from repo evidence: `.github/ISSUE_TEMPLATE` contains bug, feature, retrieval feedback, and config templates.
- [ ] Discussions - Requires verification: GitHub Discussions setting cannot be confirmed from local files.
- [ ] Beta testing guide - Likely complete from repo evidence: `docs/BETA_TESTING.md` exists.
- [ ] Social preview image - Requires verification: no local social preview image evidence found.
- [x] Release notes - the b11 GitHub prerelease is published with release notes.
- [x] Changelog - `CHANGELOG.md` records b11 as released on 2026-10-10.

## 7. Community

- [ ] Tester feedback received - PENDING; no external independent tester feedback has been received.
- [ ] Major tester blockers resolved - Requires verification: needs issue/feedback review and release-owner signoff.
- [ ] Known limitations listed - Likely complete from repo evidence: `README.md`, `docs/MCP.md`, and `BENCHMARKS.md` list limitations and claim boundaries.
- [ ] Feedback/discussion channel prepared - Requires verification: issue templates exist, but public discussion/support channel setup needs confirmation.

## 8. Release

- [x] Version - source and runtime metadata declare `2.0.0b11`.
- [x] Tag - `v2.0.0b11` exists at release commit `b6dd660`.
- [x] GitHub prerelease - [v2.0.0b11](https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b11) is published as a prerelease.
- [x] Package build - the published wheel and sdist passed artifact inspection and have recorded SHA-256 hashes.
- [x] Installation verification - the final published b11 wheel was independently downloaded, checksum-verified, installed, and smoke-tested.
- [x] Linux installed-wheel verification - the b11 `quality` job passed its installed-wheel CLI/MCP smoke.
- [x] Windows installed-wheel verification - the b11 `windows-wheel-smoke` job passed outside the source checkout using a path containing spaces.
- [ ] Fresh OS/user-profile installation - PENDING; existing disposable-environment validation is not a clean-machine claim.
- [ ] Rollback instructions - PENDING; no public rollback instructions are documented.

## 9. Marketing/demo

- [ ] 60-second video - PENDING; `docs/DEMO.md` is a CLI demo script, not a published video.
- [ ] Architecture diagram - Likely complete from repo evidence: `ARCHITECTURE.md` includes a text system-flow diagram; verify whether a public visual asset is needed.
- [ ] Screenshots - Requires verification: no screenshot assets found.
- [ ] Benchmark examples - Likely complete from repo evidence: `BENCHMARKS.md` provides measured fixture examples and cautions.
- [ ] Truthful claims only - Likely complete from repo evidence: `README.md`, `BENCHMARKS.md`, and `docs/REAL_WORLD_VALIDATION.md` repeatedly describe local estimates and avoid universal claims.
- [ ] No unsupported credit-saving claims - Likely complete from repo evidence: `README.md`, `BENCHMARKS.md`, `docs/MCP.md`, and `docs/REAL_WORLD_VALIDATION.md` explicitly reject billing/credit-saving claims.

## 10. Business

- [ ] Free-beta decision - Requires verification: no public business decision found in repository files.
- [ ] Setup/audit offering - Requires verification: `repomind audit` exists and `docs/sample-audit-report.md` exists, but offering terms are not documented.
- [ ] Initial pricing - Requires verification: no pricing document found.
- [ ] Contact method - Requires verification: no public support/contact method confirmed from repository files.
- [ ] Support expectations - Requires verification: no support SLA or scope found.
- [ ] License/commercial strategy - Requires verification: Apache-2.0 license is present, but commercial/support strategy is not documented.

## Future Release-Candidate Evidence To Attach

- [ ] Fresh command log for `repomind init`, `repomind doctor`, `repomind status`, `repomind stats`, `repomind context`, `repomind context --explain`, `repomind memory list`, `repomind map`, `repomind symbol`, `repomind callers`, `repomind dependencies`, `repomind impact`, and `repomind mcp`.
- [ ] Fresh quality log for `python -m pytest`, `ruff check .`, `mypy repomind`, `python -m build`, evaluators, synthetic benchmark, and real-world validation.
- [ ] Fresh platform log covering Windows and at least one Unix-like platform if possible.
- [ ] Fresh security/privacy log covering secret scan, exclusion behavior, no telemetry/source upload review, and disclosure instructions.
