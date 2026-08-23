from __future__ import annotations

import json
from typing import Any


def render_context(package: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(package, indent=2, sort_keys=False)
    markdown = output_format == "markdown"

    def heading(value: str) -> str:
        return f"## {value}" if markdown else f"{value}:"

    lines: list[str] = []
    task = str(package.get("task", ""))
    lines.append(f"# RepoMind context: {task}" if markdown else f"Task: {task}")
    lines.append(f"Context level: {package.get('context_level', 1)}")

    architecture = package.get("architecture", [])
    if architecture:
        lines.extend(("", heading("Architecture")))
        for fact in architecture:
            prefix = "- " if markdown else "  "
            lines.append(
                f"{prefix}{fact['category']}: {fact['name']} (evidence: {fact['evidence']})"
            )

    files = package.get("relevant_files", [])
    if files:
        lines.extend(("", heading("Likely relevant files")))
        for item in files:
            prefix = "- " if markdown else "  "
            reasons = "; ".join(item.get("reasons", []))
            lines.append(
                f"{prefix}{item['path']} [{item['purpose']}; score {item['score']}] — {reasons}"
            )

    symbols = package.get("important_symbols", [])
    if symbols:
        lines.extend(("", heading("Important symbols")))
        for item in symbols:
            prefix = "- " if markdown else "  "
            signature = (
                f" — `{item['signature']}`"
                if markdown and item.get("signature")
                else (f" — {item['signature']}" if item.get("signature") else "")
            )
            lines.append(f"{prefix}{item['name']} ({item['kind']}, {item['file']}){signature}")

    relationships = package.get("relationships", [])
    if relationships:
        lines.extend(("", heading("Relationships")))
        for item in relationships:
            prefix = "- " if markdown else "  "
            lines.append(
                f"{prefix}{item['from']} --{item['type']}--> {item['to']} [{item['confidence']}; {item['source']}]"
            )

    modifications = package.get("likely_modification_area", [])
    if modifications:
        lines.extend(("", heading("Likely modification area")))
        prefix = "- " if markdown else "  "
        lines.extend(f"{prefix}{path}" for path in modifications)

    imports = package.get("imports", [])
    if imports:
        lines.extend(("", heading("Relevant imports")))
        for item in imports:
            prefix = "- " if markdown else "  "
            resolved = (
                f" -> {item['resolved_file']}"
                if item.get("resolved_file")
                else " (external/unresolved)"
            )
            lines.append(
                f"{prefix}{item['file']}:{item['line']} imports {item['module']}{resolved}"
            )

    nearby = package.get("nearby_dependencies", [])
    if nearby:
        lines.extend(("", heading("Nearby dependencies")))
        for item in nearby:
            prefix = "- " if markdown else "  "
            lines.append(
                f"{prefix}{item['from']} --{item['type']}--> {item['to']} [{item['confidence']}]"
            )

    snippets = package.get("snippets", [])
    if snippets:
        lines.extend(("", heading("Selected source snippets")))
        for item in snippets:
            if markdown:
                lines.extend(
                    (
                        f"### {item['symbol']} — `{item['file']}:{item['lines']}`",
                        "```",
                        item["code"],
                        "```",
                    )
                )
            else:
                lines.extend((f"  {item['symbol']} — {item['file']}:{item['lines']}", item["code"]))

    lines.extend(("", f"Source authority: {package.get('source_authority', '')}"))
    budget = package.get("budget", {})
    if budget:
        lines.append(
            f"Approximate tokens: {budget.get('approximate_tokens', 0)}/{budget.get('requested_tokens', 0)}"
        )
    return "\n".join(lines).strip() + "\n"


def render_records(data: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(data, indent=2, sort_keys=False) + "\n"
    if output_format == "markdown":
        return _records_markdown(data)
    return _records_text(data)


def _records_text(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        title = key.replace("_", " ").capitalize()
        if isinstance(value, list):
            lines.append(f"{title}:")
            if not value:
                lines.append("  none")
            for item in value:
                lines.append("  " + _compact(item))
        elif isinstance(value, dict):
            lines.append(f"{title}:")
            for child_key, child_value in value.items():
                lines.append(f"  {child_key}: {_compact(child_value)}")
        else:
            lines.append(f"{title}: {_compact(value)}")
    return "\n".join(lines) + "\n"


def _records_markdown(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        title = key.replace("_", " ").title()
        lines.append(f"## {title}")
        if isinstance(value, list):
            lines.extend(f"- {_compact(item)}" for item in value) if value else lines.append(
                "- none"
            )
        elif isinstance(value, dict):
            lines.extend(
                f"- **{child_key}:** {_compact(child_value)}"
                for child_key, child_value in value.items()
            )
        else:
            lines.append(str(value))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _compact(value: Any) -> str:
    if isinstance(value, dict):
        return "; ".join(f"{key}={child}" for key, child in value.items() if child is not None)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)
