from __future__ import annotations

import importlib.util
import queue
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from repomind.config import Config
from repomind.errors import RepoMindError
from repomind.indexer import Indexer, IndexResult

UpdateCallback = Callable[[IndexResult], None]


def watchdog_available() -> bool:
    return importlib.util.find_spec("watchdog") is not None


def watch_repository(
    root: Path,
    config: Config,
    on_update: UpdateCallback,
    debounce: float = 0.5,
) -> None:
    if not watchdog_available():
        raise RepoMindError(
            "Event-driven watcher support is not installed. Run: pip install 'repomind[watch]'"
        )
    _watch_events(root, config, on_update, debounce)


def _watch_events(root: Path, config: Config, on_update: UpdateCallback, debounce: float) -> None:
    # Dynamic imports keep watchdog optional for the core package. Provide TYPE_CHECKING
    # imports so static analyzers can see the types while retaining runtime optionality.
    if TYPE_CHECKING:
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer
    try:
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError as exc:
        raise RepoMindError(
            "watchdog could not be loaded; install: pip install 'repomind[watch]'"
        ) from exc
    events: queue.Queue[str] = queue.Queue()

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event: FileSystemEvent) -> None:
            source = str(event.src_path)
            destination = str(event.dest_path) if hasattr(event, "dest_path") else ""
            for candidate in (source, destination):
                if not candidate:
                    continue
                try:
                    relative = Path(candidate).resolve().relative_to(root).as_posix()
                except ValueError:
                    continue
                parts = Path(relative).parts
                if ".repomind" not in parts and ".git" not in parts:
                    events.put(relative)

    observer = Observer()
    observer.schedule(Handler(), str(root), recursive=True)
    observer.start()
    indexer = Indexer(root, config)
    try:
        while True:
            events.get()
            deadline = time.monotonic() + debounce
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    events.get(timeout=remaining)
                    deadline = time.monotonic() + debounce
                except queue.Empty:
                    break
            result = indexer.refresh()
            if result.changes.total:
                on_update(result)
    except KeyboardInterrupt:
        return
    finally:
        observer.stop()
        observer.join(timeout=5)
