from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import tempfile
import venv
from contextlib import closing
from pathlib import Path
from typing import Any

BASELINE_VERSION = "2.0.0b10"
CANDIDATE_VERSION = "2.0.0b11"
MEMORY_KEY = "release.lifecycle.marker"
MEMORY_VALUE = "Release lifecycle manual memory must survive package upgrades."


def run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def json_command(command: list[str], *, cwd: Path) -> Any:
    return json.loads(run(command, cwd=cwd).stdout)


def environment_python(environment: Path) -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return environment / relative


def create_repository(root: Path, name: str) -> Path:
    repository = root / name
    (repository / "src").mkdir(parents=True)
    (repository / "tests").mkdir()
    (repository / "src" / "calculator.py").write_text(
        "def add(left: int, right: int) -> int:\n    return left + right\n",
        encoding="utf-8",
    )
    (repository / "tests" / "test_calculator.py").write_text(
        "from src.calculator import add\n\n\ndef test_add() -> None:\n"
        "    assert add(2, 3) == 5\n",
        encoding="utf-8",
    )
    (repository / ".repomind.toml").write_text(
        "[repomind]\ncontext_budget = 800\n", encoding="utf-8"
    )
    run(["git", "init", "--quiet"], cwd=repository)
    run(["git", "config", "user.email", "lifecycle@example.invalid"], cwd=repository)
    run(["git", "config", "user.name", "RepoMind Lifecycle Smoke"], cwd=repository)
    run(
        [
            "git",
            "add",
            ".repomind.toml",
            "src/calculator.py",
            "tests/test_calculator.py",
        ],
        cwd=repository,
    )
    run(["git", "commit", "--quiet", "-m", "fixture"], cwd=repository)
    return repository


def install(python: Path, artifact: Path, root: Path, *, upgrade: bool = False) -> None:
    command = [
        str(python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
    ]
    if upgrade:
        command.append("--upgrade")
    command.append(str(artifact))
    run(command, cwd=root)


def installed_probe(python: Path, root: Path) -> dict[str, str]:
    probe = json_command(
        [
            str(python),
            "-c",
            "import json; from importlib.metadata import version; import repomind; "
            "print(json.dumps({'metadata': version('repomind'), "
            "'runtime': repomind.__version__, 'module': repomind.__file__}))",
        ],
        cwd=root,
    )
    if probe["metadata"] != probe["runtime"]:
        raise RuntimeError("installed metadata/runtime versions do not agree")
    return {str(key): str(value) for key, value in probe.items()}


def database_state(repository: Path) -> dict[str, object]:
    database = repository / ".repomind" / "index.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        metadata = dict(connection.execute("SELECT key, value FROM meta"))
        manual_count = connection.execute(
            "SELECT COUNT(*) FROM memory WHERE source_type = 'manual'"
        ).fetchone()[0]
        marker_count = connection.execute(
            "SELECT COUNT(*) FROM memory WHERE source_type = 'manual' AND key = ? AND value = ?",
            (MEMORY_KEY, MEMORY_VALUE),
        ).fetchone()[0]
    return {
        "schema_version": metadata.get("schema_version"),
        "repository_root": metadata.get("repository_root"),
        "created_at": metadata.get("created_at"),
        "manual_count": manual_count,
        "marker_count": marker_count,
    }


def exercise_queries(python: Path, repository: Path, root: Path) -> dict[str, object]:
    status = json_command(
        [str(python), "-m", "repomind", "status", "-C", str(repository), "--format", "json"],
        cwd=root,
    )
    doctor = json_command(
        [str(python), "-m", "repomind", "doctor", str(repository), "--format", "json"],
        cwd=root,
    )
    context = json_command(
        [
            str(python),
            "-m",
            "repomind",
            "context",
            "change calculator addition",
            "-C",
            str(repository),
            "--format",
            "json",
        ],
        cwd=root,
    )
    impact = json_command(
        [
            str(python),
            "-m",
            "repomind",
            "test-impact",
            "src/calculator.py",
            "-C",
            str(repository),
            "--format",
            "json",
        ],
        cwd=root,
    )
    memory = json_command(
        [
            str(python),
            "-m",
            "repomind",
            "memory",
            "list",
            "-C",
            str(repository),
            "--format",
            "json",
        ],
        cwd=root,
    )
    if status.get("index_healthy") is not True:
        raise RuntimeError("lifecycle status did not report a healthy index")
    if doctor.get("index_health") != "healthy":
        raise RuntimeError("lifecycle doctor did not report a healthy index")
    if not context.get("relevant_files"):
        raise RuntimeError("lifecycle context returned no relevant files")
    if impact.get("schema_version") != "repomind.test-impact.v1":
        raise RuntimeError("lifecycle test-impact returned an unexpected schema")
    marker = [item for item in memory.get("memory", []) if item.get("key") == MEMORY_KEY]
    if len(marker) != 1 or marker[0].get("value") != MEMORY_VALUE:
        raise RuntimeError("manual lifecycle memory is missing or changed")
    return {
        "status": "ok",
        "doctor_checks": len(doctor["checks"]),
        "context": "ok",
        "test_impact": "ok",
        "manual_memory": "preserved",
        "recommended_commands_executed": False,
    }


def execute(baseline: Path, candidate: Path, root: Path) -> dict[str, object]:
    environment = root / "Lifecycle Environment With Spaces"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    python = environment_python(environment)
    repository = create_repository(root, "Lifecycle Repository With Spaces")

    install(python, baseline, root)
    baseline_probe = installed_probe(python, root)
    if baseline_probe["metadata"] != BASELINE_VERSION:
        raise RuntimeError(f"expected baseline {BASELINE_VERSION}, got {baseline_probe['metadata']}")
    json_command(
        [str(python), "-m", "repomind", "init", str(repository), "--format", "json"],
        cwd=root,
    )
    json_command(
        [
            str(python),
            "-m",
            "repomind",
            "memory",
            "add",
            "-C",
            str(repository),
            "--category",
            "workflow",
            "--key",
            MEMORY_KEY,
            "--source",
            "src/calculator.py",
            MEMORY_VALUE,
            "--format",
            "json",
        ],
        cwd=root,
    )
    before = database_state(repository)
    baseline_queries = exercise_queries(python, repository, root)

    install(python, candidate, root, upgrade=True)
    candidate_probe = installed_probe(python, root)
    if candidate_probe["metadata"] != CANDIDATE_VERSION:
        raise RuntimeError(
            f"expected candidate {CANDIDATE_VERSION}, got {candidate_probe['metadata']}"
        )
    if not Path(candidate_probe["module"]).resolve().is_relative_to(environment.resolve()):
        raise RuntimeError("candidate imported outside the disposable environment")
    after_upgrade = database_state(repository)
    candidate_queries = exercise_queries(python, repository, root)
    for key in ("schema_version", "repository_root", "created_at", "marker_count"):
        if before[key] != after_upgrade[key]:
            raise RuntimeError(f"index state changed unexpectedly during upgrade: {key}")

    run([str(python), "-m", "pip", "uninstall", "--yes", "repomind"], cwd=root)
    after_uninstall = database_state(repository)
    if after_uninstall["marker_count"] != 1 or not (repository / ".repomind.toml").is_file():
        raise RuntimeError("package uninstall removed repository data")
    install(python, candidate, root)
    reinstall_probe = installed_probe(python, root)
    reinstall_queries = exercise_queries(python, repository, root)

    rebuild_repository = create_repository(root, "Force Rebuild Repository With Spaces")
    json_command(
        [str(python), "-m", "repomind", "init", str(rebuild_repository), "--format", "json"],
        cwd=root,
    )
    json_command(
        [
            str(python),
            "-m",
            "repomind",
            "memory",
            "add",
            "-C",
            str(rebuild_repository),
            "--category",
            "workflow",
            "--key",
            MEMORY_KEY,
            MEMORY_VALUE,
            "--format",
            "json",
        ],
        cwd=root,
    )
    rebuild_before = database_state(rebuild_repository)
    json_command(
        [
            str(python),
            "-m",
            "repomind",
            "init",
            str(rebuild_repository),
            "--force",
            "--format",
            "json",
        ],
        cwd=root,
    )
    rebuild_after = database_state(rebuild_repository)
    if rebuild_before["marker_count"] != 1 or rebuild_after["marker_count"] != 0:
        raise RuntimeError("force rebuild manual-memory behavior was unexpected")
    if not (rebuild_repository / ".repomind.toml").is_file():
        raise RuntimeError("force rebuild removed repository configuration")

    return {
        "baseline_artifact": baseline.name,
        "baseline_version": baseline_probe["metadata"],
        "baseline_queries": baseline_queries,
        "candidate_artifact": candidate.name,
        "candidate_version": candidate_probe["metadata"],
        "candidate_module": candidate_probe["module"],
        "upgrade": {
            "schema_before": before["schema_version"],
            "schema_after": after_upgrade["schema_version"],
            "repository_identity": "preserved",
            "created_at": "preserved",
            "manual_memory": "preserved",
            "queries": candidate_queries,
        },
        "uninstall": {
            "index": "preserved",
            "configuration": "preserved",
            "manual_memory": "preserved",
        },
        "reinstall": {
            "version": reinstall_probe["metadata"],
            "queries": reinstall_queries,
        },
        "force_rebuild": {
            "configuration": "preserved",
            "manual_memory": "removed_as_documented",
            "schema": rebuild_after["schema_version"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate b10-to-candidate package lifecycle")
    parser.add_argument("--baseline-wheel", type=Path, required=True)
    parser.add_argument("--candidate-wheel", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    baseline = args.baseline_wheel.resolve()
    candidate = args.candidate_wheel.resolve()
    if not baseline.is_file() or not candidate.is_file():
        raise ValueError("baseline and candidate wheel paths must exist")

    if args.work_dir is not None:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        result = execute(baseline, candidate, args.work_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="repomind lifecycle ") as temporary:
            result = execute(baseline, candidate, Path(temporary))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
