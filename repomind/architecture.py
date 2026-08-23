from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from repomind.models import ArchitectureFact

PYTHON_TECH: dict[str, tuple[str, str]] = {
    "fastapi": ("backend", "FastAPI"),
    "django": ("backend", "Django"),
    "flask": ("backend", "Flask"),
    "starlette": ("backend", "Starlette"),
    "sqlalchemy": ("database-library", "SQLAlchemy"),
    "psycopg": ("database-library", "PostgreSQL/psycopg"),
    "psycopg2": ("database-library", "PostgreSQL/psycopg"),
    "asyncpg": ("database-library", "PostgreSQL/asyncpg"),
    "pymongo": ("database-library", "MongoDB/PyMongo"),
    "pytest": ("testing", "Pytest"),
}
JS_TECH: dict[str, tuple[str, str]] = {
    "react": ("frontend", "React"),
    "next": ("framework", "Next.js"),
    "vue": ("frontend", "Vue"),
    "svelte": ("frontend", "Svelte"),
    "express": ("backend", "Express"),
    "fastify": ("backend", "Fastify"),
    "@nestjs/core": ("backend", "NestJS"),
    "prisma": ("database-library", "Prisma"),
    "@prisma/client": ("database-library", "Prisma"),
    "pg": ("database-library", "PostgreSQL/node-postgres"),
    "mongoose": ("database-library", "MongoDB/Mongoose"),
    "vitest": ("testing", "Vitest"),
    "jest": ("testing", "Jest"),
    "typescript": ("language", "TypeScript"),
    "vite": ("build", "Vite"),
}


def _fact(category: str, name: str, evidence: str, confidence: float = 1.0) -> ArchitectureFact:
    return ArchitectureFact(category, name, evidence, confidence)


def detect_architecture(root: Path, indexed_paths: Iterable[str]) -> list[ArchitectureFact]:
    paths = set(indexed_paths)
    facts: list[ArchitectureFact] = []
    suffixes = {Path(path).suffix.lower() for path in paths}
    if ".py" in suffixes or ".pyi" in suffixes:
        facts.append(_fact("language", "Python", "*.py"))
    if suffixes & {".js", ".jsx", ".mjs", ".cjs"}:
        facts.append(_fact("language", "JavaScript", "*.js/*.jsx"))
    if suffixes & {".ts", ".tsx", ".mts", ".cts"}:
        facts.append(_fact("language", "TypeScript", "*.ts/*.tsx"))
    for extension, name in (
        (".go", "Go"),
        (".rs", "Rust"),
        (".java", "Java"),
        (".cs", "C#"),
        (".cpp", "C++"),
        (".c", "C"),
    ):
        if extension in suffixes:
            facts.append(_fact("language", name, f"*{extension}"))

    for relative in paths:
        name = Path(relative).name
        path = root / relative
        if name == "pyproject.toml":
            facts.extend(_from_pyproject(path, relative))
        elif name in {"requirements.txt", "Pipfile"}:
            facts.extend(_from_python_requirements(path, relative))
        elif name == "package.json":
            facts.extend(_from_package_json(path, relative))
        elif name == "go.mod":
            facts.append(_fact("build", "Go modules", relative))
        elif name == "Cargo.toml":
            facts.append(_fact("build", "Cargo", relative))
        elif name == "pom.xml":
            facts.append(_fact("build", "Maven", relative))
            facts.extend(
                _from_text_markers(
                    path,
                    relative,
                    {"spring-boot": ("backend", "Spring Boot"), "junit": ("testing", "JUnit")},
                )
            )
        elif name in {"build.gradle", "settings.gradle"}:
            facts.append(_fact("build", "Gradle", relative))
        elif name == "Dockerfile":
            facts.append(_fact("deployment", "Docker", relative))
        elif name in {"docker-compose.yml", "docker-compose.yaml"}:
            facts.append(_fact("deployment", "Docker Compose", relative))
            facts.extend(
                _from_text_markers(
                    path,
                    relative,
                    {
                        "postgres:": ("database", "PostgreSQL"),
                        "mysql:": ("database", "MySQL"),
                        "redis:": ("data-store", "Redis"),
                    },
                )
            )
        elif name.startswith("vite.config."):
            facts.append(_fact("build", "Vite", relative))
        elif name.startswith("next.config."):
            facts.append(_fact("framework", "Next.js", relative))
        elif name == "tsconfig.json":
            facts.append(_fact("language", "TypeScript", relative))

    return sorted(set(facts), key=lambda item: (item.category, item.name, item.evidence))


def _from_pyproject(path: Path, evidence: str) -> list[ArchitectureFact]:
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return []
    values: list[str] = []
    project = raw.get("project", {})
    if isinstance(project, dict):
        dependencies = project.get("dependencies", [])
        if isinstance(dependencies, list):
            values.extend(str(item) for item in dependencies)
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for group in optional.values():
                if isinstance(group, list):
                    values.extend(str(item) for item in group)
    poetry = raw.get("tool", {}).get("poetry", {}) if isinstance(raw.get("tool"), dict) else {}
    if isinstance(poetry, dict) and isinstance(poetry.get("dependencies"), dict):
        values.extend(str(item) for item in poetry["dependencies"])
    return _tech_facts(values, PYTHON_TECH, evidence)


def _from_python_requirements(path: Path, evidence: str) -> list[ArchitectureFact]:
    try:
        values = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return _tech_facts(values, PYTHON_TECH, evidence)


def _from_package_json(path: Path, evidence: str) -> list[ArchitectureFact]:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    packages: list[str] = []
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        values = raw.get(section, {})
        if isinstance(values, dict):
            packages.extend(str(item) for item in values)
    facts = _tech_facts(packages, JS_TECH, evidence)
    scripts = raw.get("scripts", {})
    if isinstance(scripts, dict) and any("webpack" in str(value) for value in scripts.values()):
        facts.append(_fact("build", "Webpack", evidence))
    return facts


def _tech_facts(
    values: Iterable[str], mapping: dict[str, tuple[str, str]], evidence: str
) -> list[ArchitectureFact]:
    output: list[ArchitectureFact] = []
    for raw in values:
        normalized = re.split(r"[<>=!~\[\s@]", raw.strip().lower(), maxsplit=1)[0]
        # Scoped npm packages need their full key, so check prefixes as well.
        for package, (category, name) in mapping.items():
            if normalized == package or raw.strip().lower().startswith(package + "@"):
                output.append(_fact(category, name, evidence))
    return output


def _from_text_markers(
    path: Path, evidence: str, markers: dict[str, tuple[str, str]]
) -> list[ArchitectureFact]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return []
    return [
        _fact(category, name, evidence)
        for marker, (category, name) in markers.items()
        if marker in text
    ]
