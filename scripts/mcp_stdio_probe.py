from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from mcp import Client, StdioServerParameters


async def probe(server_python: Path, repository: Path) -> dict[str, object]:
    parameters = StdioServerParameters(
        command=str(server_python),
        args=["-m", "repomind", "mcp"],
        cwd=repository,
    )
    async with Client(parameters) as client:
        listed = await client.list_tools()
        tool_names = sorted(tool.name for tool in listed.tools)
        status = await client.call_tool(
            "repomind_status", {"repository": str(repository)}
        )

    if status.is_error:
        raise RuntimeError("repomind_status returned an MCP error")
    if not isinstance(status.structured_content, dict):
        raise RuntimeError("repomind_status did not return structured content")
    if status.structured_content.get("index_health") != "ok":
        raise RuntimeError("repomind_status did not report a healthy index")
    required = {"repomind_status", "repomind_context", "repomind_test_impact"}
    missing = sorted(required.difference(tool_names))
    if missing:
        raise RuntimeError(f"installed MCP server is missing tools: {missing}")
    return {
        "startup": "ok",
        "tool_count": len(tool_names),
        "tools": tool_names,
        "status": "ok",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe an installed RepoMind MCP stdio server")
    parser.add_argument("--server-python", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(probe(args.server_python.resolve(), args.repository.resolve())),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
