# RepoMind 60-Second CLI Demo

Purpose: show a developer that RepoMind indexes a real repository once, returns task-aware context, explains why files were selected, reports local repository intelligence, remembers evidence-backed facts, and refreshes automatically when saved source changes.

Use a clean, disposable clone of a public repository. The commands below use RepoMind itself as the demo repository, but the same flow works in any non-proprietary codebase that is safe to show on screen. RepoMind commands were confirmed against the current CLI; Git status and the file edit are only demo support commands.

## Demo Setup

Open a terminal at the repository root:

```powershell
cd C:\Users\raazl\OneDrive\Documents\Repomind
```

Use a readable terminal font, keep the window wide, and avoid showing environment files, credentials, customer data, private remotes, or proprietary paths. If the repository is not public, use a synthetic or open-source clone with similar structure.

## 60-Second Flow

### 0-5s: Real Repository

Command:

```powershell
git status --short
```

Presenter says: "This is a normal working repository, not a prepared snippet. RepoMind reads the local working tree."

Visible on screen: the repository path and normal Git status. Do not dwell on exact status lines.

Fallback if output is too long: clear the terminal or skip the command and keep the prompt visible at the repository root.

### 5-12s: Initialize

Command:

```powershell
repomind init
```

Presenter says: "First, RepoMind builds a local index for this repository."

Visible on screen: RepoMind's initialization summary from the CLI. Do not quote or promise specific file counts.

Fallback if output is too long: say "The important part is that the index is initialized locally," then move on.

### 12-18s: Status

Command:

```powershell
repomind status
```

Presenter says: "Status shows whether the index is healthy and whether saved files have changed."

Visible on screen: repository path, indexed file and symbol counts, change counts, memory counts, and last refresh fields as reported by the CLI.

Fallback if output is too long: rerun later with a taller terminal; do not summarize made-up numbers.

### 18-30s: Task Context

Command:

```powershell
repomind context "add JSON output to repository intelligence stats"
```

Presenter says: "Now I ask a real coding question. RepoMind returns the files, symbols, tests, and relationships most likely to matter for that task."

Visible on screen: a ContextPack with task-specific sections such as relevant files, important symbols, relationships, tests, metrics, and freshness.

Fallback if output is too long: use the first screenful only and say "This is enough for an agent or developer to start in the right files."

### 30-38s: Explain Retrieval

Command:

```powershell
repomind context "add JSON output to repository intelligence stats" --explain
```

Presenter says: "The same task can include ranking explanations, so the selection is inspectable instead of mysterious."

Visible on screen: the same kind of ContextPack with explanation fields or reason text for selected files.

Fallback if output is too long: point at one visible explanation and move on.

### 38-44s: Stats

Command:

```powershell
repomind stats
```

Presenter says: "Stats reports local repository intelligence metrics for observability. These are local estimates, not billing or benchmark claims."

Visible on screen: indexed files, symbols, routes, relationships, memory counts, freshness, and local token-estimation method if present.

Fallback if output is too long: keep only the top of the stats output visible.

### 44-49s: Memory

Command:

```powershell
repomind memory list
```

Presenter says: "RepoMind also keeps bounded repository memory with evidence and freshness state."

Visible on screen: memory records or an empty memory list plus counts. Either result is acceptable.

Fallback if output is too long: use `repomind memory list --limit 5`.

### 49-60s: Automatic Freshness

Modify and save a source file in the disposable demo clone. Do not run `repomind refresh` or `repomind watch`.

Example source edit:

```powershell
Set-Content -Path repomind\demo_freshness_probe.py -Value 'def demo_freshness_probe() -> str:', '    return "fresh"'
```

Command:

```powershell
repomind symbol demo_freshness_probe
```

Presenter says: "I saved a new symbol and did not refresh or start a watcher. A read command checks freshness first, updates what changed, and then answers from the current index."

Visible on screen: RepoMind returns the newly saved `demo_freshness_probe` symbol, or shows freshness metadata indicating the index was refreshed before the read.

Fallback if output is too long: query the exact symbol name as shown above instead of a broad context query.

After the demo, remove the disposable file before committing any work:

```powershell
Remove-Item -Path repomind\demo_freshness_probe.py
```

## Presenter Guardrails

- Do not invent output. Let the terminal provide the numbers and paths.
- Do not claim benchmark results, cost reductions, or universal speedups.
- Do not show proprietary source, secrets, customer names, internal remotes, `.env` files, private tickets, or private branches.
- Do not run `repomind refresh` or `repomind watch` during the freshness segment.
- Keep the story simple: index once, ask for task context, inspect why it was selected, check stats and memory, then save a source change and query it immediately.

## Command-Only Version

See `scripts/demo_commands.txt` for a copy/paste command list.
