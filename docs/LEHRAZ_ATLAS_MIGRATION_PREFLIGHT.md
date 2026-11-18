# Lehraz Atlas rename — compatibility preflight (proposal)

**Status: PLAN ONLY / NO_GO for production rename.** This document records a proposed rebrand of the existing Apache-2.0 RepoMind product and repository, not a new or separate product. It does not authorize renaming the GitHub repository, changing published releases, or changing Python/MCP interfaces without compatibility tests.

## Naming decision

- Parent brand: **Lehraz**
- Product brand: **Lehraz Atlas**
- Proposed GitHub repository: `raazlehra/lehraz-atlas` (rename the existing `raazlehra/Repomind`; **do not** create an unrelated replacement repository or discard history).
- Editions: **Lehraz Atlas Free** (existing Apache-2.0 local core) and **Lehraz Atlas Pro** (commercial CI/PR automation and historical/team workflows, to be scoped separately).
- Do not imply that Pro is part of an Apache-2.0 release or that unshipped Pro features exist.

## Frozen public baseline

- Public release: `v2.0.0b13`; release URL: https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b13
- Published wheel filename: `repomind-2.0.0b13-py3-none-any.whl`
- Published wheel SHA-256: `6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9`
- Existing PyPI name `repomind` belongs to an unrelated distribution. Do not suggest plain `pip install repomind`.
- The independent site repo `raazlehra/repomind-site` publishes from `main`; the b13 website text was merged separately in PR #5.
- **Do not rewrite b13 tags, assets, checksums, historical documentation, or their version identities.**

## Source-verified rename dependencies

| Contract | Current implementation | Migration requirement |
| --- | --- | --- |
| Python distribution / entry point | `pyproject.toml`: `name = "repomind"`, `repomind = "repomind.cli:main"`, setuptools includes `repomind*` | Check `lehraz-atlas` PyPI/distribution availability separately. Preserve working old CLI before introducing additional command/renaming distribution. Do not conflate distribution, import module, and CLI names. |
| Python import module | `repomind/`, `python -m repomind`, tests and CI | Preserve module imports for the compatibility phase; a package-directory rewrite is a separate breaking-change proposal. |
| Local index | `repomind/database.py`: `.repomind/index.sqlite3`; index path hardening | Preserve existing databases, schema and safety checks; no silent data migration, deletion, reindex, or symlink bypass. |
| Config / ignore | `repomind/config.py`: `.repomind.toml` and `[repomind]`; `repomind/scanner.py`: `.repomindignore` | Read the existing config and ignore patterns correctly; preserve defaults and secret exclusions. Future new filenames require an opt-in dual-read policy and tests. |
| MCP | `repomind/mcp.py`: existing `repomind_*` tool IDs, server metadata | Do not silently rename tool IDs or break existing client tool calls. Brand labels can change independently. |
| Agent integrations | `repomind/integration.py`: Codex skill `.codex/skills/repomind/SKILL.md`; `docs/MCP.md` | Preserve current client configuration and add new branding without overwriting user-managed configuration. |
| Structured report contracts | `scripts/installed_wheel_smoke.py` and `scripts/release_lifecycle_smoke.py`: `repomind.test-impact.v1` | Preserve schema IDs and field contracts until an explicitly versioned schema migration. |
| Release automation | `scripts/verify_release_artifacts.py`, installed-wheel and lifecycle smoke, `.github/workflows/ci.yml` | Any new distribution identity requires an updated verifier and **separate** installed-wheel/upgrade tests; do not merely replace expected strings. |
| Public docs / site | `README.md`, `docs/INSTALLATION.md`, `docs/MCP.md`, `docs/index.html`, independent site `repomind-site` | Update official entry points in a second PR after runtime contract is settled. Preserve the PyPI warning and prior-release links. Resolve the duplicated legacy `docs/index.html` surface deliberately. |

This is a targeted preflight based on public `main` files, **not** a complete local search or successful test run.

## Proposed gated execution

### Gate A — local preflight and availability (no publication)

- [ ] Record clean local `git status`, current `main` SHA, release files/checksums, and active Codex worktrees/branches before any modifications.
- [ ] Verify that `raazlehra/lehraz-atlas` is available **at GitHub rename time**; check project/distribution name availability and potential trademark/confusingly similar uses independently.
- [ ] Run a full case-insensitive tracked/untracked code, configuration, binary and documentation reference inventory for `repomind`, `RepoMind`, `Repomind`, `.repomind`, `repomind-site`, and release links. Include tests, workflows, demo assets, generated files, examples and external integration files.
- [ ] Classify every match as *historical preserve*, *compatibility contract*, *brand copy update*, or *release-build change*. No blanket replacement.
- [ ] Record current b13 installed wheel, CLI/MCP, upgrade and index-preservation behavior as a baseline; keep the b13 wheel immutable.

### Gate B — compatibility-first implementation (dedicated PR, no repo rename)

- [ ] Introduce new product display branding and, if safe, a new CLI alias while keeping `repomind` working.
- [ ] Keep import path, MCP tool identifiers, `.repomind` index, ignore/config names, and public schema IDs compatible. Explicitly document any aliasing or deprecation period.
- [ ] Do **not** change distribution identity until a fresh-wheel packaging test and both installation paths are designed and validated; avoid claiming that `pip install lehraz-atlas` works before an owned artifact exists.
- [ ] Update package metadata, author fields, install examples, packaging verifier, CI and smoke scripts atomically if distribution identity is later changed.
- [ ] Make sure source-package, wheel, editable and base/Tree-sitter installations agree about metadata, import paths and executables.
- [ ] No removal of existing public Free features or licensing changes.

### Gate C — proof and controlled rename

- [ ] Pass full unit/lint/type CI and Windows/Linux installed-wheel smoke, plus MCP stdio probe, config/ignore security tests, and schema contract checks.
- [ ] Pass real b13-to-candidate upgrade preserving a working `.repomind/index.sqlite3`, memory, user config, selected tests, and `repomind` CLI/MCP compatibility.
- [ ] Validate current Free real-PR pilot cases without weaker unknown-coverage handling. Do not make new language-coverage promises unsupported by qualification.
- [ ] After a reviewed go decision, rename GitHub repository in **Settings → General → Repository name**. This step cannot be represented as completed by a docs PR.
- [ ] Update each local checkout's `origin` to `https://github.com/raazlehra/lehraz-atlas.git` and check CI, release automation, issue templates, badges, hardcoded links and integrations.
- [ ] Recheck GitHub releases, security-reporting, installed wheel downloads, GitHub REST consumers, and old redirects. **Do not reuse** the previous repository slug in a newly created repository, which would break old redirects.

### Gate D — site rebrand, then Pro

- [ ] Keep the separate `repomind-site` repository and its Pages URL initially; update content and canonical product links in a dedicated site PR. GitHub project Pages URLs are not automatically redirected on repository rename.
- [ ] Validate page links, OG preview, version/checksum, installation warnings, mobile/desktop/accessibility, and real published HTML after merge/deployment.
- [ ] Only afterward consider a site-repository slug/domain move with an explicit redirect strategy.
- [ ] Plan Pro P0 PR intelligence/test-planning work separately from Free core changes and clearly label Pro functionality as planned until qualified.

## Stop conditions and rollback

**NO_GO:** existing users lose CLI/MCP capability; indexes or memory are deleted/unreadable; installation resolves to the unrelated PyPI package; public b13 hashes are modified; security hardening is weakened; CI or release smoke fails; support claims exceed real-PR evidence; or the site continues showing a stale release after a supposed publication.

To roll back a **code-level candidate**, revert its unmerged PR without touching the b13 tag/assets. To roll back a GitHub **repository rename**, a separate admin rename back plus verification of remotes, old URLs and Pages is required; it is not equivalent to reverting a code commit. Preserve historical downloadable artifacts and warn customers about changed URLs.

## What we might be missing

- GitHub Actions referencing an action hosted at the old repository name **will not be redirected** by the rename. Audit any such consumers before renaming.
- The current repo contains a second `docs/index.html` website in addition to the independently deployed `repomind-site`; determine its supported/canonical status.
- Inspect external integrations and open-source attribution/branding; Apache-2.0 source licensing does not itself establish ownership or clearance of a new product mark.
- Brand/domain/distribution availability checks are time-sensitive; search results are not reservation, trademark clearance, or a guarantee.
- A hosted Pro portal/billing system is unnecessary before customer-run CI pilots demonstrate differentiated impact and willingness to pay.

References: [RepoMind source](https://github.com/raazlehra/Repomind); [website PR #5](https://github.com/raazlehra/repomind-site/pull/5); [GitHub repo rename guidance](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository).
