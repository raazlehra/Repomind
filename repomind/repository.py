from __future__ import annotations

from pathlib import Path

from repomind.database import INDEX_DIRECTORY, INDEX_FILENAME
from repomind.errors import NotIndexedError, RepoMindError


def resolve_repository(path: Path, require_index: bool = True) -> Path:
    candidate = path.expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    if not candidate.is_dir():
        raise RepoMindError(f"Repository path is not accessible: {candidate}")
    if not require_index:
        return candidate
    for directory in (candidate, *candidate.parents):
        if (directory / INDEX_DIRECTORY / INDEX_FILENAME).is_file():
            return directory
    raise NotIndexedError()
