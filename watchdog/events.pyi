from typing import Any


class FileSystemEvent:
    src_path: str
    dest_path: str | None


class FileSystemEventHandler:
    def on_any_event(self, event: FileSystemEvent) -> None: ...
