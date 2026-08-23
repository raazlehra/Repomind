from __future__ import annotations


class RepoMindError(Exception):
    """Expected, user-actionable RepoMind error."""


class NotIndexedError(RepoMindError):
    """Raised when a command needs an index but none exists."""

    def __init__(self) -> None:
        super().__init__("Repository is not indexed. Run: repomind init")


class ConfigError(RepoMindError):
    """Raised for invalid .repomind.toml content."""
