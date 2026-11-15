from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repomind.test_impact import MAX_TEST_SOURCE_BYTES, _is_symlink_or_junction, _read_test_source


def test_read_test_source_reads_regular_file(tmp_path: Path) -> None:
    regular_file = tmp_path / "normal_test.py"
    regular_file.write_text("def test_ok(): pass\n", encoding="utf-8")
    assert _read_test_source(regular_file) == "def test_ok(): pass\n"


def test_read_test_source_rejects_oversized_file(tmp_path: Path) -> None:
    oversized = tmp_path / "huge_test.py"
    oversized.write_text("x" * (MAX_TEST_SOURCE_BYTES + 10), encoding="utf-8")
    assert _read_test_source(oversized) == ""


def test_read_test_source_rejects_file_symlink_mocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    f = tmp_path / "mocked_link.py"
    f.write_text("secret = 1\n", encoding="utf-8")
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == f)
    assert _is_symlink_or_junction(f) is True
    assert _read_test_source(f) == ""


def test_read_test_source_rejects_parent_dir_symlink_mocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = tmp_path / "mocked_dir"
    d.mkdir()
    f = d / "test_nested.py"
    f.write_text("secret = 2\n", encoding="utf-8")
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == d)
    assert _read_test_source(f) == ""


def test_read_test_source_rejects_file_symlink_os(tmp_path: Path) -> None:
    target = tmp_path / "target.py"
    target.write_text("secret_code = 123\n", encoding="utf-8")
    link = tmp_path / "link.py"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"OS file symlink creation unsupported without privilege: {exc}")

    assert _is_symlink_or_junction(link) is True
    assert _read_test_source(link) == ""


def test_read_test_source_rejects_parent_directory_symlink_os(tmp_path: Path) -> None:
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    target_file = real_dir / "test_nested.py"
    target_file.write_text("nested_secret = 456\n", encoding="utf-8")

    link_dir = tmp_path / "link_dir"
    try:
        link_dir.symlink_to(real_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"OS directory symlink creation unsupported without privilege: {exc}")

    assert _is_symlink_or_junction(link_dir) is True
    nested_path = link_dir / "test_nested.py"
    assert _read_test_source(nested_path) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction tests apply on Windows")
def test_read_test_source_rejects_windows_junction(tmp_path: Path) -> None:
    target_dir = tmp_path / "junction_target"
    target_dir.mkdir()
    target_file = target_dir / "test_junction.py"
    target_file.write_text("junction_secret = 789\n", encoding="utf-8")

    junction_dir = tmp_path / "junction_link"
    try:
        import _winapi

        _winapi.CreateJunction(str(target_dir), str(junction_dir))
    except Exception as exc:
        pytest.skip(f"Windows junction creation failed: {exc}")

    assert _is_symlink_or_junction(junction_dir) is True
    junction_file = junction_dir / "test_junction.py"
    assert _read_test_source(junction_file) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction tests apply on Windows")
def test_read_test_source_rejects_deeply_nested_windows_junction(tmp_path: Path) -> None:
    target_dir = tmp_path / "deep_target"
    target_dir.mkdir()
    sub_dir = target_dir / "sub"
    sub_dir.mkdir()
    target_file = sub_dir / "test_deep.py"
    target_file.write_text("deep_junction_secret = 999\n", encoding="utf-8")

    junction_dir = tmp_path / "deep_junction_link"
    try:
        import _winapi

        _winapi.CreateJunction(str(target_dir), str(junction_dir))
    except Exception as exc:
        pytest.skip(f"Windows junction creation failed: {exc}")

    assert _is_symlink_or_junction(junction_dir) is True
    deep_file = junction_dir / "sub" / "test_deep.py"
    assert _read_test_source(deep_file) == ""
