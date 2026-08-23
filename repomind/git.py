from __future__ import annotations

import subprocess
from pathlib import Path

from repomind.models import GitInfo


def _run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )


def inspect_git(root: Path) -> GitInfo:
    try:
        inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return GitInfo(False, error=str(exc))
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitInfo(False, error="not a Git work tree")
    branch_result = _run_git(root, ["branch", "--show-current"])
    head_result = _run_git(root, ["rev-parse", "HEAD"])
    status_result = _run_git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
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
