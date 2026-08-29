from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True, slots=True)
class ScannedFile:
    path: str
    absolute_path: Path
    size: int
    mtime_ns: int
    language: str
    purpose: str
    is_test: bool


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    qualified_name: str
    kind: str
    signature: str
    line_start: int
    line_end: int
    exported: bool = False
    parent: str | None = None
    documentation: str | None = None


@dataclass(frozen=True, slots=True)
class ImportRecord:
    module: str
    name: str | None
    alias: str | None
    line: int
    is_relative: bool = False


@dataclass(frozen=True, slots=True)
class EdgeCandidate:
    kind: str
    source_symbol: str | None
    target: str
    line: int | None
    confidence: float
    evidence: str


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    path: str
    handler: str | None
    line: int
    confidence: float


@dataclass(slots=True)
class ParseResult:
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)
    edges: list[EdgeCandidate] = field(default_factory=list)
    routes: list[Route] = field(default_factory=list)
    summary: str = ""
    parse_error: str | None = None


@dataclass(frozen=True, slots=True)
class ChangeSet:
    created: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    renamed: tuple[tuple[str, str], ...] = ()

    @property
    def total(self) -> int:
        return len(self.created) + len(self.modified) + len(self.deleted) + len(self.renamed)


@dataclass(frozen=True, slots=True)
class ArchitectureFact:
    category: str
    name: str
    evidence: str
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: int | None
    key: str
    value: str
    category: str
    confidence: float
    source_type: str
    source_paths: tuple[str, ...]
    source_symbols: tuple[str, ...] = ()
    evidence_hash: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_verified_at: str = ""
    status: str = "valid"


@dataclass(slots=True)
class RankedFile:
    path: str
    score: float
    reasons: list[str]
    purpose: str
    language: str
    symbols: list[dict[str, Any]] = field(default_factory=list)
    score_components: dict[str, float] = field(default_factory=dict)
    explanations: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class GitInfo:
    available: bool
    branch: str | None = None
    head: str | None = None
    changed_files: tuple[str, ...] = ()
    error: str | None = None
