from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

from repomind.models import GitInfo


def passive_git_command(root: Path, args: Sequence[str]) -> list[str]:
    command = [
        "git", "-C", str(root),
        "-c", "core.fsmonitor=false",
        "-c", f"core.hooksPath={os.devnull}",
        "-c", "core.untrackedCache=false",
    ]
    if args and args[0] == "diff":
        return [*command, "diff", "--no-ext-diff", "--no-textconv", *args[1:]]
    return [*command, *args]


def passive_git_environment() -> dict[str, str]:
    # Inherited Git overrides can redirect inspection or inject configuration.
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
        GIT_PAGER="cat",
    )
    return environment


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        passive_git_command(root, args),
        env=passive_git_environment(),
        stdin=subprocess.DEVNULL,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def inspect_git(root: Path) -> GitInfo:
    try:
        inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitInfo(False, error=str(exc))
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitInfo(False, error="not a Git work tree")
    try:
        branch_result = _run_git(root, ["branch", "--show-current"])
        head_result = _run_git(root, ["rev-parse", "HEAD"])
        status_result = _run_git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return GitInfo(True, error=f"Unable to inspect Git state: {type(exc).__name__}")
    if status_result.returncode:
        return GitInfo(True, error="Unable to inspect Git state: status failed")
    changed: list[str] = []
    if status_result.returncode == 0:
        entries = status_result.stdout.split("\0")
        index = 0
        while index < len(entries):
            entry = entries[index]
            if not entry:
                index += 1
                continue
            status = entry[:2]
            path = entry[3:]
            if "R" in status or "C" in status:
                index += 1
                if index < len(entries) and entries[index]:
                    path = entries[index]
            if path and not path.startswith(".repomind/"):
                changed.append(path)
            index += 1
    return GitInfo(
        True,
        branch_result.stdout.strip() or None,
        head_result.stdout.strip() if head_result.returncode == 0 else None,
        tuple(sorted(set(changed))),
    )
