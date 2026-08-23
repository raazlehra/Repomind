"""Minimal type stubs for watchdog used only for static analysis in this repo.

These stubs are intentionally small and mirror only the symbols `repomind`
references so `mypy` can type-check without requiring the optional runtime
dependency to be installed during static checks.
"""

from typing import Any

__all__ = ["events", "observers"]
