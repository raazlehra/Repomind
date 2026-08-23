from __future__ import annotations

import os
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from repomind.architecture import detect_architecture
from repomind.config import Config
from repomind.database import INDEX_DIRECTORY, INDEX_FILENAME, IndexDatabase, utc_now
from repomind.errors import RepoMindError
from repomind.git import inspect_git
from repomind.graph import rebuild_dependency_graph
from repomind.models import ChangeSet, ScannedFile
from repomind.parsers import ParserRegistry
from repomind.scanner import RepositoryScanner
from repomind.utils import hash_file

ProgressCallback = Callable[[int, str], None]


@dataclass(slots=True)
class Detection:
    changes: ChangeSet
    scanned: dict[str, ScannedFile]
    hashes: dict[str, str] = field(default_factory=dict)
    metadata_only: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IndexResult:
    changes: ChangeSet
    indexed_files: int
    parsed_files: int
    duration_seconds: float
    index_bytes: int
    parse_errors: int


class Indexer:
    def __init__(self, root: Path, config: Config | None = None) -> None:
        self.root = root.resolve()
        self.config = config or Config.load(self.root)
        self.scanner = RepositoryScanner(self.root, self.config)
        self.parsers = ParserRegistry()

    def initialize(
        self, force: bool = False, progress: ProgressCallback | None = None
    ) -> IndexResult:
        index_path = self.root / INDEX_DIRECTORY / INDEX_FILENAME
        if index_path.exists() and not force:
            raise RepoMindError("Repository is already indexed. Run: repomind refresh")
        if force:
            for suffix in ("", "-wal", "-shm"):
                candidate = Path(str(index_path) + suffix)
                if candidate.exists():
                    candidate.unlink()
        start = time.perf_counter()
        scanned = list(self.scanner.scan())
        total = len(scanned)
        parse_errors = 0
        with IndexDatabase(self.root, create=True) as database, database.transaction():
            for index, item in enumerate(scanned, start=1):
                if progress:
                    progress(index, item.path)
                result = self.parsers.parse(item.absolute_path, item.path, item.language)
                if result.parse_error:
                    parse_errors += 1
                database.upsert_file(item, hash_file(item.absolute_path), result)
            rebuild_dependency_graph(database)
            database.replace_architecture(
                detect_architecture(self.root, (item.path for item in scanned))
            )
            self._record_git(database)
            database.set_meta("last_refresh_at", utc_now())
            database.set_meta("last_refresh_parsed", str(total))
        duration = time.perf_counter() - start
        created = tuple(item.path for item in scanned)
        return IndexResult(
            ChangeSet(created=created),
            total,
            total,
            duration,
            _index_size(index_path),
            parse_errors,
        )

    def detect_changes(self, database: IndexDatabase) -> Detection:
        scanned = {item.path: item for item in self.scanner.scan()}
        indexed = database.all_files()
        created = set(scanned) - set(indexed)
        deleted = set(indexed) - set(scanned)
        modified: set[str] = set()
        metadata_only: list[str] = []
        hashes: dict[str, str] = {}
        for path in set(scanned) & set(indexed):
            current = scanned[path]
            previous = indexed[path]
            if current.size == int(previous["size"]) and current.mtime_ns == int(
                previous["mtime_ns"]
            ):
                continue
            digest = hash_file(current.absolute_path)
            hashes[path] = digest
            if digest != str(previous["content_hash"]):
                modified.add(path)
            else:
                metadata_only.append(path)

        # A delete/create pair with the same content hash is treated as a rename.
        deleted_by_hash: dict[str, list[str]] = {}
        for path in deleted:
            deleted_by_hash.setdefault(str(indexed[path]["content_hash"]), []).append(path)
        renames: list[tuple[str, str]] = []
        for new_path in sorted(created):
            new_digest = hashes.get(new_path)
            if new_digest is None:
                new_digest = hash_file(scanned[new_path].absolute_path)
                hashes[new_path] = new_digest
            old_paths = deleted_by_hash.get(new_digest, [])
            if len(old_paths) == 1:
                old_path = old_paths.pop()
                renames.append((old_path, new_path))
                deleted.remove(old_path)
                created.remove(new_path)

        return Detection(
            ChangeSet(
                created=tuple(sorted(created)),
                modified=tuple(sorted(modified)),
                deleted=tuple(sorted(deleted)),
                renamed=tuple(sorted(renames)),
            ),
            scanned,
            hashes,
            tuple(sorted(metadata_only)),
        )

    def refresh(self, progress: ProgressCallback | None = None) -> IndexResult:
        start = time.perf_counter()
        parse_errors = 0
        with IndexDatabase(self.root) as database:
            detection = self.detect_changes(database)
            changes = detection.changes
            to_parse = [*changes.created, *changes.modified]
            with database.transaction():
                for old, new in changes.renamed:
                    database.rename_file(old, detection.scanned[new])
                database.delete_files(changes.deleted)
                for index, path in enumerate(to_parse, start=1):
                    if progress:
                        progress(index, path)
                    item = detection.scanned[path]
                    result = self.parsers.parse(item.absolute_path, item.path, item.language)
                    if result.parse_error:
                        parse_errors += 1
                    digest = detection.hashes.get(path) or hash_file(item.absolute_path)
                    database.upsert_file(item, digest, result)
                for path in detection.metadata_only:
                    item = detection.scanned[path]
                    database.connection.execute(
                        "UPDATE files SET size=?, mtime_ns=?, indexed_at=? WHERE path=?",
                        (item.size, item.mtime_ns, utc_now(), path),
                    )
                # Resolution is rebuilt from compact stored imports/references, never by reparsing unchanged files.
                if changes.total:
                    rebuild_dependency_graph(database)
                database.replace_architecture(detect_architecture(self.root, detection.scanned))
                self._record_git(database)
                database.set_meta("last_refresh_at", utc_now())
                database.set_meta("last_refresh_parsed", str(len(to_parse)))
            counts = database.counts()
        duration = time.perf_counter() - start
        return IndexResult(
            changes,
            counts["files"],
            len(to_parse),
            duration,
            _index_size(self.root / INDEX_DIRECTORY / INDEX_FILENAME),
            parse_errors,
        )

    @staticmethod
    def _record_git(database: IndexDatabase) -> None:
        git = inspect_git(database.root)
        database.set_git_state(
            {
                "available": git.available,
                "branch": git.branch,
                "head": git.head,
                "changed_files": list(git.changed_files),
                "error": git.error,
            }
        )


def _index_size(path: Path) -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        with suppress(OSError):
            total += os.path.getsize(candidate)
    return total
