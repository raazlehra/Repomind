from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from repomind.utils import approximate_tokens

TOKEN_ESTIMATION_METHOD = "character-based heuristic; estimates are not provider billing tokens"


@dataclass(slots=True)
class ContextBudget:
    requested_tokens: int
    approximate_tokens: int = 0
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_tokens": self.requested_tokens,
            "approximate_tokens": self.approximate_tokens,
            "truncated": self.truncated,
            "method": TOKEN_ESTIMATION_METHOD,
        }


@dataclass(slots=True)
class ContextMetrics:
    indexed_files: int
    repository_text_bytes: int
    candidate_files_considered: int
    files_returned: int
    selected_file_bytes: int
    retrieval_latency_seconds: float
    context_output_bytes: int = 0
    estimated_context_tokens: int = 0
    budget_used_percent: float = 0.0
    truncated: bool = False

    @property
    def estimated_repository_tokens(self) -> int:
        return estimate_tokens_from_bytes(self.repository_text_bytes)

    @property
    def file_reduction_percent(self) -> float:
        return bounded_reduction(self.indexed_files, self.files_returned)

    @property
    def context_volume_reduction_percent(self) -> float:
        return bounded_reduction(self.repository_text_bytes, self.context_output_bytes)

    def update_rendered(self, rendered: str, requested_budget: int, truncated: bool) -> None:
        self.context_output_bytes = len(rendered.encode("utf-8"))
        self.estimated_context_tokens = approximate_tokens(rendered)
        self.budget_used_percent = bounded_percent(
            self.estimated_context_tokens, requested_budget
        )
        self.truncated = truncated

    def as_dict(self) -> dict[str, Any]:
        return {
            "repository": {
                "indexed_files": self.indexed_files,
                "repository_text_bytes": self.repository_text_bytes,
                "estimated_repository_tokens": self.estimated_repository_tokens,
                "token_estimation_method": TOKEN_ESTIMATION_METHOD,
            },
            "task_context": {
                "candidate_files_considered": self.candidate_files_considered,
                "files_returned": self.files_returned,
                "selected_file_bytes": self.selected_file_bytes,
                "context_output_bytes": self.context_output_bytes,
                "estimated_context_tokens": self.estimated_context_tokens,
                "budget_used_percent": self.budget_used_percent,
                "truncated": self.truncated,
            },
            "reduction": {
                "file_reduction_percent": self.file_reduction_percent,
                "context_volume_reduction_percent": self.context_volume_reduction_percent,
            },
            "performance": {
                "retrieval_latency_seconds": round(self.retrieval_latency_seconds, 6),
            },
        }


@dataclass(slots=True)
class ContextPack:
    task: str
    context_level: int
    intent: list[str]
    architecture: list[dict[str, Any]]
    memory: list[dict[str, Any]]
    relevant_files: list[dict[str, Any]]
    important_symbols: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    likely_modification_area: list[str]
    budget: ContextBudget
    metrics: ContextMetrics
    primary_files: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    relevant_tests: list[str] = field(default_factory=list)
    routes: list[dict[str, Any]] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)
    nearby_dependencies: list[dict[str, Any]] = field(default_factory=list)
    snippets: list[dict[str, Any]] = field(default_factory=list)
    source_authority: str = (
        "RepoMind summaries guide discovery; inspect actual source before modification."
    )

    def as_dict(self, *, explain: bool = False) -> dict[str, Any]:
        files = []
        for item in self.relevant_files:
            record = dict(item)
            if not explain:
                record.pop("explanations", None)
                record.pop("score_breakdown", None)
            files.append(record)
        output: dict[str, Any] = {
            "task": self.task,
            "context_level": self.context_level,
            "intent": {"labels": self.intent},
            "architecture": self.architecture,
            "memory": self.memory,
            "relevant_files": files,
            "primary_files": self.primary_files,
            "related_files": self.related_files,
            "relevant_tests": self.relevant_tests,
            "routes": self.routes,
            "important_symbols": self.important_symbols,
            "relationships": self.relationships,
            "likely_modification_area": self.likely_modification_area,
            "source_authority": self.source_authority,
            "budget": self.budget.as_dict(),
            "metrics": self.metrics.as_dict(),
        }
        if self.imports:
            output["imports"] = self.imports
        if self.nearby_dependencies:
            output["nearby_dependencies"] = self.nearby_dependencies
        if self.snippets:
            output["snippets"] = self.snippets
        return output


def estimate_tokens_from_bytes(byte_count: int) -> int:
    return max(0, (max(byte_count, 0) + 3) // 4)


def bounded_percent(numerator: int | float, denominator: int | float) -> float:
    if denominator <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (float(numerator) / float(denominator)) * 100.0)), 2)


def bounded_reduction(total: int | float, selected: int | float) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, (1.0 - float(selected) / float(total)) * 100.0)), 2)
