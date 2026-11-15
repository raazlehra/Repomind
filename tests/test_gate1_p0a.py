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


def _test_by_path(report: dict[str, Any], path: str) -> dict[str, Any]:
    return next(item for item in report["existing_tests"] if item["file"] == path)


def test_shared_test_harness_consumer_recovery(tmp_path: Path) -> None:
    """When a shared test case helper changes:

    1. The helper is recognized in changed_files (is_test=True, purpose=test) and impacted_areas.
    2. Because it is a non-runnable case helper (.case.test.ts), it is NOT included in recommended_commands.
    3. Direct importing test suites are recovered as test-harness-consumers and included in targeted commands.
    4. Unrelated test suites are not selected.
    """
    repo = tmp_path / "shared_harness_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "harness-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    _write(
        repo / "src" / "router" / "common.case.test.ts",
        """export const runSuite = (name: string) => {
  describe(name, () => {
    it('handles wildcard', () => {});
  });
};
""",
    )
    _write(
        repo / "src" / "router" / "linear" / "router.test.ts",
        """import { runSuite } from '../common.case.test';
runSuite('linear');
""",
    )
    _write(
        repo / "src" / "router" / "trie" / "router.test.ts",
        """import { runSuite } from '../common.case.test';
runSuite('trie');
""",
    )
    _write(
        repo / "src" / "router" / "unrelated.test.ts",
        """describe('unrelated', () => {
  it('does something else', () => {});
});
""",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["src/router/common.case.test.ts"])

    # 1. Metadata in changed_files and impacted_areas is preserved
    changed_record = next(
        f for f in report["changed_files"] if f["path"] == "src/router/common.case.test.ts"
    )
    assert changed_record["is_test"] is True
    assert changed_record["purpose"] == "test"
    assert any(
        area["path"] == "src/router/common.case.test.ts" and area["kind"] == "test"
        for area in report["impacted_areas"]["high_confidence"]
    )

    # 2. Both real consumers are discovered as test-harness-consumer
    consumer_linear = _test_by_path(report, "src/router/linear/router.test.ts")
    assert consumer_linear["confidence"] == "medium"
    assert consumer_linear["structurally_related"] is True
    assert any(ev["kind"] == "test-harness-consumer" for ev in consumer_linear["evidence"])

    consumer_trie = _test_by_path(report, "src/router/trie/router.test.ts")
    assert consumer_trie["confidence"] == "medium"
    assert consumer_trie["structurally_related"] is True
    assert any(ev["kind"] == "test-harness-consumer" for ev in consumer_trie["evidence"])

    # 3. Unrelated test is NOT selected
    discovered_files = {item["file"] for item in report["existing_tests"]}
    assert "src/router/unrelated.test.ts" not in discovered_files

    # 4. Commands include the real runnable consumers, but NOT the non-runnable helper
    commands = report["recommended_commands"]
    targeted = next(cmd for cmd in commands if cmd["scope"] == "targeted")
    assert "src/router/linear/router.test.ts" in targeted["related_tests"]
    assert "src/router/trie/router.test.ts" in targeted["related_tests"]
    assert "src/router/common.case.test.ts" not in targeted["related_tests"]
    assert "src/router/common.case.test.ts" not in targeted["command"]
    assert report["uncovered_areas"] == []


def test_non_import_edges_rejected_as_harness_consumer(tmp_path: Path) -> None:
    """Non-import dependencies ('calls', 'test-target', etc.) pointing from a test

    to a changed test/helper file must NOT receive test-harness-consumer evidence.
    Only genuine 'imports' edges warrant test-harness-consumer.
    """
    repo = tmp_path / "non_import_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "non-import-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    _write(
        repo / "src" / "router" / "common.case.test.ts",
        "export const helper = () => 'test';\n",
    )
    _write(
        repo / "src" / "router" / "importing.test.ts",
        "import { helper } from './common.case.test';\ndescribe('imp', () => { helper(); });\n",
    )
    _write(
        repo / "src" / "router" / "fabricated.test.ts",
        "describe('fab', () => { it('calls helper', () => {}); });\n",
    )
    Indexer(repo).initialize()

    # Artificially insert a non-import ('calls') dependency edge in the SQLite database
    # from fabricated.test.ts to common.case.test.ts
    with IndexDatabase(repo) as db:
        fab_id = db.file_by_path("src/router/fabricated.test.ts")["id"]
        helper_id = db.file_by_path("src/router/common.case.test.ts")["id"]
        db.connection.execute(
            """INSERT INTO dependencies (source_file_id, target_file_id, kind, confidence, source)
               VALUES (?, ?, 'calls', 0.9, 'test_insertion')""",
            (fab_id, helper_id),
        )
        db.connection.commit()

    report = _analyze(repo, ["src/router/common.case.test.ts"])

    # importing.test.ts has kind='imports' -> test-harness-consumer
    imp_test = _test_by_path(report, "src/router/importing.test.ts")
    assert any(ev["kind"] == "test-harness-consumer" for ev in imp_test["evidence"])

    # fabricated.test.ts has kind='calls' -> MUST NOT have test-harness-consumer
    fab_matches = [t for t in report["existing_tests"] if t["file"] == "src/router/fabricated.test.ts"]
    if fab_matches:
        assert not any(ev["kind"] == "test-harness-consumer" for ev in fab_matches[0]["evidence"])


def test_fair_quota_distinct_from_global_max_graph_nodes(tmp_path: Path) -> None:
    """Per-file fair quota cutoff must NOT be misreported as global max_graph_nodes exhaustion.

    When a hub reaches its local quota while global nodes visited < max_graph_nodes:
    1. graph.truncated is False.
    2. 'max_graph_nodes' is NOT in graph.reasons.
    3. fair_quota_applied is True.
    """
    repo = tmp_path / "fair_quota_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "fair-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    # Hub with 30 dependents
    _write(repo / "src" / "hub.ts", "export const HUB = 1;\n")
    for i in range(30):
        _write(repo / "src" / f"dep_{i}.ts", f"import {{ HUB }} from './hub';\nexport const d{i} = HUB;\n")

    # Second file with 1 test
    _write(repo / "src" / "second.ts", "export const SECOND = 2;\n")
    _write(
        repo / "src" / "second.test.ts",
        "import { SECOND } from './second';\ndescribe('sec', () => { it('ok', () => SECOND); });\n",
    )
    Indexer(repo).initialize()

    # Budget with max_graph_nodes=50:
    # Hub fair quota is applied across passes, visiting ~40 nodes total.
    # Total nodes visited <= 50, so global cap was NEVER exhausted!
    limits = TestImpactLimits(max_graph_nodes=50)
    report = _analyze(repo, ["src/hub.ts", "src/second.ts"], limits=limits)

    graph_meta = report["truncation"]["graph"]
    assert 25 <= graph_meta["nodes_visited"] <= 50
    # Crucial assertion: global limit was NOT exhausted, so graph is NOT truncated!
    assert graph_meta["truncated"] is False
    assert "max_graph_nodes" not in graph_meta["reasons"]
    assert graph_meta["fair_quota_applied"] is True

    # second.test.ts was successfully discovered despite hub having many dependents
    second_test = _test_by_path(report, "src/second.test.ts")
    assert second_test["confidence"] == "high"


def test_global_cap_exhaustion_marked_correctly(tmp_path: Path) -> None:
    """When global nodes_visited actually reaches max_graph_nodes, graph.truncated is True

    and 'max_graph_nodes' is recorded in reasons.
    """
    repo = tmp_path / "global_exhaust_repo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "^1.0.0"}}),
    )
    changed_files = []
    for i in range(15):
        src_path = f"src/mod_{i}.ts"
        test_path = f"src/mod_{i}.test.ts"
        _write(repo / src_path, f"export const val_{i} = {i};\n")
        _write(repo / test_path, f"import {{ val_{i} }} from './mod_{i}';\n")
        changed_files.append(src_path)

    Indexer(repo).initialize()

    # Limit to 10 nodes total across 15 changed files
    limits = TestImpactLimits(max_graph_nodes=10)
    report = _analyze(repo, changed_files, limits=limits)

    graph_meta = report["truncation"]["graph"]
    assert graph_meta["nodes_visited"] <= 10
    assert graph_meta["truncated"] is True
    assert "max_graph_nodes" in graph_meta["reasons"]


def test_shared_test_harness_multiple_consumers(tmp_path: Path) -> None:
    """When a shared test harness changes, all consuming test suites are recovered."""
    repo = tmp_path / "test_harness_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "harness-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    _write(
        repo / "tests" / "harness.test.ts",
        "export const verifySchema = (obj: any) => expect(obj).toBeDefined();\n",
    )
    _write(
        repo / "tests" / "consumer_a.test.ts",
        """import { verifySchema } from './harness.test';
describe('a', () => { it('verifies', () => verifySchema({})); });
""",
    )
    _write(
        repo / "tests" / "consumer_b.test.ts",
        """import { verifySchema } from './harness.test';
describe('b', () => { it('verifies', () => verifySchema({})); });
""",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["tests/harness.test.ts"])

    ca = _test_by_path(report, "tests/consumer_a.test.ts")
    assert ca["confidence"] == "medium"
    assert any(ev["kind"] == "test-harness-consumer" for ev in ca["evidence"])

    cb = _test_by_path(report, "tests/consumer_b.test.ts")
    assert cb["confidence"] == "medium"
    assert any(ev["kind"] == "test-harness-consumer" for ev in cb["evidence"])

    harness = _test_by_path(report, "tests/harness.test.ts")
    assert harness["confidence"] == "high"


def test_unrelated_stem_match_not_promoted_as_harness_consumer(tmp_path: Path) -> None:
    """A test with a colliding filename stem that does NOT import the helper

    is not given test-harness-consumer evidence.
    """
    repo = tmp_path / "stem_collision_repo"
    _write(
        repo / "package.json",
        json.dumps({
            "name": "collision-demo",
            "scripts": {"test": "vitest run"},
            "devDependencies": {"vitest": "^1.0.0"},
        }),
    )
    _write(
        repo / "src" / "router" / "common.case.test.ts",
        "export const runRouterTests = () => {};\n",
    )
    _write(
        repo / "src" / "helper" / "css" / "common.case.test.tsx",
        "export const runCssTests = () => {};\n",
    )
    _write(
        repo / "src" / "router" / "router.test.ts",
        "import { runRouterTests } from './common.case.test';\nrunRouterTests();\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["src/router/common.case.test.ts"])

    consumer = _test_by_path(report, "src/router/router.test.ts")
    assert consumer["confidence"] == "medium"
    assert any(ev["kind"] == "test-harness-consumer" for ev in consumer["evidence"])

    css_test = [t for t in report["existing_tests"] if t["file"] == "src/helper/css/common.case.test.tsx"]
    if css_test:
        assert not any(ev["kind"] == "test-harness-consumer" for ev in css_test[0]["evidence"])


def test_mutual_import_cycle_terminates_deterministically(tmp_path: Path) -> None:
    """Two files that mutually import each other terminate safely."""
    repo = tmp_path / "cycle_repo"
    _write(
        repo / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "^1.0.0"}}),
    )
    _write(repo / "src" / "a.ts", "import { b } from './b';\nexport const a = () => b();\n")
    _write(repo / "src" / "b.ts", "import { a } from './a';\nexport const b = () => a();\n")
    _write(
        repo / "src" / "a.test.ts",
        "import { a } from './a';\ndescribe('a', () => { it('works', () => a()); });\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["src/a.ts"])

    test_a = _test_by_path(report, "src/a.test.ts")
    assert test_a["confidence"] == "high"
    assert report["truncation"]["graph"]["nodes_visited"] < 10
