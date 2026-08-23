from __future__ import annotations

from pathlib import Path
from typing import Protocol

from repomind.models import ParseResult


class StructuralParser(Protocol):
    languages: frozenset[str]

    def parse(self, path: Path, relative_path: str, source: str) -> ParseResult:
        """Extract compact structure without executing repository code."""
        ...
