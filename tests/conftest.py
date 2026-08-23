from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def python_repo(tmp_path: Path) -> Path:
    target = tmp_path / "python_app"
    shutil.copytree(FIXTURES / "python_app", target)
    return target


@pytest.fixture
def mixed_repo(tmp_path: Path) -> Path:
    target = tmp_path / "mixed_app"
    shutil.copytree(FIXTURES / "mixed_app", target)
    return target
