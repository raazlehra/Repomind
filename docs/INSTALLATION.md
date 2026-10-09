# Installation and Lifecycle

RepoMind is distributed through [GitHub Releases](https://github.com/raazlehra/Repomind/releases).
The current published beta is `v2.0.0b10`.

> [!WARNING]
> Do not run plain `pip install repomind`. The `repomind` name on PyPI currently resolves to
> a different project. Install a RepoMind wheel downloaded from this repository's GitHub
> Releases page, or install from a checkout you trust for development.

## Install a published release on Windows

The GitHub Release wheel is authoritative. For example, the published b10 wheel is:

```text
https://github.com/raazlehra/Repomind/releases/download/v2.0.0b10/repomind-2.0.0b10-py3-none-any.whl
```

Its release SHA-256 is
`8ac3533c831a9aae1032081c3a7083761d8e3aed09a69f6cc92293cf6405f9b1`.
Confirm the version and hash on the release page for every later release; do not reuse the b10
value for another artifact.

Download the exact wheel, verify it, and install it into a dedicated environment. PowerShell:

```powershell
$Wheel = (Resolve-Path "C:\Downloads\repomind-2.0.0b10-py3-none-any.whl").Path
$Expected = "8ac3533c831a9aae1032081c3a7083761d8e3aed09a69f6cc92293cf6405f9b1"
$Actual = (Get-FileHash -Algorithm SHA256 $Wheel).Hash.ToLowerInvariant()
if ($Actual -ne $Expected) { throw "RepoMind wheel checksum mismatch" }

py -3.12 -m venv "C:\Tools\RepoMind"
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install $Wheel
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind --version
& "C:\Tools\RepoMind\Scripts\repomind.exe" --version
```

The explicit interpreter form does not depend on activation or an unrelated `repomind` command
elsewhere on `PATH`. The installed distribution metadata name and CLI command are both
`repomind`, but the name alone does not prove that the wheel came from this project.

On Linux or another POSIX system with `sha256sum`:

```bash
curl -fL -o repomind-2.0.0b10-py3-none-any.whl \
  https://github.com/raazlehra/Repomind/releases/download/v2.0.0b10/repomind-2.0.0b10-py3-none-any.whl
printf '%s  %s\n' \
  '8ac3533c831a9aae1032081c3a7083761d8e3aed09a69f6cc92293cf6405f9b1' \
  'repomind-2.0.0b10-py3-none-any.whl' | sha256sum -c -
python3 -m venv "$HOME/.local/share/repomind-venv"
"$HOME/.local/share/repomind-venv/bin/python" -m pip install ./repomind-2.0.0b10-py3-none-any.whl
"$HOME/.local/share/repomind-venv/bin/python" -m repomind --version
```

On macOS, compare `shasum -a 256 <wheel>` with the GitHub Release hash before installing.

The package requires Python 3.11 or newer and currently declares support classifiers for Python
3.11 through 3.13. Windows installed-wheel release checks use paths containing spaces and run
outside the source checkout. Linux installed-wheel behavior is a CI gate; a release must not
claim it passed until the corresponding GitHub Actions run is green.

## Optional dependencies

The base wheel includes normal indexing, retrieval, and MCP support. Optional extras are encoded
in the wheel metadata and can be requested from the local wheel without consulting PyPI for the
RepoMind project itself:

```powershell
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install "C:\Downloads\repomind-<version>-py3-none-any.whl[watch]"
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install "C:\Downloads\repomind-<version>-py3-none-any.whl[treesitter]"
```

- Without `watchdog`, event-driven `repomind watch` is unavailable. Normal indexing, explicit
  refresh, and retrieval-time freshness continue to work.
- Without the Tree-sitter packages, built-in deterministic parsers remain active. Tree-sitter is
  an optional source of declaration spans, not a requirement for normal indexing or retrieval.

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
python -m pip install "dist\repomind-2.0.0b11-py3-none-any.whl"
```

Building locally does not publish a release. Use the GitHub Releases page for published assets.

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

## Upgrade an existing b10 index to a candidate

Back up important repository data, then install the candidate wheel into the same dedicated
environment using its exact path:

```powershell
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install --upgrade "C:\Downloads\repomind-<new-version>-py3-none-any.whl"
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind --version
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind status -C "C:\path\to\repository"
& "C:\Tools\RepoMind\Scripts\python.exe" -m repomind doctor "C:\path\to\repository"
```

Local Windows validation on 2026-10-10 installed the authoritative b10 wheel after matching its
published SHA-256, created a schema-2 index and manual memory, then upgraded to the exact local
`2.0.0b11` candidate wheel. Repository identity, creation metadata, schema, and manual memory were
preserved; doctor, context, and test-impact remained healthy. Uninstall/reinstall also preserved
the index, configuration, and manual memory. A separate disposable forced rebuild preserved
configuration and removed database-only manual memory as documented.

This is evidence for that exact b10-to-b11 candidate path on Windows/Python 3.12.14, not a blanket
compatibility promise. Linux evidence remains pending the actual GitHub Actions run.

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
& "C:\Tools\RepoMind\Scripts\python.exe" -m pip install "C:\Downloads\repomind-<version>-py3-none-any.whl"
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
