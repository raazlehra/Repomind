from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from repomind.config import Config
from repomind.database import IndexDatabase
from repomind.indexer import Indexer, IndexResult


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    status: str
    was_stale: bool
    created: int
    modified: int
    deleted: int
    renamed: int
    metadata_only: int
    refreshed: int
    parse_errors: int
    indexed_parse_errors: int
    checked_files: int
    hashed_files: int
    duration_seconds: float

    @property
    def warning(self) -> str | None:
        if self.status != "partial":
            return None
        noun = "file has" if self.indexed_parse_errors == 1 else "files have"
        return (
            f"Automatic freshness is current but partial: "
            f"{self.indexed_parse_errors} indexed {noun} parser errors."
        )

    def as_dict(self) -> dict[str, int | float | bool | str]:
        data: dict[str, int | float | bool | str] = {
            "status": self.status,
            "was_stale": self.was_stale,
            "created": self.created,
            "modified": self.modified,
            "deleted": self.deleted,
            "renamed": self.renamed,
            "metadata_only": self.metadata_only,
            "refreshed": self.refreshed,
            "parse_errors": self.parse_errors,
            "indexed_parse_errors": self.indexed_parse_errors,
            "checked_files": self.checked_files,
            "hashed_files": self.hashed_files,
            "duration_seconds": round(self.duration_seconds, 4),
        }
        if self.warning:
            data["warning"] = self.warning
        return data


def ensure_index_fresh(repository: str | Path, config: Config | None = None) -> FreshnessResult:
    """Refresh the persistent index only when the saved working tree is stale."""
    root = Path(repository).resolve()
    loaded_config = config or Config.load(root)
    indexer = Indexer(root, loaded_config)
    start = time.perf_counter()
    with IndexDatabase(root) as database:
        detection = indexer.detect_changes(database)

    changes = detection.changes
    was_stale = bool(changes.total or detection.metadata_only)
    result: IndexResult | None = None
    if was_stale:
        result = indexer.refresh()
        changes = result.changes

    indexed_parse_errors = _indexed_parse_error_count(root)
    duration = time.perf_counter() - start
    status = _freshness_status(was_stale, indexed_parse_errors)
    return FreshnessResult(
        status=status,
        was_stale=was_stale,
        created=len(changes.created),
        modified=len(changes.modified),
        deleted=len(changes.deleted),
        renamed=len(changes.renamed),
        metadata_only=len(detection.metadata_only),
        refreshed=result.parsed_files if result is not None else 0,
        parse_errors=result.parse_errors if result is not None else 0,
        indexed_parse_errors=indexed_parse_errors,
        checked_files=len(detection.scanned),
        hashed_files=len(detection.hashes),
        duration_seconds=duration,
    )


def _indexed_parse_error_count(root: Path) -> int:
    with IndexDatabase(root) as database:
        row = database.connection.execute(
            "SELECT COUNT(*) FROM files WHERE parse_error IS NOT NULL"
        ).fetchone()
    return int(row[0]) if row else 0


def _freshness_status(was_stale: bool, indexed_parse_errors: int) -> str:
    if indexed_parse_errors:
        return "partial"
    if was_stale:
        return "refreshed"
    return "already_fresh"
