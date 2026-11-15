from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.test_impact import TestImpactLimits, analyze_test_impact

TestImpactLimits.__test__ = False  # type: ignore[attr-defined]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _analyze(
    repo: Path, changed: list[str], limits: TestImpactLimits | None = None
) -> dict[str, Any]:
    with IndexDatabase(repo) as database:
        return analyze_test_impact(database, changed, limits=limits)


# --------------------------------------------------------------------------
# Issue 1: Non-generic stem fallback for flat test root layouts
# --------------------------------------------------------------------------

def test_non_generic_flat_test_root_matching(tmp_path: Path) -> None:
    """Non-generic stems matching between nested source and flat root tests/ directory.

    Case 1: src/payments/invoice.py vs tests/test_invoice.py (no dependency edge).
    Case 2: src/services/billing/invoice.py vs tests/unit/test_invoice.py.
    """
    repo = tmp_path / "flat_test_repo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "^1.0.0"}}),
    )
    # Source file in nested package, test in root tests/ (no import edge)
    _write(repo / "src" / "payments" / "invoice.py", "def generate_invoice(): return 'inv'\n")
    _write(repo / "tests" / "test_invoice.py", "def test_invoice(): assert True\n")

    Indexer(repo).initialize()

    report = _analyze(repo, ["src/payments/invoice.py"])
    discovered = {item["file"] for item in report["existing_tests"]}

    assert "tests/test_invoice.py" in discovered
    test_item = next(item for item in report["existing_tests"] if item["file"] == "tests/test_invoice.py")
    assert any(ev["kind"] == "filename-match" for ev in test_item["evidence"])


def test_non_generic_flat_test_unit_subdirectory_matching(tmp_path: Path) -> None:
    """Non-generic stem matching under tests/unit/ (no dependency edge)."""
    repo = tmp_path / "unit_sub_repo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "^1.0.0"}}),
    )
    _write(repo / "src" / "services" / "billing" / "invoice.py", "def bill(): return 1\n")
    _write(repo / "tests" / "unit" / "test_invoice.py", "def test_bill(): assert True\n")

    Indexer(repo).initialize()

    report = _analyze(repo, ["src/services/billing/invoice.py"])
    discovered = {item["file"] for item in report["existing_tests"]}

    assert "tests/unit/test_invoice.py" in discovered


def test_unrelated_components_sharing_distinctive_stem_rejected(tmp_path: Path) -> None:
    """Two unrelated components with distinctive stems in different directories must NOT match."""
    repo = tmp_path / "distinct_unrelated_repo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "^1.0.0"}}),
    )
    # Component A: payments/crypto.py with its own test
    _write(repo / "src" / "payments" / "crypto.py", "def pay_hash(): return 'hash'\n")
    _write(repo / "src" / "payments" / "crypto.test.ts", "describe('pay crypto', () => {});\n")

    # Component B: auth/crypto.ts with its own test
    _write(repo / "src" / "auth" / "crypto.ts", "def auth_hash(): return 'auth'\n")
    _write(repo / "src" / "auth" / "crypto.test.ts", "describe('auth crypto', () => {});\n")

    Indexer(repo).initialize()

    report = _analyze(repo, ["src/payments/crypto.py"])
    discovered = {item["file"] for item in report["existing_tests"]}

    assert "src/payments/crypto.test.ts" in discovered
    # Crucial negative assertion: auth/crypto.test.ts MUST NOT be selected for payments/crypto.py!
    assert "src/auth/crypto.test.ts" not in discovered


def test_generic_stem_flat_test_rejected(tmp_path: Path) -> None:
    """Generic stems like 'index' must NOT match flat tests/test_index.py across components."""
    repo = tmp_path / "generic_flat_repo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "^1.0.0"}}),
    )
    _write(repo / "src" / "payments" / "index.py", "def pay_index(): return 1\n")
    _write(repo / "tests" / "test_index.py", "def test_root_index(): assert True\n")

    Indexer(repo).initialize()

    report = _analyze(repo, ["src/payments/index.py"])
    discovered = {item["file"] for item in report["existing_tests"]}

    # Generic stem 'index' must NOT match across directories
    assert "tests/test_index.py" not in discovered


# --------------------------------------------------------------------------
# Issue 2: Runnable *.case.test.* vs shared helper
# --------------------------------------------------------------------------

def test_runnable_case_test_file_included_in_commands(tmp_path: Path) -> None:
    """A file named discount.case.test.ts with top-level Vitest describe/test

    is a real executable test suite and MUST be included in recommended_commands.
    """
    repo = tmp_path / "runnable_case_repo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "^1.0.0"}}),
    )
    _write(repo / "src" / "pricing" / "discount.ts", "export const discount = (x: number) => x * 0.9;\n")
    _write(
        repo / "src" / "pricing" / "discount.case.test.ts",
        """import { discount } from './discount';
describe('discount cases', () => {
  it('applies 10% discount', () => {
    expect(discount(100)).toBe(90);
  });
});
""",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["src/pricing/discount.ts"])
    discovered = {item["file"] for item in report["existing_tests"]}

    # discount.case.test.ts is runnable and must be discovered
    assert "src/pricing/discount.case.test.ts" in discovered

    # Must be in recommended_commands
    commands = report["recommended_commands"]
    targeted = next(cmd for cmd in commands if cmd["scope"] == "targeted")
    assert "src/pricing/discount.case.test.ts" in targeted["related_tests"]


def test_shared_case_helper_excluded_from_commands(tmp_path: Path) -> None:
    """A helper named common.case.test.ts that merely exports a test-registering function

    without top-level test runner calls must NOT be in recommended_commands,
    while its real importing consumers MUST be in recommended_commands.
    """
    repo = tmp_path / "helper_case_repo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "^1.0.0"}}),
    )
    _write(
        repo / "src" / "router" / "common.case.test.ts",
        """export const createRouterSuite = (name: string, factory: any) => {
  describe(name, () => {
    it('works', () => {});
  });
};
""",
    )
    _write(
        repo / "src" / "router" / "linear.test.ts",
        """import { createRouterSuite } from './common.case.test';
createRouterSuite('linear', null);
""",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["src/router/common.case.test.ts"])

    commands = report["recommended_commands"]
    targeted = next(cmd for cmd in commands if cmd["scope"] == "targeted")

    # Helper is excluded from command execution
    assert "src/router/common.case.test.ts" not in targeted["related_tests"]
    assert "src/router/common.case.test.ts" not in targeted["command"]

    # Consumer is included in command execution
    assert "src/router/linear.test.ts" in targeted["related_tests"]


# --------------------------------------------------------------------------
# Issue 3: Fair-quota warning generation bug
# --------------------------------------------------------------------------

def test_fair_quota_warning_emitted_in_report_warnings(tmp_path: Path) -> None:
    """When a per-file fair quota cutoff is applied while graph is not globally truncated,

    report["warnings"] MUST contain the fair quota warning message.
    """
    repo = tmp_path / "warning_bug_repo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "^1.0.0"}}),
    )
    # Hub with 30 dependents
    _write(repo / "src" / "hub.ts", "export const HUB = 1;\n")
    for i in range(30):
        _write(repo / "src" / f"dep_{i}.ts", f"import {{ HUB }} from './hub';\nexport const d{i} = HUB;\n")

    _write(repo / "src" / "second.ts", "export const SECOND = 2;\n")
    _write(repo / "src" / "second.test.ts", "import { SECOND } from './second';\ndescribe('sec', () => {});\n")
    Indexer(repo).initialize()

    # Limit of 50 nodes: hub fair quota is 25. Total visited <= 50, so global truncation is False.
    limits = TestImpactLimits(max_graph_nodes=50)
    report = _analyze(repo, ["src/hub.ts", "src/second.ts"], limits=limits)

    graph_meta = report["truncation"]["graph"]
    assert graph_meta["fair_quota_applied"] is True
    assert graph_meta["truncated"] is False

    # This assertion verifies the bugfix: the warning MUST be in report["warnings"]!
    expected_warning = "Per-file fair graph traversal quota was applied to one or more changed files."
    assert expected_warning in report["warnings"], f"Expected warning not in report['warnings']: {report['warnings']}"
