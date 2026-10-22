from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import venv
from pathlib import Path
from typing import Any


def run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 180,
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
    completed = run(command, cwd=cwd)
    return json.loads(completed.stdout)


def resolve_wheel(candidate: Path) -> Path:
    if candidate.is_file() and candidate.suffix == ".whl":
        return candidate.resolve()
    wheels = sorted(candidate.glob("*.whl")) if candidate.is_dir() else []
    if len(wheels) != 1:
        raise ValueError(f"expected exactly one wheel at {candidate}, found {len(wheels)}")
    return wheels[0].resolve()


def environment_python(environment: Path) -> Path:
    relative = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    return environment / relative


def environment_cli(environment: Path) -> Path:
    relative = Path("Scripts/repomind.exe") if os.name == "nt" else Path("bin/repomind")
    return environment / relative


def create_repository(root: Path) -> Path:
    repository = root / "Synthetic Repository With Spaces"
    (repository / "src").mkdir(parents=True)
    (repository / "tests").mkdir()
    (repository / "test").mkdir()
    (repository / "corpus").mkdir()
    (repository / "src" / "app.py").write_text(
        "def greeting(name: str) -> str:\n    return f'Hello, {name}'\n",
        encoding="utf-8",
    )
    (repository / "tests" / "test_app.py").write_text(
        "from src.app import greeting\n\n\ndef test_greeting() -> None:\n"
        "    assert greeting('RepoMind') == 'Hello, RepoMind'\n",
        encoding="utf-8",
    )
    (repository / "package.json").write_text(
        json.dumps({"scripts": {"test": "node --test test/*.test.mjs"}}),
        encoding="utf-8",
    )
    (repository / "corpus" / "fixture.jsonl").write_text(
        "# fixture content is indexed but never executed\n",
        encoding="utf-8",
    )
    (repository / "test" / "fixture.test.mjs").write_text(
        """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
readFileSync(join(CORPUS, 'fixture.jsonl'), 'utf8');
""",
        encoding="utf-8",
    )
    run(["git", "init", "--quiet"], cwd=repository)
    run(["git", "config", "user.email", "release-smoke@example.invalid"], cwd=repository)
    run(["git", "config", "user.name", "RepoMind Release Smoke"], cwd=repository)
    run(
        [
            "git",
            "add",
            "src/app.py",
            "tests/test_app.py",
            "package.json",
            "corpus/fixture.jsonl",
            "test/fixture.test.mjs",
        ],
        cwd=repository,
    )
    run(["git", "commit", "--quiet", "-m", "fixture"], cwd=repository)
    return repository


def execute_smoke(
    wheel: Path, root: Path, *, treesitter: bool = False
) -> dict[str, object]:
    environment = root / "Installed Wheel Environment With Spaces"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    python = environment_python(environment)
    cli = environment_cli(environment)
    install_target = (
        f"repomind[treesitter] @ {wheel.as_uri()}" if treesitter else str(wheel)
    )
    run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            install_target,
        ],
        cwd=root,
        timeout=300,
    )

    repository = create_repository(root)
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
        raise RuntimeError("package metadata and runtime versions differ")
    module_path = Path(probe["module"]).resolve()
    if not module_path.is_relative_to(environment.resolve()):
        raise RuntimeError(f"RepoMind imported outside the disposable environment: {module_path}")

    module_version = run([str(python), "-m", "repomind", "--version"], cwd=root).stdout.strip()
    cli_version = run([str(cli), "--version"], cwd=root).stdout.strip()
    expected_version = str(probe["metadata"])
    if expected_version not in module_version or expected_version not in cli_version:
        raise RuntimeError("CLI version output does not match installed metadata")

    initialized = json_command(
        [str(python), "-m", "repomind", "init", str(repository), "--format", "json"],
        cwd=root,
    )
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
            "trace the greeting flow",
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
            "src/app.py",
            "-C",
            str(repository),
            "--format",
            "json",
        ],
        cwd=root,
    )
    fixture_impact = json_command(
        [
            str(python),
            "-m",
            "repomind",
            "test-impact",
            "corpus/fixture.jsonl",
            "-C",
            str(repository),
            "--format",
            "json",
        ],
        cwd=root,
    )
    if status.get("index_healthy") is not True:
        raise RuntimeError("installed CLI did not report a healthy index")
    if doctor.get("index_health") != "healthy":
        raise RuntimeError("installed CLI doctor did not report a healthy index")
    if not context.get("relevant_files"):
        raise RuntimeError("installed CLI context returned no relevant files")
    if impact.get("schema_version") != "repomind.test-impact.v1":
        raise RuntimeError("installed CLI test-impact returned an unexpected schema")

    fixture_edges = [
        evidence
        for test in fixture_impact.get("existing_tests", [])
        if test.get("file") == "test/fixture.test.mjs"
        for evidence in test.get("evidence", [])
        if evidence.get("relationship") == "fixture-reference"
    ]
    if treesitter and not fixture_edges:
        raise RuntimeError("Tree-sitter wheel smoke found no fixture-reference edge")
    if not treesitter and fixture_edges:
        raise RuntimeError("base wheel fallback invented a fixture-reference edge")

    probe_script = Path(__file__).with_name("mcp_stdio_probe.py").resolve()
    mcp = json_command(
        [
            str(python),
            str(probe_script),
            "--server-python",
            str(python),
            "--repository",
            str(repository),
        ],
        cwd=root,
    )
    return {
        "wheel": wheel.name,
        "version": expected_version,
        "python": run([str(python), "--version"], cwd=root).stdout.strip(),
        "module_path": str(module_path),
        "explicit_interpreter": "ok",
        "cli_entrypoint": "ok",
        "path_with_spaces": "ok",
        "init_indexed_files": initialized.get("indexed_files"),
        "status": "ok",
        "doctor_checks": len(doctor["checks"]),
        "context": "ok",
        "test_impact": "ok",
        "fixture_analysis": "tree-sitter" if treesitter else "safe lexical fallback",
        "recommended_commands_executed": False,
        "mcp": mcp,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a built RepoMind wheel")
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument(
        "--treesitter",
        action="store_true",
        help="install and verify the optional Tree-sitter fixture backend",
    )
    args = parser.parse_args()
    wheel = resolve_wheel(args.wheel)

    if args.work_dir is not None:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        result = execute_smoke(
            wheel, args.work_dir.resolve(), treesitter=args.treesitter
        )
    else:
        with tempfile.TemporaryDirectory(prefix="repomind release smoke ") as temporary:
            result = execute_smoke(wheel, Path(temporary), treesitter=args.treesitter)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
