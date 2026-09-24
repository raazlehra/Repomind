# Installation and Lifecycle

RepoMind is distributed through [GitHub Releases](https://github.com/raazlehra/Repomind/releases).
The current published beta is `v2.0.0b10`.

> [!WARNING]
> Do not run plain `pip install repomind`. The `repomind` name on PyPI currently resolves to
> a different project. Install a RepoMind wheel downloaded from this repository's GitHub
> Releases page, or install from a checkout you trust for development.

## Install a published release on Windows

Download the `.whl` asset for the release you intend to use. Then create an isolated virtual
environment and install that exact file. This PowerShell flow is the primary verified path:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install "C:\Downloads\repomind-<version>-py3-none-any.whl"

repomind --version
repomind --help
python -m repomind --help
```

Replace the example path and filename with the asset you downloaded. Keeping RepoMind in a
dedicated virtual environment makes its Python interpreter easy to identify when configuring
an MCP client.

The package requires Python 3.11 or newer. Project metadata currently declares classifiers for
Python 3.11 through 3.13. The Day 7 lifecycle run also completed on Python 3.14.7, but that is an
observed compatibility result, not a declaration of formal Python 3.14 support.

Day 7 exercised newly created disposable virtual environments on Windows, including repository
paths containing spaces, an `E:` drive repository, and installed-package execution outside the
source checkout. That run was process-isolated; it was not a fresh Windows VM or user profile.
Linux and macOS lifecycle validation is still pending.

## Optional dependencies

The base wheel includes normal indexing, retrieval, and MCP support. Optional extras are encoded
in the wheel metadata and can be requested from the local wheel without consulting PyPI for the
RepoMind project itself:

```powershell
python -m pip install "C:\Downloads\repomind-<version>-py3-none-any.whl[watch]"
python -m pip install "C:\Downloads\repomind-<version>-py3-none-any.whl[treesitter]"
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
python -m pip install "dist\repomind-2.0.0b10-py3-none-any.whl"
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

## Upgrade from beta 9

Install the newer wheel into the same virtual environment:

```powershell
python -m pip install --upgrade "C:\Downloads\repomind-<new-version>-py3-none-any.whl"
repomind --version
repomind status -C "C:\path\to\repository"
repomind doctor "C:\path\to\repository"
```

Day 7 specifically tested upgrading a disposable schema-2 index created by published beta 9 to
`2.0.0b10`. In that test, the existing index opened without reindexing,
repository identity remained intact, and existing memory data remained available. This result is
limited to that tested beta-9/schema-2 path; it is not a blanket compatibility promise for every
older or future index format. If `doctor` or `status` requests a rebuild for another schema, follow
that explicit diagnostic instead of assuming compatibility.

## Uninstall and reinstall

Uninstall the Python package through the environment's interpreter:

```powershell
python -m pip uninstall repomind
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
python -m pip install "C:\Downloads\repomind-<version>-py3-none-any.whl"
repomind status -C "C:\path\to\repository"
repomind context "trace the authentication flow" -C "C:\path\to\repository"
```

The Day 7 disposable lifecycle confirmed that a preserved index remained usable after package
uninstall and reinstall.

## Next step: agent integration

After installing and initializing the target repository, see [MCP integration](MCP.md) for Codex,
GitHub Copilot CLI, VS Code Copilot Chat, and optional Claude Code setup.
