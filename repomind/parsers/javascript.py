from __future__ import annotations

import re
from pathlib import Path

from repomind.models import EdgeCandidate, ImportRecord, ParseResult, Route, Symbol

_IMPORT_RE = re.compile(
    r"(?:import|export)\s+(?P<what>.*?)\s+from\s*['\"](?P<module>[^'\"]+)['\"]",
    re.MULTILINE,
)
_SIDE_EFFECT_RE = re.compile(r"import\s*['\"](?P<module>[^'\"]+)['\"]")
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
        occupied: list[tuple[int, int]] = []
        for match in _IMPORT_RE.finditer(source):
            occupied.append(match.span())
            module = match.group("module")
            what = match.group("what").strip()
            line = source.count("\n", 0, match.start()) + 1
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
                result.imports.append(
                    ImportRecord(module, "*", alias, line, module.startswith("."))
                )
            else:
                default_name = what.split(",", 1)[0].strip()
                if default_name:
                    result.imports.append(
                        ImportRecord(module, "default", default_name, line, module.startswith("."))
                    )
        for match in _SIDE_EFFECT_RE.finditer(source):
            if any(start <= match.start() < end for start, end in occupied):
                continue
            module = match.group("module")
            line = source.count("\n", 0, match.start()) + 1
            result.imports.append(ImportRecord(module, None, None, line, module.startswith(".")))
        for match in _REQUIRE_RE.finditer(source):
            module = match.group("module")
            line = source.count("\n", 0, match.start()) + 1
            result.imports.append(
                ImportRecord(
                    module, None, match.group("what").strip(), line, module.startswith(".")
                )
            )
