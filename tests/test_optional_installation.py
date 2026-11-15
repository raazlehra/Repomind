from __future__ import annotations

import builtins
from pathlib import Path

import pytest

from repomind.config import Config
from repomind.doctor import run_doctor
from repomind.errors import RepoMindError
from repomind.indexer import Indexer
from repomind.watcher import watch_repository


@pytest.mark.parametrize("core_present", [False, True])
def test_doctor_missing_optional_backends_uses_verified_artifact_guidance(
    python_repo: Path, monkeypatch: pytest.MonkeyPatch, core_present: bool
) -> None:
    Indexer(python_repo).initialize()

    class BuiltinRegistry:
        supported_languages = ("python", "javascript", "typescript")
        tree_sitter_languages: tuple[str, ...] = ()

    monkeypatch.setattr("repomind.doctor.ParserRegistry", BuiltinRegistry)
    monkeypatch.setattr("repomind.doctor.importlib.util.find_spec", lambda _: core_present or None)
    monkeypatch.setattr("repomind.doctor.watchdog_available", lambda: False)

    result = run_doctor(python_repo)
    assert result["index_health"] == "healthy"
    checks = {item["check"]: item for item in result["checks"]}
    assert "built-in" in checks["tree-sitter"]["detail"]
    for name, extra in [("tree-sitter", "treesitter"), ("watcher", "watch")]:
        hint = checks[name]["action"]
        assert f"[{extra}]" in hint
        assert "checksum-verified" in hint and "GitHub Release wheel" in hint
        assert "github.com/raazlehra/Repomind/" in hint
        assert "pip install" not in hint


@pytest.mark.parametrize("detected", [False, True])
def test_missing_or_unloadable_watchdog_never_recommends_pypi_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, detected: bool
) -> None:
    monkeypatch.setattr("repomind.watcher.watchdog_available", lambda: detected)
    original_import = builtins.__import__

    def without_watchdog(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("watchdog"):
            raise ImportError("simulated missing optional backend")
        return original_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", without_watchdog)
    with pytest.raises(RepoMindError, match="checksum-verified") as error:
        watch_repository(tmp_path, Config(), lambda _: None)
    assert "[watch]" in str(error.value)
    assert "pip install" not in str(error.value)
    assert not (tmp_path / ".repomind").exists()
