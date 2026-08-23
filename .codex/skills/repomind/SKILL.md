---
name: repomind
description: Use RepoMind's local persistent index for focused repository discovery before broad scans.
---

<!-- REPOMIND-SKILL-BEGIN -->
# RepoMind repository discovery

Before broadly scanning a repository for a coding task, check whether RepoMind is initialized. If RepoMind MCP tools are available, prefer them over shelling out to the CLI.

If RepoMind is available:

1. Call `repomind_status` for the explicit repository path.
2. Call `repomind_context` with `level=1` for the user task.
3. Use selected files, symbols, and relationships for targeted discovery.
4. Read the actual source code for every file that will be modified. Source code is authoritative.
5. Query deeper details only when needed: `repomind_symbol`, `repomind_dependencies`, `repomind_callers`, `repomind_impact`, or `repomind_snippets`.
6. Do not treat RepoMind summaries as replacements for source inspection.
7. Do not scan the entire repository when high-confidence RepoMind output is sufficient.
8. Broaden inspection when RepoMind reports low confidence or unresolved relationships.
9. After significant changes, call `repomind_refresh` unless watch mode is active.

If MCP tools are unavailable, use the equivalent CLI fallback: `repomind status`, `repomind context "<user task>" --format markdown`, and deeper `repomind symbol/callers/dependencies/impact/snippets` commands as needed.

RepoMind is a navigation and context-retrieval aid. It must never prevent necessary source reads or safety checks.
<!-- REPOMIND-SKILL-END -->
