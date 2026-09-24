# RepoMind Public CLI Demo

This short demo shows local indexing, bounded task retrieval, and change-aware test-impact
analysis without using proprietary source or modifying the demo repository.

Use a clean, disposable clone of RepoMind or another public repository that is safe to show.
The commands below were checked against the current CLI. Install a published GitHub Release
wheel first by following [INSTALLATION.md](INSTALLATION.md); do not use plain
`pip install repomind`, which currently resolves an unrelated PyPI project.

## Setup

In an isolated environment, install a wheel downloaded from the GitHub Releases page. Replace
the placeholder with the filename of an actually published asset:

```powershell
python -m pip install "C:\Downloads\repomind-<published-version>-py3-none-any.whl"
repomind --version
```

Then open Windows PowerShell at the safe repository root:

```powershell
Set-Location "C:\path\to\Repomind"
```

For the current beta wheel, the version command should report `RepoMind 2.0.0b10`.

## Demo flow

### 1. Build the local index

```powershell
repomind init
repomind status
```

Explain that the index is stored locally under `.repomind/`. Read the actual status output;
do not quote prepared file or symbol counts.

### 2. Retrieve bounded task context

```powershell
repomind context "tighten test-impact evidence limits" --explain
```

Point out the selected files, symbols, relationships, tests, and ranking explanations. These
are discovery evidence, not a guarantee that every relevant runtime path was found.

### 3. Analyze a hypothetical change set

```powershell
repomind test-impact -C . --format markdown repomind/test_impact.py repomind/cli.py
```

The two repository-relative paths are explicit analysis inputs; no source edit is required.
Show the changed files, affected areas, existing tests, uncovered areas, and recommended commands
in the Markdown output. Rerun with `--format json` when the audience needs the explicit
completeness, lower-bound, and truncation fields shown in the sanitized sample report.

Explain that RepoMind does not run the recommended commands. A developer or trusted agent must
review the evidence, verify each command and working directory, and decide what to execute.
Confidence labels summarize static evidence; they are not probabilities or correctness claims.

For a compact example with verified output fields, see
[SAMPLE_TEST_IMPACT_REPORT.md](SAMPLE_TEST_IMPACT_REPORT.md).

## Presenter guardrails

- Use only public or synthetic source and keep private remotes, branches, paths, tickets, and
  environment files off screen.
- Let the terminal provide counts and paths; do not invent output or benchmark claims.
- Do not claim that static analysis proves runtime behavior, security, or exhaustive coverage.
- Respect `truncated`, `discovery_complete`, and lower-bound metadata before interpreting totals.
- Keep recommended commands visible as suggestions; do not execute them as part of this demo.

## Command-only version

See `scripts/demo_commands.txt` for the copy/paste command list.
