"""Verify source/editable and sdist-built installations in disposable environments."""

from __future__ import annotations

import argparse
import json
import shutil
import tarfile
import tempfile
import tomllib
import venv
from pathlib import Path

from installed_wheel_smoke import environment_cli, environment_python, execute_smoke, run


def execute(source: Path, sdist: Path, root: Path) -> dict[str, object]:
    expected = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    copied = root / "Editable Source With Spaces"
    copied.mkdir()
    for name in ("repomind", "pyproject.toml", "README.md", "LICENSE"):
        entry = source / name
        if entry.is_dir():
            shutil.copytree(entry, copied / name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(entry, copied / name)
    environment = root / "Editable Environment With Spaces"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment_python(environment)
    run([str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(copied)], cwd=root)
    probe = json.loads(run(
        [str(python), "-c", "import json,repomind; from importlib.metadata import version; "
         "print(json.dumps({'version':version('repomind'),'runtime':repomind.__version__,'module':repomind.__file__}))"],
        cwd=root,
    ).stdout)
    if probe["version"] != expected or probe["runtime"] != expected:
        raise RuntimeError("editable metadata/runtime mismatch")
    if not Path(probe["module"]).resolve().is_relative_to(copied.resolve()):
        raise RuntimeError("editable import escaped the disposable source copy")
    for name in ("repomind", "lehraz-atlas"):
        if expected not in run([str(environment_cli(environment, name)), "--version"], cwd=root).stdout:
            raise RuntimeError(f"editable {name} did not execute correctly")
    wheels = root / "Wheel Built From Sdist"
    run([str(python), "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheels), str(sdist)], cwd=root)
    built = list(wheels.glob("*.whl"))
    if len(built) != 1:
        raise RuntimeError("sdist did not produce exactly one project wheel")
    smoke_root = root / "Sdist Wheel Smoke"
    smoke_root.mkdir()
    wheel_result = execute_smoke(built[0], smoke_root)
    # Exercise actual packaged Go manifests/source through the sdist-built wheel.
    fixture = root / "Packaged Go Workspace With Spaces"
    fixture.mkdir()
    members = ("go.work", "app/go.mod", "app/pkg/app.go", "app/pkg/app_test.go",
               "lib/go.mod", "lib/pkg/value.go", "lib/pkg/value_test.go")
    with tarfile.open(sdist, "r:gz") as archive:
        for relative in members:
            name = f"repomind-{expected}/tests/fixtures/go_workspace/{relative}"
            member = archive.getmember(name)
            if not member.isfile() or member.size > 10_000:
                raise RuntimeError("unsafe or oversized packaged Go fixture")
            content = archive.extractfile(member)
            if content is None:
                raise RuntimeError("packaged Go fixture is not readable")
            target = fixture / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.read())
    wheel_python = environment_python(smoke_root / "Installed Wheel Environment With Spaces")
    run([str(wheel_python), "-m", "repomind", "init", str(fixture), "--format", "json"], cwd=root)
    plan = json.loads(run([str(wheel_python), "-m", "repomind", "test-impact", "lib/pkg/value.go", "-C", str(fixture), "--format", "json"], cwd=root).stdout)
    commands = {(c["working_directory"], tuple(c["argv"])) for c in plan["recommended_commands"]}
    if commands != {("app", ("go", "test", "./pkg")), ("lib", ("go", "test", "./pkg"))}:
        raise RuntimeError("packaged workspace did not preserve local Go package relationships")
    if any(test["coverage"] != "unknown" for test in plan["existing_tests"]):
        raise RuntimeError("packaged Go fixture invented runtime coverage")
    return {"editable": probe, "sdist_wheel": wheel_result,
            "packaged_go_workspace": {"status": "ok", "fixture_files": len(members), "commands_executed": False}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sdist", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="lehraz atlas source smoke ") as temporary:
        result = execute(args.source.resolve(), args.sdist.resolve(), Path(temporary))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
