from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.verify_release_artifacts import validate_member_names, verify_sdist, verify_wheel


def make_wheel(tmp_path: Path, *, alias: bool = True, project: str = "repomind", runtime: str = "2.0.0b14") -> Path:
    wheel = tmp_path / "repomind-2.0.0b14-py3-none-any.whl"
    info = "repomind-2.0.0b14.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("repomind/__init__.py", f'__version__ = "{runtime}"\n')
        archive.writestr("repomind/cli.py", "")
        archive.writestr("repomind/mcp.py", "")
        archive.writestr(f"{info}/METADATA", f"Name: {project}\nVersion: 2.0.0b14\n")
        entries = "[console_scripts]\nrepomind = repomind.cli:main\n"
        if alias:
            entries += "lehraz-atlas = repomind.cli:main\n"
        archive.writestr(f"{info}/entry_points.txt", entries)
        archive.writestr(f"{info}/licenses/LICENSE", "test attribution")
    return wheel


def test_candidate_verifier_requires_both_real_entrypoints(tmp_path: Path) -> None:
    wheel = make_wheel(tmp_path)
    assert verify_wheel(wheel, "2.0.0b14")["console_scripts"] == ["repomind", "lehraz-atlas"]
    make_wheel(tmp_path, alias=False)
    with pytest.raises(ValueError, match="lehraz-atlas"):
        verify_wheel(wheel, "2.0.0b14")
    # The opt-in historical mode does not require an alias that b13 never shipped.
    assert verify_wheel(wheel, "2.0.0b14", ("repomind",))["name"] == "repomind"


@pytest.mark.parametrize("project,runtime", [("lehraz-atlas", "2.0.0b14"), ("repomind", "2.0.0b13")])
def test_verifier_rejects_distribution_or_runtime_identity_drift(
    tmp_path: Path, project: str, runtime: str
) -> None:
    with pytest.raises(ValueError, match="metadata|version"):
        verify_wheel(make_wheel(tmp_path, project=project, runtime=runtime), "2.0.0b14")


@pytest.mark.parametrize("name", ["../escape.py", "C:/escape.py", "repomind\\escape.py", ".repomind/index.sqlite3", ".venv/private.py", "reports/private.md"])
def test_archive_private_and_escape_paths_remain_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        validate_member_names([name], allow_tests=True)


def test_sdist_rejects_links_before_extracting_anything(tmp_path: Path) -> None:
    archive = tmp_path / "repomind-2.0.0b14.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        member = tarfile.TarInfo("repomind-2.0.0b14/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "/outside"
        handle.addfile(member)
        metadata = b"Name: repomind\nVersion: 2.0.0b14\n"
        member = tarfile.TarInfo("repomind-2.0.0b14/PKG-INFO")
        member.size = len(metadata)
        handle.addfile(member, io.BytesIO(metadata))
    with pytest.raises(ValueError, match="regular files"):
        verify_sdist(archive, "2.0.0b14")
