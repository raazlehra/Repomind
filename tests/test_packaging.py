from __future__ import annotations

import re
import tomllib
from pathlib import Path

from repomind import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_candidate_version_advances_published_beta_9() -> None:
    metadata = tomllib.loads(
        (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    project_version = metadata["project"]["version"]

    assert project_version == __version__
    match = re.fullmatch(r"2\.0\.0b(\d+)", __version__)
    assert match is not None
    assert int(match.group(1)) > 9


def test_apache_license_contains_full_terms() -> None:
    license_text = (PROJECT_ROOT / "LICENSE").read_text(encoding="utf-8")

    assert license_text.startswith("Copyright 2026 RepoMind contributors")
    assert "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION" in license_text
    assert "2. Grant of Copyright License." in license_text
    assert "3. Grant of Patent License." in license_text
    assert "4. Redistribution." in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
