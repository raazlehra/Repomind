from __future__ import annotations

import re
from pathlib import Path

from repomind.models import EdgeCandidate, ImportRecord, ParseResult, Route, Symbol

_STATIC_IMPORT_BOUNDARY_RE = re.compile(r"^|[;}]", re.MULTILINE)
_STATIC_IMPORT_KEYWORD_RE = re.compile(r"(?P<keyword>import|export)\b")
_MAX_STATIC_IMPORT_CHARS = 8_192
_REQUIRE_RE = re.compile(
    r"(?:const|let|var)\s+(?P<what>[\w${},\s]+)\s*=\s*require\(['\"](?P<module>[^'\"]+)['\"]\)"
)
_DECL_RE = re.compile(
    r"(?P<export>export\s+(?:default\s+)?)?"
    r"(?P<kind>async\s+function|function|class|interface|type|enum)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)"
    r"(?P<tail>[^\n{;]*)",
    re.MULTILINE,
)
_ARROW_RE = re.compile(
    r"(?P<export>export\s+)?(?:const|let)\s+(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"(?::[^=\n]+)?=\s*(?:async\s*)?(?P<args>\([^\n)]*\)|[A-Za-z_$][\w$]*)\s*=>",
    re.MULTILINE,
)
_ROUTE_RE = re.compile(
    r"(?P<owner>[A-Za-z_$][\w$]*)\.(?P<method>get|post|put|patch|delete|options|head|use)"
    r"\(\s*['\"](?P<path>[^'\"]+)['\"]\s*,\s*(?P<handler>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)",
    re.IGNORECASE,
)
_CALL_RE = re.compile(r"(?P<target>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)\s*\(")


class JavaScriptParser:
    languages = frozenset({"javascript", "typescript", "jsx", "tsx"})

    def parse(self, path: Path, relative_path: str, source: str) -> ParseResult:
        result = ParseResult()
        self._imports(source, result)
        declarations: list[tuple[int, int, str]] = []
        for match in _DECL_RE.finditer(source):
            raw_kind = match.group("kind")
            kind = "function" if "function" in raw_kind else raw_kind
            name = match.group("name")
            line = source.count("\n", 0, match.start()) + 1
            tail = " ".join(match.group("tail").strip().split())
            keyword = "async function" if raw_kind.startswith("async") else kind
            signature = f"{keyword} {name}{tail}"
            exported = bool(match.group("export"))
            result.symbols.append(Symbol(name, name, kind, signature, line, line, exported))
            declarations.append((match.start(), line, name))
            if kind == "class":
                inheritance = re.search(r"\bextends\s+([\w$.]+)", tail)
                if inheritance:
                    result.edges.append(
                        EdgeCandidate(
                            "inherits", name, inheritance.group(1), line, 0.9, "extends clause"
                        )
                    )
                implementation = re.search(r"\bimplements\s+([\w$., ]+)", tail)
                if implementation:
                    for target in implementation.group(1).split(","):
                        result.edges.append(
                            EdgeCandidate(
                                "implements", name, target.strip(), line, 0.9, "implements clause"
                            )
                        )
        for match in _ARROW_RE.finditer(source):
            name = match.group("name")
            line = source.count("\n", 0, match.start()) + 1
            signature = f"const {name} = {match.group('args')} =>"
            kind = (
                "component"
                if name[:1].isupper() and path.suffix.lower() in {".jsx", ".tsx"}
                else "function"
            )
            result.symbols.append(
                Symbol(name, name, kind, signature, line, line, bool(match.group("export")))
            )
            declarations.append((match.start(), line, name))

        for route_match in _ROUTE_RE.finditer(source):
            line = source.count("\n", 0, route_match.start()) + 1
            handler = route_match.group("handler")
            method = route_match.group("method").upper()
            result.routes.append(Route(method, route_match.group("path"), handler, line, 0.9))
            result.edges.append(
                EdgeCandidate("route-handler", None, handler, line, 0.9, route_match.group(0))
            )

        # Lexical calls are intentionally medium/low confidence and only retained when later resolvable.
        declaration_names = {symbol.name for symbol in result.symbols}
        for call_match in _CALL_RE.finditer(source):
            target = call_match.group("target")
            if target in {"if", "for", "while", "switch", "catch", "function", "require"}:
                continue
            before = [item for item in declarations if item[0] <= call_match.start()]
            source_symbol = before[-1][2] if before else None
            if source_symbol and (target not in declaration_names or target != source_symbol):
                line = source.count("\n", 0, call_match.start()) + 1
                result.edges.append(
                    EdgeCandidate("calls", source_symbol, target, line, 0.55, "lexical call")
                )

        counts: dict[str, int] = {}
        for symbol in result.symbols:
            counts[symbol.kind] = counts.get(symbol.kind, 0) + 1
        result.summary = ", ".join(
            f"{value} {key}{'' if value == 1 else 's'}" for key, value in sorted(counts.items())
        )
        return result

    @staticmethod
    def _imports(source: str, result: ParseResult) -> None:
        code_positions = _code_positions(source)
        for match in _STATIC_IMPORT_BOUNDARY_RE.finditer(source):
            trivia_limit = min(len(source), match.end() + _MAX_STATIC_IMPORT_CHARS)
            start = _skip_static_import_trivia(source, match.end(), trivia_limit)
            keyword_match = _STATIC_IMPORT_KEYWORD_RE.match(source, start, trivia_limit)
            if keyword_match is None:
                continue
            if not code_positions[start]:
                continue
            keyword = keyword_match.group("keyword")
            parsed = _static_import_at(source, keyword, start, keyword_match.end())
            if parsed is None:
                continue
            module, clause = parsed
            line = source.count("\n", 0, start) + 1
            _append_import_records(result, module, clause, line)
        for match in _REQUIRE_RE.finditer(source):
            if not code_positions[match.start()]:
                continue
            module = match.group("module")
            line = source.count("\n", 0, match.start()) + 1
            result.imports.append(
                ImportRecord(
                    module, None, match.group("what").strip(), line, module.startswith(".")
                )
            )


def _static_import_at(
    source: str, keyword: str, start: int, keyword_end: int
) -> tuple[str, str | None] | None:
    limit = min(len(source), start + _MAX_STATIC_IMPORT_CHARS)
    cursor = _skip_space_and_comments(source, keyword_end, limit)
    if cursor >= limit:
        return None
    if keyword == "import" and source[cursor] in {"'", '"'}:
        module = _read_string(source, cursor, limit)
        return (module[0], None) if module is not None else None
    if keyword == "import" and source[cursor] in {"(", "."}:
        return None
    if keyword == "export" and source[cursor] not in {"{", "*"}:
        return None

    clause_start = cursor
    depths = {"{": 0, "[": 0, "(": 0}
    closing = {"}": "{", "]": "[", ")": "("}
    while cursor < limit:
        cursor = _skip_space_and_comments(source, cursor, limit)
        if cursor >= limit:
            return None
        character = source[cursor]
        if character == ";" and not any(depths.values()):
            return None
        if character in depths:
            depths[character] += 1
            cursor += 1
            continue
        if character in closing:
            opener = closing[character]
            if depths[opener] == 0:
                return None
            depths[opener] -= 1
            cursor += 1
            continue
        if character in {"'", '"', "\x60"}:
            return None
        identifier = re.match(r"[A-Za-z_$][\w$]*", source[cursor:limit])
        if identifier is None:
            cursor += 1
            continue
        word = identifier.group(0)
        word_start = cursor
        cursor += identifier.end()
        if any(depths.values()):
            continue
        if word in {"import", "export"}:
            return None
        if word != "from":
            continue
        module_start = _skip_space_and_comments(source, cursor, limit)
        if module_start >= limit or source[module_start] not in {"'", '"'}:
            return None
        module = _read_string(source, module_start, limit)
        if module is None or not module[0]:
            return None
        return module[0], source[clause_start:word_start]
    return None


def _append_import_records(result: ParseResult, module: str, clause: str | None, line: int) -> None:
    if clause is None:
        result.imports.append(ImportRecord(module, None, None, line, module.startswith(".")))
        return
    code_positions = _code_positions(clause)
    what = " ".join(
        "".join(
            character if code_positions[index] else " " for index, character in enumerate(clause)
        )
        .strip()
        .split()
    )
    if what.startswith("type "):
        what = what.removeprefix("type ").lstrip()
    if what.startswith("{") and what.endswith("}"):
        for item in what[1:-1].split(","):
            bits = item.strip().split(" as ")
            if bits and bits[0]:
                result.imports.append(
                    ImportRecord(
                        module,
                        bits[0],
                        bits[1] if len(bits) > 1 else None,
                        line,
                        module.startswith("."),
                    )
                )
    elif what.startswith("*"):
        alias = what.split(" as ")[-1].strip()
        result.imports.append(ImportRecord(module, "*", alias, line, module.startswith(".")))
    else:
        default_name = what.split(",", 1)[0].strip()
        if default_name:
            result.imports.append(
                ImportRecord(module, "default", default_name, line, module.startswith("."))
            )


def _skip_static_import_trivia(source: str, cursor: int, limit: int) -> int:
    while cursor < limit:
        if source[cursor] in " \t\f\v":
            cursor += 1
        elif source.startswith("/*", cursor):
            end = source.find("*/", cursor + 2, limit)
            if end == -1:
                return limit
            cursor = end + 2
        else:
            break
    return cursor


def _skip_space_and_comments(source: str, cursor: int, limit: int) -> int:
    while cursor < limit:
        if source[cursor].isspace():
            cursor += 1
        elif source.startswith("//", cursor):
            newline = source.find("\n", cursor + 2, limit)
            cursor = limit if newline == -1 else newline + 1
        elif source.startswith("/*", cursor):
            end = source.find("*/", cursor + 2, limit)
            cursor = limit if end == -1 else end + 2
        else:
            break
    return cursor


def _read_string(source: str, start: int, limit: int) -> tuple[str, int] | None:
    quote = source[start]
    cursor = start + 1
    while cursor < limit:
        character = source[cursor]
        if character in {"\n", "\r"}:
            return None
        if character == "\\":
            cursor += 2
            continue
        if character == quote:
            return source[start + 1 : cursor], cursor + 1
        cursor += 1
    return None


def _code_positions(source: str) -> bytearray:
    positions = bytearray(b"\x01") * len(source)
    cursor = 0
    while cursor < len(source):
        if source.startswith("//", cursor):
            end = source.find("\n", cursor + 2)
            end = len(source) if end == -1 else end
            positions[cursor:end] = b"\x00" * (end - cursor)
            cursor = end
        elif source.startswith("/*", cursor):
            end = source.find("*/", cursor + 2)
            end = len(source) if end == -1 else end + 2
            positions[cursor:end] = b"\x00" * (end - cursor)
            cursor = end
        elif source[cursor] in {"'", '"', "\x60"}:
            quote = source[cursor]
            end = cursor + 1
            while end < len(source):
                if source[end] == "\\":
                    end += 2
                    continue
                end += 1
                if source[end - 1] == quote:
                    break
            positions[cursor:end] = b"\x00" * (end - cursor)
            cursor = end
        else:
            cursor += 1
    return positions
