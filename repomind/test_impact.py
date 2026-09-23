from __future__ import annotations

import json
import math
import queue
import re
import shlex
import subprocess
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal

from repomind.database import IndexDatabase
from repomind.git import _run_git
from repomind.scanner import classify_file, is_executable_test_path

TEST_IMPACT_SCHEMA_VERSION = "repomind.test-impact.v1"
MAX_TEST_SOURCE_BYTES = 500_000

OutputMode = Literal["compact_json", "pretty_json"]

Confidence = Literal["high", "medium", "low"]
_CONFIDENCE_RANK: dict[str, int] = {"low": 1, "medium": 2, "high": 3}

@dataclass(frozen=True, slots=True)
class TestImpactLimits:
    max_graph_nodes: int = 500
    max_graph_edges: int = 2_000
    max_impacted_areas: int = 100
    max_tests: int = 50
    max_commands: int = 20
    max_evidence_per_result: int = 10
    max_output_bytes: int = 200_000
    max_changed_files: int = 200
    max_path_length: int = 1_000
    max_test_candidates_scanned: int = 5_000
    max_migration_candidates_scanned: int = 1_000
    max_route_candidates_scanned: int = 5_000
    max_direct_edges_per_file: int = 500
    max_indirect_edges_per_file: int = 500
    max_impacted_candidates: int = 1_000
    max_relevant_test_candidates: int = 500
    max_evidence_candidates: int = 5_000
    max_evidence_candidates_scanned: int = 20_000
    max_command_candidates: int = 100
    max_project_files_scanned: int = 5_000
    max_git_output_bytes: int = 1_000_000
    max_git_stderr_bytes: int = 16_384
    max_analysis_seconds: float = 10.0

    def __post_init__(self) -> None:
        hard_caps = {
            "max_graph_nodes": 10_000,
            "max_graph_edges": 50_000,
            "max_impacted_areas": 1_000,
            "max_tests": 500,
            "max_commands": 100,
            "max_evidence_per_result": 50,
            "max_output_bytes": 2_000_000,
            "max_changed_files": 1_000,
            "max_path_length": 4_096,
            "max_test_candidates_scanned": 20_000,
            "max_migration_candidates_scanned": 5_000,
            "max_route_candidates_scanned": 20_000,
            "max_direct_edges_per_file": 2_000,
            "max_indirect_edges_per_file": 5_000,
            "max_impacted_candidates": 5_000,
            "max_relevant_test_candidates": 2_000,
            "max_evidence_candidates": 20_000,
            "max_evidence_candidates_scanned": 100_000,
            "max_command_candidates": 500,
            "max_project_files_scanned": 20_000,
            "max_git_output_bytes": 8_000_000,
            "max_git_stderr_bytes": 65_536,
        }
        for name, cap in hard_caps.items():
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
            if value > cap:
                raise ValueError(f"{name} must be at most {cap}")
        if self.max_output_bytes < 4_096:
            raise ValueError("max_output_bytes must be at least 4096")
        duration = self.max_analysis_seconds
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ValueError("max_analysis_seconds must be a finite number")
        if not math.isfinite(float(duration)):
            raise ValueError("max_analysis_seconds must be a finite number")
        if duration <= 0 or duration > 60:
            raise ValueError("max_analysis_seconds must be greater than 0 and at most 60")


@dataclass(slots=True)
class _GraphBudget:
    nodes_visited: int = 0
    edges_visited: int = 0
    truncated: bool = False
    reasons: set[str] | None = None

    def mark(self, reason: str) -> None:
        self.truncated = True
        if self.reasons is None:
            self.reasons = set()
        self.reasons.add(reason)


@dataclass(slots=True)
class _AnalysisBudget:
    limits: TestImpactLimits
    started: float
    processed: dict[str, int]
    reasons: dict[str, int | float]
    exhausted_by: dict[str, str]

    @classmethod
    def start(cls, limits: TestImpactLimits) -> _AnalysisBudget:
        return cls(limits, time.perf_counter(), {}, {}, {})

    def consume(self, name: str, limit_name: str) -> bool:
        if not self.within_time():
            return False
        limit = int(getattr(self.limits, limit_name))
        current = self.processed.get(name, 0)
        if current >= limit:
            self.reasons.setdefault(limit_name, limit)
            return False
        self.processed[name] = current + 1
        return True

    def within_time(self) -> bool:
        if time.perf_counter() - self.started < float(self.limits.max_analysis_seconds):
            return True
        self.reasons.setdefault("max_analysis_seconds", self.limits.max_analysis_seconds)
        return False

    def mark(self, limit_name: str) -> None:
        self.reasons.setdefault(limit_name, getattr(self.limits, limit_name))

    def consume_shared(
        self,
        total_name: str,
        family_name: str,
        limit_name: str,
    ) -> bool:
        if not self.within_time():
            return False
        limit = int(getattr(self.limits, limit_name))
        current = self.processed.get(total_name, 0)
        if current >= limit:
            self.reasons.setdefault(limit_name, limit)
            self.exhausted_by.setdefault(limit_name, family_name)
            return False
        self.processed[total_name] = current + 1
        family_key = f"{total_name}:{family_name}"
        self.processed[family_key] = self.processed.get(family_key, 0) + 1
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "processed": dict(sorted(self.processed.items())),
            "truncated": bool(self.reasons),
            "reasons": [
                {"limit": name, "value": value}
                for name, value in sorted(self.reasons.items())
            ],
            "exhausted_by": dict(sorted(self.exhausted_by.items())),
        }


@dataclass(frozen=True, slots=True)
class _EvidenceEntry:
    priority: int
    test_path: str
    key: str
    value: dict[str, Any]


@dataclass(slots=True)
class _EvidenceStore:
    limits: TestImpactLimits
    budget: _AnalysisBudget
    rows: dict[tuple[str, str], _EvidenceEntry]
    per_test_scanned: dict[str, int]
    scanned: int = 0
    result_truncated: bool = False
    scan_truncated: bool = False

    @classmethod
    def start(
        cls, limits: TestImpactLimits, budget: _AnalysisBudget
    ) -> _EvidenceStore:
        return cls(limits, budget, {}, {})

    @property
    def exhausted(self) -> bool:
        return self.scan_truncated

    def consider(self, test_path: str, evidence: dict[str, Any]) -> bool:
        if self.scan_truncated:
            return False
        if not self.budget.consume(
            "evidence_candidates_scanned", "max_evidence_candidates_scanned"
        ):
            self.scan_truncated = True
            return False
        self.scanned += 1
        self.per_test_scanned[test_path] = self.per_test_scanned.get(test_path, 0) + 1
        key = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        identity = (test_path, key)
        if identity in self.rows:
            return True
        entry = _EvidenceEntry(
            _evidence_priority(evidence),
            test_path,
            key,
            evidence,
        )
        ordered = sorted(
            [*self.rows.values(), entry],
            key=lambda item: (item.priority, item.test_path, item.key),
        )
        retained: dict[tuple[str, str], _EvidenceEntry] = {}
        per_test: dict[str, int] = {}
        per_result_truncated = False
        global_truncated = False
        for candidate in ordered:
            if per_test.get(candidate.test_path, 0) >= self.limits.max_evidence_per_result:
                per_result_truncated = True
                continue
            if len(retained) >= self.limits.max_evidence_candidates:
                global_truncated = True
                break
            retained[(candidate.test_path, candidate.key)] = candidate
            per_test[candidate.test_path] = per_test.get(candidate.test_path, 0) + 1
        if per_result_truncated:
            self.budget.mark("max_evidence_per_result")
        if global_truncated:
            self.budget.mark("max_evidence_candidates")
        self.result_truncated = (
            self.result_truncated or per_result_truncated or global_truncated
        )
        self.rows = retained
        return True

    def for_test(self, test_path: str) -> list[dict[str, Any]]:
        return [
            entry.value
            for entry in sorted(
                (
                    item
                    for item in self.rows.values()
                    if item.test_path == test_path
                ),
                key=lambda item: (item.priority, item.key),
            )
        ]


def _evidence_priority(evidence: dict[str, Any]) -> int:
    kind = str(evidence.get("kind") or "")
    if kind == "dependency":
        return 0
    if kind == "changed-test-file":
        return 1
    if kind in {"migration-suite", "route-literal", "route-api-client", "route-e2e"}:
        return 2
    if kind == "dependency-reachability":
        return 3
    return 4


def analyze_test_impact(
    database: IndexDatabase,
    changed_files: Iterable[str] | None = None,
    *,
    base: str | None = None,
    limits: TestImpactLimits | None = None,
    output_mode: OutputMode = "compact_json",
    additional_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded, analysis-only test recommendation report."""
    limits = limits or TestImpactLimits()
    budget = _AnalysisBudget.start(limits)
    selected, change_source, selection_warnings, selection_stats = _select_changes(
        database.root, changed_files, base, limits, budget
    )
    changed = [_changed_file_record(database, path) for path in selected]
    graph_stats = _GraphBudget()
    tests, test_stats = _relevant_tests(
        database, changed, limits, graph_stats, budget
    )
    impacted_areas, area_stats, graph_stats = _impacted_areas(
        database, changed, limits, graph_stats, budget
    )
    uncovered = _uncovered_areas(changed, tests)
    command_stats: dict[str, Any] = {}
    commands, command_warnings = detect_test_commands(
        database,
        tests,
        limits=limits,
        metadata=command_stats,
        analysis_budget=budget,
    )
    indexed_source_count = int(
        database.connection.execute(
            "SELECT COUNT(*) FROM files WHERE purpose NOT IN ('documentation', 'configuration')"
        ).fetchone()[0]
    )
    supported = indexed_source_count > 0
    warnings = [*selection_warnings, *command_warnings]
    if not supported:
        warnings.append("No supported source files were found in the index.")
    if not selected:
        warnings.append("No changed files were selected; no change-specific impact was inferred.")
    evidence = [
        {
            "kind": "analysis-boundary",
            "detail": (
                "Static graph, migration, route, API, filename, and test-source evidence only; "
                "coverage remains unknown unless external coverage data is supplied."
            ),
        },
        {
            "kind": "change-selection",
            "detail": f"Selected {len(selected)} file(s) from {change_source}.",
        },
    ]
    any_truncation = bool(
        graph_stats.truncated
        or area_stats["truncated"]
        or test_stats["truncated"]
        or command_stats.get("truncated")
        or selection_stats["truncated"]
        or budget.reasons
    )
    report: dict[str, Any] = {
        "schema_version": TEST_IMPACT_SCHEMA_VERSION,
        "repository": ".",
        "supported": supported,
        "analysis_status": (
            "unsupported"
            if not supported
            else (
                "no_changes"
                if not selected
                else ("truncated" if any_truncation else "complete")
            )
        ),
        "change_source": change_source,
        "changed_files": changed,
        "impacted_areas": impacted_areas,
        "existing_tests": tests,
        "uncovered_areas": uncovered,
        "recommended_commands": commands,
        "evidence": evidence,
        "confidence": _overall_confidence(changed, tests),
        "limits": asdict(limits),
        "truncation": {
            "change_selection": selection_stats,
            "analysis": budget.as_dict(),
            "graph": {
                "nodes_visited": graph_stats.nodes_visited,
                "edges_visited": graph_stats.edges_visited,
                "truncated": graph_stats.truncated,
                "reasons": sorted(graph_stats.reasons or set()),
                "limits": {
                    "max_graph_nodes": limits.max_graph_nodes,
                    "max_graph_edges": limits.max_graph_edges,
                    "max_direct_edges_per_file": limits.max_direct_edges_per_file,
                    "max_indirect_edges_per_file": limits.max_indirect_edges_per_file,
                },
            },
            "impacted_areas": area_stats,
            "relevant_tests": test_stats,
            "commands": command_stats,
            "output": {
                "measurement": "canonical_compact_json_utf8_bytes",
                "mode": output_mode,
                "total_discovered": 0,
                "total_returned": 0,
                "truncated": False,
                "limit": limits.max_output_bytes,
            },
        },
        "warnings": list(dict.fromkeys(warnings)),
    }
    if additional_metadata:
        report.update(additional_metadata)
    _fit_report_to_output_budget(report, limits.max_output_bytes, output_mode)
    return report


def detect_test_commands(
    database: IndexDatabase,
    relevant_tests: list[dict[str, Any]] | None = None,
    *,
    limits: TestImpactLimits | None = None,
    metadata: dict[str, Any] | None = None,
    analysis_budget: _AnalysisBudget | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    limits = limits or TestImpactLimits()
    budget = analysis_budget or _AnalysisBudget.start(limits)
    relevant_tests = relevant_tests or []
    path_rows = list(
        database.connection.execute(
            "SELECT path FROM files ORDER BY path LIMIT ?",
            (limits.max_route_candidates_scanned + 1,),
        )
    )
    if len(path_rows) > limits.max_route_candidates_scanned:
        budget.mark("max_route_candidates_scanned")
        path_rows.pop()
    paths = {str(row["path"]) for row in path_rows}
    test_rows = list(
        database.connection.execute(
            "SELECT path FROM files WHERE is_test=1 ORDER BY path LIMIT ?",
            (limits.max_test_candidates_scanned + 1,),
        )
    )
    if len(test_rows) > limits.max_test_candidates_scanned:
        budget.mark("max_test_candidates_scanned")
        test_rows.pop()
    test_paths = {
        str(row["path"])
        for row in test_rows
        if is_executable_test_path(str(row["path"]))
    }
    relevant_paths = {
        str(item["file"]) for item in relevant_tests if isinstance(item.get("file"), str)
    }
    commands: list[dict[str, Any]] = []
    warnings: list[str] = []

    python_tests = sorted(path for path in test_paths if Path(path).suffix.lower() == ".py")
    python_groups: dict[str, list[str]] = {}
    for path_value in python_tests:
        python_groups.setdefault(_python_project_boundary(path_value, paths), []).append(path_value)
    for boundary, group_tests in sorted(python_groups.items()):
        selected = sorted(set(group_tests) & relevant_paths)
        prefix = ["python", "-m", "pytest"]
        if selected:
            relative_tests = [_relative_to_boundary(path_value, boundary) for path_value in selected]
            if not _append_command_candidate(
                commands,
                _command(
                    "pytest",
                    "targeted",
                    [*prefix, *relative_tests],
                    boundary,
                    selected,
                    "Run statically related executable Python tests in their owning project.",
                ),
                budget,
            ):
                break
        if not _append_command_candidate(
            commands,
            _command(
                "pytest",
                "broad",
                prefix,
                boundary,
                group_tests,
                "Run the owning Python project's broader pytest suite.",
            ),
            budget,
        ):
            break

    manifests: dict[str, tuple[dict[str, Any], set[str], dict[str, Any]]] = {}
    for relative in sorted(path_value for path_value in paths if Path(path_value).name == "package.json"):
        manifest_path = database.root / relative
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Could not read test commands from {relative}: {exc}")
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("scripts", {}), dict):
            warnings.append(f"Could not read test commands from {relative}: scripts must be an object")
            continue
        scripts = raw.get("scripts", {})
        dependencies: set[str] = set()
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            values = raw.get(section, {})
            if isinstance(values, dict):
                dependencies.update(str(name).lower() for name in values)
        package_dir = PurePosixPath(relative).parent.as_posix()
        manifests[package_dir] = (scripts, dependencies, raw)

    grouped_js: dict[tuple[str, str, str], list[str]] = {}
    js_suffixes = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}
    for test_path in sorted(path_value for path_value in test_paths if Path(path_value).suffix.lower() in js_suffixes):
        if not budget.consume("command_test_candidates", "max_test_candidates_scanned"):
            break
        owner = _nearest_owner(test_path, set(manifests))
        if owner is None:
            continue
        scripts, dependencies, _ = manifests[owner]
        source = _read_test_source(database.root / test_path)
        framework = _javascript_test_framework_for_file(
            test_path, source, dependencies, scripts
        )
        if framework is None:
            warnings.append(f"Could not classify JavaScript test framework for {test_path}.")
            continue
        script_name = _script_for_framework(framework, scripts)
        if script_name is None:
            warnings.append(
                f"No existing npm script for {framework} test {test_path} in "
                f"{_manifest_path(owner)}."
            )
            continue
        grouped_js.setdefault((owner, framework, script_name), []).append(test_path)

    for (owner, framework, script_name), family_tests in sorted(grouped_js.items()):
        selected = sorted(set(family_tests) & relevant_paths)
        prefix = ["npm"]
        if owner != ".":
            prefix.extend(["--prefix", owner])
        prefix.extend(["run", script_name])
        if selected:
            package_relative = [_relative_to_boundary(path_value, owner) for path_value in selected]
            if not _append_command_candidate(
                commands,
                _command(
                    framework,
                    "targeted",
                    [*prefix, "--", *package_relative],
                    ".",
                    selected,
                    f"Run related {framework} tests through their owning npm script.",
                ),
                budget,
            ):
                break
        if not _append_command_candidate(
            commands,
            _command(
                framework,
                "broad",
                prefix,
                ".",
                sorted(family_tests),
                f"Run the existing npm '{script_name}' {framework} suite.",
            ),
            budget,
        ):
            break

    for item in _gradle_commands(paths, test_paths, relevant_paths):
        if not _append_command_candidate(commands, item, budget):
            break
    for item in _maestro_commands(paths, test_paths, relevant_paths):
        if not _append_command_candidate(commands, item, budget):
            break
    commands = _dedupe_commands(commands)
    commands.sort(
        key=lambda item: (
            0 if item["scope"] == "targeted" else 1,
            0 if item["related_tests"] else 1,
            item["framework"],
            item["working_directory"],
            item["command"],
        )
    )
    total = len(commands)
    commands = commands[: limits.max_commands]
    for index, item in enumerate(commands, start=1):
        item["id"] = f"test-command-{index}"
    command_by_test: dict[str, list[str]] = {}
    for item in commands:
        for path_value in item["related_tests"]:
            command_by_test.setdefault(str(path_value), []).append(str(item["id"]))
    for test in relevant_tests:
        test["command_ids"] = sorted(
            set(command_by_test.get(str(test["file"]), []))
        )
    if total > len(commands):
        warnings.append(
            f"Recommended commands truncated: returned {len(commands)} of {total}."
        )
    if metadata is not None:
        candidate_reasons = [
            name
            for name in (
                "max_test_candidates_scanned",
                "max_route_candidates_scanned",
                "max_command_candidates",
            )
            if name in budget.reasons
        ]
        metadata.update(_truncation_record(total, len(commands), limits.max_commands))
        metadata["candidate_limit"] = limits.max_command_candidates
        metadata["candidate_limit_reached"] = bool(candidate_reasons)
        metadata["discovery_complete"] = not candidate_reasons
        metadata["total_discovered_is_lower_bound"] = bool(candidate_reasons)
        metadata["reasons"] = [
            *candidate_reasons,
            *(["max_commands"] if total > len(commands) else []),
        ]
    return commands, warnings


def _append_command_candidate(
    commands: list[dict[str, Any]],
    command: dict[str, Any],
    budget: _AnalysisBudget,
) -> bool:
    if not budget.consume("command_candidates", "max_command_candidates"):
        return False
    commands.append(command)
    return True


def _python_project_boundary(path: str, paths: set[str]) -> str:
    configs = {"pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg"}
    parent = PurePosixPath(path).parent
    candidates: list[str] = []
    for config_path in paths:
        config = PurePosixPath(config_path)
        if config.name not in configs:
            continue
        boundary = config.parent
        try:
            parent.relative_to(boundary)
        except ValueError:
            continue
        candidates.append(boundary.as_posix())
    return max(candidates, key=lambda value: (len(PurePosixPath(value).parts), value), default=".")


def _nearest_owner(path: str, owners: set[str]) -> str | None:
    parent = PurePosixPath(path).parent
    matches: list[str] = []
    for owner in owners:
        boundary = PurePosixPath(owner)
        try:
            parent.relative_to(boundary)
        except ValueError:
            continue
        matches.append(owner)
    if not matches:
        return None
    return max(matches, key=lambda value: (len(PurePosixPath(value).parts), value))


def _relative_to_boundary(path: str, boundary: str) -> str:
    return (
        PurePosixPath(path).relative_to(PurePosixPath(boundary)).as_posix()
        if boundary != "."
        else path
    )


def _manifest_path(owner: str) -> str:
    return "package.json" if owner == "." else f"{owner}/package.json"


def _javascript_test_framework_for_file(
    path: str, source: str, dependencies: set[str], scripts: dict[str, Any]
) -> str | None:
    lowered = source.lower()
    parts = {part.lower() for part in PurePosixPath(path).parts}
    if "@playwright/test" in lowered:
        return "playwright"
    if "from 'vitest'" in lowered or 'from "vitest"' in lowered:
        return "vitest"
    if "@jest/globals" in lowered:
        return "jest"
    if "playwright" in dependencies and ("e2e" in parts or "playwright" in parts):
        return "playwright"
    name = PurePosixPath(path).name.lower()
    if "vitest" in dependencies and ".test." in name:
        return "vitest"
    if "jest" in dependencies and ".test." in name:
        return "jest"
    frameworks = {
        framework
        for framework in ("playwright", "vitest", "jest")
        if framework in dependencies
        or any(framework in str(value).lower() for value in scripts.values())
    }
    return next(iter(sorted(frameworks))) if len(frameworks) == 1 else None


def _script_for_framework(framework: str, scripts: dict[str, Any]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for raw_name, raw_value in scripts.items():
        name, value = str(raw_name), str(raw_value).lower()
        lowered_name = name.lower()
        score = 0
        if framework in value:
            score += 100
        if framework == "playwright" and ("e2e" in lowered_name or "playwright" in lowered_name):
            score += 50
        if framework in {"vitest", "jest"} and lowered_name in {"test", "test:unit", "unit"}:
            score += 40
        if score:
            candidates.append((-score, name))
    return sorted(candidates)[0][1] if candidates else None

def render_test_impact(
    report: dict[str, Any], output_format: str, max_output_bytes: int | None = None
) -> str:
    if output_format == "json":
        limit = max_output_bytes or int(report["limits"]["max_output_bytes"])
        output = report.get("truncation", {}).get("output", {})
        rendered = _serialize_report(report, "pretty_json")
        measured = len(rendered.encode("utf-8"))
        if (
            output.get("mode") != "pretty_json"
            or output.get("limit") != limit
            or output.get("total_returned") != measured
            or measured > limit
        ):
            _fit_report_to_output_budget(report, limit, "pretty_json")
            rendered = _serialize_report(report, "pretty_json")
        return rendered
    lines = [
        "# RepoMind Test Impact",
        "",
        f"Repository: {report['repository']}",
        f"Change source: {report['change_source']}",
        f"Analysis status: {report['analysis_status']}",
        f"Overall confidence: {report['confidence']}",
        "",
        "RepoMind recommends commands as data only and never executes repository code. "
        "Codex, CI, or a developer must separately approve and run any command.",
        "",
        "Test discovery and static relationship evidence do not prove behavioral coverage. "
        "Coverage is **unknown** unless separately measured.",
        "",
        "## Changed Files",
        "",
    ]
    changed = report.get("changed_files", [])
    lines.extend(
        f"- {item['path']} — indexed={str(item['indexed']).lower()}, test={str(item['is_test']).lower()}"
        for item in changed
    )
    if not changed:
        lines.append("- None selected.")
    for label, key in (
        ("High confidence", "high_confidence"),
        ("Medium confidence", "medium_confidence"),
        ("Low confidence", "low_confidence"),
    ):
        lines.extend(("", f"## {label} affected areas", ""))
        items = report.get("impacted_areas", {}).get(key, [])
        if not items:
            lines.append("- None detected.")
        for item in items:
            name = f" — {item['name']}" if item.get("name") else ""
            lines.append(f"- {item['path']}{name}: {item['reason']}")
    lines.extend(("", "## Relevant Existing Tests", ""))
    tests = report.get("existing_tests", [])
    if not tests:
        lines.append("- No relevant existing tests were detected.")
    for item in tests:
        state = "structurally related" if item["structurally_related"] else "discovered"
        lines.append(
            f"- {item['file']} — {item['confidence']} confidence; {state}; "
            f"coverage unknown. {'; '.join(item['reasons'])}"
        )
    lines.extend(("", "## Potential Test Gaps", ""))
    gaps = report.get("uncovered_areas", [])
    if not gaps:
        lines.append("- No change-specific evidence gaps were detected by this analysis.")
    for item in gaps:
        lines.append(f"- {item['path']}: {item['reason']} Coverage remains unknown.")
    lines.extend(("", "## Recommended Commands", ""))
    commands = report.get("recommended_commands", [])
    if not commands:
        lines.append("- No existing project test command was detected.")
    for item in commands:
        lines.append(f"- {item['command']} — {item['scope']}. {item['reason']}")
    if report.get("warnings"):
        lines.extend(("", "## Warnings", ""))
        lines.extend(f"- {warning}" for warning in report["warnings"])
    lines.append("")
    rendered = "\n".join(lines)
    if max_output_bytes is None or len(rendered.encode("utf-8")) <= max_output_bytes:
        return rendered
    marker = "\n... text output truncated by RepoMind output budget ...\n"
    keep = max(0, max_output_bytes - len(marker.encode("utf-8")))
    return rendered.encode("utf-8")[:keep].decode("utf-8", errors="ignore") + marker


@dataclass(slots=True)
class _GitChangeResult:
    paths: list[str]
    total_discovered: int
    processed: int
    discovery_complete: bool
    total_discovered_is_lower_bound: bool
    reasons: list[str]
    stdout_bytes: int
    stderr_bytes: int
    malformed_record: bool = False


class _GitPathParser:
    def __init__(self, mode: str, max_entries: int, max_path_length: int) -> None:
        self.mode = mode
        self.max_entries = max_entries
        self.max_path_length = max_path_length
        self.paths: list[str] = []
        self.total_discovered = 0
        self.buffer = bytearray()
        self.state = "record" if mode == "status" else "status"
        self.pending_status = ""
        self.count_truncated = False
        self.malformed = False

    def feed(self, chunk: bytes) -> bool:
        self.buffer.extend(chunk)
        while True:
            separator = self.buffer.find(0)
            if separator < 0:
                if len(self.buffer) > self.max_path_length + 64:
                    raise ValueError(
                        f"Git changed file path exceeds max_path_length "
                        f"({self.max_path_length})"
                    )
                return True
            token = bytes(self.buffer[:separator])
            del self.buffer[: separator + 1]
            if not self._token(token):
                self.buffer.clear()
                return False

    def finish(self) -> None:
        expected = "record" if self.mode == "status" else "status"
        if self.buffer or self.state != expected:
            self.malformed = True
        self.buffer.clear()

    def _token(self, token: bytes) -> bool:
        if self.mode == "status":
            return self._status_token(token)
        return self._diff_token(token)

    def _status_token(self, token: bytes) -> bool:
        if self.state == "rename_source":
            self.state = "record"
            return self._validate_path(token)
        if len(token) < 4 or token[2:3] != b" ":
            self.malformed = True
            return False
        status = token[:2].decode("ascii", errors="replace")
        path = token[3:]
        if "R" in status or "C" in status:
            # Porcelain v1 -z emits the destination before the source.
            self.state = "rename_source"
            return self._emit(path)
        return self._emit(path)

    def _diff_token(self, token: bytes) -> bool:
        if self.state == "status":
            status = token.decode("ascii", errors="replace")
            if not status:
                self.malformed = True
                return False
            self.pending_status = status
            self.state = "rename_source" if status.startswith(("R", "C")) else "path"
            return True
        if self.state == "rename_source":
            self.state = "rename_destination"
            return self._validate_path(token)
        if self.state in {"path", "rename_destination"}:
            self.state = "status"
            return self._emit(token)
        self.malformed = True
        return False

    def _validate_path(self, raw_path: bytes) -> bool:
        if not raw_path:
            self.malformed = True
            return False
        if len(raw_path) > self.max_path_length:
            raise ValueError(
                f"Git changed file path exceeds max_path_length "
                f"({self.max_path_length})"
            )
        return True

    def _emit(self, raw_path: bytes) -> bool:
        if not self._validate_path(raw_path):
            return False
        self.total_discovered += 1
        if len(self.paths) >= self.max_entries:
            self.count_truncated = True
            return False
        self.paths.append(raw_path.decode("utf-8", errors="replace"))
        return True


def _queue_pipe(
    pipe: Any,
    chunks: queue.Queue[bytes | None],
    stop: threading.Event,
) -> None:
    try:
        while not stop.is_set():
            chunk = pipe.read(8_192)
            if not chunk:
                break
            while not stop.is_set():
                try:
                    chunks.put(chunk, timeout=0.05)
                    break
                except queue.Full:
                    continue
    finally:
        while not stop.is_set():
            try:
                chunks.put(None, timeout=0.05)
                break
            except queue.Full:
                continue


def _drain_stderr(
    pipe: Any,
    limit: int,
    state: dict[str, int | bool],
    stop: threading.Event,
) -> None:
    retained = 0
    total = 0
    while not stop.is_set():
        chunk = pipe.read(4_096)
        if not chunk:
            break
        total += len(chunk)
        retained += min(len(chunk), max(0, limit - retained))
        if total > limit:
            state["exceeded"] = True
            stop.set()
            break
    state["retained"] = retained


def _terminate_git_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _bounded_git_changes(
    root: Path,
    args: Sequence[str],
    mode: str,
    limits: TestImpactLimits,
    budget: _AnalysisBudget,
) -> _GitChangeResult:
    if mode not in {"status", "diff"}:
        raise ValueError("unsupported Git change parser mode")
    parser = _GitPathParser(mode, limits.max_changed_files, limits.max_path_length)
    chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=8)
    stop = threading.Event()
    stderr_state: dict[str, int | bool] = {"retained": 0, "exceeded": False}
    try:
        process = subprocess.Popen(
            ["git", "-C", str(root), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
    except OSError as exc:
        raise ValueError(f"Unable to inspect Git changes: {type(exc).__name__}") from exc
    if process.stdout is None or process.stderr is None:
        _terminate_git_process(process)
        raise ValueError("Unable to inspect Git changes: missing process pipes")
    stdout_thread = threading.Thread(
        target=_queue_pipe,
        args=(process.stdout, chunks, stop),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_stderr,
        args=(process.stderr, limits.max_git_stderr_bytes, stderr_state, stop),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    stdout_bytes = 0
    reasons: list[str] = []
    deliberate_stop = False
    deadline = budget.started + min(5.0, float(limits.max_analysis_seconds))
    try:
        reached_eof = False
        while not reached_eof:
            if bool(stderr_state["exceeded"]):
                reasons.append("max_git_stderr_bytes")
                budget.mark("max_git_stderr_bytes")
                deliberate_stop = True
                break
            if time.perf_counter() >= deadline:
                reasons.append("max_analysis_seconds")
                budget.mark("max_analysis_seconds")
                deliberate_stop = True
                break
            try:
                chunk = chunks.get(timeout=0.05)
            except queue.Empty:
                if process.poll() is not None and not stdout_thread.is_alive():
                    break
                continue
            if chunk is None:
                reached_eof = True
                continue
            remaining = limits.max_git_output_bytes - stdout_bytes
            if len(chunk) > remaining:
                accepted = True
                if remaining > 0:
                    accepted = parser.feed(chunk[:remaining])
                    stdout_bytes += remaining
                if not accepted:
                    if parser.count_truncated:
                        reasons.append("max_changed_files")
                        budget.mark("max_changed_files")
                    else:
                        reasons.append("git_record_truncated")
                reasons.append("max_git_output_bytes")
                budget.mark("max_git_output_bytes")
                deliberate_stop = True
                break
            stdout_bytes += len(chunk)
            if not parser.feed(chunk):
                if parser.count_truncated:
                    reasons.append("max_changed_files")
                    budget.mark("max_changed_files")
                else:
                    reasons.append("git_record_truncated")
                deliberate_stop = True
                break
        if deliberate_stop:
            _terminate_git_process(process)
        else:
            remaining_time = max(0.05, deadline - time.perf_counter())
            try:
                process.wait(timeout=remaining_time)
            except subprocess.TimeoutExpired:
                reasons.append("max_analysis_seconds")
                budget.mark("max_analysis_seconds")
                deliberate_stop = True
                _terminate_git_process(process)
        if not deliberate_stop and process.returncode:
            raise ValueError("Unable to inspect Git changes: Git command failed")
        if not deliberate_stop:
            parser.finish()
            if parser.malformed:
                reasons.append("git_record_truncated")
    finally:
        stop.set()
        _terminate_git_process(process)
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        process.stdout.close()
        process.stderr.close()
    reasons = sorted(set(reasons))
    complete = not reasons and not parser.malformed
    return _GitChangeResult(
        parser.paths,
        parser.total_discovered,
        len(parser.paths),
        complete,
        not complete,
        reasons,
        stdout_bytes,
        int(stderr_state["retained"]),
        parser.malformed,
    )


def _select_changes(
    root: Path,
    supplied: Iterable[str] | None,
    base: str | None,
    limits: TestImpactLimits,
    budget: _AnalysisBudget,
) -> tuple[list[str], str, list[str], dict[str, Any]]:
    if supplied is not None and base:
        raise ValueError("supplied file paths and base cannot be used together")
    warnings: list[str] = []
    if supplied is not None:
        selection = _bounded_supplied_changes(supplied, limits, budget)
        source = "supplied paths"
    elif base:
        selection = _git_diff_paths(root, base, limits, budget)
        source = f"git diff from {base}"
    else:
        try:
            inside = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
        except Exception as exc:
            return (
                [],
                "working tree",
                [f"Git working-tree state is unavailable: {type(exc).__name__}."],
                _truncation_record(0, 0, limits.max_changed_files),
            )
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return (
                [],
                "working tree",
                ["Git working-tree state is unavailable."],
                _truncation_record(0, 0, limits.max_changed_files),
            )
        selection = _bounded_git_changes(
            root,
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            "status",
            limits,
            budget,
        )
        source = "working tree"
    if selection.reasons:
        warnings.append(
            "Changed-file selection truncated by "
            + ", ".join(selection.reasons)
            + "."
        )
    normalized = sorted(
        {
            _normalize_input_path(root, path_value, limits.max_path_length)
            for path_value in selection.paths
            if not path_value.replace("\\", "/").startswith(".repomind/")
        }
    )
    stats = _truncation_record(
        selection.total_discovered,
        len(normalized),
        limits.max_changed_files,
    )
    stats["truncated"] = bool(selection.reasons)
    stats["processed"] = selection.processed
    stats["discovery_complete"] = selection.discovery_complete
    stats["total_discovered_is_lower_bound"] = (
        selection.total_discovered_is_lower_bound
    )
    stats["reasons"] = selection.reasons
    stats["reason"] = selection.reasons[0] if selection.reasons else None
    stats["duplicates_or_internal_paths_removed"] = (
        selection.processed - len(normalized)
    )
    stats["git"] = {
        "stdout_bytes_processed": selection.stdout_bytes,
        "stdout_byte_limit": limits.max_git_output_bytes,
        "stderr_bytes_retained": selection.stderr_bytes,
        "stderr_byte_limit": limits.max_git_stderr_bytes,
        "malformed_record": selection.malformed_record,
    }
    return normalized, source, warnings, stats


def _bounded_supplied_changes(
    supplied: Iterable[str],
    limits: TestImpactLimits,
    budget: _AnalysisBudget,
) -> _GitChangeResult:
    paths: list[str] = []
    known_total = (
        len(supplied)
        if isinstance(supplied, Sequence) and not isinstance(supplied, (str, bytes))
        else None
    )
    iterator = iter(supplied)
    for _ in range(limits.max_changed_files):
        try:
            raw = next(iterator)
        except StopIteration:
            break
        if not isinstance(raw, str):
            raise ValueError("changed file paths must be strings")
        if _changed_path_byte_length(raw) > limits.max_path_length:
            raise ValueError(
                f"changed file path exceeds max_path_length ({limits.max_path_length})"
            )
        paths.append(raw)
    overflow = bool(known_total is not None and known_total > len(paths))
    total = known_total if known_total is not None else len(paths)
    if known_total is None:
        try:
            next(iterator)
        except StopIteration:
            pass
        else:
            overflow = True
            total = len(paths) + 1
    reasons: list[str] = []
    if overflow:
        reasons.append("max_changed_files")
        budget.mark("max_changed_files")
    return _GitChangeResult(
        paths,
        int(total),
        len(paths),
        not overflow,
        known_total is None and overflow,
        reasons,
        0,
        0,
    )


def _git_diff_paths(
    root: Path,
    base: str,
    limits: TestImpactLimits,
    budget: _AnalysisBudget,
) -> _GitChangeResult:
    if not base.strip() or base.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._/@{}~^:+-]+", base):
        raise ValueError("base must be a valid Git revision name")
    try:
        revision = _run_git(root, ["rev-parse", "--verify", f"{base}^{{commit}}"])
        if revision.returncode != 0:
            raise ValueError(f"Git base revision was not found: {base}")
        digest = revision.stdout.strip()
        return _bounded_git_changes(
            root,
            [
                "diff",
                "--name-status",
                "--diff-filter=ACMRTUXB",
                "-z",
                digest,
                "--",
            ],
            "diff",
            limits,
            budget,
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Unable to inspect Git diff: {type(exc).__name__}") from exc


def _normalize_input_path(root: Path, raw: str, max_length: int) -> str:
    if not isinstance(raw, str):
        raise ValueError("changed file paths must be strings")
    if not raw.strip():
        raise ValueError("changed file paths cannot be empty")
    if _changed_path_byte_length(raw) > max_length:
        raise ValueError(f"changed file path exceeds max_path_length ({max_length})")
    candidate = Path(raw)
    windows_candidate = PureWindowsPath(raw)
    if windows_candidate.drive and not windows_candidate.is_absolute():
        raise ValueError(f"changed file must be a repository-relative path: {raw}")
    if candidate.is_absolute():
        try:
            relative = candidate.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"changed file is outside the repository: {raw}") from exc
        normalized = relative.as_posix()
    else:
        normalized = PurePosixPath(raw.replace("\\", "/").removeprefix("./")).as_posix()
    path_value = PurePosixPath(normalized)
    if normalized in {"", "."} or path_value.is_absolute() or ".." in path_value.parts:
        raise ValueError(f"changed file must be a repository-relative path: {raw}")
    return normalized


def _changed_path_byte_length(raw: str) -> int:
    if "\0" in raw:
        raise ValueError("changed file paths cannot contain NUL bytes")
    try:
        return len(raw.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("changed file paths must be valid UTF-8") from exc


def _changed_file_record(database: IndexDatabase, path: str) -> dict[str, Any]:
    row = database.file_by_path(path)
    classified = classify_file(path)
    return {
        "path": path,
        "indexed": row is not None,
        "language": str(row["language"]) if row is not None else (classified[0] if classified else None),
        "purpose": str(row["purpose"]) if row is not None else (classified[1] if classified else None),
        "is_test": (
            bool(row["is_test"]) and is_executable_test_path(path)
            if row is not None
            else bool(classified and classified[2])
        ),
    }


def _impacted_areas(
    database: IndexDatabase,
    changed: list[dict[str, Any]],
    limits: TestImpactLimits,
    graph: _GraphBudget,
    budget: _AnalysisBudget,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], _GraphBudget]:
    areas: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in changed:
        if not budget.within_time():
            break
        if len(areas) >= limits.max_impacted_candidates:
            budget.mark("max_impacted_candidates")
            break
        path = str(item["path"])
        if item["is_test"]:
            _merge_area(
                areas, "test", path, None, "high", "The test file itself changed.", "changed-file"
            )
            continue
        _merge_area(
            areas,
            str(item.get("purpose") or "file"),
            path,
            None,
            "high",
            "The production file itself changed.",
            "changed-file",
        )
        if not item["indexed"]:
            continue
        direct, indirect = _bounded_dependents(database, path, graph, limits, budget)
        for dependent in direct:
            if len(areas) >= limits.max_impacted_candidates:
                budget.mark("max_impacted_candidates")
                break
            confidence = _numeric_confidence(float(dependent["confidence"]))
            _merge_area(
                areas,
                "dependent-file",
                str(dependent["path"]),
                str(dependent.get("symbol") or "") or None,
                confidence,
                f"Direct {dependent['kind']} relationship to {path}.",
                str(dependent["source"]),
            )
        for dependent_path in indirect:
            if len(areas) >= limits.max_impacted_candidates:
                budget.mark("max_impacted_candidates")
                break
            _merge_area(
                areas,
                "dependent-file",
                dependent_path,
                None,
                "low",
                f"Bounded indirect dependency path reaches {path}.",
                "dependency graph traversal",
            )
        related_paths = {path, *(str(row["path"]) for row in direct), *indirect}
        for route_path in sorted(related_paths):
            for row in database.connection.execute(
                """SELECT r.method, r.path, r.handler FROM routes r
                   JOIN files f ON f.id=r.file_id WHERE f.path=? ORDER BY r.line""",
                (route_path,),
            ):
                if not budget.consume("impacted_route_candidates", "max_route_candidates_scanned"):
                    break
                if len(areas) >= limits.max_impacted_candidates:
                    budget.mark("max_impacted_candidates")
                    break
                _merge_area(
                    areas,
                    "route",
                    route_path,
                    f"{row['method']} {row['path']}",
                    "high" if route_path == path else "medium",
                    (
                        "Route is declared in the changed file."
                        if route_path == path
                        else f"Route caller is directly or bounded-indirectly linked to {path}."
                    ),
                    "route and bounded dependency graph",
                )
        for row in database.connection.execute(
            """SELECT qualified_name FROM symbols s JOIN files f ON f.id=s.file_id
               WHERE f.path=? AND s.kind='component' ORDER BY s.line_start""",
            (path,),
        ):
            if not budget.consume("component_candidates", "max_route_candidates_scanned"):
                break
            if len(areas) >= limits.max_impacted_candidates:
                budget.mark("max_impacted_candidates")
                break
            _merge_area(
                areas,
                "component",
                path,
                str(row["qualified_name"]),
                "high",
                "UI component is declared in the changed file.",
                "symbols",
            )

    ordered = sorted(
        areas.values(),
        key=lambda value: (
            -_CONFIDENCE_RANK[str(value["confidence"])],
            str(value["path"]),
            str(value["kind"]),
            str(value.get("name") or ""),
            str(value["reason"]),
        ),
    )
    total = len(ordered)
    ordered = ordered[: limits.max_impacted_areas]
    output: dict[str, list[dict[str, Any]]] = {
        "high_confidence": [],
        "medium_confidence": [],
        "low_confidence": [],
    }
    bucket = {"high": "high_confidence", "medium": "medium_confidence", "low": "low_confidence"}
    for area in ordered:
        output[bucket[str(area["confidence"])]].append(area)
    metadata = _truncation_record(total, len(ordered), limits.max_impacted_areas)
    metadata["candidate_limit"] = limits.max_impacted_candidates
    candidate_limit_reached = "max_impacted_candidates" in budget.reasons
    metadata["candidate_limit_reached"] = candidate_limit_reached
    metadata["discovery_complete"] = not candidate_limit_reached
    metadata["total_discovered_is_lower_bound"] = candidate_limit_reached
    metadata["reasons"] = [
        name
        for name in ("max_impacted_candidates", "max_impacted_areas", "max_output_bytes")
        if (
            (name == "max_impacted_candidates" and name in budget.reasons)
            or (name == "max_impacted_areas" and total > len(ordered))
        )
    ]
    return output, metadata, graph


def _bounded_dependents(
    database: IndexDatabase,
    target_path: str,
    graph: _GraphBudget,
    limits: TestImpactLimits,
    budget: _AnalysisBudget,
    max_indirect_edges: int | None = None,
    max_direct_edges: int | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not budget.within_time():
        graph.mark("max_analysis_seconds")
        return [], []
    if graph.nodes_visited >= limits.max_graph_nodes:
        graph.mark("max_graph_nodes")
        return [], []
    graph.nodes_visited += 1
    direct: list[dict[str, Any]] = []
    direct_ids: list[int] = []
    seen_paths = {target_path}
    rows = database.connection.execute(
        """SELECT DISTINCT sf.id, sf.path, sf.is_test, ss.qualified_name AS symbol,
                  d.kind, d.confidence, d.source
           FROM dependencies d
           JOIN files sf ON sf.id=d.source_file_id
           LEFT JOIN files tf ON tf.id=d.target_file_id
           LEFT JOIN symbols ts ON ts.id=d.target_symbol_id
           LEFT JOIN files tsf ON tsf.id=ts.file_id
           LEFT JOIN symbols ss ON ss.id=d.source_symbol_id
           WHERE COALESCE(tf.path, tsf.path)=?
           ORDER BY d.confidence DESC, sf.path, d.kind""",
        (target_path,),
    )
    for direct_edges, row in enumerate(rows):
        if not budget.within_time():
            graph.mark("max_analysis_seconds")
            break
        if max_direct_edges is not None and direct_edges >= max_direct_edges:
            graph.mark("max_direct_edges_per_file")
            break
        if graph.edges_visited >= limits.max_graph_edges:
            graph.mark("max_graph_edges")
            break
        graph.edges_visited += 1
        path = str(row["path"])
        if path not in seen_paths:
            if graph.nodes_visited >= limits.max_graph_nodes:
                graph.mark("max_graph_nodes")
                break
            graph.nodes_visited += 1
            seen_paths.add(path)
        direct.append(
            {
                "id": int(row["id"]),
                "path": path,
                "is_test": bool(row["is_test"]),
                "symbol": row["symbol"],
                "kind": str(row["kind"]),
                "confidence": float(row["confidence"]),
                "source": str(row["source"]),
            }
        )
        direct_ids.append(int(row["id"]))

    indirect: set[str] = set()
    queue = [(file_id, 0) for file_id in sorted(set(direct_ids))]
    cursor = 0
    seen_ids = set(direct_ids)
    indirect_edges = 0
    while cursor < len(queue):
        file_id, depth = queue[cursor]
        cursor += 1
        if depth >= 2 or graph.truncated:
            continue
        for row in database.connection.execute(
            """SELECT DISTINCT f.id, f.path FROM dependencies d
               JOIN files f ON f.id=d.source_file_id
               WHERE d.target_file_id=? ORDER BY f.path""",
            (file_id,),
        ):
            if not budget.within_time():
                graph.mark("max_analysis_seconds")
                return direct, sorted(indirect)
            if max_indirect_edges is not None and indirect_edges >= max_indirect_edges:
                if max_indirect_edges:
                    graph.mark("max_indirect_edges_per_file")
                return direct, sorted(indirect)
            indirect_edges += 1
            if graph.edges_visited >= limits.max_graph_edges:
                graph.mark("max_graph_edges")
                break
            graph.edges_visited += 1
            dependent_id = int(row["id"])
            if dependent_id in seen_ids:
                continue
            if graph.nodes_visited >= limits.max_graph_nodes:
                graph.mark("max_graph_nodes")
                break
            graph.nodes_visited += 1
            seen_ids.add(dependent_id)
            dependent_path = str(row["path"])
            indirect.add(dependent_path)
            queue.append((dependent_id, depth + 1))
    return direct, sorted(indirect)


def _numeric_confidence(value: float) -> Confidence:
    if value >= 0.85:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"

def _merge_area(
    areas: dict[tuple[str, str, str], dict[str, Any]],
    kind: str,
    path: str,
    name: str | None,
    confidence: str,
    reason: str,
    evidence: str,
) -> None:
    key = (kind, path, name or "")
    previous = areas.get(key)
    if previous is not None and _CONFIDENCE_RANK[previous["confidence"]] >= _CONFIDENCE_RANK[confidence]:
        return
    areas[key] = {
        "kind": kind,
        "path": path,
        "name": name or None,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence,
    }


def _relevant_tests(
    database: IndexDatabase,
    changed: list[dict[str, Any]],
    limits: TestImpactLimits,
    graph: _GraphBudget,
    budget: _AnalysisBudget,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    evidence_store = _EvidenceStore.start(limits, budget)
    test_rows = list(
        database.connection.execute(
            "SELECT path FROM files WHERE is_test=1 ORDER BY path LIMIT ?",
            (limits.max_test_candidates_scanned + 1,),
        )
    )
    if len(test_rows) > limits.max_test_candidates_scanned:
        test_rows.pop()
        budget.mark("max_test_candidates_scanned")
    test_paths = [
        str(row["path"])
        for row in test_rows
        if is_executable_test_path(str(row["path"]))
    ]
    source_cache: dict[str, str] = {}
    for changed_item in changed:
        if evidence_store.exhausted:
            break
        if not budget.within_time():
            break
        if len(candidates) >= limits.max_relevant_test_candidates:
            budget.mark("max_relevant_test_candidates")
            break
        changed_path = str(changed_item["path"])
        if changed_item["is_test"] and is_executable_test_path(changed_path):
            _merge_test(
                candidates,
                changed_path,
                changed_path,
                "high",
                False,
                "The executable test file itself changed.",
                {"kind": "changed-test-file", "path": changed_path},
                evidence_store,
            )
            if evidence_store.exhausted:
                break
            continue
        if changed_item["indexed"]:
            direct, indirect = _bounded_dependents(
                database,
                changed_path,
                graph,
                limits,
                budget,
                max_indirect_edges=limits.max_indirect_edges_per_file,
                max_direct_edges=limits.max_direct_edges_per_file,
            )
            for row in direct:
                if evidence_store.exhausted:
                    break
                test_path = str(row["path"])
                if (
                    test_path not in candidates
                    and len(candidates) >= limits.max_relevant_test_candidates
                ):
                    budget.mark("max_relevant_test_candidates")
                    break
                if bool(row["is_test"]) and is_executable_test_path(test_path):
                    _merge_test(
                        candidates,
                        test_path,
                        changed_path,
                        _numeric_confidence(float(row["confidence"])),
                        True,
                        f"Test has a direct {row['kind']} relationship to the changed file.",
                        {
                            "kind": "dependency",
                            "path": test_path,
                            "target": changed_path,
                            "relationship": str(row["kind"]),
                            "source": str(row["source"]),
                        },
                        evidence_store,
                    )
            for test_path in sorted(set(indirect) & set(test_paths)):
                if evidence_store.exhausted:
                    break
                if (
                    test_path not in candidates
                    and len(candidates) >= limits.max_relevant_test_candidates
                ):
                    budget.mark("max_relevant_test_candidates")
                    break
                _merge_test(
                    candidates,
                    test_path,
                    changed_path,
                    "medium",
                    True,
                    "Test is reachable through a bounded indirect dependency path.",
                    {
                        "kind": "dependency-reachability",
                        "path": test_path,
                        "target": changed_path,
                        "classification": "indirect",
                    },
                    evidence_store,
                )
        changed_stem = _semantic_stem(changed_path)
        for test_path in test_paths:
            if evidence_store.exhausted:
                break
            if not budget.consume("filename_test_candidates", "max_test_candidates_scanned"):
                break
            if len(candidates) >= limits.max_relevant_test_candidates:
                budget.mark("max_relevant_test_candidates")
                break
            if changed_stem and changed_stem == _semantic_stem(test_path):
                _merge_test(
                    candidates,
                    test_path,
                    changed_path,
                    "medium",
                    False,
                    "Test filename matches the changed module or component name.",
                    {"kind": "filename-match", "path": test_path, "target": changed_path},
                    evidence_store,
                )
        _link_migration_tests(
            database,
            candidates,
            test_paths,
            source_cache,
            changed_path,
            changed_item,
            graph,
            limits,
            budget,
            evidence_store,
        )
        if evidence_store.exhausted:
            break
        _link_route_api_tests(
            database,
            candidates,
            test_paths,
            source_cache,
            changed_path,
            changed_item,
            graph,
            limits,
            budget,
            evidence_store,
        )
        if evidence_store.exhausted:
            break

    for item in candidates.values():
        test_path = str(item["file"])
        item["reasons"] = sorted(set(str(reason) for reason in item["reasons"]))
        item["evidence"] = evidence_store.for_test(test_path)
        item["evidence_total"] = evidence_store.per_test_scanned.get(test_path, 0)
        item["evidence_truncated"] = (
            int(item["evidence_total"]) > len(item["evidence"])
            or evidence_store.scan_truncated
        )
    ordered = sorted(
        candidates.values(),
        key=lambda item: (
            -_CONFIDENCE_RANK[str(item["confidence"])],
            _test_priority(item),
            str(item["file"]),
        ),
    )
    total = len(ordered)
    ordered = ordered[: limits.max_tests]
    evidence_total = sum(int(item["evidence_total"]) for item in ordered)
    evidence_returned = sum(len(item["evidence"]) for item in ordered)
    metadata = _truncation_record(total, len(ordered), limits.max_tests)
    candidate_reasons = [
        name
        for name in (
            "max_test_candidates_scanned",
            "max_migration_candidates_scanned",
            "max_route_candidates_scanned",
            "max_relevant_test_candidates",
        )
        if name in budget.reasons
    ]
    metadata["candidate_limit"] = limits.max_relevant_test_candidates
    metadata["candidate_limit_reached"] = bool(candidate_reasons)
    metadata["discovery_complete"] = not candidate_reasons
    metadata["total_discovered_is_lower_bound"] = bool(candidate_reasons)
    metadata["reasons"] = [
        name
        for name in (
            "max_test_candidates_scanned",
            "max_migration_candidates_scanned",
            "max_route_candidates_scanned",
            "max_relevant_test_candidates",
            "max_tests",
        )
        if (
            name in budget.reasons
            or (name == "max_tests" and total > len(ordered))
        )
    ]
    metadata["evidence"] = {
        "total_discovered": evidence_total,
        "total_returned": evidence_returned,
        "truncated": (
            evidence_total > evidence_returned
            or evidence_store.result_truncated
            or evidence_store.scan_truncated
        ),
        "limit_per_result": limits.max_evidence_per_result,
        "candidate_limit": limits.max_evidence_candidates,
        "candidate_limit_reached": "max_evidence_candidates" in budget.reasons,
        "discovery_complete": not evidence_store.scan_truncated,
        "total_discovered_is_lower_bound": evidence_store.scan_truncated,
        "count_scope": "returned_relevant_tests",
    }
    return ordered, metadata


def _link_migration_tests(
    database: IndexDatabase,
    candidates: dict[str, dict[str, Any]],
    test_paths: list[str],
    source_cache: dict[str, str],
    changed_path: str,
    changed_item: dict[str, Any],
    graph: _GraphBudget,
    limits: TestImpactLimits,
    budget: _AnalysisBudget,
    evidence_store: _EvidenceStore,
) -> None:
    parts = {part.lower() for part in PurePosixPath(changed_path).parts}
    is_migration = (
        changed_item.get("purpose") == "migration"
        or "migrations" in parts
        or ("alembic" in parts and "versions" in parts)
    )
    if not is_migration:
        return
    source = _bounded_source(
        database.root, changed_path, source_cache, graph, limits, budget
    )
    if source is None:
        return
    identifiers = _migration_identifiers(changed_path, source)
    for test_path in test_paths:
        if evidence_store.exhausted:
            break
        if not budget.consume(
            "migration_candidates", "max_migration_candidates_scanned"
        ):
            break
        if (
            test_path not in candidates
            and len(candidates) >= limits.max_relevant_test_candidates
        ):
            budget.mark("max_relevant_test_candidates")
            break
        test_source = _bounded_source(
            database.root, test_path, source_cache, graph, limits, budget
        )
        if test_source is None:
            break
        lowered = test_source.lower()
        exact = sorted(
            identifier
            for identifier in identifiers
            if re.search(
                rf"(?<![a-z0-9_]){re.escape(identifier)}(?![a-z0-9_])",
                lowered,
            )
        )
        migration_named = "migration" in PurePosixPath(test_path).name.lower()
        api_usage = bool(
            re.search(r"\balembic\b|command\.(?:upgrade|downgrade)", lowered)
        )
        if exact:
            confidence: Confidence = "high"
            reason = (
                "Migration-suite evidence: test source references migration identifier(s) "
                + ", ".join(exact[:3])
                + "."
            )
        elif migration_named and api_usage:
            confidence = "medium"
            reason = "Migration-suite evidence: migration-oriented test naming and API usage."
        elif migration_named or api_usage:
            confidence = "low"
            reason = "Migration-suite evidence: weak migration naming or API evidence."
        else:
            continue
        _merge_test(
            candidates,
            test_path,
            changed_path,
            confidence,
            bool(exact),
            reason,
            {
                "kind": "migration-suite",
                "path": test_path,
                "target": changed_path,
                "identifiers": exact[:3],
                "migration_named": migration_named,
                "api_usage": api_usage,
            },
            evidence_store,
        )


def _migration_identifiers(path: str, source: str) -> set[str]:
    identifiers: set[str] = set()
    stem = PurePosixPath(path).stem.lower()
    if re.match(r"^(?:[0-9]+|[0-9a-f]{6,})[_-]", stem):
        identifiers.add(stem)
    assignment = re.compile(
        r"(?m)^\s*(?:revision|down_revision)\s*(?::[^=]+)?=\s*['\"]([^'\"]+)['\"]"
    )
    for value in assignment.findall(source):
        normalized = value.strip().lower()
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,127}", normalized):
            identifiers.add(normalized)
    return identifiers


def _link_route_api_tests(
    database: IndexDatabase,
    candidates: dict[str, dict[str, Any]],
    test_paths: list[str],
    source_cache: dict[str, str],
    changed_path: str,
    changed_item: dict[str, Any],
    graph: _GraphBudget,
    limits: TestImpactLimits,
    budget: _AnalysisBudget,
    evidence_store: _EvidenceStore,
) -> None:
    if not changed_item.get("indexed"):
        return
    direct, indirect = _bounded_dependents(
        database,
        changed_path,
        graph,
        limits,
        budget,
        max_indirect_edges=0,
        max_direct_edges=limits.max_direct_edges_per_file,
    )
    related_paths = {changed_path, *(str(row["path"]) for row in direct), *indirect}
    route_literals: set[str] = set()
    route_files: set[str] = set()
    for path in sorted(related_paths):
        for row in database.connection.execute(
            """SELECT r.path FROM routes r JOIN files f ON f.id=r.file_id
               WHERE f.path=? ORDER BY r.line""",
            (path,),
        ):
            if not budget.consume_shared(
                "route_candidates", "route_rows", "max_route_candidates_scanned"
            ):
                return
            literal = str(row["path"])
            if literal:
                route_literals.add(literal)
                route_files.add(path)
    if not route_literals:
        return
    route_tokens = sorted(
        {
            literal.split("{", 1)[0].rstrip("/") or "/"
            for literal in route_literals
            if literal.startswith("/")
        },
        key=lambda value: (-len(value), value),
    )
    for test_path in test_paths:
        if not budget.consume_shared(
            "route_candidates", "test_sources", "max_route_candidates_scanned"
        ):
            return
        if test_path not in candidates and len(candidates) >= limits.max_relevant_test_candidates:
            budget.mark("max_relevant_test_candidates")
            break
        source = _bounded_source(
            database.root, test_path, source_cache, graph, limits, budget
        )
        if source is None:
            break
        matches = _source_route_matches(source, route_tokens)
        if not matches:
            continue
        _merge_test(
            candidates,
            test_path,
            changed_path,
            "medium",
            False,
            f"Test source contains the exact changed route path {matches[0]}.",
            {
                "kind": "route-literal",
                "path": test_path,
                "target": changed_path,
                "routes": matches[:10],
            },
            evidence_store,
        )
        if evidence_store.exhausted:
            return

    api_modules: set[str] = set()
    rows = database.connection.execute(
        """SELECT path FROM files
           WHERE is_test=0 AND language IN ('javascript', 'jsx', 'typescript', 'tsx')
           ORDER BY CASE WHEN lower(path) LIKE '%api%' THEN 0 ELSE 1 END, path
           LIMIT ?""",
        (limits.max_route_candidates_scanned + 1,),
    )
    for row in rows:
        if not budget.consume_shared(
            "route_candidates", "frontend_api_modules", "max_route_candidates_scanned"
        ):
            return
        path = str(row["path"])
        source = _bounded_source(database.root, path, source_cache, graph, limits, budget)
        if source is None:
            break
        if _source_route_matches(source, route_tokens):
            api_modules.add(path)
    for api_path in sorted(api_modules):
        for row in database.connection.execute(
            """SELECT DISTINCT sf.path FROM dependencies d
               JOIN files sf ON sf.id=d.source_file_id
               LEFT JOIN files tf ON tf.id=d.target_file_id
               LEFT JOIN symbols ts ON ts.id=d.target_symbol_id
               LEFT JOIN files tsf ON tsf.id=ts.file_id
               WHERE sf.is_test=1 AND COALESCE(tf.path, tsf.path)=?
               ORDER BY sf.path""",
            (api_path,),
        ):
            if not budget.consume_shared(
                "route_candidates", "dependency_rows", "max_route_candidates_scanned"
            ):
                return
            test_path = str(row["path"])
            if test_path not in candidates and len(candidates) >= limits.max_relevant_test_candidates:
                budget.mark("max_relevant_test_candidates")
                break
            if not is_executable_test_path(test_path):
                continue
            _merge_test(
                candidates,
                test_path,
                changed_path,
                "medium",
                True,
                f"Route/API evidence: test imports client module {api_path} that references affected routes.",
                {
                    "kind": "route-api-client",
                    "path": test_path,
                    "target": changed_path,
                    "api_module": api_path,
                    "route_files": sorted(route_files),
                },
                evidence_store,
            )
            if evidence_store.exhausted:
                return
    for test_path in test_paths:
        if not budget.consume_shared(
            "route_candidates", "e2e_candidates", "max_route_candidates_scanned"
        ):
            return
        if test_path not in candidates and len(candidates) >= limits.max_relevant_test_candidates:
            budget.mark("max_relevant_test_candidates")
            break
        lower_parts = {part.lower() for part in PurePosixPath(test_path).parts}
        if "e2e" not in lower_parts and "playwright" not in lower_parts:
            continue
        source = _bounded_source(
            database.root, test_path, source_cache, graph, limits, budget
        )
        if source is None:
            break
        matches = _source_route_matches(source, route_tokens)
        if not matches:
            continue
        _merge_test(
            candidates,
            test_path,
            changed_path,
            "medium",
            False,
            "Route/API evidence: E2E test exercises affected route literal(s).",
            {
                "kind": "route-e2e",
                "path": test_path,
                "target": changed_path,
                "routes": matches[:10],
            },
            evidence_store,
        )
        if evidence_store.exhausted:
            return



def _source_route_matches(source: str, route_tokens: list[str]) -> list[str]:
    matches: list[str] = []
    for token in route_tokens:
        if token == "/":
            continue
        pattern = (
            rf"(?<![A-Za-z0-9_-]){re.escape(token)}"
            r"(?=$|[/?&#'\"}\s)])"
        )
        if re.search(pattern, source):
            matches.append(token)
    return matches


def _bounded_source(
    root: Path,
    path: str,
    source_cache: dict[str, str],
    graph: _GraphBudget,
    limits: TestImpactLimits,
    budget: _AnalysisBudget,
) -> str | None:
    cached = source_cache.get(path)
    if cached is not None:
        return cached
    if not budget.within_time():
        graph.mark("max_analysis_seconds")
        return None
    if graph.nodes_visited >= limits.max_graph_nodes:
        graph.mark("max_graph_nodes")
        return None
    graph.nodes_visited += 1
    source = _read_test_source(root / path)
    source_cache[path] = source
    return source


def _test_priority(item: dict[str, Any]) -> int:
    kinds = {str(evidence.get("kind")) for evidence in item.get("evidence", [])}
    if "changed-test-file" in kinds or "dependency" in kinds:
        return 0
    if "migration-suite" in kinds or "route-api-client" in kinds or "route-e2e" in kinds:
        return 1
    if "dependency-reachability" in kinds:
        return 2
    return 3

def _merge_test(
    candidates: dict[str, dict[str, Any]],
    test_path: str,
    changed_path: str,
    confidence: Confidence,
    structural: bool,
    reason: str,
    evidence: dict[str, Any],
    evidence_store: _EvidenceStore,
) -> bool:
    item = candidates.setdefault(
        test_path,
        {
            "file": test_path,
            "confidence": confidence,
            "discovered": True,
            "structurally_related": structural,
            "coverage": "unknown",
            "reasons": [],
            "affected_changed_files": [],
            "command_ids": [],
        },
    )
    if _CONFIDENCE_RANK[confidence] > _CONFIDENCE_RANK[str(item["confidence"])]:
        item["confidence"] = confidence
    item["structurally_related"] = bool(item["structurally_related"] or structural)
    if reason not in item["reasons"]:
        item["reasons"].append(reason)
    if changed_path not in item["affected_changed_files"]:
        item["affected_changed_files"].append(changed_path)
        item["affected_changed_files"].sort()
    return evidence_store.consider(test_path, evidence)


def _uncovered_areas(
    changed: list[dict[str, Any]], tests: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    meaningful = {
        path
        for test in tests
        if test["confidence"] in {"high", "medium"}
        for path in test["affected_changed_files"]
    }
    gaps: list[dict[str, Any]] = []
    for item in changed:
        path = str(item["path"])
        if item["is_test"] or item.get("purpose") in {"documentation", "configuration"}:
            continue
        if path in meaningful:
            continue
        gaps.append(
            {
                "path": path,
                "area": str(item.get("purpose") or "production file"),
                "confidence": "high" if not tests else "medium",
                "reason": (
                    "No discovered tests were attributable to this changed production area."
                    if not tests
                    else "No high- or medium-confidence test relationship was detected for this changed production area."
                ),
                "coverage": "unknown",
                "evidence": {
                    "kind": "absence-of-matching-static-evidence",
                    "reviewed_relevant_tests": len(tests),
                },
            }
        )
    return gaps


def _command(
    framework: str,
    scope: str,
    argv: list[str],
    working_directory: str,
    related_tests: list[str],
    reason: str,
) -> dict[str, Any]:
    return {
        "id": "",
        "framework": framework,
        "scope": scope,
        "command": shlex.join(argv),
        "argv": argv,
        "working_directory": working_directory,
        "related_tests": related_tests,
        "reason": reason,
    }


def _gradle_commands(
    paths: set[str], test_paths: set[str], relevant_paths: set[str]
) -> list[dict[str, Any]]:
    manifests = sorted(
        path_value
        for path_value in paths
        if Path(path_value).name in {"build.gradle", "build.gradle.kts"}
    )
    if not manifests:
        return []
    if "gradlew.bat" in paths:
        executable = "gradlew.bat"
    elif "gradlew" in paths:
        executable = "./gradlew"
    else:
        executable = "gradle"
    gradle_tests = sorted(
        path_value
        for path_value in test_paths
        if Path(path_value).suffix.lower() in {".java", ".kt", ".kts"}
    )
    selected = sorted(set(gradle_tests) & relevant_paths)
    return [
        _command(
            "gradle",
            "broad",
            [executable, "test"],
            ".",
            selected or gradle_tests,
            "Recommend the existing Gradle test task; no test configuration is modified.",
        )
    ]


def _maestro_commands(
    paths: set[str], test_paths: set[str], relevant_paths: set[str]
) -> list[dict[str, Any]]:
    flows = sorted(
        path_value
        for path_value in paths
        if ".maestro" in PurePosixPath(path_value).parts
        and Path(path_value).suffix.lower() in {".yaml", ".yml"}
    )
    if not flows:
        return []
    selected = sorted((set(flows) & relevant_paths) or (set(flows) & test_paths))
    target = selected[0] if len(selected) == 1 else ".maestro"
    return [
        _command(
            "maestro",
            "targeted" if selected else "broad",
            ["maestro", "test", target],
            ".",
            selected or flows,
            "Recommend the repository's existing Maestro flow definitions.",
        )
    ]


def _dedupe_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in commands:
        key = (str(item["working_directory"]), str(item["command"]))
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _read_test_source(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_TEST_SOURCE_BYTES:
            return ""
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _semantic_stem(path: str) -> str:
    stem = Path(path).stem.lower()
    stem = re.sub(r"^(?:test_|spec_)", "", stem)
    stem = re.sub(r"(?:\.test|\.spec|_test|_spec)$", "", stem)
    return re.sub(r"[^a-z0-9]+", "", stem)


def _overall_confidence(changed: list[dict[str, Any]], tests: list[dict[str, Any]]) -> str:
    if not changed or any(not item["indexed"] for item in changed):
        return "low"
    if any(item["confidence"] == "high" for item in tests):
        return "high"
    return "medium" if tests else "low"


def _truncation_record(total: int, returned: int, limit: int) -> dict[str, Any]:
    return {
        "total_discovered": total,
        "total_returned": returned,
        "truncated": total > returned,
        "limit": limit,
    }


def _serialize_report(report: dict[str, Any], mode: OutputMode) -> str:
    if mode == "pretty_json":
        return json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    return json.dumps(
        report,
        sort_keys=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _stabilize_output_size(report: dict[str, Any], mode: OutputMode) -> int:
    output = report["truncation"]["output"]
    for _ in range(32):
        size = len(_serialize_report(report, mode).encode("utf-8"))
        if output["total_returned"] == size:
            return size
        output["total_returned"] = size
    return len(_serialize_report(report, mode).encode("utf-8"))


def _fit_report_to_output_budget(
    report: dict[str, Any], limit: int, mode: OutputMode = "compact_json"
) -> None:
    output = report["truncation"]["output"]
    output.update(
        {
            "measurement": (
                "rendered_pretty_json_utf8_bytes"
                if mode == "pretty_json"
                else "canonical_compact_json_utf8_bytes"
            ),
            "mode": mode,
            "total_discovered": 0,
            "total_returned": 0,
            "truncated": False,
            "limit": limit,
        }
    )
    for _ in range(32):
        size = _stabilize_output_size(report, mode)
        if output["total_discovered"] == size:
            break
        output["total_discovered"] = size
    full_size = len(_serialize_report(report, mode).encode("utf-8"))
    output["total_discovered"] = full_size
    output["total_returned"] = full_size
    if full_size <= limit:
        _stabilize_output_size(report, mode)
        return

    output["truncated"] = True
    report["analysis_status"] = "truncated"
    buckets = report["impacted_areas"]
    while _stabilize_output_size(report, mode) > limit:
        removed = False
        for bucket in ("low_confidence", "medium_confidence"):
            if buckets[bucket]:
                buckets[bucket].pop()
                area_meta = report["truncation"]["impacted_areas"]
                area_meta["total_returned"] = sum(len(values) for values in buckets.values())
                area_meta["truncated"] = True
                area_meta.setdefault("reasons", []).append("max_output_bytes")
                removed = True
                break
        if removed:
            continue
        for test in reversed(report["existing_tests"]):
            if test.get("evidence"):
                test["evidence"].pop()
                test["evidence_truncated"] = True
                evidence_meta = report["truncation"]["relevant_tests"]["evidence"]
                evidence_meta["total_returned"] = max(
                    0, int(evidence_meta["total_returned"]) - 1
                )
                evidence_meta["truncated"] = True
                removed = True
                break
        if removed:
            continue
        if report["uncovered_areas"]:
            report["uncovered_areas"].pop()
            removed = True
        elif report["existing_tests"]:
            report["existing_tests"].pop()
            test_meta = report["truncation"]["relevant_tests"]
            test_meta["total_returned"] = len(report["existing_tests"])
            test_meta["truncated"] = True
            test_meta.setdefault("reasons", []).append("max_output_bytes")
            evidence_meta = test_meta["evidence"]
            evidence_meta["total_returned"] = sum(
                len(test["evidence"]) for test in report["existing_tests"]
            )
            evidence_meta["truncated"] = True
            removed = True
        elif report["recommended_commands"]:
            broad_index = next(
                (
                    index
                    for index in range(len(report["recommended_commands"]) - 1, -1, -1)
                    if report["recommended_commands"][index]["scope"] == "broad"
                ),
                len(report["recommended_commands"]) - 1,
            )
            report["recommended_commands"].pop(broad_index)
            command_meta = report["truncation"]["commands"]
            command_meta["total_returned"] = len(report["recommended_commands"])
            command_meta["truncated"] = True
            command_meta.setdefault("reasons", []).append("max_output_bytes")
            removed = True
        elif buckets["high_confidence"]:
            buckets["high_confidence"].pop()
            area_meta = report["truncation"]["impacted_areas"]
            area_meta["total_returned"] = sum(len(values) for values in buckets.values())
            area_meta["truncated"] = True
            area_meta.setdefault("reasons", []).append("max_output_bytes")
            removed = True
        elif len(report["warnings"]) > 1:
            report["warnings"].pop()
            removed = True
        if not removed:
            break

    if _stabilize_output_size(report, mode) > limit:
        original = report
        truncation = original["truncation"]
        area_meta = dict(truncation["impacted_areas"])
        area_meta.update(total_returned=0, truncated=bool(area_meta["total_discovered"]))
        test_meta = dict(truncation["relevant_tests"])
        evidence_meta = dict(test_meta["evidence"])
        evidence_meta.update(
            total_returned=0,
            truncated=bool(evidence_meta["total_discovered"]),
        )
        test_meta.update(
            total_returned=0,
            truncated=bool(test_meta["total_discovered"]),
            evidence=evidence_meta,
        )
        command_meta = dict(truncation["commands"])
        command_meta.update(
            total_returned=0,
            truncated=bool(command_meta["total_discovered"]),
        )
        replacement: dict[str, Any] = {
            "schema_version": TEST_IMPACT_SCHEMA_VERSION,
            "repository": ".",
            "supported": original["supported"],
            "analysis_status": "truncated",
            "change_source": original["change_source"],
            "changed_files": [],
            "impacted_areas": {
                "high_confidence": [],
                "medium_confidence": [],
                "low_confidence": [],
            },
            "existing_tests": [],
            "uncovered_areas": [],
            "recommended_commands": [],
            "evidence": [],
            "confidence": "low",
            "limits": original["limits"],
            "truncation": {
                "change_selection": truncation["change_selection"],
                "analysis": truncation["analysis"],
                "graph": truncation["graph"],
                "impacted_areas": area_meta,
                "relevant_tests": test_meta,
                "commands": command_meta,
                "output": {
                    "measurement": output["measurement"],
                    "mode": mode,
                    "total_discovered": full_size,
                    "total_returned": 0,
                    "truncated": True,
                    "limit": limit,
                },
            },
            "warnings": [
                "The output budget required a schema-stable summary; detailed rows "
                "and recommended commands were omitted."
            ],
        }
        if "freshness" in original:
            replacement["freshness"] = original["freshness"]
        report.clear()
        report.update(replacement)
        output = report["truncation"]["output"]

    output["total_discovered"] = max(full_size, int(output["total_discovered"]))
    _stabilize_output_size(report, mode)
