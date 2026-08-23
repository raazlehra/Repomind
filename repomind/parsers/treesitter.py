from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from repomind.models import ParseResult, Symbol
from repomind.parsers.javascript import JavaScriptParser


class TreeSitterJavaScriptParser:
    """Optional Tree-sitter declarations with deterministic lexical relationship extraction."""

    languages: frozenset[str]

    def __init__(self, language: str) -> None:
        tree_sitter = importlib.import_module("tree_sitter")
        grammar_module_name = (
            "tree_sitter_javascript"
            if language in {"javascript", "jsx"}
            else "tree_sitter_typescript"
        )
        grammar = importlib.import_module(grammar_module_name)
        if language == "typescript":
            capsule = grammar.language_typescript()
        elif language == "tsx":
            capsule = grammar.language_tsx()
        else:
            capsule = grammar.language()
        language_object = tree_sitter.Language(capsule)
        try:
            self._parser = tree_sitter.Parser(language_object)
        except TypeError:
            self._parser = tree_sitter.Parser()
            self._parser.language = language_object
        self.languages = frozenset({language})
        self._lexical = JavaScriptParser()

    def parse(self, path: Path, relative_path: str, source: str) -> ParseResult:
        # The lexical pass retains imports/routes/call evidence; Tree-sitter supplies declaration spans.
        result = self._lexical.parse(path, relative_path, source)
        encoded = source.encode("utf-8")
        tree = self._parser.parse(encoded)
        symbols: list[Symbol] = []
        self._walk(tree.root_node, encoded, path, symbols, parent=None)
        if symbols:
            result.symbols = _unique_symbols(symbols)
            counts: dict[str, int] = {}
            for symbol in result.symbols:
                counts[symbol.kind] = counts.get(symbol.kind, 0) + 1
            result.summary = ", ".join(
                f"{count} {kind}{'' if count == 1 else 's'}"
                for kind, count in sorted(counts.items())
            )
        if bool(getattr(tree.root_node, "has_error", False)):
            result.summary = (result.summary + "; Tree-sitter recovered syntax errors").lstrip("; ")
        return result

    def _walk(
        self,
        node: Any,
        source: bytes,
        path: Path,
        output: list[Symbol],
        parent: str | None,
    ) -> None:
        node_type = str(node.type)
        declaration_kinds = {
            "function_declaration": "function",
            "generator_function_declaration": "function",
            "class_declaration": "class",
            "interface_declaration": "interface",
            "type_alias_declaration": "type",
            "enum_declaration": "enum",
        }
        next_parent = parent
        if node_type in declaration_kinds:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = _node_text(name_node, source)
                qualified = f"{parent}.{name}" if parent else name
                kind = declaration_kinds[node_type]
                output.append(
                    _symbol_from_node(
                        node, source, name, qualified, kind, parent, exported=_exported(node)
                    )
                )
                if kind == "class":
                    next_parent = qualified
        elif node_type == "method_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = _node_text(name_node, source)
                qualified = f"{parent}.{name}" if parent else name
                output.append(
                    _symbol_from_node(
                        node, source, name, qualified, "method", parent, exported=False
                    )
                )
        elif node_type == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if (
                name_node is not None
                and value_node is not None
                and str(value_node.type) in {"arrow_function", "function_expression"}
            ):
                name = _node_text(name_node, source)
                qualified = f"{parent}.{name}" if parent else name
                is_component = name[:1].isupper() and path.suffix.lower() in {".jsx", ".tsx"}
                output.append(
                    _symbol_from_node(
                        node,
                        source,
                        name,
                        qualified,
                        "component" if is_component else "function",
                        parent,
                        exported=_exported(node),
                    )
                )
        for child in node.named_children:
            self._walk(child, source, path, output, next_parent)


def _node_text(node: Any, source: bytes) -> str:
    return source[int(node.start_byte) : int(node.end_byte)].decode("utf-8", errors="replace")


def _symbol_from_node(
    node: Any,
    source: bytes,
    name: str,
    qualified: str,
    kind: str,
    parent: str | None,
    *,
    exported: bool,
) -> Symbol:
    body = node.child_by_field_name("body")
    signature_end = (
        int(body.start_byte)
        if body is not None
        else min(int(node.end_byte), int(node.start_byte) + 300)
    )
    signature = " ".join(
        source[int(node.start_byte) : signature_end].decode("utf-8", errors="replace").split()
    ).rstrip(" {")
    return Symbol(
        name=name,
        qualified_name=qualified,
        kind=kind,
        signature=signature,
        line_start=int(node.start_point[0]) + 1,
        line_end=int(node.end_point[0]) + 1,
        exported=exported,
        parent=parent,
    )


def _exported(node: Any) -> bool:
    current = node
    for _ in range(3):
        current = getattr(current, "parent", None)
        if current is None:
            return False
        if str(current.type) == "export_statement":
            return True
    return False


def _unique_symbols(symbols: list[Symbol]) -> list[Symbol]:
    seen: set[tuple[str, int]] = set()
    output: list[Symbol] = []
    for symbol in symbols:
        key = (symbol.qualified_name, symbol.line_start)
        if key not in seen:
            seen.add(key)
            output.append(symbol)
    return output
