from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any

from repomind.config import Config
from repomind.database import SCHEMA_VERSION, IndexDatabase
from repomind.errors import RepoMindError
from repomind.parsers import ParserRegistry
from repomind.watcher import watchdog_available


def run_doctor(root: Path) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str, action: str = "none") -> None:
        checks.append({"check": name, "status": status, "detail": detail, "action": action})

    if root.is_dir() and os.access(root, os.R_OK):
        add("repository", "ok", f"readable: {root}")
    else:
        add("repository", "error", f"not readable: {root}", "Check path and permissions")
    try:
        Config.load(root)
        add("configuration", "ok", ".repomind.toml is valid or absent")
    except RepoMindError as exc:
        add("configuration", "error", str(exc), "Fix .repomind.toml")
    try:
        with IndexDatabase(root) as database:
            integrity = database.integrity_check()
            add(
                "database integrity",
                "ok" if integrity == "ok" else "error",
                integrity,
                "Reinitialize with repomind init --force" if integrity != "ok" else "none",
            )
            version = database.get_meta("schema_version")
            add(
                "index schema",
                "ok" if version == str(SCHEMA_VERSION) else "error",
                f"found {version}; expected {SCHEMA_VERSION}",
            )
    except RepoMindError as exc:
        add("index", "error", str(exc), "Run: repomind init")
    registry = ParserRegistry()
    add("parsers", "ok", "built-in: " + ", ".join(registry.supported_languages))
    tree_sitter_installed = importlib.util.find_spec("tree_sitter") is not None
    tree_sitter_languages = registry.tree_sitter_languages
    add(
        "tree-sitter",
        "ok" if tree_sitter_languages else "info",
        (
            "active for: " + ", ".join(tree_sitter_languages)
            if tree_sitter_languages
            else (
                "core installed but compatible JS/TS grammars unavailable; built-in parsers are active"
                if tree_sitter_installed
                else "not installed; built-in deterministic parsers are active"
            )
        ),
        "Optional: pip install 'repomind[treesitter]'" if not tree_sitter_languages else "none",
    )
    native_watch = watchdog_available()
    add(
        "watcher",
        "ok" if native_watch else "warning",
        "event-driven watchdog backend" if native_watch else "event-driven backend not installed",
        "Install: pip install 'repomind[watch]'" if not native_watch else "none",
    )
    git = shutil.which("git")
    add(
        "git",
        "ok" if git else "info",
        git or "Git executable not found",
        "Install Git for branch/change-aware ranking" if not git else "none",
    )
    overall = "healthy" if not any(item["status"] == "error" for item in checks) else "unhealthy"
    return {"index_health": overall, "checks": checks}
