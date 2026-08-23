from __future__ import annotations

import re
from pathlib import Path

from repomind.models import EdgeCandidate, ImportRecord, ParseResult, Symbol

_CLASS_RE = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+|abstract\s+|final\s+)*"
    r"(?P<kind>class|interface|struct|enum|trait)\s+(?P<name>[A-Za-z_]\w*)"
    r"(?P<tail>[^\n{]*)",
    re.MULTILINE,
)
_FUNCTION_RE = re.compile(
    r"^\s*(?:pub(?:lic)?\s+|private\s+|protected\s+|static\s+|async\s+|virtual\s+|override\s+)*"
    r"(?:fn|func|def)\s+(?P<name>[A-Za-z_]\w*)\s*(?P<args>\([^\n{;]*\))",
    re.MULTILINE,
)
_C_STYLE_FUNCTION_RE = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+|virtual\s+|const\s+)*"
    r"(?P<return>[A-Za-z_][\w:<>,\[\]*&? ]+)\s+(?P<name>[A-Za-z_]\w*)\s*"
    r"(?P<args>\([^\n;{}]*\))\s*(?:\{|=>)",
    re.MULTILINE,
)
_IMPORT_PATTERNS = (
    re.compile(r"^\s*import\s+(?P<module>[\w.]+)", re.MULTILINE),
    re.compile(r"^\s*use\s+(?P<module>[\w:]+)", re.MULTILINE),
    re.compile(r"^\s*#include\s*[<\"](?P<module>[^>\"]+)[>\"]", re.MULTILINE),
    re.compile(r"^\s*using\s+(?P<module>[\w.]+)", re.MULTILINE),
)


class FallbackParser:
    languages = frozenset(
        {"java", "go", "rust", "csharp", "c", "cpp", "ruby", "php", "swift", "kotlin", "scala"}
    )

    def parse(self, path: Path, relative_path: str, source: str) -> ParseResult:
        result = ParseResult()
        for pattern in _IMPORT_PATTERNS:
            for match in pattern.finditer(source):
                module = match.group("module")
                line = source.count("\n", 0, match.start()) + 1
                result.imports.append(ImportRecord(module, None, None, line))
        for match in _CLASS_RE.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            kind, name, tail = match.group("kind", "name", "tail")
            result.symbols.append(
                Symbol(name, name, kind, f"{kind} {name}{tail.strip()}", line, line, True)
            )
            inheritance = re.search(r"(?:extends|:)\s*([A-Za-z_]\w*)", tail)
            if inheritance:
                result.edges.append(
                    EdgeCandidate(
                        "inherits",
                        name,
                        inheritance.group(1),
                        line,
                        0.75,
                        "fallback inheritance match",
                    )
                )
        matched_spans: set[tuple[int, int]] = set()
        for pattern in (_FUNCTION_RE, _C_STYLE_FUNCTION_RE):
            for match in pattern.finditer(source):
                span = match.span()
                if any(start <= span[0] <= end for start, end in matched_spans):
                    continue
                matched_spans.add(span)
                line = source.count("\n", 0, match.start()) + 1
                name, args = match.group("name", "args")
                result.symbols.append(
                    Symbol(name, name, "function", f"{name}{args}", line, line, True)
                )
        result.summary = (
            f"{len(result.symbols)} symbols (fallback parser)"
            if result.symbols
            else "fallback structural scan"
        )
        return result


class PlainTextParser:
    languages = frozenset({"config", "documentation", "shell", "sql", "text"})

    def parse(self, path: Path, relative_path: str, source: str) -> ParseResult:
        kind = (
            "configuration"
            if path.suffix.lower() in {".json", ".toml", ".yaml", ".yml", ".ini", ".xml"}
            else "text"
        )
        return ParseResult(summary=kind)
