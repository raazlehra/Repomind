from __future__ import annotations

import re
import runpy
import tomllib
from pathlib import Path

import pytest

from repomind import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_project_and_runtime_versions_match_release_format() -> None:
    metadata = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = metadata["project"]["version"]

    assert project_version == __version__
    assert re.fullmatch(
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
        r"(?:(?:a|b|rc)(?:0|[1-9]\d*))?",
        __version__,
    )


def test_module_entrypoint_propagates_cli_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("repomind.cli.main", lambda: 17)

    with pytest.raises(SystemExit) as error:
        runpy.run_module("repomind.__main__", run_name="__main__")

    assert error.value.code == 17


def test_apache_license_contains_full_terms() -> None:
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert license_text.startswith("Copyright 2026 RepoMind contributors")
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in license_text
    assert "2. Grant of Copyright License." in license_text
    assert "3. Grant of Patent License." in license_text
    assert "4. Redistribution." in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
