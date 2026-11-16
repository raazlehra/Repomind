from __future__ import annotations

from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.scanner import classify_file, is_executable_test_path
from repomind.test_impact import (
    _changed_file_record,
    _uncovered_areas,
    analyze_test_impact,
    render_test_impact,
)


def test_go_test_file_classification() -> None:
    # 1. Direct Go test file recognition
    classified_test = classify_file("middleware/wrap_writer_readfrom_test.go")
    assert classified_test is not None
    lang, purpose, is_test = classified_test
    assert lang == "go"
    assert purpose == "test"
    assert is_test is True

    # 2. Production Go file
    classified_prod = classify_file("middleware/wrap_writer.go")
    assert classified_prod is not None
    lang_p, purpose_p, is_test_p = classified_prod
    assert lang_p == "go"
    assert purpose_p == "source"
    assert is_test_p is False

    # 3. is_executable_test_path recognition
    assert is_executable_test_path("middleware/wrap_writer_readfrom_test.go") is True
    assert is_executable_test_path("middleware/wrap_writer.go") is False

    # 4. Negative controls: support/fixture directories
    assert is_executable_test_path("testdata/mock_writer_test.go") is False
    assert is_executable_test_path("helpers/test_helper_test.go") is False
    assert is_executable_test_path("fixtures/sample_test.go") is False


def test_go_changed_file_record(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    Indexer(root).initialize()
    with IndexDatabase(root) as db:
        # Record for newly changed unindexed Go test file
        rec_test = _changed_file_record(db, "middleware/wrap_writer_readfrom_test.go")
        assert rec_test["language"] == "go"
        assert rec_test["purpose"] == "test"
        assert rec_test["is_test"] is True

        # Record for Go production file
        rec_prod = _changed_file_record(db, "middleware/wrap_writer.go")
        assert rec_prod["language"] == "go"
        assert rec_prod["purpose"] == "source"
        assert rec_prod["is_test"] is False


def test_go_test_file_never_in_uncovered_areas() -> None:
    changed = [
        {
            "path": "middleware/wrap_writer_readfrom_test.go",
            "language": "go",
            "purpose": "test",
            "is_test": True,
            "indexed": False,
        }
    ]
    gaps = _uncovered_areas(changed, [])
    # Changed test file MUST NOT be reported as an uncovered production area
    assert gaps == []


def test_go_production_file_uncovered_area_uncertainty() -> None:
    changed = [
        {
            "path": "middleware/wrap_writer.go",
            "language": "go",
            "purpose": "source",
            "is_test": False,
            "indexed": True,
        }
    ]
    gaps = _uncovered_areas(changed, [])
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["path"] == "middleware/wrap_writer.go"
    # Must represent unknown rather than false certainty: confidence low, coverage unknown
    assert gap["confidence"] == "low"
    assert gap["coverage"] == "unknown"
    assert "unsupported" in gap["reason"].lower()
    assert gap["evidence"]["kind"] == "unsupported-language-relationship-extraction"
    assert gap["evidence"]["language"] == "go"


def test_pure_go_synthetic_repository_analysis(tmp_path: Path) -> None:
    root = tmp_path / "go_repo"
    (root / "middleware").mkdir(parents=True, exist_ok=True)
    (root / "middleware" / "wrap_writer.go").write_text("package middleware\n", encoding="utf-8")
    (root / "middleware" / "wrap_writer_readfrom_test.go").write_text(
        "package middleware\nimport \"testing\"\nfunc TestReadFrom(t *testing.T) {}\n",
        encoding="utf-8",
    )
    Indexer(root).initialize()
    with IndexDatabase(root) as db:
        report = analyze_test_impact(
            db,
            ["middleware/wrap_writer.go", "middleware/wrap_writer_readfrom_test.go"],
        )

        # 1. Recommended commands MUST be empty for Go under Option 1
        assert report["recommended_commands"] == []

        # 2. Changed test file must NOT be in uncovered_areas
        gap_paths = [g["path"] for g in report["uncovered_areas"]]
        assert "middleware/wrap_writer_readfrom_test.go" not in gap_paths

        # 3. Explicit Go warning emitted
        warnings_text = " ".join(report["warnings"])
        assert "Go" in warnings_text
        assert "unsupported" in warnings_text.lower()

        # 4. Truthful capabilities reported
        assert "capabilities" in report
        caps = report["capabilities"]
        assert caps["dependency_graph_supported"] is False
        assert caps["test_selection_supported"] is False
        assert caps["runner_supported"] is False

        # 5. Schema version preserved
        assert report["schema_version"] == "repomind.test-impact.v1"


def test_go_production_file_only_change(tmp_path: Path) -> None:
    root = tmp_path / "go_prod_only"
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "service.go").write_text("package pkg\n", encoding="utf-8")
    (root / "pkg" / "service_test.go").write_text("package pkg\n", encoding="utf-8")
    Indexer(root).initialize()
    with IndexDatabase(root) as db:
        report = analyze_test_impact(db, ["pkg/service.go"])
        # Production-to-test selection is unsupported, so existing_tests is empty
        assert report["existing_tests"] == []
        assert report["recommended_commands"] == []
        # Gaps should include service.go with low confidence and unknown coverage
        assert len(report["uncovered_areas"]) == 1
        gap = report["uncovered_areas"][0]
        assert gap["path"] == "pkg/service.go"
        assert gap["confidence"] == "low"
        assert gap["coverage"] == "unknown"
        assert gap["evidence"]["kind"] == "unsupported-language-relationship-extraction"


def test_go_test_file_addition_only_change(tmp_path: Path) -> None:
    root = tmp_path / "go_test_add"
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "service.go").write_text("package pkg\n", encoding="utf-8")
    Indexer(root).initialize()
    # Add a new test file not in base index
    (root / "pkg" / "service_test.go").write_text("package pkg\n", encoding="utf-8")
    with IndexDatabase(root) as db:
        report = analyze_test_impact(db, ["pkg/service_test.go"])
        # Test addition MUST NOT create any uncovered production gaps
        assert report["uncovered_areas"] == []
        # Test is recognized as changed test file
        assert len(report["existing_tests"]) == 1
        assert report["existing_tests"][0]["file"] == "pkg/service_test.go"
        # No commands recommended
        assert report["recommended_commands"] == []
        assert report["capabilities"]["runner_supported"] is False


def test_mixed_language_negative_controls(tmp_path: Path) -> None:
    root = tmp_path / "mixed_repo"
    root.mkdir(parents=True, exist_ok=True)
    # Python project with pyproject.toml
    (root / "pyproject.toml").write_text('[project]\nname="mixed"\n', encoding="utf-8")
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "calc.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_calc.py").write_text(
        "from src.calc import add\ndef test_add(): assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    # Go project
    (root / "internal").mkdir(parents=True, exist_ok=True)
    (root / "internal" / "calc.go").write_text("package internal\n", encoding="utf-8")
    (root / "internal" / "calc_test.go").write_text("package internal\n", encoding="utf-8")

    Indexer(root).initialize()
    with IndexDatabase(root) as db:
        # Case A: Only Python changes -> full support
        py_report = analyze_test_impact(db, ["src/calc.py"])
        assert py_report["capabilities"]["test_selection_supported"] is True
        assert py_report["capabilities"]["runner_supported"] is True
        assert any(cmd["framework"] == "pytest" for cmd in py_report["recommended_commands"])

        # Case B: Both Python and Go change
        mixed_report = analyze_test_impact(db, ["src/calc.py", "internal/calc_test.go"])
        # Python test is selected
        selected_files = [t["file"] for t in mixed_report["existing_tests"]]
        assert "tests/test_calc.py" in selected_files
        assert "internal/calc_test.go" in selected_files
        # Go test is NOT in uncovered_areas
        assert "internal/calc_test.go" not in [g["path"] for g in mixed_report["uncovered_areas"]]
        # Only Python pytest command is recommended; no Go command
        for cmd in mixed_report["recommended_commands"]:
            assert "go test" not in cmd["command"]


def test_markdown_and_json_rendering(tmp_path: Path) -> None:
    root = tmp_path / "go_render"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pkg").mkdir(parents=True, exist_ok=True)
    (root / "pkg" / "app.go").write_text("package pkg\n", encoding="utf-8")
    (root / "pkg" / "app_test.go").write_text("package pkg\n", encoding="utf-8")
    Indexer(root).initialize()
    with IndexDatabase(root) as db:
        report = analyze_test_impact(db, ["pkg/app.go", "pkg/app_test.go"])
        # Markdown rendering
        md = render_test_impact(report, "markdown")
        assert "# Lehraz Atlas Free Test Impact" in md
        assert "## Warnings" in md
        assert "Go" in md
        assert "Coverage is **unknown**" in md
        assert "No existing project test command was detected." in md

        # JSON rendering
        json_str = render_test_impact(report, "json")
        assert '"schema_version": "repomind.test-impact.v1"' in json_str
        assert '"runner_supported": false' in json_str
