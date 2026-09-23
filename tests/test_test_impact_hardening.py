from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

import repomind.test_impact as test_impact_module
from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.mcp import create_server
from repomind.queries import impact
from repomind.services import test_impact as service_test_impact
from repomind.test_impact import TestImpactLimits as ImpactLimits
from repomind.test_impact import analyze_test_impact, render_test_impact


def test_mixed_vitest_and_playwright_are_separate_commands(tmp_path: Path) -> None:
    repo = tmp_path / "mixed frameworks"
    _write(
        repo / "frontend" / "package.json",
        json.dumps(
            {
                "scripts": {
                    "test": "vitest run src",
                    "test:jest": "jest",
                    "test:e2e": "playwright test",
                },
                "devDependencies": {
                    "vitest": "5",
                    "jest": "30",
                    "@playwright/test": "1",
                },
            }
        ),
    )
    _write(repo / "frontend" / "src" / "api.ts", "export const api = true;\n")
    _write(
        repo / "frontend" / "src" / "api.test.ts",
        "import { describe, it } from 'vitest';\nimport { api } from './api';\n"
        "describe('api', () => it('works', () => api));\n",
    )
    _write(
        repo / "frontend" / "src" / "legacy.spec.ts",
        "import { describe } from '@jest/globals';\ndescribe('legacy', () => {});\n",
    )
    _write(
        repo / "frontend" / "e2e" / "critical-workflows.spec.ts",
        "import { test } from '@playwright/test';\ntest('critical', async () => {});\n",
    )
    Indexer(repo).initialize()

    report = _analyze(
        repo,
        [
            "frontend/src/api.test.ts",
            "frontend/src/legacy.spec.ts",
            "frontend/e2e/critical-workflows.spec.ts",
        ],
    )
    targeted = [item for item in report["recommended_commands"] if item["scope"] == "targeted"]
    vitest = next(item for item in targeted if item["framework"] == "vitest")
    jest = next(item for item in targeted if item["framework"] == "jest")
    playwright = next(item for item in targeted if item["framework"] == "playwright")

    assert vitest["related_tests"] == ["frontend/src/api.test.ts"]
    assert jest["related_tests"] == ["frontend/src/legacy.spec.ts"]
    assert playwright["related_tests"] == ["frontend/e2e/critical-workflows.spec.ts"]
    assert "npm --prefix frontend run test -- src/api.test.ts" in vitest["command"]
    assert (
        "npm --prefix frontend run test:e2e -- e2e/critical-workflows.spec.ts"
        in playwright["command"]
    )


def test_nearest_nested_package_owns_javascript_test(tmp_path: Path) -> None:
    repo = tmp_path / "monorepo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "jest"}, "devDependencies": {"jest": "1"}}),
    )
    _write(
        repo / "packages" / "web" / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "5"}}),
    )
    _write(repo / "packages" / "web" / "src" / "widget.ts", "export const widget = true;\n")
    _write(
        repo / "packages" / "web" / "src" / "widget.test.ts",
        "import { widget } from './widget';\ntest('widget', () => widget);\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["packages/web/src/widget.ts"])
    targeted = [item for item in report["recommended_commands"] if item["scope"] == "targeted"]

    assert len(targeted) == 1
    assert targeted[0]["framework"] == "vitest"
    assert "npm --prefix packages/web" in targeted[0]["command"]


def test_python_boundary_and_helper_under_tests_are_not_targets(tmp_path: Path) -> None:
    repo = tmp_path / "python monorepo"
    _write(repo / "backend" / "pyproject.toml", "[project]\nname='backend'\nversion='1'\n")
    _write(repo / "backend" / "app" / "service.py", "def value():\n    return 1\n")
    _write(
        repo / "backend" / "tests" / "test_service.py",
        "from app.service import value\n\ndef test_value():\n    assert value()\n",
    )
    _write(repo / "backend" / "tests" / "e2e_server.py", "def serve():\n    return True\n")
    _write(repo / "backend" / "tests" / "conftest.py", "VALUE = 1\n")
    Indexer(repo).initialize()

    report = _analyze(repo, ["backend/app/service.py"])
    command = next(
        item
        for item in report["recommended_commands"]
        if item["scope"] == "targeted" and item["framework"] == "pytest"
    )

    assert command["working_directory"] == "backend"
    assert command["related_tests"] == ["backend/tests/test_service.py"]
    assert "tests/test_service.py" in command["command"]
    assert "e2e_server.py" not in json.dumps(report)
    with IndexDatabase(repo) as database:
        helper = database.file_by_path("backend/tests/e2e_server.py")
    assert helper is not None
    assert bool(helper["is_test"]) is False


def test_migration_only_change_links_migration_suite(tmp_path: Path) -> None:
    repo = tmp_path / "migration"
    _write(
        repo / "backend" / "alembic" / "versions" / "0004_payment_idempotency.py",
        'from alembic import op\nrevision = "0004_payment_idempotency"\n',
    )
    _write(
        repo / "backend" / "tests" / "test_migrations.py",
        "from alembic import command\n\n"
        "def test_0004():\n    command.upgrade(None, '0004_payment_idempotency')\n",
    )
    Indexer(repo).initialize()

    report = _analyze(
        repo, ["backend/alembic/versions/0004_payment_idempotency.py"]
    )
    test = _by_file(report, "backend/tests/test_migrations.py")

    assert test["confidence"] == "high"
    assert any(row["kind"] == "migration-suite" for row in test["evidence"])
    assert any("Migration-suite evidence" in reason for reason in test["reasons"])


def test_backend_service_links_bounded_backend_api_and_e2e_tests(tmp_path: Path) -> None:
    repo = tmp_path / "cross stack"
    _write(repo / "backend" / "app" / "services.py", "def create_payment():\n    return True\n")
    _write(
        repo / "backend" / "app" / "main.py",
        "from fastapi import FastAPI\nfrom app.services import create_payment\n"
        "app = FastAPI()\n@app.post('/api/payments')\n"
        "def pay():\n    return create_payment()\n",
    )
    _write(
        repo / "backend" / "tests" / "test_business_logic.py",
        "from app.services import create_payment\n\ndef test_payment():\n    assert create_payment()\n",
    )
    _write(
        repo / "backend" / "tests" / "test_migrations.py",
        "from app.services import create_payment\n\ndef test_runtime_parity():\n    assert create_payment()\n",
    )
    _write(
        repo / "frontend" / "package.json",
        json.dumps(
            {
                "scripts": {"test": "vitest run", "test:e2e": "playwright test"},
                "devDependencies": {"vitest": "5", "@playwright/test": "1"},
            }
        ),
    )
    _write(
        repo / "frontend" / "src" / "api.ts",
        "export const createPayment = () => fetch('/api/payments');\n",
    )
    _write(
        repo / "frontend" / "src" / "api.test.ts",
        "import { describe } from 'vitest';\nimport { createPayment } from './api';\n"
        "describe('payment', () => createPayment);\n",
    )
    _write(
        repo / "frontend" / "e2e" / "critical-workflows.spec.ts",
        "import { test } from '@playwright/test';\n"
        "test('pay', async ({ page }) => page.waitForResponse('/api/payments'));\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["backend/app/services.py"])
    found = {item["file"] for item in report["existing_tests"]}

    assert {
        "backend/tests/test_business_logic.py",
        "backend/tests/test_migrations.py",
        "frontend/src/api.test.ts",
        "frontend/e2e/critical-workflows.spec.ts",
    } <= found
    for item in report["existing_tests"]:
        assert item["reasons"]
        assert item["confidence"] in {"high", "medium", "low"}


def test_rename_uses_destination_path(tmp_path: Path) -> None:
    repo = tmp_path / "rename"
    _write(repo / "app" / "old.py", "value = 1\n")
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "RepoMind Tests")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    Indexer(repo).initialize()
    _git(repo, "mv", "app/old.py", "app/new.py")

    report = service_test_impact(str(repo), base="HEAD")

    assert [item["path"] for item in report["changed_files"]] == ["app/new.py"]


def test_git_working_tree_discovery_is_bounded_and_deterministic(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "bounded git discovery"
    for index in reversed(range(64)):
        _write(repo / "changes" / f"file_{index:03d}.py", f"value = {index}\n")
    _git(repo, "init")
    limits = ImpactLimits(max_changed_files=3)

    first_budget = test_impact_module._AnalysisBudget.start(limits)
    first_paths, source, warnings, first_stats = test_impact_module._select_changes(
        repo,
        None,
        None,
        limits,
        first_budget,
    )
    second_budget = test_impact_module._AnalysisBudget.start(limits)
    second_paths, _, _, second_stats = test_impact_module._select_changes(
        repo,
        None,
        None,
        limits,
        second_budget,
    )

    expected = [
        "changes/file_000.py",
        "changes/file_001.py",
        "changes/file_002.py",
    ]
    assert first_paths == expected
    assert second_paths == expected
    assert source == "working tree"
    assert warnings == ["Changed-file selection truncated by max_changed_files."]
    assert {
        key: first_stats[key]
        for key in (
            "total_discovered",
            "total_returned",
            "truncated",
            "limit",
            "processed",
            "discovery_complete",
            "total_discovered_is_lower_bound",
            "reasons",
            "reason",
            "duplicates_or_internal_paths_removed",
        )
    } == {
        "total_discovered": 4,
        "total_returned": 3,
        "truncated": True,
        "limit": 3,
        "processed": 3,
        "discovery_complete": False,
        "total_discovered_is_lower_bound": True,
        "reasons": ["max_changed_files"],
        "reason": "max_changed_files",
        "duplicates_or_internal_paths_removed": 0,
    }
    assert first_stats["git"]["stdout_bytes_processed"] > 0
    assert first_stats["git"]["stdout_bytes_processed"] <= limits.max_git_output_bytes
    assert first_stats["git"]["stdout_byte_limit"] == limits.max_git_output_bytes
    assert first_stats["git"]["stderr_bytes_retained"] == 0
    assert first_stats["git"]["stderr_byte_limit"] == limits.max_git_stderr_bytes
    assert first_stats["git"]["malformed_record"] is False
    assert second_stats["total_discovered"] == 4
    assert first_budget.reasons == {"max_changed_files": 3}
    assert second_budget.reasons == {"max_changed_files": 3}


def test_git_diff_discovery_is_bounded_and_deterministic(tmp_path: Path) -> None:
    repo = tmp_path / "bounded git diff"
    for index in range(32):
        _write(repo / "changes" / f"file_{index:03d}.py", "value = 0\n")
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "RepoMind Tests")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    for index in reversed(range(32)):
        _write(repo / "changes" / f"file_{index:03d}.py", f"value = {index + 1}\n")
    limits = ImpactLimits(max_changed_files=3)

    first_budget = test_impact_module._AnalysisBudget.start(limits)
    first_paths, source, warnings, first_stats = test_impact_module._select_changes(
        repo,
        None,
        "HEAD",
        limits,
        first_budget,
    )
    second_budget = test_impact_module._AnalysisBudget.start(limits)
    second_paths, _, _, second_stats = test_impact_module._select_changes(
        repo,
        None,
        "HEAD",
        limits,
        second_budget,
    )

    expected = [
        "changes/file_000.py",
        "changes/file_001.py",
        "changes/file_002.py",
    ]
    assert first_paths == expected
    assert second_paths == expected
    assert source == "git diff from HEAD"
    assert warnings == ["Changed-file selection truncated by max_changed_files."]
    assert first_stats["total_discovered"] == 4
    assert first_stats["total_returned"] == 3
    assert first_stats["processed"] == 3
    assert first_stats["truncated"] is True
    assert first_stats["discovery_complete"] is False
    assert first_stats["total_discovered_is_lower_bound"] is True
    assert first_stats["reasons"] == ["max_changed_files"]
    assert first_stats["reason"] == "max_changed_files"
    assert first_stats["git"]["stdout_bytes_processed"] > 0
    assert first_stats["git"]["malformed_record"] is False
    assert second_stats["total_discovered"] == 4
    assert first_budget.reasons == {"max_changed_files": 3}
    assert second_budget.reasons == {"max_changed_files": 3}


def test_git_working_tree_rename_uses_unusual_destination_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "status rename"
    old_path = "app/old name.py"
    new_path = "app/new naïve name.py"
    _write(repo / old_path, "value = 1\n")
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "RepoMind Tests")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    _git(repo, "mv", old_path, new_path)
    limits = ImpactLimits(max_changed_files=3)

    selected, source, warnings, stats = test_impact_module._select_changes(
        repo,
        None,
        None,
        limits,
        test_impact_module._AnalysisBudget.start(limits),
    )

    assert selected == [new_path]
    assert source == "working tree"
    assert warnings == []
    assert stats["total_discovered"] == 1
    assert stats["processed"] == 1
    assert stats["discovery_complete"] is True
    assert stats["total_discovered_is_lower_bound"] is False
    assert stats["git"]["malformed_record"] is False


def test_explicit_empty_changed_files_does_not_discover_dirty_tree(tmp_path: Path) -> None:
    repo = tmp_path / "empty selection"
    _write(repo / "app.py", "value = 1\n")
    Indexer(repo).initialize()

    report = _analyze(repo, [])

    assert report["change_source"] == "supplied paths"
    assert report["changed_files"] == []


def test_ordering_is_deterministic_for_equal_confidence(tmp_path: Path) -> None:
    repo = tmp_path / "ordering"
    _write(repo / "app" / "service.py", "def value():\n    return 1\n")
    for name in ("zeta", "alpha", "middle"):
        _write(
            repo / "tests" / f"test_{name}.py",
            "from app.service import value\n\ndef test_value():\n    assert value()\n",
        )
    Indexer(repo).initialize()

    first = _analyze(repo, ["app/service.py"])
    second = _analyze(repo, ["app/service.py"])

    assert first == second
    assert [item["file"] for item in first["existing_tests"]] == sorted(
        item["file"] for item in first["existing_tests"]
    )


def test_analysis_and_output_truncation_are_visible(tmp_path: Path) -> None:
    repo = tmp_path / "budgets"
    _write(repo / "app" / "shared.py", "def value():\n    return 1\n")
    for index in range(8):
        _write(
            repo / "tests" / f"test_{index}.py",
            "from app.shared import value\n\ndef test_value():\n    assert value()\n",
        )
    Indexer(repo).initialize()
    limits = ImpactLimits(
        max_graph_nodes=5,
        max_graph_edges=5,
        max_impacted_areas=2,
        max_tests=2,
        max_commands=1,
        max_evidence_per_result=1,
        max_output_bytes=5_000,
        max_direct_edges_per_file=2,
        max_indirect_edges_per_file=2,
    )

    report = _analyze(repo, ["app/shared.py"], limits=limits)

    assert report["truncation"]["graph"]["truncated"] is True
    assert report["truncation"]["graph"]["nodes_visited"] <= 5
    assert report["truncation"]["impacted_areas"]["total_returned"] <= 2
    assert report["truncation"]["relevant_tests"]["total_returned"] <= 2
    assert report["truncation"]["commands"]["total_returned"] <= 1
    assert report["truncation"]["output"]["limit"] == 5_000
    encoded = test_impact_module._serialize_report(report, "compact_json").encode("utf-8")
    assert len(encoded) <= 5_000
    assert report["truncation"]["output"]["total_returned"] == len(encoded)
    if not report["truncation"]["output"]["truncated"]:
        assert (
            report["truncation"]["output"]["total_discovered"]
            == report["truncation"]["output"]["total_returned"]
        )


def test_irreducible_command_plan_returns_bounded_no_plan_report(tmp_path: Path) -> None:
    repo = tmp_path / "many projects"
    for index in range(30):
        project = repo / f"project_{index:02d}"
        _write(project / "pyproject.toml", f"[project]\nname='p{index}'\nversion='1'\n")
        _write(project / "tests" / f"test_{index:02d}.py", "def test_value():\n    assert True\n")
    Indexer(repo).initialize()
    limits = ImpactLimits(max_commands=50, max_output_bytes=4_096)

    report = _analyze(repo, ["project_00/tests/test_00.py"], limits=limits)
    encoded = test_impact_module._serialize_report(
        report, "compact_json"
    ).encode("utf-8")

    assert len(encoded) <= 4_096
    assert report["analysis_status"] == "truncated"
    assert "plan_id" not in report
    assert report["truncation"]["commands"]["total_discovered"] > 0
    assert report["truncation"]["commands"]["total_returned"] == len(
        report["recommended_commands"]
    )
    assert report["truncation"]["output"]["truncated"] is True


def test_support_directories_remain_evidence_not_targets(tmp_path: Path) -> None:
    repo = tmp_path / "support files"
    _write(repo / "app" / "users.py", "def user():\n    return True\n")
    _write(
        repo / "tests" / "test_users.py",
        "from app.users import user\n\ndef test_user():\n    assert user()\n",
    )
    support_paths = [
        "tests/fixtures/test_users.py",
        "tests/factories/user_test.py",
        "tests/helpers/test_auth.py",
        "tests/utilities/test_db.py",
        "tests/support/test_server.py",
        "tests/testdata/test_rows.py",
        "tests/data/test_payloads.py",
        "tests/conftest.py",
        "tests/e2e_server.py",
    ]
    for path in support_paths:
        _write(repo / path, "from app.users import user\n")
    Indexer(repo).initialize()

    report = _analyze(repo, ["app/users.py"])
    command_tests = {
        path
        for command in report["recommended_commands"]
        for path in command["related_tests"]
    }

    assert command_tests == {"tests/test_users.py"}
    for path in support_paths:
        assert all(item["file"] != path for item in report["existing_tests"])
        with IndexDatabase(repo) as database:
            row = database.file_by_path(path)
        assert row is not None
        assert bool(row["is_test"]) is False


def test_migration_generic_token_does_not_create_high_confidence_link(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "migration precision"
    _write(
        repo / "migrations" / "0005_add_digest.py",
        "revision = '0005_add_digest'\nalgorithm = 'sha256'\n",
    )
    _write(
        repo / "tests" / "test_crypto.py",
        "import hashlib\n\ndef test_sha256():\n    assert hashlib.sha256(b'x')\n",
    )
    _write(
        repo / "tests" / "test_migrations.py",
        "from alembic import command\n\ndef test_upgrade():\n"
        "    command.upgrade(None, '0005_add_digest')\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["migrations/0005_add_digest.py"])

    assert _by_file(report, "tests/test_migrations.py")["confidence"] == "high"
    assert all(item["file"] != "tests/test_crypto.py" for item in report["existing_tests"])


def test_segment_aware_routes_reject_unrelated_fragments(tmp_path: Path) -> None:
    repo = tmp_path / "route segments"
    _write(
        repo / "app" / "routes.py",
        "from fastapi import FastAPI\napp=FastAPI()\n"
        "@app.get('/api/pay')\ndef pay(): return True\n",
    )
    _write(
        repo / "tests" / "test_unrelated.py",
        "def test_archive():\n    assert '/api/payment-archive'\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["app/routes.py"])

    assert all(item["file"] != "tests/test_unrelated.py" for item in report["existing_tests"])


def test_freshness_and_compact_json_byte_metadata_are_exact(tmp_path: Path) -> None:
    repo = tmp_path / "freshness bytes"
    _write(repo / "app.py", "value = '₹'\n")
    _write(repo / "tests" / "test_app.py", "from app import value\n\ndef test_value(): assert value\n")
    Indexer(repo).initialize()

    report = service_test_impact(str(repo), ["app.py"])
    encoded = test_impact_module._serialize_report(report, "compact_json").encode("utf-8")

    assert "freshness" in report
    assert report["truncation"]["output"]["measurement"] == (
        "canonical_compact_json_utf8_bytes"
    )
    assert report["truncation"]["output"]["total_returned"] == len(encoded)
    assert len(encoded) <= report["truncation"]["output"]["limit"]


def test_pretty_json_byte_metadata_utf8_and_boundary_are_exact(tmp_path: Path) -> None:
    repo = tmp_path / "pretty bytes"
    _write(repo / "app.py", "value = 'é₹'\n")
    for index in range(12):
        _write(
            repo / "tests" / f"test_app_{index}.py",
            "from app import value\n\ndef test_value(): assert value\n",
        )
    Indexer(repo).initialize()

    limit = 20_000
    for _ in range(8):
        report = _analyze(
            repo,
            ["app.py"],
            limits=ImpactLimits(max_output_bytes=limit),
            output_mode="pretty_json",
        )
        discovered_before_render = report["truncation"]["output"]["total_discovered"]
        rendered = render_test_impact(report, "json", limit)
        assert (
            report["truncation"]["output"]["total_discovered"]
            == discovered_before_render
        )
        size = len(rendered.encode("utf-8"))
        if size == limit:
            break
        limit = size

    assert size == limit
    assert report["truncation"]["output"]["total_returned"] == size
    assert report["truncation"]["output"]["measurement"] == (
        "rendered_pretty_json_utf8_bytes"
    )

    smaller = _analyze(
        repo,
        ["app.py"],
        limits=ImpactLimits(max_output_bytes=max(4_096, limit - 1)),
        output_mode="pretty_json",
    )
    smaller_rendered = render_test_impact(
        smaller, "json", max(4_096, limit - 1)
    )
    assert len(smaller_rendered.encode("utf-8")) <= max(4_096, limit - 1)
    assert smaller["truncation"]["output"]["truncated"] is True
    assert "plan_id" not in smaller


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_graph_nodes", 10_001),
        ("max_graph_edges", 50_001),
        ("max_impacted_areas", 1_001),
        ("max_tests", 501),
        ("max_commands", 101),
        ("max_evidence_per_result", 51),
        ("max_output_bytes", 2_000_001),
        ("max_changed_files", 1_001),
        ("max_path_length", 4_097),
        ("max_test_candidates_scanned", 20_001),
        ("max_migration_candidates_scanned", 5_001),
        ("max_route_candidates_scanned", 20_001),
        ("max_direct_edges_per_file", 2_001),
        ("max_indirect_edges_per_file", 5_001),
        ("max_impacted_candidates", 5_001),
        ("max_relevant_test_candidates", 2_001),
        ("max_evidence_candidates", 20_001),
        ("max_command_candidates", 501),
    ],
)
def test_analysis_limits_have_immutable_hard_caps(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=f"{field} must be at most"):
        ImpactLimits(**{field: value})




@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, 0, -1])
def test_analysis_duration_rejects_non_finite_boolean_and_non_positive(
    value: object,
) -> None:
    with pytest.raises(ValueError):
        ImpactLimits(max_analysis_seconds=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, 0, -1])
def test_integer_limits_reject_booleans_and_non_positive(value: object) -> None:
    with pytest.raises(ValueError):
        ImpactLimits(max_commands=value)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_mcp_rejects_limits_above_hard_caps(tmp_path: Path) -> None:
    async with Client(create_server()) as client:
        result = await client.call_tool(
            "repomind_test_impact", {"repository": str(tmp_path), "max_commands": 101}
        )
    assert result.structured_content["error"] == "invalid_arguments"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_commands", True),
        ("max_commands", 0),
        ("max_commands", -1),
        ("max_analysis_seconds", float("nan")),
        ("max_analysis_seconds", float("inf")),
        ("max_analysis_seconds", float("-inf")),
    ],
)
async def test_mcp_rejects_malformed_numeric_limits(
    tmp_path: Path, field: str, value: object
) -> None:
    async with Client(create_server()) as client:
        result = await client.call_tool(
            "repomind_test_impact",
            {"repository": str(tmp_path), field: value},
        )
    if result.is_error:
        assert result.structured_content is None
    else:
        assert result.structured_content is not None
        assert result.structured_content["error"] == "invalid_arguments"


def test_hostile_change_and_candidate_sizes_are_bounded(tmp_path: Path) -> None:
    repo = tmp_path / "hostile sizes"
    for index in range(8):
        _write(repo / "app" / f"module_{index}.py", f"value = {index}\n")
        _write(
            repo / "tests" / f"test_module_{index}.py",
            f"from app.module_{index} import value\n\ndef test_value(): assert value >= 0\n",
        )
    Indexer(repo).initialize()
    limits = ImpactLimits(
        max_changed_files=2,
        max_test_candidates_scanned=3,
        max_relevant_test_candidates=2,
        max_direct_edges_per_file=1,
        max_indirect_edges_per_file=1,
        max_command_candidates=2,
    )

    report = _analyze(
        repo,
        [f"app/module_{index}.py" for index in range(8)],
        limits=limits,
    )

    assert len(report["changed_files"]) == 2
    change_selection = report["truncation"]["change_selection"]
    assert change_selection == {
        "total_discovered": 8,
        "total_returned": 2,
        "truncated": True,
        "limit": 2,
        "processed": 2,
        "discovery_complete": False,
        "total_discovered_is_lower_bound": False,
        "reasons": ["max_changed_files"],
        "reason": "max_changed_files",
        "duplicates_or_internal_paths_removed": 0,
        "git": {
            "stdout_bytes_processed": 0,
            "stdout_byte_limit": limits.max_git_output_bytes,
            "stderr_bytes_retained": 0,
            "stderr_byte_limit": limits.max_git_stderr_bytes,
            "malformed_record": False,
        },
    }
    analysis_reasons = {
        item["limit"] for item in report["truncation"]["analysis"]["reasons"]
    }
    assert "max_changed_files" in analysis_reasons
    assert "max_test_candidates_scanned" in analysis_reasons
    test_stats = report["truncation"]["relevant_tests"]
    assert test_stats["candidate_limit_reached"] is True
    assert test_stats["discovery_complete"] is False
    assert test_stats["total_discovered_is_lower_bound"] is True
    assert report["analysis_status"] == "truncated"


def test_changed_path_length_is_rejected_before_analysis(tmp_path: Path) -> None:
    repo = tmp_path / "long path"
    _write(repo / "app.py", "value = 1\n")
    Indexer(repo).initialize()

    with pytest.raises(ValueError, match="max_path_length"):
        _analyze(
            repo,
            ["a" * 33 + ".py"],
            limits=ImpactLimits(max_path_length=32),
        )


def test_analysis_duration_cap_is_reported_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "duration"
    _write(repo / "app.py", "value = 1\n")
    Indexer(repo).initialize()
    ticks = iter([0.0, 100.0, 100.0, 100.0])
    monkeypatch.setattr(
        test_impact_module.time,
        "perf_counter",
        lambda: next(ticks, 100.0),
    )

    report = _analyze(
        repo,
        ["app.py"],
        limits=ImpactLimits(max_analysis_seconds=1.0),
    )

    assert report["analysis_status"] == "truncated"
    assert {
        item["limit"] for item in report["truncation"]["analysis"]["reasons"]
    } == {"max_analysis_seconds"}


def test_legacy_impact_query_contract_remains_unchanged(tmp_path: Path) -> None:
    repo = tmp_path / "legacy"
    _write(repo / "app.py", "value = 1\n")
    _write(repo / "tests" / "test_app.py", "from app import value\n\ndef test_value():\n    assert value\n")
    Indexer(repo).initialize()

    with IndexDatabase(repo) as database:
        result = impact(database, "app.py")

    assert set(result) == {
        "query",
        "direct_dependents",
        "possible_indirect_dependents",
        "tests_likely_affected",
        "routes_likely_affected",
        "ui_components_possibly_affected",
    }


@pytest.mark.anyio
async def test_mcp_schema_is_analysis_only_and_rejects_execution_arguments(
    tmp_path: Path,
) -> None:
    async with Client(create_server()) as client:
        tools = await client.list_tools()
        schema = next(
            tool.input_schema
            for tool in tools.tools
            if tool.name == "repomind_test_impact"
        )
        run_result = await client.call_tool(
            "repomind_test_impact",
            {"repository": str(tmp_path), "run": True},
        )
        plan_result = await client.call_tool(
            "repomind_test_impact",
            {"repository": str(tmp_path), "plan_id": "not-supported"},
        )

    properties = schema.get("properties", {})
    assert "run" not in properties
    assert "plan_id" not in properties
    assert run_result.is_error is True
    assert plan_result.is_error is True


def _analyze(
    repo: Path,
    changed: list[str],
    *,
    limits: ImpactLimits | None = None,
    output_mode: str = "compact_json",
) -> dict[str, Any]:
    with IndexDatabase(repo) as database:
        return analyze_test_impact(
            database,
            changed,
            limits=limits,
            output_mode=output_mode,  # type: ignore[arg-type]
        )


def _by_file(report: dict[str, Any], path: str) -> dict[str, Any]:
    return next(item for item in report["existing_tests"] if item["file"] == path)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
