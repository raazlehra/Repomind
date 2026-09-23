from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

import repomind.test_impact as test_impact_module
from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.test_impact import TestImpactLimits as ImpactLimits
from repomind.test_impact import analyze_test_impact


@pytest.mark.parametrize("input_kind", ["sequence", "generator"])
@pytest.mark.parametrize("count", [1, 2, 3])
def test_supplied_change_boundaries_report_exact_or_lower_bound_totals(
    input_kind: str,
    count: int,
) -> None:
    values = [f"app/file_{index}.py" for index in range(count)]
    supplied = values if input_kind == "sequence" else (value for value in values)
    limits = ImpactLimits(max_changed_files=2)
    budget = test_impact_module._AnalysisBudget.start(limits)

    result = test_impact_module._bounded_supplied_changes(supplied, limits, budget)

    overflow = count > limits.max_changed_files
    assert result.paths == values[: limits.max_changed_files]
    assert result.total_discovered == count
    assert result.processed == min(count, limits.max_changed_files)
    assert result.discovery_complete is not overflow
    assert result.total_discovered_is_lower_bound is (
        input_kind == "generator" and overflow
    )
    assert result.reasons == (["max_changed_files"] if overflow else [])
    assert budget.reasons == (
        {"max_changed_files": limits.max_changed_files} if overflow else {}
    )


@pytest.mark.parametrize(
    ("field", "valid", "invalid"),
    [
        ("max_evidence_candidates_scanned", 100_000, 100_001),
        ("max_project_files_scanned", 20_000, 20_001),
        ("max_git_output_bytes", 8_000_000, 8_000_001),
        ("max_git_stderr_bytes", 65_536, 65_537),
    ],
)
def test_remaining_integer_hard_caps_accept_boundary_and_reject_overflow(
    field: str,
    valid: int,
    invalid: int,
) -> None:
    ImpactLimits(**{field: valid})
    with pytest.raises(ValueError, match=f"{field} must be at most"):
        ImpactLimits(**{field: invalid})


def test_output_and_duration_configuration_boundaries() -> None:
    ImpactLimits(max_output_bytes=4_096, max_analysis_seconds=60)
    with pytest.raises(ValueError, match="max_output_bytes must be at least 4096"):
        ImpactLimits(max_output_bytes=4_095)
    with pytest.raises(ValueError, match="max_analysis_seconds"):
        ImpactLimits(max_analysis_seconds=60.000_001)


def test_safe_path_normalization_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    inside = root / "folder" / "inside.py"

    assert test_impact_module._normalize_input_path(
        root, "folder/naïve file [1].py", 1_000
    ) == "folder/naïve file [1].py"
    assert test_impact_module._normalize_input_path(
        root, str(inside), 1_000
    ) == "folder/inside.py"

    for raw in (
        "",
        "   ",
        "../outside.py",
        "C:outside.py",
        str(tmp_path / "outside.py"),
    ):
        with pytest.raises(ValueError):
            test_impact_module._normalize_input_path(root, raw, 1_000)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("bad" + chr(0) + ".py", "NUL"),
        ("bad" + chr(0xD800) + ".py", "UTF-8"),
    ],
)
def test_malformed_supplied_paths_are_rejected_as_value_errors(
    tmp_path: Path,
    raw: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        test_impact_module._normalize_input_path(tmp_path, raw, 1_000)


@pytest.mark.parametrize(
    ("mode", "payload", "expected"),
    [
        ("status", b" M folder/file name.py\0", ["folder/file name.py"]),
        ("status", b"R  new name.py\0old name.py\0", ["new name.py"]),
        ("diff", b"M\0folder/file name.py\0", ["folder/file name.py"]),
        ("diff", b"R100\0old name.py\0new name.py\0", ["new name.py"]),
    ],
)
def test_git_path_parser_handles_every_stream_split(
    mode: str,
    payload: bytes,
    expected: list[str],
) -> None:
    for split in range(1, len(payload)):
        parser = test_impact_module._GitPathParser(mode, 10, 1_000)
        assert parser.feed(payload[:split])
        assert parser.feed(payload[split:])
        parser.finish()
        assert parser.paths == expected
        assert parser.total_discovered == len(expected)
        assert parser.malformed is False


@pytest.mark.parametrize(
    ("mode", "payload"),
    [
        ("status", b" M incomplete.py"),
        ("diff", b"R100\0old.py\0incomplete.py"),
    ],
)
def test_git_path_parser_marks_incomplete_records(mode: str, payload: bytes) -> None:
    parser = test_impact_module._GitPathParser(mode, 10, 1_000)
    assert parser.feed(payload)

    parser.finish()

    assert parser.malformed is True


def test_git_diff_rename_source_respects_path_length_limit() -> None:
    parser = test_impact_module._GitPathParser("diff", 10, 5)

    with pytest.raises(ValueError, match="max_path_length"):
        parser.feed(b"R100\0source-too-long.py\0x.py\0")


def test_overlapping_git_caps_report_every_reached_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"?? f0.py\0?? f1.py\0?? f2.py\0"
    process = _FakeProcess(stdout=payload, stderr=b"", returncode=0)
    monkeypatch.setattr(
        test_impact_module.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    limits = ImpactLimits(max_changed_files=1, max_git_output_bytes=20)
    budget = test_impact_module._AnalysisBudget.start(limits)

    result = test_impact_module._bounded_git_changes(
        tmp_path,
        ["status"],
        "status",
        limits,
        budget,
    )

    assert result.paths == ["f0.py"]
    assert result.total_discovered == 2
    assert result.stdout_bytes == 20
    assert result.reasons == ["max_changed_files", "max_git_output_bytes"]
    assert budget.reasons == {
        "max_changed_files": 1,
        "max_git_output_bytes": 20,
    }


def test_git_process_failure_is_reported_without_leaking_stderr(tmp_path: Path) -> None:
    limits = ImpactLimits()
    budget = test_impact_module._AnalysisBudget.start(limits)

    with pytest.raises(ValueError, match="Git command failed"):
        test_impact_module._bounded_git_changes(
            tmp_path,
            ["not-a-real-git-command"],
            "status",
            limits,
            budget,
        )


def test_git_timeout_is_reported_and_process_is_terminated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(stdout=b"", stderr=b"", returncode=None)
    monkeypatch.setattr(
        test_impact_module.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(test_impact_module.time, "perf_counter", lambda: 100.0)
    limits = ImpactLimits(max_analysis_seconds=1)
    budget = test_impact_module._AnalysisBudget(limits, 0.0, {}, {}, {})

    result = test_impact_module._bounded_git_changes(
        tmp_path,
        ["status"],
        "status",
        limits,
        budget,
    )

    assert result.reasons == ["max_analysis_seconds"]
    assert result.discovery_complete is False
    assert result.total_discovered_is_lower_bound is True
    assert process.terminated is True


def test_stderr_drain_retains_only_its_budget() -> None:
    state: dict[str, int | bool] = {"retained": 0, "exceeded": False}
    stop = test_impact_module.threading.Event()

    test_impact_module._drain_stderr(io.BytesIO(b"0123456789"), 4, state, stop)

    assert state == {"retained": 4, "exceeded": True}
    assert stop.is_set()


def test_evidence_retention_cap_keeps_best_candidate_and_complete_counts(
    tmp_path: Path,
) -> None:
    repo = _evidence_repository(tmp_path / "retention")
    limits = ImpactLimits(
        max_evidence_per_result=10,
        max_evidence_candidates=1,
        max_evidence_candidates_scanned=10,
    )

    first = _analyze(repo, limits)
    second = _analyze(repo, limits)
    test = first["existing_tests"][0]
    metadata = first["truncation"]["relevant_tests"]["evidence"]

    assert test["evidence"] == [
        {
            "kind": "dependency",
            "path": "tests/test_all.py",
            "target": "app/a.py",
            "relationship": "imports",
            "source": "import:app.a",
        }
    ]
    assert test["evidence_total"] == 6
    assert test["evidence_truncated"] is True
    assert metadata == {
        "total_discovered": 6,
        "total_returned": 1,
        "truncated": True,
        "limit_per_result": 10,
        "candidate_limit": 1,
        "candidate_limit_reached": True,
        "discovery_complete": True,
        "total_discovered_is_lower_bound": False,
        "count_scope": "returned_relevant_tests",
    }
    assert second["existing_tests"][0]["evidence"] == test["evidence"]
    assert second["truncation"]["relevant_tests"]["evidence"] == metadata


def test_evidence_scan_cap_reports_incomplete_lower_bound(tmp_path: Path) -> None:
    repo = _evidence_repository(tmp_path / "scan")
    limits = ImpactLimits(
        max_evidence_per_result=10,
        max_evidence_candidates=10,
        max_evidence_candidates_scanned=1,
    )

    report = _analyze(repo, limits)
    metadata = report["truncation"]["relevant_tests"]["evidence"]

    assert metadata == {
        "total_discovered": 1,
        "total_returned": 1,
        "truncated": True,
        "limit_per_result": 10,
        "candidate_limit": 10,
        "candidate_limit_reached": False,
        "discovery_complete": False,
        "total_discovered_is_lower_bound": True,
        "count_scope": "returned_relevant_tests",
    }
    assert report["analysis_status"] == "truncated"


class _FakeProcess:
    def __init__(
        self,
        *,
        stdout: bytes,
        stderr: bytes,
        returncode: int | None,
    ) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0 if self.returncode is None else self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.terminated = True
        self.returncode = -9


def _evidence_repository(repo: Path) -> Path:
    for index, name in enumerate(("a", "b", "c")):
        _write(repo / "app" / f"{name}.py", f"VALUE = {index}\n")
    _write(
        repo / "tests" / "test_all.py",
        "from app.a import VALUE as A\n"
        "from app.b import VALUE as B\n"
        "from app.c import VALUE as C\n\n"
        "def test_all():\n"
        "    assert A + B + C >= 0\n",
    )
    Indexer(repo).initialize()
    return repo


def _analyze(repo: Path, limits: ImpactLimits) -> dict[str, Any]:
    with IndexDatabase(repo) as database:
        return analyze_test_impact(
            database,
            ["app/c.py", "app/b.py", "app/a.py"],
            limits=limits,
        )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
