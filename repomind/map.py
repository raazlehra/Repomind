from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from repomind.database import IndexDatabase


def build_repository_map(
    database: IndexDatabase, depth: int | None = None, symbols: bool = False
) -> list[dict[str, Any]]:
    symbol_map: dict[int, list[dict[str, str]]] = defaultdict(list)
    if symbols:
        for row in database.connection.execute(
            "SELECT file_id, qualified_name, kind, signature FROM symbols ORDER BY line_start"
        ):
            symbol_map[int(row["file_id"])].append(
                {
                    "name": str(row["qualified_name"]),
                    "kind": str(row["kind"]),
                    "signature": str(row["signature"]),
                }
            )
    output: list[dict[str, Any]] = []
    for row in database.connection.execute(
        "SELECT id, path, language, purpose FROM files ORDER BY path"
    ):
        path = str(row["path"])
        path_depth = path.count("/") + 1
        if depth is not None and path_depth > depth:
            continue
        item: dict[str, Any] = {
            "path": path,
            "language": str(row["language"]),
            "purpose": str(row["purpose"]),
        }
        if symbols:
            item["symbols"] = symbol_map.get(int(row["id"]), [])
        output.append(item)
    return output


def render_repository_map(items: list[dict[str, Any]], output_format: str) -> str:
    if output_format == "json":
        return json.dumps({"files": items}, indent=2) + "\n"
    lines: list[str] = []
    previous_parts: list[str] = []
    for item in items:
        parts = str(item["path"]).split("/")
        common = 0
        while (
            common < len(previous_parts) - 1
            and common < len(parts) - 1
            and previous_parts[common] == parts[common]
        ):
            common += 1
        for index in range(common, len(parts) - 1):
            lines.append(f"{'  ' * index}{parts[index]}/")
        lines.append(f"{'  ' * (len(parts) - 1)}{parts[-1]} [{item['purpose']}]")
        for symbol in item.get("symbols", []):
            lines.append(f"{'  ' * len(parts)}{symbol['kind']} {symbol['name']}")
        previous_parts = parts
    return "\n".join(lines) + ("\n" if lines else "")
