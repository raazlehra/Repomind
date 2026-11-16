from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from repomind import services
from repomind.database import IndexDatabase
from repomind.go_analysis import GO_META_KEY, load_go_analysis
from repomind.indexer import Indexer
from repomind.mcp import create_server
from repomind.parsers.go import GoManifestParser, GoParser
from repomind.scanner import RepositoryScanner
from repomind.test_impact import TestImpactLimits as ImpactLimits
from repomind.test_impact import analyze_test_impact


def write(root: Path, name: str, text: str) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def module(root: Path, directory: str = ".", name: str = "example.org/app") -> None:
    write(root / directory, "go.mod", f"module {name}\n\ngo 1.24\n")
    write(root / directory, "pkg/a.go", "package pkg\nfunc Value() int { return 1 }\n")
    write(root / directory, "pkg/b.go", "package pkg\nfunc Other() int { return Value() }\n")
    write(
        root / directory,
        "pkg/a_test.go",
        'package pkg\nimport "testing"\nfunc TestValue(t *testing.T) { _ = Value() }\n',
    )
    write(
        root / directory,
        "pkg/external_test.go",
        f'package pkg_test\nimport renamed "{name}/pkg"\nfunc Example() {{ _ = renamed.Value() }}\n',
    )


def report(root: Path, *paths: str, **kwargs: Any) -> dict[str, Any]:
    with IndexDatabase(root) as database:
        return analyze_test_impact(database, paths, **kwargs)


def edges(root: Path) -> set[tuple[str, str, str]]:
    with IndexDatabase(root) as database:
        return {
            (str(r[0]), str(r[1]), str(r[2]))
            for r in database.connection.execute(
                "SELECT s.path,t.path,d.kind FROM dependencies d JOIN files s ON s.id=d.source_file_id JOIN files t ON t.id=d.target_file_id"
            )
        }


def test_go_package_imports_and_declarations_exclude_comment_and_string_text() -> None:
    source = """// package fake; import "evil.invalid/x"
package actual
import (
    alias "example.org/store"
    _ "example.org/sideeffect"
    "fmt" // comment
)
type Writer struct{}
func (w *Writer) Write() { _ = `import "evil.invalid/y"`; fmt.Println("}") }
"""
    result = GoParser().parse(Path("a.go"), "a.go", source)
    assert not result.parse_error
    assert [(i.module, i.alias) for i in result.imports] == [
        ("example.org/store", "alias"),
        ("example.org/sideeffect", "_"),
        ("fmt", None),
    ]
    assert [e.target for e in result.edges if e.kind == "go-package"] == ["actual"]
    assert {s.name for s in result.symbols} == {"Writer", "Write"}
    assert "(w *Writer) Write()" in next(s.signature for s in result.symbols if s.name == "Write")


@pytest.mark.parametrize(
    "source",
    [
        'package x\nimport ("example.org/x"\n',
        'package x\nimport "../outside"\n',
        'package x\nimport "C:\\secret"\n',
        'package x\nimport "https://example.org/x"\n',
        "package x\n/* unclosed",
        "package x\nfunc Run() {",
        'package x\nvar text = "unclosed',
        "package x\npackage y\n",
        'package x\nfunc Run() {}\nimport "fmt"\n',
        'package x\nimport "example.org/\\u0078"\n',
        "package x\n" + "x " * 40_001,
    ],
)
def test_malformed_and_unsupported_source_has_no_proven_edges(source: str) -> None:
    result = GoParser().parse(Path("a.go"), "a.go", source)
    assert result.parse_error and not result.imports and not result.edges


def test_package_tests_and_imports_resolve_all_files_without_single_file_guess(
    tmp_path: Path,
) -> None:
    module(tmp_path)
    write(
        tmp_path,
        "consumer/main.go",
        'package consumer\nimport "example.org/app/pkg"\nfunc Run() {}\n',
    )
    write(tmp_path, "consumer/main_test.go", "package consumer\nfunc TestRun() {}\n")
    Indexer(tmp_path).initialize()
    found = edges(tmp_path)
    assert {("consumer/main.go", f"pkg/{n}.go", "go-import") for n in ("a", "b")} <= found
    assert ("pkg/a_test.go", "pkg/b.go", "go-package-test") in found
    assert ("pkg/external_test.go", "pkg/a.go", "go-test-target") in found
    result = report(tmp_path, "pkg/b.go")
    tests = {t["file"] for t in result["existing_tests"]}
    assert tests == {"pkg/a_test.go", "pkg/external_test.go", "consumer/main_test.go"}
    assert all(t["coverage"] == "unknown" for t in result["existing_tests"])
    commands = {(tuple(c["argv"]), c["working_directory"]) for c in result["recommended_commands"]}
    assert commands == {(("go", "test", "./pkg"), "."), (("go", "test", "./consumer"), ".")}
    assert result["capabilities"]["by_language"]["go"]["dependency_graph_supported"] is True
    with IndexDatabase(tmp_path) as db:
        assert (
            db.connection.execute(
                "SELECT COUNT(*) FROM imports WHERE resolved_file_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("workspace", [False, True])
def test_local_replacement_or_workspace_connects_modules(tmp_path: Path, workspace: bool) -> None:
    module(tmp_path, "app", "example.org/app")
    module(tmp_path, "lib", "example.org/lib")
    write(
        tmp_path,
        "app/pkg/a.go",
        'package pkg\nimport "example.org/lib/pkg"\nfunc Value() int { return 1 }\n',
    )
    if workspace:
        write(tmp_path, "go.work", 'go 1.24\nuse (\n "./app"\n ./lib\n)\n')
    else:
        write(
            tmp_path,
            "app/go.mod",
            "module example.org/app\ngo 1.24\nrequire example.org/lib v1.0.0\nreplace example.org/lib => ../lib\n",
        )
    Indexer(tmp_path).initialize()
    assert ("app/pkg/a.go", "lib/pkg/a.go", "go-import") in edges(tmp_path)

    result = report(tmp_path, "lib/pkg/a.go")
    assert "app/pkg/a_test.go" in {t["file"] for t in result["existing_tests"]}
    assert {(c["working_directory"], tuple(c["argv"])) for c in result["recommended_commands"]} == {
        ("app", ("go", "test", "./pkg")),
        ("lib", ("go", "test", "./pkg")),
    }
    if workspace:
        assert ("app/go.mod", "go.work", "go-workspace") in edges(tmp_path)
        assert (
            report(tmp_path, "go.work")["capabilities"]["by_language"]["go"]["runner_supported"]
            is True
        )


def test_workspace_replacement_overrides_module_replacement(tmp_path: Path) -> None:
    module(tmp_path, "app", "example.org/app")
    module(tmp_path, "lib", "example.org/lib")
    write(tmp_path, "go.work", "go 1.24\nuse ./app\nreplace example.org/lib => ./lib\n")
    write(
        tmp_path,
        "app/go.mod",
        "module example.org/app\ngo 1.24\nrequire example.org/lib v1.0.0\nreplace example.org/lib => ../../outside\n",
    )
    write(
        tmp_path,
        "app/pkg/a.go",
        'package pkg\nimport "example.org/lib/pkg"\nfunc Value() int { return 1 }\n',
    )
    Indexer(tmp_path).initialize()
    assert ("app/pkg/a.go", "lib/pkg/a.go", "go-import") in edges(tmp_path)
    dependency_report = report(tmp_path, "lib/pkg/a.go")
    assert dependency_report["capabilities"]["by_language"]["go"]["runner_supported"] is False
    assert all(c["working_directory"] == "app" for c in dependency_report["recommended_commands"])


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "malformed",
        "duplicate",
        "outside-workspace",
        "outside-replace",
        "conflict",
        "syntax",
    ],
)
def test_unproven_packages_keep_unknown_coverage_and_no_commands(
    tmp_path: Path, change: str
) -> None:
    module(tmp_path)
    if change == "missing":
        (tmp_path / "go.mod").unlink()
    elif change == "malformed":
        write(tmp_path, "go.mod", "module example.org/app\ngo garbage\n")
    elif change == "duplicate":
        module(tmp_path, "duplicate")
    elif change == "outside-workspace":
        write(tmp_path, "go.work", "go 1.24\nuse (\n.\n../outside\n)\n")
    elif change == "outside-replace":
        write(
            tmp_path,
            "go.mod",
            "module example.org/app\ngo 1.24\nrequire example.org/lib v1.0.0\nreplace example.org/lib => ../outside\n",
        )
    elif change == "conflict":
        write(tmp_path, "pkg/b.go", "package wrong\n")
    else:
        write(tmp_path, "pkg/b.go", "package pkg\nfunc Broken( {\n")
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "pkg/a.go")
    assert not result["recommended_commands"]
    assert result["capabilities"]["by_language"]["go"]["runner_supported"] is False
    assert result["uncovered_areas"][0]["coverage"] == "unknown"
    assert any("unsupported" in warning.lower() for warning in result["warnings"])


@pytest.mark.parametrize(
    "prefix,filename",
    [
        ("//go:build linux\n", "conditional.go"),
        ("", "only_windows.go"),
        ("", "_ignored.go"),
        ("// Code generated by tool DO NOT EDIT.\n", "generated.go"),
        ("", "testdata/fixture.go"),
    ],
)
def test_build_generated_and_support_files_do_not_claim_qualified_selection(
    tmp_path: Path, prefix: str, filename: str
) -> None:
    module(tmp_path)
    target = f"pkg/{filename}"
    write(tmp_path, target, prefix + "package pkg\nfunc Conditional() {}\n")
    Indexer(tmp_path).initialize()
    result = report(tmp_path, target)
    if "testdata" in filename:
        # No production package with executable tests exists under testdata.
        assert not result["recommended_commands"]
    else:
        assert result["capabilities"]["by_language"]["go"]["test_selection_supported"] is False
        assert not result["recommended_commands"]
    assert all(t["coverage"] == "unknown" for t in result["existing_tests"])
    assert report(tmp_path, "pkg/a.go")["recommended_commands"]


def test_external_import_does_not_suffix_resolve_into_unrelated_package(tmp_path: Path) -> None:
    module(tmp_path)
    write(
        tmp_path,
        "consumer/main.go",
        'package consumer\nimport "other.invalid/app/pkg"\nfunc Run() {}\n',
    )
    Indexer(tmp_path).initialize()
    assert not any(
        s == "consumer/main.go" and kind == "go-import" for s, _, kind in edges(tmp_path)
    )


def test_nested_module_boundary_prevents_outer_module_suffix_guess(tmp_path: Path) -> None:
    module(tmp_path)
    module(tmp_path, "nested", "other.org/nested")
    write(
        tmp_path,
        "pkg/a.go",
        'package pkg\nimport "example.org/app/nested/pkg"\nfunc Value() int { return 1 }\n',
    )
    Indexer(tmp_path).initialize()
    assert not any(
        s == "pkg/a.go" and t.startswith("nested/") and kind == "go-import"
        for s, t, kind in edges(tmp_path)
    )


def test_incremental_import_manifest_workspace_and_rename_freshness(tmp_path: Path) -> None:
    module(tmp_path, "app", "example.org/app")
    module(tmp_path, "lib", "example.org/lib")
    write(tmp_path, "go.work", "go 1.24\nuse (\n./app\n./lib\n)\n")
    Indexer(tmp_path).initialize()
    write(
        tmp_path,
        "app/pkg/a.go",
        'package pkg\nimport "example.org/lib/pkg"\nfunc Value() int { return 1 }\n',
    )
    services.test_impact(tmp_path, ["lib/pkg/a.go"])
    assert ("app/pkg/a.go", "lib/pkg/a.go", "go-import") in edges(tmp_path)
    write(tmp_path, "go.work", "go 1.24\nuse ./app\n")
    services.test_impact(tmp_path, ["lib/pkg/a.go"])
    assert not any(s == "app/pkg/a.go" and t == "lib/pkg/a.go" for s, t, _ in edges(tmp_path))
    (tmp_path / "app/pkg/b.go").rename(tmp_path / "app/pkg/b_windows.go")
    services.test_impact(tmp_path, ["app/pkg/b_windows.go"])
    with IndexDatabase(tmp_path) as db:
        assert not load_go_analysis(db)["files"]["app/pkg/b_windows.go"]["supported"]


def test_b13_go_index_is_upgraded_without_force_or_reparsing_python(tmp_path: Path) -> None:
    module(tmp_path)
    write(tmp_path, "keep.py", "def keep(): return 1\n")
    Indexer(tmp_path).initialize()
    with IndexDatabase(tmp_path) as db, db.transaction():
        original_id = db.file_by_path("pkg/a.go")["id"]
        created = db.get_meta("created_at")
        db.connection.execute("DELETE FROM meta WHERE key=?", (GO_META_KEY,))
        db.connection.execute("DELETE FROM dependencies WHERE kind LIKE 'go-%'")
        db.connection.execute("DELETE FROM \"references\" WHERE kind LIKE 'go-%'")
        db.connection.execute(
            "UPDATE files SET summary='fallback structural scan' WHERE language='go'"
        )
    result = services.test_impact(tmp_path, ["pkg/a.go"])
    assert result["recommended_commands"]
    assert result["freshness"]["refreshed"] == 5  # Go source/test files and go.mod only
    with IndexDatabase(tmp_path) as db:
        assert (
            db.file_by_path("pkg/a.go")["id"] == original_id
            and db.get_meta("created_at") == created
        )
    # Detect and repair a graph rebuilt by b13 during a rollback, even if sources are unchanged.
    with IndexDatabase(tmp_path) as db, db.transaction():
        old_count = db.connection.execute("SELECT COUNT(*) FROM dependencies WHERE kind LIKE 'go-%'").fetchone()[0]
        db.connection.execute("DELETE FROM dependencies WHERE kind LIKE 'go-%'")
        target_id = db.file_by_path("keep.py")["id"]
        for number in range(old_count):
            db.connection.execute("INSERT INTO dependencies(source_file_id,target_file_id,kind,confidence,source) VALUES(?,?,'go-module',1.0,?)", (original_id, target_id, f"legacy replacement {number}"))
        assert db.connection.execute("SELECT COUNT(*) FROM dependencies WHERE kind LIKE 'go-%'").fetchone()[0] == old_count
    assert services.test_impact(tmp_path, ["pkg/a.go"])["recommended_commands"]
    assert not any(target == "keep.py" and kind.startswith("go-") for _, target, kind in edges(tmp_path))


def test_go_graph_and_package_budgets_are_visible_without_fabricated_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module(tmp_path)
    monkeypatch.setattr("repomind.go_analysis.MAX_GO_EDGES", 1)
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "pkg/a.go")
    assert result["analysis_status"] == "truncated"
    assert result["truncation"]["go_index"]["truncated"]
    assert not result["recommended_commands"]


def test_recommendations_never_execute_go_or_repository_scripts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module(tmp_path)
    original = subprocess.Popen
    calls = []

    def guarded(command: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(command)
        assert isinstance(command, list) and Path(str(command[0])).stem.lower() != "go"
        assert "go test" not in str(command[0])
        return original(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", guarded)
    Indexer(tmp_path).initialize()
    assert services.test_impact(tmp_path, ["pkg/a.go"])["recommended_commands"]
    assert all(str(c[0]) != "go" for c in calls)


@pytest.mark.anyio
@pytest.mark.parametrize("atlas", [False, True])
async def test_both_mcp_namespaces_return_the_same_go_plan(tmp_path: Path, atlas: bool) -> None:
    module(tmp_path)
    Indexer(tmp_path).initialize()
    async with Client(create_server(atlas=atlas)) as client:
        result = await client.call_tool(
            "atlas_test_impact" if atlas else "repomind_test_impact",
            {"repository": str(tmp_path), "changed_files": ["pkg/a.go"]},
        )
    assert not result.is_error
    payload = result.structured_content
    assert payload["schema_version"] == "repomind.test-impact.v1"
    assert payload["recommended_commands"][0]["argv"] == ["go", "test", "./pkg"]


@pytest.mark.parametrize(
    "name,source",
    [
        ("go.mod", "module one\nmodule two\n"),
        ("go.mod", "module example.org/app\nreplace bad\n"),
        ("go.work", "use ../outside\n"),
        ("go.work", "go 1.24\nuse (\n.\n"),
        ("go.mod", 'module "unterminated\n'),
        ("go.mod", "module example.org/app\n" + "go 1.24\n" * 1025),
    ],
)
def test_malformed_manifests_fail_closed(name: str, source: str) -> None:
    result = GoManifestParser().parse(Path(name), name, source)
    assert result.parse_error and not result.edges


def test_graph_selection_and_output_limits_still_apply(tmp_path: Path) -> None:
    module(tmp_path)
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "pkg/a.go", limits=ImpactLimits(max_graph_nodes=1, max_tests=1))
    assert result["analysis_status"] == "truncated"
    assert len(result["existing_tests"]) <= 1
    assert (
        len(json.dumps(result, separators=(",", ":")).encode())
        <= result["limits"]["max_output_bytes"]
    )


def test_packaged_workspace_fixture_selects_both_owning_packages(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    shutil.copytree(Path(__file__).parent / "fixtures/go_workspace", root)
    Indexer(root).initialize()
    result = report(root, "lib/pkg/value.go")
    assert {(c["working_directory"], tuple(c["argv"])) for c in result["recommended_commands"]} == {
        ("app", ("go", "test", "./pkg")),
        ("lib", ("go", "test", "./pkg")),
    }


@pytest.mark.parametrize(
    "kind",
    [
        "symlink",
        pytest.param(
            "junction",
            marks=pytest.mark.skipif(sys.platform != "win32", reason="Windows junction behavior"),
        ),
    ],
)
def test_go_scanning_rejects_symlinked_workspace_member(tmp_path: Path, kind: str) -> None:
    root, outside = tmp_path / "root", tmp_path / "outside"
    module(root)
    module(outside, name="example.org/other")
    try:
        if kind == "junction":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(root / "linked"), str(outside)],
                check=True,
                capture_output=True,
            )
        else:
            (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"OS symlink creation unsupported: {exc}")
    write(root, "go.work", "go 1.24\nuse (\n.\n./linked\n)\n")
    from repomind.config import Config

    assert not any(f.path.startswith("linked/") for f in RepositoryScanner(root, Config()).scan())
    Indexer(root).initialize()
    assert not report(root, "pkg/a.go")["recommended_commands"]


@pytest.mark.parametrize(
    "source", ["package for\n", 'package x\nimport func "fmt"\n', "package x\n" + " " * 256_001]
)
def test_reserved_identifiers_and_source_byte_limits_are_not_promoted(source: str) -> None:
    assert GoParser().parse(Path("a.go"), "a.go", source).parse_error


@pytest.mark.parametrize("directive", ['import "C"', 'import . "fmt"'])
def test_cgo_and_dot_imports_remain_explicitly_unsupported(tmp_path: Path, directive: str) -> None:
    module(tmp_path)
    write(tmp_path, "pkg/b.go", f"package pkg\n{directive}\nfunc Other() {{}}\n")
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "pkg/b.go")
    assert not result["recommended_commands"]
    assert result["uncovered_areas"][0]["coverage"] == "unknown"
    assert not result["capabilities"]["by_language"]["go"]["dependency_graph_supported"]


def test_partial_go_change_retains_only_the_proven_package_plan(tmp_path: Path) -> None:
    module(tmp_path)
    write(tmp_path, "pkg/platform_windows.go", "package pkg\nfunc Platform() {}\n")
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "pkg/a.go", "pkg/platform_windows.go")
    assert result["recommended_commands"][0]["argv"] == ["go", "test", "./pkg"]
    assert not result["capabilities"]["by_language"]["go"]["test_selection_supported"]
    assert any("partially supported" in warning for warning in result["warnings"])
    assert result["uncovered_areas"][0]["path"] == "pkg/platform_windows.go"


@pytest.mark.parametrize(
    "limit",
    [
        "MAX_GO_FILES",
        "MAX_GO_RECORDS",
        "MAX_GO_PACKAGE_FILES",
        "MAX_GO_MODULES",
        "MAX_GO_WORKSPACES",
    ],
)
def test_go_index_discovery_limits_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: str
) -> None:
    module(tmp_path)
    write(tmp_path, "go.work", "go 1.24\nuse .\n")
    monkeypatch.setattr("repomind.go_analysis." + limit, 0)
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "pkg/a.go")
    assert result["analysis_status"] == "truncated" and not result["recommended_commands"]


def test_creating_and_deleting_module_updates_previously_unknown_files(tmp_path: Path) -> None:
    module(tmp_path)
    manifest = (tmp_path / "go.mod").read_text()
    (tmp_path / "go.mod").unlink()
    Indexer(tmp_path).initialize()
    assert not report(tmp_path, "pkg/a.go")["recommended_commands"]
    write(tmp_path, "go.mod", manifest)
    result = services.test_impact(tmp_path, ["pkg/a.go"])
    assert result["recommended_commands"] and result["freshness"]["refreshed"] == 1
    (tmp_path / "go.mod").unlink()
    assert not services.test_impact(tmp_path, ["pkg/a.go"])["recommended_commands"]


def test_workspace_members_with_spaces_use_module_cwd_and_literal_package_args(
    tmp_path: Path,
) -> None:
    module(tmp_path, "module with spaces")
    write(tmp_path, "go.work", 'go 1.24\nuse "./module with spaces"\n')
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "module with spaces/pkg/a.go")
    command = result["recommended_commands"][0]
    assert command["working_directory"] == "module with spaces"
    assert command["argv"] == ["go", "test", "./pkg"]


def test_unsafe_module_manifest_change_is_not_advertised_as_supported(tmp_path: Path) -> None:
    module(tmp_path)
    write(tmp_path, "go.mod", "module example.org/app\ngo 1.24\nrequire example.org/lib v1.0.0\nreplace example.org/lib => ../outside\n")
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "go.mod")
    assert not result["capabilities"]["by_language"]["go"]["dependency_graph_supported"]
    assert not result["recommended_commands"]


def test_uppercase_go_extension_does_not_claim_toolchain_support(tmp_path: Path) -> None:
    module(tmp_path)
    write(tmp_path, "pkg/ignored.GO", "package pkg\nfunc Uppercase() {}\n")
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "pkg/ignored.GO")
    assert not result["capabilities"]["by_language"]["go"]["dependency_graph_supported"]
    assert not result["recommended_commands"]


def test_transitive_go_package_tests_are_selected_within_existing_graph_budgets(tmp_path: Path) -> None:
    module(tmp_path)
    write(tmp_path, "layer1/a.go", 'package layer1\nimport "example.org/app/pkg"\nfunc Use() { _ = pkg.Value() }\n')
    write(tmp_path, "layer2/a.go", 'package layer2\nimport "example.org/app/layer1"\nfunc Use() { layer1.Use() }\n')
    for name in ("layer1", "layer2"):
        write(tmp_path, f"{name}/a_test.go", f'package {name}\nimport "testing"\nfunc TestUse(t *testing.T) {{ Use() }}\n')
    Indexer(tmp_path).initialize()
    result = report(tmp_path, "pkg/a.go")
    assert {"pkg/a_test.go", "pkg/external_test.go", "layer1/a_test.go", "layer2/a_test.go"} <= {t["file"] for t in result["existing_tests"]}
