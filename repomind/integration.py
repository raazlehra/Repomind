from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SKILL_BEGIN = "<!-- REPOMIND-SKILL-BEGIN -->"
SKILL_END = "<!-- REPOMIND-SKILL-END -->"
AGENTS_BEGIN = "<!-- REPOMIND-INSTRUCTIONS-BEGIN -->"
AGENTS_END = "<!-- REPOMIND-INSTRUCTIONS-END -->"

SKILL_CONTENT = f"""---
name: repomind
description: Use RepoMind's local persistent index for focused repository discovery before broad scans.
---

{SKILL_BEGIN}
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
{SKILL_END}
"""

AGENTS_SECTION = f"""{AGENTS_BEGIN}
## RepoMind

Use RepoMind for initial codebase discovery and task-specific context retrieval before broad repository scans. When MCP tools are available, start with `repomind_status`, then `repomind_context` at level 1, and query deeper tools only as needed. Always inspect actual source files before modifying them. If MCP is unavailable, use the equivalent `repomind status` and `repomind context "<task>"` CLI flow. Refresh RepoMind after significant changes when watch mode is not active.
{AGENTS_END}"""


@dataclass(frozen=True, slots=True)
class InstallResult:
    skill_path: str
    skill_action: str
    agents_path: str
    agents_action: str


def install_codex(root: Path) -> InstallResult:
    skill_path = root / ".codex" / "skills" / "repomind" / "SKILL.md"
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    if not skill_path.exists():
        skill_path.write_text(SKILL_CONTENT, encoding="utf-8")
        skill_action = "created"
    else:
        existing_skill = skill_path.read_text(encoding="utf-8", errors="replace")
        if SKILL_BEGIN in existing_skill and SKILL_END in existing_skill:
            if existing_skill == SKILL_CONTENT:
                skill_action = "unchanged"
            else:
                skill_path.write_text(SKILL_CONTENT, encoding="utf-8")
                skill_action = "updated RepoMind-managed skill"
        else:
            skill_action = "preserved existing unmanaged skill"

    agents_path = root / "AGENTS.md"
    if agents_path.exists():
        existing = agents_path.read_text(encoding="utf-8", errors="replace")
        if AGENTS_BEGIN in existing and AGENTS_END in existing:
            agents_action = "unchanged"
        else:
            separator = (
                ""
                if not existing or existing.endswith("\n\n")
                else ("\n" if existing.endswith("\n") else "\n\n")
            )
            agents_path.write_text(existing + separator + AGENTS_SECTION + "\n", encoding="utf-8")
            agents_action = "appended"
    else:
        agents_path.write_text("# Agent instructions\n\n" + AGENTS_SECTION + "\n", encoding="utf-8")
        agents_action = "created"
    return InstallResult(
        skill_path.relative_to(root).as_posix(),
        skill_action,
        agents_path.relative_to(root).as_posix(),
        agents_action,
    )
