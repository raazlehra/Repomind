from __future__ import annotations

import fnmatch
import os
import re
import stat
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repomind.config import Config
from repomind.models import ScannedFile

_TOP_LEVEL_TEST_CALL = re.compile(
    r"(?m)^(?:(?:export\s+)?(?:default\s+)?\s*)?(?:describe|test|it|suite)\s*(?:\.(?:only|skip|todo|concurrent|each))?\s*\("
)


def _is_symlink_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        if sys.platform == "win32":
            st = os.lstat(path)
            tag = getattr(st, "st_reparse_tag", 0)
            if tag in {
                getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0),
                getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0),
            }:
                return True
    except OSError:
        return True
    return False


def _has_top_level_test_runner_calls(path: Path) -> bool:
    try:
        if _is_symlink_or_junction(path):
            return False
        for parent in path.parents:
            if str(parent) == path.anchor:
                break
            if _is_symlink_or_junction(parent):
                return False
        if path.stat().st_size > 1_000_000:
            return False
        content = path.read_text(encoding="utf-8-sig", errors="replace")
        clean_content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
        clean_content = re.sub(r"//.*$", "", clean_content, flags=re.MULTILINE)
        return bool(_TOP_LEVEL_TEST_CALL.search(clean_content))
    except OSError:
        return False

SOURCE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".c": "c",
    ".h": "cpp",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sh": "shell",
    ".bash": "shell",
    ".sql": "sql",
}
CONFIG_EXTENSIONS = {
    ".json",
    ".jsonl",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".xml",
    ".properties",
}
DOC_EXTENSIONS = {".md", ".mdx", ".rst", ".adoc"}
SPECIAL_CONFIGS = {
    "Dockerfile",
    "Makefile",
    "Procfile",
    "requirements.txt",
    "Pipfile",
    "go.mod",
    "go.work",
    "go.work.sum",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "tsconfig.json",
    "docker-compose.yml",
    "docker-compose.yaml",
}

TEST_SUPPORT_DIRECTORIES = {
    "data",
    "factories",
    "fixtures",
    "helpers",
    "support",
    "testdata",
    "utilities",
}


def is_executable_test_path(relative: str, root: Path | None = None) -> bool:
    """Return whether a path is an executable test target rather than test support."""
    path = PurePosixPath(relative.replace("\\", "/"))
    name = path.name.lower()
    suffix = path.suffix.lower()
    lower_parts = {part.lower() for part in path.parts[:-1]}
    if lower_parts & TEST_SUPPORT_DIRECTORIES:
        return False
    if name in {"conftest.py", "e2e_server.py"}:
        return False
    if suffix == ".py":
        return name.startswith("test_") or name.endswith("_test.py")
    if suffix in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx"}:
        if not (".test." in name or ".spec." in name):
            return False
        # Case helpers vs runnable case suites
        if ".case.test." in name or ".case.spec." in name or name.startswith(("common.", "helper.", "base.")):
            if root is not None:
                target_file = root / relative
                if target_file.is_file():
                    return _has_top_level_test_runner_calls(target_file)
            if name.startswith(("common.", "helper.", "base.")):
                return False
        return True
    if suffix in {".java", ".kt", ".kts", ".cs"}:
        stem = path.stem.lower()
        return (
            "test" in lower_parts
            or "tests" in lower_parts
            or "androidtest" in lower_parts
            or stem.endswith(("test", "tests", "testcase"))
        )
    if suffix == ".go":
        return name.endswith("_test.go")
    return ".maestro" in lower_parts and suffix in {".yaml", ".yml"}


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    pattern: str
    base: str
    negated: bool
    directory_only: bool

    def matches(self, relative: str, is_dir: bool) -> bool:
        if self.directory_only and not is_dir:
            return False
        candidate = relative
        if self.base:
            prefix = f"{self.base}/"
            if not candidate.startswith(prefix):
                return False
            candidate = candidate[len(prefix) :]
        pattern = self.pattern.lstrip("/")
        if "/" not in pattern:
            return fnmatch.fnmatchcase(PurePosixPath(candidate).name, pattern)
        return fnmatch.fnmatchcase(candidate, pattern) or PurePosixPath(candidate).match(pattern)


class IgnoreMatcher:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.rules: list[IgnoreRule] = []
        for pattern in config.exclude:
            self.rules.append(self._make_rule(pattern, ""))

    @staticmethod
    def _make_rule(raw: str, base: str) -> IgnoreRule:
        stripped = raw.strip()
        negated = stripped.startswith("!")
        if negated:
            stripped = stripped[1:]
        directory_only = stripped.endswith("/")
        stripped = stripped.rstrip("/")
        return IgnoreRule(stripped, base, negated, directory_only)

    def load_file(self, path: Path, base: str) -> None:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            self.rules.append(self._make_rule(stripped, base))

    def forced_include(self, relative: str) -> bool:
        return any(_pattern_matches(pattern, relative) for pattern in self.config.include)

    def should_ignore(self, relative: str, is_dir: bool) -> bool:
        path = PurePosixPath(relative)
        parts = path.parts
        # Index internals and Git internals are always hard exclusions.
        if ".repomind" in parts or ".git" in parts:
            return True
        if is_dir and path.name in self.config.generated_directories:
            return not self._could_contain_include(relative)
        ignored = False
        for rule in self.rules:
            if rule.matches(relative, is_dir):
                ignored = not rule.negated
        if self.forced_include(relative):
            return False
        return ignored

    def _could_contain_include(self, relative: str) -> bool:
        prefix = relative.rstrip("/") + "/"
        return any(
            pattern.lstrip("!").lstrip("/").startswith(prefix) for pattern in self.config.include
        )


def _pattern_matches(pattern: str, relative: str) -> bool:
    clean = pattern.lstrip("!").lstrip("/").rstrip("/")
    return (
        fnmatch.fnmatchcase(relative, clean)
        or PurePosixPath(relative).match(clean)
        or ("/" not in clean and fnmatch.fnmatchcase(PurePosixPath(relative).name, clean))
    )


def _is_secret(relative: str, config: Config) -> bool:
    name = PurePosixPath(relative).name
    return any(
        _pattern_matches(pattern, relative) or fnmatch.fnmatchcase(name, pattern)
        for pattern in config.secret_patterns
    )


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            sample = handle.read(8192)
    except OSError:
        return True
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    control = sum(byte < 9 or 13 < byte < 32 for byte in sample)
    return control / len(sample) > 0.08


def classify_file(relative: str, root: Path | None = None) -> tuple[str, str, bool] | None:
    path = PurePosixPath(relative)
    name = path.name
    lower_name = name.lower()
    suffix = path.suffix.lower()
    lower_parts = {part.lower() for part in path.parts}
    is_exec_test = is_executable_test_path(relative, root=root)
    is_test = (
        is_exec_test
        or ".case.test." in lower_name
        or ".case.spec." in lower_name
        or lower_name.endswith(
            (
                ".case.test.ts",
                ".case.test.tsx",
                ".case.test.js",
                ".case.test.jsx",
                ".case.spec.ts",
                ".case.spec.tsx",
            )
        )
    )
    if name in SPECIAL_CONFIGS or name.startswith(("vite.config.", "next.config.")):
        return "config", "configuration", is_test
    if suffix in SOURCE_EXTENSIONS:
        language = SOURCE_EXTENSIONS[suffix]
        if is_test:
            purpose = "test"
        elif "migration" in lower_parts or "migrations" in lower_parts:
            purpose = "migration"
        elif any(part in lower_parts for part in {"routes", "controllers", "api"}):
            purpose = "api"
        else:
            purpose = "source"
        return language, purpose, is_test
    if suffix in CONFIG_EXTENSIONS:
        return "config", "configuration", is_test
    if suffix in DOC_EXTENSIONS:
        return "documentation", "documentation", is_test
    return None


class RepositoryScanner:
    def __init__(self, root: Path, config: Config) -> None:
        self.root = root.resolve()
        self.config = config

    def scan(self) -> Iterator[ScannedFile]:
        matcher = IgnoreMatcher(self.config)
        root_gitignore = self.root / ".gitignore"
        root_rmignore = self.root / ".repomindignore"
        if root_gitignore.is_file():
            matcher.load_file(root_gitignore, "")
        if root_rmignore.is_file():
            matcher.load_file(root_rmignore, "")

        for current, dirnames, filenames in os.walk(self.root, topdown=True, followlinks=False):
            current_path = Path(current)
            base = current_path.relative_to(self.root).as_posix()
            if base == ".":
                base = ""
            # Nested .gitignore patterns apply from their containing directory.
            if base:
                nested_ignore = current_path / ".gitignore"
                nested_rmignore = current_path / ".repomindignore"
                if nested_ignore.is_file():
                    matcher.load_file(nested_ignore, base)
                if nested_rmignore.is_file():
                    matcher.load_file(nested_rmignore, base)

            kept_dirs: list[str] = []
            for dirname in sorted(dirnames):
                relative = f"{base}/{dirname}" if base else dirname
                path = current_path / dirname
                if _is_symlink_or_junction(path) or matcher.should_ignore(relative, is_dir=True):
                    continue
                kept_dirs.append(dirname)
            dirnames[:] = kept_dirs

            for filename in sorted(filenames):
                path = current_path / filename
                if _is_symlink_or_junction(path):
                    continue
                relative = f"{base}/{filename}" if base else filename
                relative = PurePosixPath(relative).as_posix()
                if matcher.should_ignore(relative, is_dir=False) or _is_secret(
                    relative, self.config
                ):
                    continue
                classified = classify_file(relative, root=self.root)
                if classified is None and not matcher.forced_include(relative):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size > self.config.max_file_size or _is_binary(path):
                    continue
                language, purpose, is_test = classified or ("text", "other", False)
                if self.config.languages and language not in self.config.languages:
                    continue
                yield ScannedFile(
                    path=relative,
                    absolute_path=path,
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    language=language,
                    purpose=purpose,
                    is_test=is_test,
                )
