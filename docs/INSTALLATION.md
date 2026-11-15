# Installation and Lifecycle

RepoMind is distributed through [GitHub Releases](https://github.com/raazlehra/Repomind/releases).
That page is authoritative for which beta versions and assets have actually been published.
Source metadata or candidate documentation alone does not establish publication.

> [!WARNING]
> Do not run plain `pip install repomind`. The `repomind` name on PyPI currently resolves to
> a different project. Install a RepoMind wheel downloaded from this repository's GitHub
> Releases page, or install from a checkout you trust for development.

## Install a published release on Windows

The GitHub Release wheel is authoritative. Select an asset that is actually attached to a release;
do not construct or guess a download URL. Copy the exact SHA-256 published for that asset, and do
not reuse a checksum from another version or build.

The latest published beta is [v2.0.0b13](https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b13), published on November 15, 2026.
Its exact [wheel URL](https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/repomind-2.0.0b13-py3-none-any.whl) is:

~~~text
https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/repomind-2.0.0b13-py3-none-any.whl
~~~

The wheel SHA-256 is `6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9`.
The [source distribution](https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/repomind-2.0.0b13.tar.gz) has SHA-256
`eae981560f5777dcac85da01d509f38c11d7937db63b0326122f42aa045a6d85`. Both values are recorded in the published
[SHA256SUMS.txt](https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/SHA256SUMS.txt); do not reuse them for a different build.

Download the wheel above, then verify it before installing. Windows PowerShell:

~~~powershell
$Wheel = (Resolve-Path "C:\Downloads\repomind-2.0.0b13-py3-none-any.whl").Path
$Expected = "6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9"
$Actual = (Get-FileHash -LiteralPath $Wheel -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Actual -ne $Expected) { throw "RepoMind wheel checksum mismatch" }

python -m venv "C:\Tools\RepoMind"
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install $Wheel
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip check
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind --version
~~~

Use a maintained, security-patched Python 3.11+ interpreter for environment creation. The explicit environment
interpreter avoids activation-policy changes and an unrelated command elsewhere on PATH.
The expected version is `2.0.0b13`; the name alone does not prove the wheel's origin.

## Install b13 on Linux

The following chain stops before installation if download or checksum verification fails:

~~~sh
curl -fL -o repomind-2.0.0b13-py3-none-any.whl \
  https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/repomind-2.0.0b13-py3-none-any.whl &&
printf '%s  %s\n' \
  '6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9' \
  'repomind-2.0.0b13-py3-none-any.whl' | sha256sum --check - &&
python3 -m venv "$HOME/.local/share/repomind-venv" &&
"$HOME/.local/share/repomind-venv/bin/python" -m pip install ./repomind-2.0.0b13-py3-none-any.whl &&
"$HOME/.local/share/repomind-venv/bin/python" -m pip check &&
"$HOME/.local/share/repomind-venv/bin/python" -m repomind --version
~~~

On macOS, `shasum -a 256 <wheel>` can compare the published hash, but macOS has not
been release-validated. This checksum note does not add a macOS support claim.

## Qualification and historical releases

RepoMind requires Python>=3.11; classifiers advertise 3.11-3.13 rather than every future runtime.
The [b13 post-merge CI](https://github.com/raazlehra/Repomind/actions/runs/43707122224)
passed Linux tests on patched Python 3.11.18, 3.12.16 and 3.13.18 (399 passed and four
Windows-only junction skips per version), quality checks, and Linux/Windows installed-wheel
smokes. Windows CI used Python 3.12.10 for functional package smokes. Separate local Windows
Python 3.13.18 source and installed-wheel qualification passed 403/403; native symlink tests
passed 19/19 with zero skips and junction tests passed 4/4. The actual published wheel was
downloaded, hash-verified and installed in a fresh Windows Python 3.13.18 environment.

macOS and Python 3.14 are not broadly release-qualified. Earlier WSL Python 3.14.4 symlink
results do not expand the advertised Python matrix. See the [b13 notes](releases/v2.0.0b13.md)
and [upgrade guide](UPGRADE_B13.md) for scope and limitations.

[b12](https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b12) remains available as a
historical release. Its unchanged wheel SHA-256 is
`34c751e3ffb893bcc07403d4bdf2f6d1c5154ac04e4afcac92bbdfadcf43b827`.
Its recorded Windows/Python 3.12.14 base and Tree-sitter checks are historical b12 evidence,
not the current b13 installation example.

## Optional dependencies

The base wheel includes normal indexing, retrieval, and MCP support. Optional extras are encoded
in the wheel metadata and can be requested from the local wheel without consulting PyPI for the
RepoMind project itself:

```powershell
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install "C:\Downloads\repomind-2.0.0b13-py3-none-any.whl[watch]"
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install "C:\Downloads\repomind-2.0.0b13-py3-none-any.whl[treesitter]"
```

- Without `watchdog`, event-driven `repomind watch` is unavailable. Normal indexing, explicit
  refresh, and retrieval-time freshness continue to work.
- Without the Tree-sitter packages, built-in deterministic parsers remain active. Tree-sitter is
  an optional source of declaration spans, not a requirement for normal indexing or retrieval.

Since `2.0.0b12`, tightly constrained source-anchored `.json`/`.jsonl`
fixture-reference analysis also requires the Tree-sitter extra. It does not follow arbitrary
wrapper-based data flow, does not execute repository scripts, and provides structural test-impact
evidence rather than runtime coverage. The published b11 wheel does not contain this b12 change.

`repomind doctor <repository>` reports these optional capabilities as notices rather than making
them mandatory.

## Development installation

Editable installation is for contributors working from a trusted source checkout, not the public
release installation path:

```powershell
git clone https://github.com/raazlehra/Repomind.git
cd Repomind
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

To validate a local source build, build artifacts from the intended commit and install the
resulting wheel in a separate disposable environment:

```powershell
python -m build
python -m pip install "dist\repomind-2.0.0b13-py3-none-any.whl"
```

Building locally does not publish a release. Do not describe any locally built wheel as a
published asset. Use the GitHub Releases page for published assets and their exact checksums.

## Initialize a repository

Run RepoMind from the repository you want to inspect, or pass its path explicitly:

```powershell
Set-Location "C:\path\to\My Project"
repomind init
repomind status
repomind doctor
repomind map
repomind context "trace the authentication flow"
```

`init` creates repository-local `.repomind` index data. It does not mean "install RepoMind."
Treat `.repomind/` as local metadata and do not normally commit it.

## Historical upgrade from b10 to b11

Back up important repository data, then install the b11 wheel into the same dedicated environment
using its exact path:

```powershell
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install --upgrade "C:\Downloads\repomind-2.0.0b11-py3-none-any.whl"
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind --version
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind status -C "C:\path\to\repository"
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind doctor "C:\path\to\repository"
```

Pre-release Windows validation on 2026-10-10 installed the authoritative b10 wheel after matching
its published SHA-256, created a schema-2 index and manual memory, then upgraded to the exact local
`2.0.0b11` candidate wheel built from the release code. Repository identity, creation metadata,
schema, and manual memory were preserved; doctor, context, and test-impact remained healthy.
Uninstall/reinstall also preserved the index, configuration, and manual memory. A separate
disposable forced rebuild preserved configuration and removed database-only manual memory as
documented.

The final public b11 wheel was later rebuilt from the same release commit and independently
downloaded, checksum-verified, installed, and smoke-tested. The full b10-to-final-downloaded-b11
lifecycle sequence was not repeated. The lifecycle evidence is therefore limited to the exact
b10-to-b11 candidate path on Windows/Python 3.12.14; Linux and Windows installed-wheel CI checks
for the final release commit passed separately. This is not a blanket compatibility promise.

## Historical b11-to-b12 candidate validation

On 2026-10-23, release preparation used the authentic b11 GitHub Release wheel only after its
SHA-256 matched
`3202f593084a5f13cbe68c21bc7a2bc3c6207671a28e10303267bf0b0594ba9f`. Upgrading that
wheel to the locally built `2.0.0b12` candidate preserved schema 2, repository identity,
creation metadata, configuration, and manual memory. Uninstall/reinstall preserved repository
data, while `init --force` preserved configuration and removed database-only manual memory as
documented. Recommended test commands were not executed.

These lifecycle results apply to the locally built b12 candidate. Separately, after publication
on 2026-10-23 the maintainer reported independent download/checksum checks on the public wheel
and sdist and successful base and Tree-sitter installed-wheel smokes on Windows/Python 3.12.14.
This does not establish macOS or Python 3.14 compatibility or a full upgrade lifecycle run
against the final publicly downloaded b12 wheel.

## Uninstall and reinstall

Uninstall the Python package through the environment's interpreter:

```powershell
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip uninstall repomind
```

Package uninstall removes the installed module and command from that environment. It does not
automatically remove:

- repository `.repomind/` index data;
- repository `.repomind.toml` configuration;
- MCP registrations stored by Codex, Copilot, Claude Code, or another client.

This preservation is intentional: package lifecycle and repository/user data lifecycle are
separate. Inspect data before deleting it. Inspect and remove an MCP registration with that
client's own commands only when desired.

Reinstall the same way as the original release installation:

```powershell
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install "C:\Downloads\repomind-2.0.0b13-py3-none-any.whl"
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind status -C "C:\path\to\repository"
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind context "trace the authentication flow" -C "C:\path\to\repository"
```

The Day 7 disposable lifecycle confirmed that a preserved index remained usable after package
uninstall and reinstall.

`repomind init --force` is different from package reinstall: it deletes the SQLite index files
and rebuilds them from source. Manual memory stored only in that database is removed. Export or
record manual facts before forcing a rebuild when they must be preserved.

## Next step: agent integration

After installing and initializing the target repository, see [MCP integration](MCP.md) for Codex,
GitHub Copilot CLI, VS Code Copilot Chat, and optional Claude Code setup.

## Current b12-to-b13 upgrade

b13 is published. Follow the [upgrade guide](UPGRADE_B13.md) using the exact
[public b13 wheel](https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/repomind-2.0.0b13-py3-none-any.whl) and its published checksum.
Historical b11/b12 lifecycle evidence above remains scoped to those original runs.
