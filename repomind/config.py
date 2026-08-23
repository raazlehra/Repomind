from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repomind.errors import ConfigError

DEFAULT_GENERATED = (
    ".git",
    ".repomind",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".next",
    ".nuxt",
    "target",
    "vendor",
    "__pycache__",
    ".venv",
    "venv",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
)
DEFAULT_SECRETS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "credentials*",
    "secrets*",
    "*credential*.json",
    "id_rsa*",
    "id_ed25519*",
)


@dataclass(frozen=True, slots=True)
class Config:
    exclude: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    context_budget: int = 2000
    watch: bool = False
    languages: tuple[str, ...] = ()
    max_file_size: int = 1_000_000
    generated_directories: tuple[str, ...] = DEFAULT_GENERATED
    secret_patterns: tuple[str, ...] = DEFAULT_SECRETS

    @classmethod
    def load(cls, root: Path) -> Config:
        path = root / ".repomind.toml"
        if not path.exists():
            return cls()
        try:
            with path.open("rb") as handle:
                raw = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Invalid .repomind.toml: {exc}") from exc
        section: dict[str, Any]
        selected = raw.get("repomind", raw)
        if not isinstance(selected, dict):
            raise ConfigError(".repomind.toml must contain a table of settings")
        section = selected

        def strings(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
            value = section.get(name, list(default))
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ConfigError(f"{name} must be an array of strings")
            return tuple(value)

        budget = section.get("context_budget", 2000)
        max_size = section.get("max_file_size", 1_000_000)
        watch = section.get("watch", False)
        if not isinstance(budget, int) or budget < 100:
            raise ConfigError("context_budget must be an integer of at least 100")
        if not isinstance(max_size, int) or max_size < 1024:
            raise ConfigError("max_file_size must be an integer of at least 1024")
        if not isinstance(watch, bool):
            raise ConfigError("watch must be true or false")
        return cls(
            exclude=strings("exclude", ()),
            include=strings("include", ()),
            context_budget=budget,
            watch=watch,
            languages=strings("languages", ()),
            max_file_size=max_size,
            generated_directories=strings("generated_directories", DEFAULT_GENERATED),
            secret_patterns=strings("secret_patterns", DEFAULT_SECRETS),
        )
