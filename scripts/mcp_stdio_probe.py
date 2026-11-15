from __future__ import annotations

import argparse
import ast
import asyncio
import json
from pathlib import Path

from mcp import Client, StdioServerParameters


async def probe(
    server_python: Path, repository: Path, *, exercise_all: bool = False
) -> dict[str, object]:
    parameters = StdioServerParameters(
        command=str(server_python),
        args=["-m", "repomind", "mcp"],
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
    async with Client(parameters, mode="legacy") as client:
        if client.server_info is None or client.server_info.name != "repomind":
            raise RuntimeError("MCP internal server identity changed")
        listed = await client.list_tools()
        tool_names = sorted(tool.name for tool in listed.tools)
        missing = sorted(set(arguments).difference(tool_names))
        if missing:
            raise RuntimeError(f"installed MCP server is missing tools: {missing}")
        payloads = {}
        calls = arguments if exercise_all else {"repomind_status": {}}
        for name, extra in calls.items():
            result = await client.call_tool(name, {"repository": str(repository), **extra})
            if result.is_error or not isinstance(result.structured_content, dict):
                raise RuntimeError(f"{name} did not return successful structured content")
            if "error" in result.structured_content:
                raise RuntimeError(f"{name} returned a structured error")
            payloads[name] = result.structured_content

    if payloads["repomind_status"].get("index_health") != "ok":
        raise RuntimeError("repomind_status did not report a healthy index")
    if exercise_all and payloads["repomind_test_impact"].get("schema_version") != "repomind.test-impact.v1":
        raise RuntimeError("MCP test-impact schema identity changed")
    return {
        "startup": "ok",
        "tool_count": len(tool_names),
        "tools": tool_names,
        "legacy_tool_calls": sorted(payloads),
        "server_identity": "repomind",
        "status": "ok",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe an installed Lehraz Atlas Free MCP server")
    parser.add_argument("--server-python", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--exercise-all", action="store_true", help="call all tools, including refresh, on an owned synthetic release fixture")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(probe(args.server_python.resolve(), args.repository.resolve(), exercise_all=args.exercise_all)),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
