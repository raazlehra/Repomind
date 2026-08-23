from __future__ import annotations

from pathlib import Path

import pytest

from repomind.config import Config
from repomind.errors import RepoMindError
from repomind.watcher import watch_repository


def test_watch_requires_event_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("repomind.watcher.watchdog_available", lambda: False)
    with pytest.raises(RepoMindError, match=r"repomind\[watch\]"):
        watch_repository(tmp_path, Config(), lambda result: None)
