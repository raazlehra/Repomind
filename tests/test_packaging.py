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
