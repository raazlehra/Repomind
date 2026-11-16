from __future__ import annotations

import argparse
import ast
import asyncio
import json
import os
from pathlib import Path
from typing import Literal

from mcp import Client, StdioServerParameters

if __package__:
    from .go_smoke_fixture import assert_go_plan
else:
    from go_smoke_fixture import assert_go_plan


def server_command(
    server_python: Path, mode: Literal["module", "repomind", "atlas"]
) -> tuple[str, list[str]]:
    # Resolving a venv's python symlink can select the host interpreter on POSIX.
    python = server_python.absolute()
    if mode == "module":
        return str(python), ["-m", "repomind", "mcp"]
    name = "lehraz-atlas" if mode == "atlas" else "repomind"
    executable = name + (".exe" if os.name == "nt" else "")
    return str(python.with_name(executable)), ["mcp"]


async def probe(
    server_python: Path, repository: Path, *, exercise_all: bool = False,
    mode: Literal["module", "repomind", "atlas"] = "module",
) -> dict[str, object]:
    command, args = server_command(server_python, mode)
    prefix = "atlas" if mode == "atlas" else "repomind"
    server_name = "lehraz-atlas" if mode == "atlas" else "repomind"
    parameters = StdioServerParameters(
        command=command,
        args=args,
        cwd=repository,
    )
    symbol, target = "__probe_missing__", "__probe_missing__.py"
    if exercise_all:
        # The full release gate owns this synthetic repository; normal probes remain read-only.
        source = next((repository / "src").glob("*.py"))
        symbol = next(
            node.name for node in ast.parse(source.read_text(encoding="utf-8")).body
            if isinstance(node, ast.FunctionDef)
        )
        target = source.relative_to(repository).as_posix()
    arguments = {
        "repomind_status": {},
        "repomind_context": {"task": "trace the source function", "level": 1},
        "repomind_symbol": {"symbol": symbol},
        "repomind_callers": {"symbol": symbol},
        "repomind_dependencies": {"target": target},
        "repomind_impact": {"target": target},
        "repomind_test_impact": {"changed_files": [target]},
        "repomind_snippets": {"target": target, "line_bound": 10, "token_bound": 500},
        "repomind_refresh": {},
        "repomind_map": {"depth": 2},
        "repomind_stats": {},
        "repomind_memory": {"limit": 2},
    }
    arguments = {name.replace("repomind_", f"{prefix}_", 1): extra for name, extra in arguments.items()}
    async with Client(parameters, mode="legacy") as client:
        if client.server_info is None or client.server_info.name != server_name:
            raise RuntimeError("MCP internal server identity changed")
        listed = await client.list_tools()
        tool_names = sorted(tool.name for tool in listed.tools)
        if len(tool_names) != 12 or set(arguments) != set(tool_names):
            raise RuntimeError(f"MCP server has a missing or duplicate namespace: {tool_names}")
        schemas = {
            tool.name.removeprefix(f"{prefix}_"): tool.model_dump(by_alias=True)["inputSchema"]
            for tool in listed.tools
        }
        payloads = {}
        calls = arguments if exercise_all else {f"{prefix}_status": {}}
        for name, extra in calls.items():
            result = await client.call_tool(name, {"repository": str(repository), **extra})
            if result.is_error or not isinstance(result.structured_content, dict):
                raise RuntimeError(f"{name} did not return successful structured content")
            if "error" in result.structured_content:
                raise RuntimeError(f"{name} returned a structured error")
            payloads[name] = result.structured_content
        validation_checks = []
        go_analysis = "not_requested"
        if exercise_all:
            if (repository / "gopkg/math.go").is_file():
                result = await client.call_tool(f"{prefix}_test_impact", {
                    "repository": str(repository), "changed_files": ["gopkg/math.go"]
                })
                if result.is_error:
                    raise RuntimeError("Go stdio analysis returned an MCP error")
                assert_go_plan(result.structured_content)
                go_analysis = "ok"
            for invalid in ({"max_commands": True}, {"max_commands": "2"}, {"execute": True}):
                result = await client.call_tool(
                    f"{prefix}_test_impact", {"repository": str(repository), **invalid}
                )
                if not result.is_error or result.structured_content is not None:
                    raise RuntimeError(f"MCP strict validation accepted {invalid}")
                validation_checks.append(next(iter(invalid)))
            result = await client.call_tool(
                f"{prefix}_test_impact", {"repository": str(repository), "max_commands": 101}
            )
            if result.is_error or not isinstance(result.structured_content, dict) or result.structured_content.get("error") != "invalid_arguments":
                raise RuntimeError("MCP bounded-argument error behavior changed")
            validation_checks.append("hard_cap")

    if payloads[f"{prefix}_status"].get("index_health") != "ok":
        raise RuntimeError("MCP status did not report a healthy index")
    if exercise_all and payloads[f"{prefix}_test_impact"].get("schema_version") != "repomind.test-impact.v1":
        raise RuntimeError("MCP test-impact schema identity changed")
    return {
        "startup": "ok",
        "tool_count": len(tool_names),
        "tools": tool_names,
        "legacy_tool_calls": sorted(payloads) if prefix == "repomind" else [],
        "tool_calls": sorted(payloads),
        "server_identity": server_name,
        "mode": mode,
        "input_schemas": schemas,
        "strict_validation_checks": validation_checks,
        "go_package_analysis": go_analysis,
        "status": "ok",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe an installed Lehraz Atlas Free MCP server")
    parser.add_argument("--server-python", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--mode", choices=("module", "repomind", "atlas"), default="module")
    parser.add_argument("--exercise-all", action="store_true", help="call all tools, including refresh, on an owned synthetic release fixture")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(probe(args.server_python.absolute(), args.repository.resolve(), exercise_all=args.exercise_all, mode=args.mode)),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
