from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exactly_one(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected one {pattern} artifact in {directory}, found {len(matches)}")
    return matches[0]


def validate_member_names(names: list[str], *, allow_tests: bool) -> None:
    forbidden_segments = {".repomind", "brag-output", "__pycache__", ".git", "dist", "build"}
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError(f"unsafe archive member path: {name}")
        if forbidden_segments.intersection(path.parts) or name.endswith((".pyc", ".pyo")):
            raise ValueError(f"unexpected generated/private archive member: {name}")
        if not allow_tests and "tests" in path.parts:
            raise ValueError(f"tests must not be installed by the wheel: {name}")


def verify_wheel(wheel: Path, expected_version: str) -> dict[str, object]:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        validate_member_names(names, allow_tests=False)
        required_suffixes = {
            "repomind/__init__.py",
            "repomind/cli.py",
            "repomind/mcp.py",
            ".dist-info/METADATA",
            ".dist-info/entry_points.txt",
            ".dist-info/licenses/LICENSE",
        }
        for suffix in required_suffixes:
            if not any(name.endswith(suffix) for name in names):
                raise ValueError(f"wheel is missing {suffix}")
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
        entrypoints_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entrypoints = archive.read(entrypoints_name).decode("utf-8")
    if metadata["Name"] != "repomind" or metadata["Version"] != expected_version:
        raise ValueError("wheel project name/version metadata is incorrect")
    if "repomind = repomind.cli:main" not in entrypoints:
        raise ValueError("wheel is missing the repomind console entrypoint")
    return {
        "filename": wheel.name,
        "sha256": sha256(wheel),
        "members": len(names),
        "name": metadata["Name"],
        "version": metadata["Version"],
        "license": "included",
        "tests_included": False,
    }


def verify_sdist(sdist: Path, expected_version: str) -> dict[str, object]:
    expected_root = f"repomind-{expected_version}"
    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        validate_member_names(names, allow_tests=True)
    required = {
        f"{expected_root}/LICENSE",
        f"{expected_root}/README.md",
        f"{expected_root}/pyproject.toml",
        f"{expected_root}/repomind/__init__.py",
        f"{expected_root}/repomind/mcp.py",
        f"{expected_root}/tests/test_packaging.py",
    }
    missing = sorted(required.difference(names))
    if missing:
        raise ValueError(f"source distribution is missing expected files: {missing}")
    if any(not name.startswith(f"{expected_root}/") and name != expected_root for name in names):
        raise ValueError("source distribution contains members outside its versioned root")
    return {
        "filename": sdist.name,
        "sha256": sha256(sdist),
        "members": len(names),
        "version": expected_version,
        "license": "included",
        "tests_included": True,
        "tests_policy": "source tests are intentionally included for sdist verification",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify RepoMind wheel and sdist contents")
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--expected-version")
    args = parser.parse_args()
    directory = args.dist_dir.resolve()
    wheel = exactly_one(directory, "*.whl")
    sdist = exactly_one(directory, "*.tar.gz")
    expected = args.expected_version
    if expected is None:
        wheel_stem = wheel.name.removeprefix("repomind-")
        expected = wheel_stem.split("-", 1)[0]
    result = {
        "wheel": verify_wheel(wheel, expected),
        "sdist": verify_sdist(sdist, expected),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
