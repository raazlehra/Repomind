from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from repomind import services
from repomind.cli import atlas_main, main
from repomind.mcp import create_server
from scripts.mcp_stdio_probe import server_command

# Captured over MCP from the qualified 55468b5 wheel, with its repomind/mcp.py
# bytes verified against that wheel. Keep this independent of create_server().
BASELINE = json.loads(
    (Path(__file__).parent / "fixtures" / "legacy_mcp_schemas.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("entry,program", [(main, "repomind"), (atlas_main, "lehraz-atlas")])
@pytest.mark.parametrize("args", [["--help"], ["mcp", "--help"], ["test-impact", "--help"]])
def test_cli_help_uses_the_selected_interface(
    entry: Callable[..., int], program: str, args: list[str], capsys: Any
) -> None:
    with pytest.raises(SystemExit) as error:
        entry(args)
    assert error.value.code == 0
    output = capsys.readouterr().out
    assert output.startswith(f"usage: {program} ")
    if entry is atlas_main and args == ["--help"]:
        assert "Lehraz Atlas Free" in output


@pytest.mark.parametrize("entry,atlas", [(main, False), (atlas_main, True)])
def test_cli_mcp_selects_a_mode_without_relying_on_argv_filename(
    entry: Callable[..., int], atlas: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr("sys.argv", ["an-arbitrary-wrapper"])
    monkeypatch.setattr("repomind.mcp.run_stdio", lambda **kwargs: calls.append(kwargs))
    assert entry(["mcp", "--debug"]) == 0
    assert calls == [{"debug": True, "atlas": atlas}]


@pytest.mark.anyio
@pytest.mark.parametrize("atlas", [False, True])
async def test_each_server_has_exactly_one_namespace_and_frozen_wire_schemas(atlas: bool) -> None:
    prefix = "atlas" if atlas else "repomind"
    async with Client(create_server(atlas=atlas), mode="legacy") as client:
        assert client.server_info is not None
        assert client.server_info.name == ("lehraz-atlas" if atlas else "repomind")
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {
        name.replace("repomind_", f"{prefix}_", 1) for name in BASELINE
    }
    assert len(tools) == 12
    for tool in tools:
        old_name = tool.name.replace(f"{prefix}_", "repomind_", 1)
        dump = tool.model_dump(by_alias=True)
        assert {key: dump.get(key) for key in ("inputSchema", "outputSchema")} == BASELINE[old_name]


@pytest.mark.anyio
@pytest.mark.parametrize("atlas", [False, True])
async def test_both_namespaces_share_the_same_analysis_service(
    atlas: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(services, "stats", lambda repository: {"repository": repository, "shared": True})
    async with Client(create_server(atlas=atlas)) as client:
        result = await client.call_tool(
            "atlas_stats" if atlas else "repomind_stats", {"repository": "test-repository"}
        )
    assert not result.is_error
    assert result.structured_content == {"repository": "test-repository", "shared": True}


@pytest.mark.anyio
@pytest.mark.parametrize("atlas", [False, True])
@pytest.mark.parametrize("extra", [{"max_commands": True}, {"max_commands": "2"}, {"execute": True}])
async def test_strict_validation_rejects_coercion_and_execution_in_both_modes(
    tmp_path: Path, atlas: bool, extra: dict[str, Any]
) -> None:
    async with Client(create_server(atlas=atlas)) as client:
        result = await client.call_tool(
            "atlas_test_impact" if atlas else "repomind_test_impact",
            {"repository": str(tmp_path), **extra},
        )
    assert result.is_error
    assert result.structured_content is None


@pytest.mark.anyio
@pytest.mark.parametrize("atlas", [False, True])
async def test_structured_error_behavior_is_identical_in_both_modes(tmp_path: Path, atlas: bool) -> None:
    prefix = "atlas" if atlas else "repomind"
    async with Client(create_server(atlas=atlas)) as client:
        cap = await client.call_tool(f"{prefix}_test_impact", {"repository": str(tmp_path), "max_commands": 101})
        missing = await client.call_tool(f"{prefix}_context", {"repository": str(tmp_path), "task": "inspect"})
    assert not cap.is_error and cap.structured_content["error"] == "invalid_arguments"
    assert not missing.is_error
    assert missing.structured_content == {
        "error": "repository_not_indexed", "message": "Run repomind init for this repository."
    }


def test_module_stdio_command_preserves_a_venv_path_without_resolving_symlinks(tmp_path: Path) -> None:
    interpreter = tmp_path / "venv with spaces" / "bin" / "python"
    command, args = server_command(interpreter, "module")
    assert command == str(interpreter.absolute())
    assert args == ["-m", "repomind", "mcp"]
