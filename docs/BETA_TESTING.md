# RepoMind External Beta Testing

RepoMind is a local-first repository intelligence layer for AI coding agents. This guide is for external beta testers running RepoMind on real repositories and reporting practical feedback.

## Who should test

Developers willing to run RepoMind on a real repository they understand and can safely inspect.

Good beta testers include people who:

- maintain an application, library, internal tool, CLI, service, or monorepo;
- use AI coding agents and want better repository discovery;
- can compare RepoMind output with their own knowledge of the project;
- are willing to report confusing retrieval results, stale facts, installation issues, and command output.

## Safety

RepoMind is beta software. Test it on a repository you own or control.

Before testing:

- make normal Git backups or commits first;
- avoid running beta tests on your only uncommitted copy of important work;
- do not send private source code in bug reports;
- redact secrets and proprietary paths where appropriate;
- do not paste API keys, credentials, private keys, tokens, or other secrets into public issues;
- treat `.repomind/` as local repository metadata and do not normally commit it.

RepoMind is designed for static local analysis. It should not execute repository source code during indexing or retrieval, but beta testers should still use normal care with any pre-release developer tool.

## Requirements

- Git
- Python 3.11 or newer
- A terminal: PowerShell, Command Prompt, bash, zsh, or similar
- Access to this repository's GitHub Releases page
- A real repository you own or control

## Installation

The latest published beta is [v2.0.0b13](https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b13), published on November 15, 2026.
Download its [exact wheel](https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/repomind-2.0.0b13-py3-none-any.whl) and verify SHA-256
`6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9` before installation.
The published [checksum file](https://github.com/raazlehra/Repomind/releases/download/v2.0.0b13/SHA256SUMS.txt) also records the source-distribution hash.

Do not use plain `pip install repomind`. The package with that name on PyPI is a different
project.

Verify the downloaded b13 wheel and use an explicit isolated interpreter on Windows PowerShell:

~~~powershell
$WheelPath = (Resolve-Path "C:\Downloads\repomind-2.0.0b13-py3-none-any.whl").Path
$Expected = "6152d1fa9761dd55662defe68a77d02cd50e7dd22bc4c013f62a1b7080601bd9"
if ((Get-FileHash -LiteralPath $WheelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Expected) { throw "RepoMind wheel checksum mismatch" }
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install $WheelPath
& ".\.venv\Scripts\python.exe" -m repomind --version
& ".\.venv\Scripts\python.exe" -m repomind --help
& ".\.venv\Scripts\repomind.exe" --help
~~~

For Linux, follow the matching checksum-gated b13 commands in
[Installation and lifecycle](INSTALLATION.md).

The reported version must match the release asset you selected. The published b13 wheel reports:

```text
RepoMind 2.0.0b13
```

Contributors who intentionally need an editable source install should follow
[CONTRIBUTING.md](../CONTRIBUTING.md). Public beta installation should use the release wheel.
See [Installation and lifecycle](INSTALLATION.md) for optional extras, local-build validation,
upgrade scope, and uninstall/reinstall behavior.

### b13 release verification and analysis boundaries

The current published beta is [v2.0.0b13](https://github.com/raazlehra/Repomind/releases/tag/v2.0.0b13). Verify its exact wheel hash above
and follow [Installation and lifecycle](INSTALLATION.md). The b11/b12 records there are
explicitly historical and their hashes must not be substituted for b13.
The `.json`/`.jsonl` source-anchored fixture-reference evidence requires the optional `[treesitter]`
extra. This is structural evidence, not runtime coverage. Unsupported wrapper-based data flow
remains unsupported, coverage remains unknown, and RepoMind never executes recommended npm tests.
The maintainer's public-wheel smoke tests do not substitute for your own repository validation.

## Test workflow

Run RepoMind against your own project, not the RepoMind checkout:

```bash
cd <your-project>
repomind init
repomind doctor
repomind status
repomind stats
repomind map
```

Then try context retrieval with a real task from your project:

```bash
repomind context "<real task>"
repomind context "<real task>" --explain
```

Examples of real tasks:

- "fix failing login redirect test"
- "add validation to invoice export"
- "find where monthly totals are calculated"
- "update API response for dashboard summary"

Memory:

```bash
repomind memory list
```

Symbol and graph commands should use actual symbols and files from your repository:

```bash
repomind symbol <actual-symbol>
repomind callers <actual-symbol>
repomind dependencies <actual-file-or-symbol>
repomind impact <actual-file-or-symbol>
repomind snippets <actual-symbol>
```

## Automatic freshness test

Please test whether saved working-tree changes are reflected without a manual refresh.

1. Query a real symbol in your repository:

   ```bash
   repomind symbol <actual-symbol>
   ```

2. Edit and save the source file that defines that symbol.
3. Add a new symbol or rename the symbol.
4. Do not run `repomind refresh`.
5. Do not run `repomind watch`.
6. Query again:

   ```bash
   repomind symbol <new-or-renamed-symbol>
   repomind status
   ```

7. Report whether the change appeared automatically and whether the freshness/status output was understandable.

## Repository memory test

Run:

```bash
repomind memory list
repomind context "<real task>" --explain
```

Please report:

- Was memory relevant to the task?
- Was any memory misleading or noisy?
- Did stale memory disappear appropriately from normal task context?
- Were source paths, categories, and statuses useful?
- Was it clear which memory was automatic and which was manual?

If you add manual memory, use a repository fact that does not expose private source:

```bash
repomind memory add --category architecture --source <actual-file> "Short repository convention written without proprietary details."
repomind memory list --status manual
```

## Feedback requested

Please include as much of the following as you can:

- RepoMind version
- OS and shell
- Python version
- Project language and framework
- Approximate repository size
- Installation experience
- Command run
- Expected result
- Actual result
- Error or output
- Whether the issue is reproducible
- Retrieval relevance
- Explainability usefulness
- Stats usefulness
- Memory usefulness or noise
- Freshness result
- Performance impression

For retrieval feedback, sanitized file paths are usually enough. For example:

```text
Expected: backend/routes.py, backend/services.py, tests/test_auth.py
Selected: backend/routes.py, backend/models.py, tests/test_auth.py
```

## Privacy guidance

Do not paste proprietary code, API keys, credentials, private keys, tokens, secrets, customer data, internal URLs, or sensitive business details into public issues.

When reporting problems:

- redact source snippets unless they are from a public reproduction;
- replace proprietary path segments with neutral names;
- remove usernames, hostnames, tokens, and internal service names when appropriate;
- prefer minimal synthetic reproductions when possible;
- share only the command, sanitized output, and high-level project context needed to understand the issue.

Access to the RepoMind repository does not make your own project source public. Keep your project's confidentiality rules in place while testing.
