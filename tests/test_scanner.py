from __future__ import annotations

from pathlib import Path

from repomind.config import Config
from repomind.scanner import RepositoryScanner, classify_file
from repomind.utils import hash_file


def paths(root: Path, config: Config | None = None) -> set[str]:
    return {item.path for item in RepositoryScanner(root, config or Config.load(root)).scan()}


def test_classifies_sources_tests_configs_and_docs() -> None:
    assert classify_file("src/main.py") == ("python", "source", False)
    assert classify_file("tests/test_main.py") == ("python", "test", True)
    assert classify_file("package.json") == ("config", "configuration", False)
    assert classify_file("README.md") == ("documentation", "documentation", False)
    assert classify_file("photo.png") is None


def test_respects_gitignore_and_generated_directories(python_repo: Path) -> None:
    (python_repo / "node_modules").mkdir()
    (python_repo / "node_modules" / "dep.js").write_text("export const x = 1")
    (python_repo / "build").mkdir()
    (python_repo / "build" / "bundle.js").write_text("const x = 1")
    found = paths(python_repo)
    assert "ignored.py" not in found
    assert "node_modules/dep.js" not in found
    assert "build/bundle.js" not in found
    assert "app/auth.py" in found


def test_secret_and_binary_exclusion(python_repo: Path) -> None:
    (python_repo / ".env").write_text("PASSWORD=secret")
    (python_repo / "credentials-prod.json").write_text('{"token": "secret"}')
    (python_repo / "private.pem").write_text("PRIVATE KEY")
    (python_repo / "binary.py").write_bytes(b"abc\x00def")
    found = paths(python_repo)
    assert ".env" not in found
    assert "credentials-prod.json" not in found
    assert "private.pem" not in found
    assert "binary.py" not in found


def test_repomindignore_and_negation(python_repo: Path) -> None:
    (python_repo / ".repomindignore").write_text("app/*.py\n!app/auth.py\n")
    found = paths(python_repo)
    assert "app/auth.py" in found
    assert "app/models.py" not in found


def test_configuration_include_override(python_repo: Path) -> None:
    (python_repo / "notes.custom").write_text("structural notes")
    config = Config(include=("notes.custom",))
    assert "notes.custom" in paths(python_repo, config)


def test_max_file_size(python_repo: Path) -> None:
    (python_repo / "huge.py").write_text("x" * 5000)
    assert "huge.py" not in paths(python_repo, Config(max_file_size=1024))


def test_file_hash_changes(tmp_path: Path) -> None:
    path = tmp_path / "a.py"
    path.write_text("a = 1")
    before = hash_file(path)
    path.write_text("a = 2")
    assert hash_file(path) != before
