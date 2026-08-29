# RepoMind Public Launch Readiness Checklist

All boxes are intentionally open until the launch owner verifies the gate for the exact release candidate. Each item includes a repo-evidence status:

- Likely complete from repo evidence: supporting documentation, metadata, tests, or command definitions are present in this repository.
- Requires verification: no local evidence was found, or the item requires a live/manual check outside repository files.

## 1. Product

- [ ] Positioning clear - Likely complete from repo evidence: `README.md` opens with "Local-first repository intelligence for AI coding agents" and explains what RepoMind is and is not.
- [ ] README understandable in 30 seconds - Requires verification: run a timed read with at least one developer unfamiliar with RepoMind.
- [ ] Current beta limitations documented - Likely complete from repo evidence: `README.md` has `Limitations`; `pyproject.toml` marks beta status.
- [ ] Supported languages accurate - Requires verification: `README.md` documents language support, but confirm against parser implementations and tests before public launch.
- [ ] Roadmap accurate - Requires verification: `IMPLEMENTATION_PLAN.md` exists, but owner should confirm it reflects current priorities.

## 2. Installation

- [ ] Clean-machine install tested - Requires verification: test from a fresh environment, not the existing dev checkout.
- [ ] Windows tested - Requires verification: `docs/BETA_TESTING.md` includes PowerShell setup, but record an actual Windows install and smoke run.
- [ ] macOS/Linux tested if possible - Requires verification: docs include Unix activation; record actual install and smoke runs where available.
- [ ] Python requirements documented - Likely complete from repo evidence: `README.md`, `docs/BETA_TESTING.md`, and `pyproject.toml` require Python 3.11+.
- [ ] Uninstall instructions - Requires verification: no dedicated uninstall instructions found.
- [ ] Upgrade instructions - Requires verification: no public upgrade section found beyond install-from-checkout beta guidance.
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

- [ ] Full pytest - Requires verification: run `python -m pytest` for the release candidate.
- [ ] Ruff - Requires verification: run `ruff check .` for the release candidate.
- [ ] mypy - Requires verification: run `mypy repomind` or `python -m mypy repomind` for the release candidate.
- [ ] Build - Requires verification: run `python -m build` and inspect artifacts.
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
- [ ] Release notes - Requires verification: `CHANGELOG.md` exists, but GitHub release notes for the public launch must be drafted/published.
- [ ] Changelog - Likely complete from repo evidence: `CHANGELOG.md` exists and includes beta/release history.

## 7. Community

- [ ] Tester feedback received - Requires verification: no sanitized feedback summary was found in repository files.
- [ ] Major tester blockers resolved - Requires verification: needs issue/feedback review and release-owner signoff.
- [ ] Known limitations listed - Likely complete from repo evidence: `README.md`, `docs/MCP.md`, and `BENCHMARKS.md` list limitations and claim boundaries.
- [ ] Feedback/discussion channel prepared - Requires verification: issue templates exist, but public discussion/support channel setup needs confirmation.

## 8. Release

- [ ] Version - Likely complete from repo evidence: `pyproject.toml` declares `2.0.0b8`; confirm intended public-launch version.
- [ ] Tag - Requires verification: create or verify the release tag for the exact version.
- [ ] GitHub prerelease/release - Requires verification: publish or verify the GitHub release entry.
- [ ] Package build - Requires verification: run `python -m build` and inspect the wheel/sdist.
- [ ] Installation verification - Requires verification: install from the built artifact in a clean environment and run smoke commands.
- [ ] Rollback instructions - Requires verification: no public rollback instructions found.

## 9. Marketing/demo

- [ ] 60-second demo - Likely complete from repo evidence: `docs/DEMO.md` exists in the working tree.
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

## Release-Candidate Evidence To Attach

- [ ] Fresh command log for `repomind init`, `repomind doctor`, `repomind status`, `repomind stats`, `repomind context`, `repomind context --explain`, `repomind memory list`, `repomind map`, `repomind symbol`, `repomind callers`, `repomind dependencies`, `repomind impact`, and `repomind mcp`.
- [ ] Fresh quality log for `python -m pytest`, `ruff check .`, `mypy repomind`, `python -m build`, evaluators, synthetic benchmark, and real-world validation.
- [ ] Fresh platform log covering Windows and at least one Unix-like platform if possible.
- [ ] Fresh security/privacy log covering secret scan, exclusion behavior, no telemetry/source upload review, and disclosure instructions.
