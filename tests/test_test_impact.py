from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from repomind.cli import main
from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.services import test_impact as service_test_impact
from repomind.test_impact import analyze_test_impact, detect_test_commands


def test_changed_service_maps_to_unit_test_without_promoting_unrelated_test(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "service_repo"
    _write(repo / "app" / "services.py", "def charge():\n    return True\n")
    _write(
        repo / "tests" / "test_services.py",
        "from app.services import charge\n\ndef test_charge():\n    assert charge()\n",
    )
    _write(repo / "tests" / "test_unrelated.py", "def test_unrelated():\n    assert True\n")
    Indexer(repo).initialize()

    report = _analyze(repo, ["app/services.py"])

    related = _test_by_path(report, "tests/test_services.py")
    assert related["confidence"] == "high"
    assert related["discovered"] is True
    assert related["structurally_related"] is True
    assert related["coverage"] == "unknown"
    assert "actually_executed" not in related
    assert "passed" not in related
    unrelated = [item for item in report["existing_tests"] if item["file"] == "tests/test_unrelated.py"]
    assert not unrelated or unrelated[0]["confidence"] != "high"
    assert report["uncovered_areas"] == []


def test_route_change_finds_api_test_by_dependency_reachability(tmp_path: Path) -> None:
    repo = tmp_path / "route_repo"
    _write(
        repo / "app" / "routes.py",
        """from fastapi import APIRouter

router = APIRouter()

@router.get("/users")
def list_users():
    return []
""",
    )
    _write(repo / "app" / "main.py", "from app.routes import router\n")
    _write(
        repo / "tests" / "test_api.py",
        "from app.main import router\n\ndef test_users_route():\n    assert router\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["app/routes.py"])

    test = _test_by_path(report, "tests/test_api.py")
    assert test["confidence"] in {"high", "medium"}
    assert test["structurally_related"] is True
    assert any(
        item["kind"] == "route" and item["name"] == "GET /users"
        for item in report["impacted_areas"]["high_confidence"]
    )


def test_route_literal_is_medium_evidence_not_claimed_as_structural(tmp_path: Path) -> None:
    repo = tmp_path / "route_literal_repo"
    _write(
        repo / "app" / "routes.py",
        """from fastapi import APIRouter
router = APIRouter()
@router.post("/orders")
def create_order():
    return {"ok": True}
""",
    )
    _write(
        repo / "tests" / "test_external_api.py",
        "def test_order_endpoint():\n    assert '/orders'.startswith('/')\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["app/routes.py"])
    test = _test_by_path(report, "tests/test_external_api.py")

    assert test["confidence"] == "medium"
    assert test["structurally_related"] is False
    assert "exact changed route path" in " ".join(test["reasons"])


def test_frontend_component_change_finds_frontend_test(tmp_path: Path) -> None:
    repo = tmp_path / "frontend_repo"
    _write(
        repo / "frontend" / "package.json",
        json.dumps(
            {
                "scripts": {"test": "vitest run"},
                "devDependencies": {"vitest": "1.0.0", "react": "18.0.0"},
            }
        ),
    )
    _write(
        repo / "frontend" / "src" / "Dashboard.tsx",
        "export function Dashboard() { return <main>Dashboard</main>; }\n",
    )
    _write(
        repo / "frontend" / "src" / "Dashboard.test.tsx",
        "import { Dashboard } from './Dashboard';\ntest('dashboard', () => { expect(Dashboard).toBeTruthy(); });\n",
    )
    Indexer(repo).initialize()

    report = _analyze(repo, ["frontend/src/Dashboard.tsx"])

    test = _test_by_path(report, "frontend/src/Dashboard.test.tsx")
    assert test["confidence"] == "high"
    assert test["structurally_related"] is True
    targeted = [item for item in report["recommended_commands"] if item["scope"] == "targeted"]
    assert targeted
    assert targeted[0]["framework"] == "vitest"
    assert "Dashboard.test.tsx" in targeted[0]["command"]


def test_no_tests_produces_truthful_gap_and_unknown_coverage(tmp_path: Path) -> None:
    repo = tmp_path / "no_tests_repo"
    _write(repo / "app" / "billing.py", "def total():\n    return 10\n")
    Indexer(repo).initialize()

    report = _analyze(repo, ["app/billing.py"])

    assert report["existing_tests"] == []
    assert report["uncovered_areas"] == [
        {
            "path": "app/billing.py",
            "area": "source",
            "confidence": "high",
            "reason": "No discovered tests were attributable to this changed production area.",
            "coverage": "unknown",
            "evidence": {
                "kind": "absence-of-matching-static-evidence",
                "reviewed_relevant_tests": 0,
            },
        }
    ]
    assert report["recommended_commands"] == []


def test_command_detection_and_multi_language_repository(tmp_path: Path) -> None:
    repo = tmp_path / "mixed_repo"
    _write(
        repo / "pyproject.toml",
        "[project]\nname='sample'\nversion='0.1'\ndependencies=[]\n[project.optional-dependencies]\ndev=['pytest']\n",
    )
    _write(repo / "backend" / "service.py", "def work():\n    return True\n")
    _write(
        repo / "tests" / "test_service.py",
        "from backend.service import work\n\ndef test_work():\n    assert work()\n",
    )
    _write(
        repo / "frontend" / "package.json",
        json.dumps({"scripts": {"test": "vitest run"}, "devDependencies": {"vitest": "1"}}),
    )
    _write(repo / "frontend" / "src" / "Widget.ts", "export const widget = true;\n")
    _write(
        repo / "frontend" / "src" / "Widget.test.ts",
        "import { widget } from './Widget';\ntest('widget', () => expect(widget).toBe(true));\n",
    )
    _write(repo / "build.gradle.kts", "plugins { kotlin(\"jvm\") version \"1.9.0\" }\n")
    _write(repo / "gradlew.bat", "@echo off\n")
    _write(repo / "src" / "main" / "kotlin" / "Thing.kt", "class Thing\n")
    _write(repo / "src" / "test" / "kotlin" / "ThingTest.kt", "class ThingTest\n")
    Indexer(repo).initialize()

    with IndexDatabase(repo) as database:
        tests = analyze_test_impact(
            database, ["backend/service.py", "frontend/src/Widget.ts", "src/main/kotlin/Thing.kt"]
        )["existing_tests"]
        commands, warnings = detect_test_commands(database, tests)

    assert warnings == []
    frameworks = {item["framework"] for item in commands}
    assert {"pytest", "vitest", "gradle"} <= frameworks
    scopes = {item["scope"] for item in commands}
    assert {"targeted", "broad"} <= scopes


def test_unsupported_repository_is_truthful(tmp_path: Path) -> None:
    repo = tmp_path / "docs_only"
    _write(repo / "README.md", "# Documentation only\n")
    Indexer(repo).initialize()

    report = _analyze(repo, ["README.md"])

    assert report["supported"] is False
    assert report["analysis_status"] == "unsupported"
    assert report["existing_tests"] == []
    assert report["uncovered_areas"] == []
    assert "No supported source files were found in the index." in report["warnings"]


def test_cli_rejects_malformed_config_without_modifying_it(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "malformed_config"
    _write(repo / "app.py", "value = 1\n")
    Indexer(repo).initialize()
    malformed = "[repomind\ninvalid"
    _write(repo / ".repomind.toml", malformed)

    result = main(["test-impact", "app.py", "-C", str(repo), "--format", "json"])

    captured = capsys.readouterr()
    assert result == 2
    assert "Invalid .repomind.toml" in captured.err
    assert (repo / ".repomind.toml").read_text(encoding="utf-8") == malformed


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--max-analysis-seconds", "nan"),
        ("--max-analysis-seconds", "inf"),
        ("--max-analysis-seconds", "-inf"),
        ("--max-commands", "0"),
        ("--max-commands", "-1"),
        ("--max-commands", "101"),
    ],
)
def test_cli_rejects_invalid_limits(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    option: str,
    value: str,
) -> None:
    repo = tmp_path / "invalid_limits"
    _write(repo / "app.py", "value = 1\n")
    Indexer(repo).initialize()

    result = main(
        ["test-impact", "app.py", "-C", str(repo), f"{option}={value}", "--format", "json"]
    )

    assert result == 2
    assert "RepoMind error:" in capsys.readouterr().err


def test_dirty_working_tree_is_used_without_commit(tmp_path: Path) -> None:
    repo = tmp_path / "dirty_repo"
    _write(repo / "app" / "service.py", "def value():\n    return 1\n")
    _write(
        repo / "tests" / "test_service.py",
        "from app.service import value\n\ndef test_value():\n    assert value() == 1\n",
    )
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "RepoMind Tests")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    Indexer(repo).initialize()
    _write(repo / "app" / "service.py", "def value():\n    return 2\n")

    report = service_test_impact(str(repo))

    assert report["change_source"] == "working tree"
    assert [item["path"] for item in report["changed_files"]] == ["app/service.py"]
    assert _test_by_path(report, "tests/test_service.py")["confidence"] == "high"


def test_git_diff_base_selects_changed_files(tmp_path: Path) -> None:
    repo = tmp_path / "base_repo"
    _write(repo / "app.py", "value = 1\n")
    _git(repo, "init")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "RepoMind Tests")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    Indexer(repo).initialize()
    _write(repo / "app.py", "value = 2\n")

    report = service_test_impact(str(repo), base="HEAD")

    assert report["change_source"] == "git diff from HEAD"
    assert [item["path"] for item in report["changed_files"]] == ["app.py"]


def test_test_impact_never_starts_a_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "analysis_only"
    _write(repo / "app.py", "def value():\n    return 1\n")
    _write(repo / "tests" / "test_app.py", "from app import value\n\ndef test_value():\n    assert value()\n")
    Indexer(repo).initialize()

    def fail_popen(*args: object, **kwargs: object) -> object:
        raise AssertionError("test-impact must not create a subprocess")

    monkeypatch.setattr(subprocess, "Popen", fail_popen)
    with IndexDatabase(repo) as database:
        report = analyze_test_impact(database, ["app.py"])

    assert report["recommended_commands"]
    assert "plan_id" not in report
    assert "results" not in report
    assert "executed_commands" not in report


def test_cli_help_exposes_no_execution_switches(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as test_impact_exit:
        main(["test-impact", "--help"])
    test_impact_help = capsys.readouterr().out
    with pytest.raises(SystemExit) as mcp_exit:
        main(["mcp", "--help"])
    mcp_help = capsys.readouterr().out

    assert test_impact_exit.value.code == 0
    assert mcp_exit.value.code == 0
    assert "--run" not in test_impact_help
    assert "allow-test-execution" not in mcp_help


def test_cli_json_includes_canonical_test_impact(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "cli_repo"
    _write(repo / "app.py", "def value():\n    return 1\n")
    _write(repo / "tests" / "test_app.py", "from app import value\n\ndef test_value():\n    assert value()\n")
    Indexer(repo).initialize()

    assert main(["test-impact", "app.py", "-C", str(repo), "--format", "json"]) == 0
    cli_report = json.loads(capsys.readouterr().out)
    assert cli_report["schema_version"] == "repomind.test-impact.v1"
    assert cli_report["changed_files"][0]["path"] == "app.py"
    assert cli_report["repository"] == "."
    assert "executed_commands" not in cli_report
    assert "results" not in cli_report
    assert "plan_id" not in cli_report

def _analyze(repo: Path, changed: list[str]) -> dict[str, object]:
    with IndexDatabase(repo) as database:
        return analyze_test_impact(database, changed)


def _test_by_path(report: dict[str, object], path: str) -> dict[str, object]:
    return next(item for item in report["existing_tests"] if item["file"] == path)  # type: ignore[index,union-attr,no-any-return]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
