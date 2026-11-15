from __future__ import annotations

from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.scanner import (
    _has_top_level_test_runner_calls,
)
from repomind.test_impact import _changed_file_record, analyze_test_impact


def test_documentation_and_config_only_changes_not_flagged_as_go(tmp_path: Path) -> None:
    root = tmp_path / "doc_repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname="doc_repo"\n', encoding="utf-8")
    (root / "README.md").write_text("# Documentation\n", encoding="utf-8")
    Indexer(root).initialize()
    with IndexDatabase(root) as db:
        report = analyze_test_impact(db, ["README.md", "pyproject.toml"])
        # A documentation/configuration change set MUST NOT be treated as pure Go!
        warnings_text = " ".join(report.get("warnings", []))
        assert "Go" not in warnings_text, f"Unexpected Go warning for doc-only change: {warnings_text}"
        caps = report.get("capabilities", {})
        assert "by_language" in caps or "dependency_graph_supported" in caps
        # Capability flags must not be all false due to pure-Go misclassification
        assert caps.get("test_selection_supported") is not False or "by_language" in caps


def test_mixed_python_and_go_capabilities_and_warnings(tmp_path: Path) -> None:
    root = tmp_path / "mixed_repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname="mixed"\n', encoding="utf-8")
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_text("def run(): return 1\n", encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_app.py").write_text("from src.app import run\ndef test_run(): assert run() == 1\n", encoding="utf-8")
    (root / "internal").mkdir(parents=True, exist_ok=True)
    (root / "internal" / "server.go").write_text("package internal\n", encoding="utf-8")
    (root / "internal" / "server_test.go").write_text("package internal\n", encoding="utf-8")
    Indexer(root).initialize()
    with IndexDatabase(root) as db:
        report = analyze_test_impact(db, ["src/app.py", "internal/server.go"])
        # Python pytest command must be recommended
        commands = report.get("recommended_commands", [])
        assert any(cmd["framework"] == "pytest" for cmd in commands)
        # No Go commands
        assert not any("go test" in cmd["command"] for cmd in commands)

        # Capabilities must be truthful for both languages
        caps = report.get("capabilities", {})
        # by_language must expose per-language capabilities
        assert "by_language" in caps, "capabilities must include by_language breakdown"
        assert caps["by_language"]["python"]["runner_supported"] is True
        assert caps["by_language"]["go"]["runner_supported"] is False
        assert caps["by_language"]["go"]["test_selection_supported"] is False

        # In mixed change, aggregate booleans must not falsely claim Go runner is supported
        assert caps["runner_supported"] is False, "Aggregate runner_supported cannot be True when Go runner is unsupported"

        # Explicit warning about mixed-language status
        warnings = " ".join(report.get("warnings", []))
        assert "Mixed" in warnings or "Go" in warnings


def test_pure_go_confidence_and_legacy_fields(tmp_path: Path) -> None:
    root = tmp_path / "go_repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "writer.go").write_text("package pkg\n", encoding="utf-8")
    (root / "pkg" / "writer_test.go").write_text("package pkg\n", encoding="utf-8")
    Indexer(root).initialize()
    with IndexDatabase(root) as db:
        report = analyze_test_impact(db, ["pkg/writer.go", "pkg/writer_test.go"])
        # For pure Go, overall confidence must be low because test-to-production relationships are unsupported
        assert report["confidence"] == "low"
        # Legacy status complete indicates processing completed
        assert report["analysis_status"] == "complete"
        # Uncovered areas contains writer.go (unsupported attribution) with low confidence
        gaps = report["uncovered_areas"]
        assert len(gaps) == 1
        assert gaps[0]["path"] == "pkg/writer.go"
        assert gaps[0]["confidence"] == "low"
        assert gaps[0]["coverage"] == "unknown"
        # Test file itself is NOT in gaps
        assert "pkg/writer_test.go" not in [g["path"] for g in gaps]


def test_has_top_level_test_runner_calls_security_and_edge_cases(tmp_path: Path) -> None:
    # 1. Normal runnable file
    runnable = tmp_path / "test.ts"
    runnable.write_text("describe('suite', () => { it('works', () => {}); });\n", encoding="utf-8")
    assert _has_top_level_test_runner_calls(runnable) is True

    # 2. Commented-out runner calls (should NOT count as runnable calls)
    commented = tmp_path / "commented.ts"
    commented.write_text("// describe('fake', () => {});\n/* test('fake', () => {}); */\n", encoding="utf-8")
    assert _has_top_level_test_runner_calls(commented) is False

    # 3. Pure export helper without top-level runner invocation
    helper = tmp_path / "helper.ts"
    helper.write_text("export const runSuite = (name: string) => { describe(name, () => {}); };\n", encoding="utf-8")
    assert _has_top_level_test_runner_calls(helper) is False

    # 4. Multiline call
    multiline = tmp_path / "multiline.ts"
    multiline.write_text("describe(\n  'multiline suite',\n  () => {}\n);\n", encoding="utf-8")
    assert _has_top_level_test_runner_calls(multiline) is True


def test_legacy_b12_index_row_compatibility(tmp_path: Path) -> None:
    # Simulate a repository indexed with legacy b12 (where Go test files had is_test=0, purpose='source')
    root = tmp_path / "legacy_repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "api.go").write_text("package pkg\n", encoding="utf-8")
    (root / "pkg" / "api_test.go").write_text("package pkg\n", encoding="utf-8")
    Indexer(root).initialize()

    # Manually downgrade index row to simulate b12 stale database
    with IndexDatabase(root) as db:
        db.connection.execute(
            "UPDATE files SET is_test = 0, purpose = 'source' WHERE path = 'pkg/api_test.go'"
        )
        db.connection.commit()

        # Changed file record must accurately classify it as test despite stale index row
        record = _changed_file_record(db, "pkg/api_test.go")
        assert record["is_test"] is True
        assert record["purpose"] == "test"

        # Analysis on changed test file must not put it into uncovered gaps
        report = analyze_test_impact(db, ["pkg/api_test.go"])
        assert report["uncovered_areas"] == []
        assert len(report["existing_tests"]) == 1
        assert report["existing_tests"][0]["file"] == "pkg/api_test.go"
