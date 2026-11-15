from __future__ import annotations

from pathlib import Path

from repomind.config import Config
from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.test_impact import TestImpactLimits, analyze_test_impact


def _create_sqlite_repo(root: Path, files: dict[str, str]) -> IndexDatabase:
    """Helper to create files and index them with RepoMind Indexer."""
    for rel_path, content in files.items():
        p = root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    indexer = Indexer(root, Config.load(root))
    indexer.initialize()
    return IndexDatabase(root)


def test_direct_qualified_import_and_call_selected(tmp_path: Path) -> None:
    """Direct qualified import and call must be selected in targeted pytest command."""
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "src/__init__.py": "",
        "src/worker.py": "def do_work(): return 42\n",
        "tests/__init__.py": "",
        "tests/test_worker.py": (
            "from src.worker import do_work\n"
            "def test_work():\n"
            "    assert do_work() == 42\n"
        ),
        "tests/test_other.py": (
            "def test_unrelated():\n"
            "    assert True\n"
        ),
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["src/worker.py"])
        cmds = report["recommended_commands"]
        targeted = [c for c in cmds if c["scope"] == "targeted" and c["framework"] == "pytest"]
        assert len(targeted) == 1
        assert "tests/test_worker.py" in targeted[0]["related_tests"]
        assert "tests/test_other.py" not in targeted[0]["related_tests"]


def test_package_facade_reexport_demoted_to_broad(tmp_path: Path) -> None:
    """Tests reaching ONLY via package __init__.py facade without direct symbol usage

    must be demoted to broad fallback and NOT included in the targeted pytest command.
    """
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "pkg/__init__.py": (
            "from .submodule import special_func\n"
            "from .unrelated import other_func\n"
        ),
        "pkg/submodule.py": "def special_func(): return 'special'\n",
        "pkg/unrelated.py": "def other_func(): return 'other'\n",
        "tests/__init__.py": "",
        "tests/test_special.py": (
            "import pkg\n"
            "def test_special():\n"
            "    assert pkg.special_func() == 'special'\n"
        ),
        "tests/test_only_imports_pkg.py": (
            "import pkg\n"
            "def test_other():\n"
            "    assert pkg.other_func() == 'other'\n"
        ),
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["pkg/submodule.py"])
        cmds = report["recommended_commands"]
        targeted = [c for c in cmds if c["scope"] == "targeted" and c["framework"] == "pytest"]
        assert len(targeted) == 1
        # test_special calls special_func which originates in pkg/submodule.py -> targeted
        assert "tests/test_special.py" in targeted[0]["related_tests"]
        # test_only_imports_pkg merely imports pkg and uses unrelated other_func -> NOT in targeted
        assert "tests/test_only_imports_pkg.py" not in targeted[0]["related_tests"]

        # In existing_tests, test_only_imports_pkg should be recorded with low confidence / facade reachability
        existing = {t["file"]: t for t in report.get("existing_tests", [])}
        assert "tests/test_only_imports_pkg.py" in existing
        assert existing["tests/test_only_imports_pkg.py"]["confidence"] == "low"
        facade_ev = [
            e for e in existing["tests/test_only_imports_pkg.py"].get("evidence", [])
            if e.get("kind") == "facade-reachability"
        ]
        assert len(facade_ev) >= 1


def test_dynamic_imports_and_unobservable_runtime_dispatch(tmp_path: Path) -> None:
    """Dynamic reflection or dynamic imports with no observable static relationship

    must report coverage='unknown' and not be falsely claimed as targeted.
    """
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "src/__init__.py": "",
        "src/loader.py": "def load_dynamic(): return 123\n",
        "tests/__init__.py": "",
        "tests/test_dynamic.py": (
            "import importlib\n"
            "def test_dynamic():\n"
            "    mod = importlib.import_module('src.loader')\n"
            "    assert getattr(mod, 'load_dynamic')() == 123\n"
        ),
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["src/loader.py"])
        # Because importlib.import_module is dynamic and unobservable in AST,
        # loader.py must be in uncovered_areas with coverage='unknown'
        uncovered = [u for u in report["uncovered_areas"] if u["path"] == "src/loader.py"]
        assert len(uncovered) == 1
        assert uncovered[0]["coverage"] == "unknown"


def test_sibling_and_flat_test_layouts(tmp_path: Path) -> None:
    """Sibling tests and flat tests/test_<name>.py layouts match by component stem."""
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "src/__init__.py": "",
        "src/billing.py": "def bill(): pass\n",
        "src/core/__init__.py": "",
        "src/core/auth.py": "def authenticate(): pass\n",
        "src/core/test_auth.py": "def test_auth(): pass\n",
        "tests/__init__.py": "",
        "tests/test_billing.py": "def test_bill(): pass\n",
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["src/billing.py", "src/core/auth.py"])
        cmds = report["recommended_commands"]
        targeted = [c for c in cmds if c["scope"] == "targeted" and c["framework"] == "pytest"]
        assert len(targeted) == 1
        assert "tests/test_billing.py" in targeted[0]["related_tests"]
        assert "src/core/test_auth.py" in targeted[0]["related_tests"]


def test_two_similarly_named_components_no_cross_match(tmp_path: Path) -> None:
    """src/billing/token.py should NOT match tests/auth/test_token.py across different components."""
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "src/billing/__init__.py": "",
        "src/billing/token.py": "def generate_billing_token(): pass\n",
        "src/auth/__init__.py": "",
        "src/auth/token.py": "def generate_auth_token(): pass\n",
        "tests/billing/__init__.py": "",
        "tests/billing/test_token.py": "def test_billing_token(): pass\n",
        "tests/auth/__init__.py": "",
        "tests/auth/test_token.py": "def test_auth_token(): pass\n",
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["src/billing/token.py"])
        cmds = report["recommended_commands"]
        targeted = [c for c in cmds if c["scope"] == "targeted" and c["framework"] == "pytest"]
        assert len(targeted) == 1
        assert "tests/billing/test_token.py" in targeted[0]["related_tests"]
        assert "tests/auth/test_token.py" not in targeted[0]["related_tests"]


def test_multiple_changed_files_fair_caps(tmp_path: Path) -> None:
    """Fair graph traversal quota is distributed across multiple changed files."""
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "src/__init__.py": "",
        "src/a.py": "a = 1\n",
        "src/b.py": "b = 2\n",
        "src/c.py": "c = 3\n",
        "tests/__init__.py": "",
        "tests/test_a.py": "from src.a import a\n",
        "tests/test_b.py": "from src.b import b\n",
        "tests/test_c.py": "from src.c import c\n",
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        limits = TestImpactLimits(max_graph_nodes=3)
        report = analyze_test_impact(db, changed_files=["src/a.py", "src/b.py", "src/c.py"], limits=limits)
        assert report["truncation"]["graph"]["fair_quota_applied"] is True


def test_mixed_python_and_go_unaffected(tmp_path: Path) -> None:
    """Mixed Python and Go changes preserve Python test selection while reporting truthful Go capabilities."""
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "pkg/__init__.py": "",
        "pkg/module.py": "def calc(): return 1\n",
        "pkg/handler.go": "package pkg\nfunc Handle() {}\n",
        "tests/__init__.py": "",
        "tests/test_module.py": "from pkg.module import calc\ndef test_calc(): assert calc() == 1\n",
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["pkg/module.py", "pkg/handler.go"])
        caps = report["capabilities"]
        assert caps["by_language"]["python"]["runner_supported"] is True
        assert caps["by_language"]["go"]["runner_supported"] is False
        cmds = report["recommended_commands"]
        pytest_cmds = [c for c in cmds if c["framework"] == "pytest"]
        assert len(pytest_cmds) >= 1
        go_cmds = [c for c in cmds if c["framework"] == "go"]
        assert len(go_cmds) == 0


def test_test_module_owning_runner_boundary(tmp_path: Path) -> None:
    """Owning project boundary groups tests and commands correctly."""
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir(parents=True)
    files = {
        "backend/pyproject.toml": "[tool.pytest.ini_options]\n",
        "backend/service.py": "def svc(): return 99\n",
        "backend/tests/__init__.py": "",
        "backend/tests/test_service.py": "from service import svc\ndef test_svc(): assert svc() == 99\n",
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["backend/service.py"])
        cmds = report["recommended_commands"]
        targeted = [c for c in cmds if c["scope"] == "targeted" and c["framework"] == "pytest"]
        assert len(targeted) == 1
        assert targeted[0]["working_directory"] == "backend"
        assert targeted[0]["argv"] == ["python", "-m", "pytest", "tests/test_service.py"]


def test_directly_changed_tests_never_silently_dropped(tmp_path: Path) -> None:
    """Directly changed test files in git diff are always included in targeted commands with high confidence."""
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "src/__init__.py": "",
        "src/core.py": "x = 1\n",
        "tests/__init__.py": "",
        "tests/test_unrelated_custom.py": "def test_custom(): pass\n",
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["src/core.py", "tests/test_unrelated_custom.py"])
        cmds = report["recommended_commands"]
        targeted = [c for c in cmds if c["scope"] == "targeted" and c["framework"] == "pytest"]
        assert len(targeted) == 1
        assert "tests/test_unrelated_custom.py" in targeted[0]["related_tests"]
        existing = {t["file"]: t for t in report.get("existing_tests", [])}
        assert existing["tests/test_unrelated_custom.py"]["confidence"] == "high"


def test_unverifiable_static_relationship_flagged_unknown(tmp_path: Path) -> None:
    """Changed files without verified tests are flagged coverage='unknown' in uncovered_areas."""
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "src/__init__.py": "",
        "src/secret.py": "def secret(): pass\n",
        "tests/__init__.py": "",
        "tests/test_public.py": "def test_public(): pass\n",
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["src/secret.py"])
        uncovered = [u for u in report["uncovered_areas"] if u["path"] == "src/secret.py"]
        assert len(uncovered) == 1
        assert uncovered[0]["coverage"] == "unknown"
        assert "absence-of-matching-static-evidence" in uncovered[0]["evidence"]["kind"]


def test_py01_synthetic_fixture_retains_client_and_demotes_unrelated_models(tmp_path: Path) -> None:
    """Synthetic PY-01 fixture: changing _config.py retains tests/client/test_client.py

    and demotes tests/models/test_model.py which only imports the package root facade.
    """
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "httpx/__init__.py": (
            "from ._config import Timeout, Proxy\n"
            "from ._client import Client\n"
            "from ._models import Model\n"
        ),
        "httpx/_config.py": (
            "class Timeout: pass\n"
            "class Proxy: pass\n"
        ),
        "httpx/_client.py": (
            "from ._config import Timeout, Proxy\n"
            "class Client:\n"
            "    def __init__(self): self.timeout = Timeout()\n"
        ),
        "httpx/_models.py": (
            "class Model: pass\n"
        ),
        "tests/__init__.py": "",
        "tests/test_config.py": (
            "import httpx\n"
            "def test_cfg(): assert httpx.Timeout\n"
        ),
        "tests/client/__init__.py": "",
        "tests/client/test_client.py": (
            "import httpx\n"
            "def test_cli(): c = httpx.Client()\n"
        ),
        "tests/models/__init__.py": "",
        "tests/models/test_model.py": (
            "import httpx\n"
            "def test_mod(): m = httpx.Model()\n"
        ),
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        report = analyze_test_impact(db, changed_files=["httpx/_config.py"])
        cmds = report["recommended_commands"]
        targeted = [c for c in cmds if c["scope"] == "targeted" and c["framework"] == "pytest"]
        assert len(targeted) == 1
        rel_tests = targeted[0]["related_tests"]
        # test_config.py directly calls Timeout -> targeted
        assert "tests/test_config.py" in rel_tests
        # test_client.py calls Client which directly depends on Timeout -> targeted
        assert "tests/client/test_client.py" in rel_tests
        # test_model.py ONLY reaches via httpx/__init__.py -> demoted, NOT in targeted!
        assert "tests/models/test_model.py" not in rel_tests


def test_py02_synthetic_fixture_preserves_changed_tests_and_demotes_facade(tmp_path: Path) -> None:
    """Synthetic PY-02 fixture: changing _content.py and changed test files retains

    changed tests and direct tests, while demoting unrelated tests that only import facade.
    """
    files = {
        "pyproject.toml": "[tool.pytest.ini_options]\n",
        "httpx/__init__.py": (
            "from ._content import encode_json\n"
            "from ._models import Request\n"
            "from ._utils import helper\n"
        ),
        "httpx/_content.py": (
            "def encode_json(val): return str(val)\n"
        ),
        "httpx/_models.py": (
            "from ._content import encode_json\n"
            "class Request:\n"
            "    def __init__(self, data): self.body = encode_json(data)\n"
        ),
        "httpx/_utils.py": (
            "def helper(): return 1\n"
        ),
        "tests/__init__.py": "",
        "tests/test_content.py": (
            "import httpx\n"
            "def test_content(): assert httpx.encode_json(1) == '1'\n"
        ),
        "tests/models/__init__.py": "",
        "tests/models/test_requests.py": (
            "import httpx\n"
            "def test_req(): r = httpx.Request(1)\n"
        ),
        "tests/test_utils.py": (
            "import httpx\n"
            "def test_ut(): assert httpx.helper() == 1\n"
        ),
    }
    with _create_sqlite_repo(tmp_path, files) as db:
        # PR changes _content.py and tests/test_content.py
        report = analyze_test_impact(db, changed_files=["httpx/_content.py", "tests/test_content.py"])
        cmds = report["recommended_commands"]
        targeted = [c for c in cmds if c["scope"] == "targeted" and c["framework"] == "pytest"]
        assert len(targeted) == 1
        rel_tests = targeted[0]["related_tests"]
        # tests/test_content.py changed and calls encode_json -> targeted
        assert "tests/test_content.py" in rel_tests
        # tests/models/test_requests.py calls Request which calls encode_json -> targeted
        assert "tests/models/test_requests.py" in rel_tests
        # tests/test_utils.py only imports httpx and calls helper -> demoted, NOT in targeted!
        assert "tests/test_utils.py" not in rel_tests
