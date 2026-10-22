from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from repomind.models import EdgeCandidate

MAX_FIXTURE_SOURCE_CHARS = 256_000
MAX_FIXTURE_AST_NODES = 40_000
MAX_FIXTURE_SCOPES = 1_024
MAX_FIXTURE_BINDINGS = 4_096
MAX_FIXTURE_CONSTANTS = 256
MAX_FIXTURE_READER_CALLS = 512
MAX_FIXTURE_REFERENCES = 256
MAX_FIXTURE_EXPRESSION_CHARS = 8_192
MAX_FIXTURE_PATH_CHARS = 4_096
MAX_FIXTURE_EXPRESSION_NODES = 8_192
MAX_FIXTURE_EXPRESSION_DEPTH = 32
MAX_FIXTURE_SCOPE_DEPTH = 128

_FIXTURE_SUFFIXES = frozenset({".json", ".jsonl"})
_NODE_FS_READERS = frozenset({"readFile", "readFileSync"})
_FUNCTION_TYPES = frozenset(
    {
        "arrow_function",
        "function_declaration",
        "function_expression",
        "generator_function",
        "generator_function_declaration",
        "method_definition",
    }
)
_SCOPE_TYPES = frozenset(
    {
        "program",
        "statement_block",
        "catch_clause",
        "for_statement",
        "for_in_statement",
        "switch_statement",
        "switch_body",
        "class",
        "class_static_block",
        *_FUNCTION_TYPES,
    }
)


class _AbortFixtureAnalysis(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _ImportBinding:
    role: str
    confidence: float


@dataclass(frozen=True, slots=True)
class _Constant:
    name: str
    value_node: Any
    declared_at: int


@dataclass(frozen=True, slots=True)
class _Binding:
    kind: str
    imported: _ImportBinding | None = None
    constant: _Constant | None = None


@dataclass(frozen=True, slots=True)
class _StaticPath:
    value: PurePosixPath


@dataclass(frozen=True, slots=True)
class _SourceUrl:
    pass


_Ambiguous = object()
ScopeKey = tuple[int, int, str]


def extract_fixture_references(
    root: Any, source: bytes, relative_path: str
) -> list[EdgeCandidate]:
    """Extract bounded static fixture paths from a successfully parsed JS/TS AST."""
    try:
        return _FixtureExtractor(root, source, relative_path).run()
    except (
        _AbortFixtureAnalysis,
        AttributeError,
        IndexError,
        MemoryError,
        OverflowError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        return []


class _FixtureExtractor:
    def __init__(self, root: Any, source: bytes, relative_path: str) -> None:
        self.root = root
        self.source = source
        self.relative_path = relative_path
        self.nodes: list[Any] = []
        self.scope_keys: set[ScopeKey] = set()
        self.bindings: dict[ScopeKey, dict[str, _Binding | object]] = {}
        self.imports: dict[str, _ImportBinding] = {}
        self.constants: dict[str, _Constant] = {}
        self.constant_cache: dict[str, _StaticPath | None] = {}
        self.constants_in_progress: set[str] = set()
        self.expression_nodes = 0

    def run(self) -> list[EdgeCandidate]:
        if (
            len(self.source) > MAX_FIXTURE_SOURCE_CHARS
            or bool(getattr(self.root, "has_error", False))
            or int(getattr(self.root, "descendant_count", 0)) > MAX_FIXTURE_AST_NODES
        ):
            return []
        self.nodes = self._collect_nodes()
        self.scope_keys = {
            _scope_key(node) for node in self.nodes if str(node.type) in _SCOPE_TYPES
        }
        if len(self.scope_keys) > MAX_FIXTURE_SCOPES:
            raise _AbortFixtureAnalysis
        self.imports = self._collect_imports()
        self.constants = self._collect_module_constants()
        relevant = set(self.imports) | set(self.constants)
        self._collect_bindings(relevant)
        self._reject_reassignments(relevant)

        edges: list[EdgeCandidate] = []
        seen: set[str] = set()
        reader_calls = 0
        for node in self.nodes:
            if str(node.type) != "call_expression":
                continue
            function = node.child_by_field_name("function")
            if function is None or str(function.type) != "identifier":
                continue
            if any(str(child.type) == "optional_chain" for child in node.children):
                continue
            name = _node_text(function, self.source)
            binding = self._resolve_binding(function, name)
            if (
                binding is None
                or binding.kind != "import"
                or binding.imported is None
                or not binding.imported.role.startswith("reader:")
            ):
                continue
            reader_calls += 1
            if reader_calls > MAX_FIXTURE_READER_CALLS:
                raise _AbortFixtureAnalysis
            arguments = node.child_by_field_name("arguments")
            if arguments is None or not arguments.named_children:
                continue
            value = self._evaluate(arguments.named_children[0], 0)
            if not isinstance(value, _StaticPath):
                continue
            target = value.value.as_posix()
            if value.value.suffix.lower() not in _FIXTURE_SUFFIXES or target in seen:
                continue
            if len(edges) >= MAX_FIXTURE_REFERENCES:
                raise _AbortFixtureAnalysis
            seen.add(target)
            local_reader = binding.imported.role == "reader:local"
            edges.append(
                EdgeCandidate(
                    "fixture-reference",
                    None,
                    target,
                    int(node.start_point[0]) + 1,
                    binding.imported.confidence,
                    (
                        "AST-proven static path argument to imported read* function"
                        if local_reader
                        else "AST-proven source-anchored node:fs fixture path"
                    ),
                )
            )
        return edges

    def _collect_nodes(self) -> list[Any]:
        nodes: list[Any] = []
        stack = [self.root]
        while stack:
            node = stack.pop()
            nodes.append(node)
            if len(nodes) > MAX_FIXTURE_AST_NODES:
                raise _AbortFixtureAnalysis
            stack.extend(reversed(node.named_children))
        return nodes

    def _collect_imports(self) -> dict[str, _ImportBinding]:
        imports: dict[str, _ImportBinding] = {}
        for statement in self.nodes:
            if str(statement.type) != "import_statement":
                continue
            source_node = statement.child_by_field_name("source")
            module = _simple_string(source_node, self.source)
            if module is None:
                continue
            stack = list(reversed(statement.named_children))
            while stack:
                node = stack.pop()
                if str(node.type) == "import_specifier":
                    name_node = node.child_by_field_name("name")
                    alias_node = node.child_by_field_name("alias")
                    if name_node is None:
                        raise _AbortFixtureAnalysis
                    imported_name = _node_text(name_node, self.source)
                    local_name = _node_text(alias_node or name_node, self.source)
                    binding = _supported_import(module, imported_name)
                    if binding is not None:
                        if local_name in imports:
                            raise _AbortFixtureAnalysis
                        imports[local_name] = binding
                stack.extend(reversed(node.named_children))
        return imports

    def _collect_module_constants(self) -> dict[str, _Constant]:
        constants: dict[str, _Constant] = {}
        for declaration in self.nodes:
            if str(declaration.type) != "lexical_declaration":
                continue
            if not _is_module_declaration(declaration, self.root):
                continue
            if not declaration.children or str(declaration.children[0].type) != "const":
                continue
            for declarator in declaration.named_children:
                if str(declarator.type) != "variable_declarator":
                    continue
                name_node = declarator.child_by_field_name("name")
                value_node = declarator.child_by_field_name("value")
                if (
                    name_node is None
                    or value_node is None
                    or str(name_node.type) != "identifier"
                ):
                    continue
                name = _node_text(name_node, self.source)
                if name in constants:
                    raise _AbortFixtureAnalysis
                constants[name] = _Constant(name, value_node, int(declarator.start_byte))
                if len(constants) > MAX_FIXTURE_CONSTANTS:
                    raise _AbortFixtureAnalysis
        return constants

    def _collect_bindings(self, relevant: set[str]) -> None:
        program = _scope_key(self.root)
        for name, imported in self.imports.items():
            self._add_binding(program, name, _Binding("import", imported=imported), relevant)

        for node in self.nodes:
            node_type = str(node.type)
            if node_type == "variable_declarator":
                name_node = node.child_by_field_name("name")
                declaration = node.parent
                if name_node is None or declaration is None:
                    raise _AbortFixtureAnalysis
                declaration_type = str(declaration.type)
                if declaration_type not in {"lexical_declaration", "variable_declaration"}:
                    raise _AbortFixtureAnalysis
                is_var = bool(
                    declaration.children and str(declaration.children[0].type) == "var"
                )
                scope = self._nearest_scope(declaration.parent, function_only=is_var)
                for name in _binding_names(name_node, self.source):
                    constant = self.constants.get(name)
                    kind = (
                        "constant"
                        if constant is not None and scope == program
                        else "local"
                    )
                    self._add_binding(
                        scope,
                        name,
                        _Binding(kind, constant=constant if kind == "constant" else None),
                        relevant,
                    )
            elif node_type in _FUNCTION_TYPES:
                self._collect_function_bindings(node, relevant)
            elif node_type == "catch_clause":
                parameter = node.child_by_field_name("parameter")
                if parameter is not None:
                    scope = _scope_key(node)
                    for name in _binding_names(parameter, self.source):
                        self._add_binding(scope, name, _Binding("local"), relevant)
            elif node_type in {"class", "class_declaration"}:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    scope = (
                        _scope_key(node)
                        if node_type == "class"
                        else self._nearest_scope(node.parent)
                    )
                    self._add_binding(
                        scope,
                        _node_text(name_node, self.source),
                        _Binding("local"),
                        relevant,
                    )
        if sum(len(values) for values in self.bindings.values()) > MAX_FIXTURE_BINDINGS:
            raise _AbortFixtureAnalysis

    def _reject_reassignments(self, relevant: set[str]) -> None:
        for node in self.nodes:
            node_type = str(node.type)
            target = None
            if node_type in {"assignment_expression", "augmented_assignment_expression"}:
                target = node.child_by_field_name("left")
            elif node_type == "update_expression":
                target = node.child_by_field_name("argument")
                if target is None and node.named_children:
                    target = node.named_children[0]
            if target is None:
                continue
            if str(target.type) == "identifier":
                names = {_node_text(target, self.source)}
            elif str(target.type) in {"object_pattern", "array_pattern"}:
                names = _binding_names(target, self.source)
            else:
                continue
            for name in names & relevant:
                binding = self._resolve_binding(target, name)
                if binding is not None and binding.kind in {"import", "constant"}:
                    raise _AbortFixtureAnalysis

    def _collect_function_bindings(self, node: Any, relevant: set[str]) -> None:
        node_type = str(node.type)
        name_node = node.child_by_field_name("name")
        if name_node is not None and node_type != "method_definition":
            target_scope = (
                self._nearest_scope(node.parent)
                if node_type in {"function_declaration", "generator_function_declaration"}
                else _scope_key(node)
            )
            self._add_binding(
                target_scope,
                _node_text(name_node, self.source),
                _Binding("local"),
                relevant,
            )
        parameters = node.child_by_field_name("parameters")
        parameter = node.child_by_field_name("parameter")
        parameter_node = parameters or parameter
        if parameter_node is not None:
            scope = _scope_key(node)
            for name in _binding_names(parameter_node, self.source):
                self._add_binding(scope, name, _Binding("local"), relevant)

    def _add_binding(
        self,
        scope: ScopeKey,
        name: str,
        binding: _Binding,
        relevant: set[str],
    ) -> None:
        if name not in relevant:
            return
        values = self.bindings.setdefault(scope, {})
        existing = values.get(name)
        if existing is None:
            values[name] = binding
        elif isinstance(existing, _Binding) and existing.kind == binding.kind == "local":
            return
        else:
            values[name] = _Ambiguous

    def _nearest_scope(self, node: Any, *, function_only: bool = False) -> ScopeKey:
        depth = 0
        current = node
        allowed = _FUNCTION_TYPES | {"program"} if function_only else _SCOPE_TYPES
        while current is not None:
            depth += 1
            if depth > MAX_FIXTURE_SCOPE_DEPTH:
                raise _AbortFixtureAnalysis
            if str(current.type) in allowed:
                return _scope_key(current)
            current = current.parent
        raise _AbortFixtureAnalysis

    def _resolve_binding(self, node: Any, name: str) -> _Binding | None:
        depth = 0
        current = node
        while current is not None:
            depth += 1
            if depth > MAX_FIXTURE_SCOPE_DEPTH:
                raise _AbortFixtureAnalysis
            key = _scope_key(current)
            if key in self.scope_keys:
                binding = self.bindings.get(key, {}).get(name)
                if binding is _Ambiguous:
                    raise _AbortFixtureAnalysis
                if isinstance(binding, _Binding):
                    return binding
            current = current.parent
        return None

    def _constant_value(self, node: Any, name: str, depth: int) -> _StaticPath | None:
        binding = self._resolve_binding(node, name)
        if binding is None or binding.kind != "constant" or binding.constant is None:
            return None
        constant = binding.constant
        if constant.declared_at >= int(node.start_byte):
            return None
        if name in self.constant_cache:
            return self.constant_cache[name]
        if name in self.constants_in_progress:
            raise _AbortFixtureAnalysis
        self.constants_in_progress.add(name)
        value = self._evaluate(constant.value_node, depth + 1)
        self.constants_in_progress.remove(name)
        result = value if isinstance(value, _StaticPath) else None
        self.constant_cache[name] = result
        return result

    def _evaluate(self, node: Any, depth: int) -> _StaticPath | _SourceUrl | str | None:
        if depth > MAX_FIXTURE_EXPRESSION_DEPTH:
            raise _AbortFixtureAnalysis
        self.expression_nodes += 1
        if self.expression_nodes > MAX_FIXTURE_EXPRESSION_NODES:
            raise _AbortFixtureAnalysis
        if int(node.end_byte) - int(node.start_byte) > MAX_FIXTURE_EXPRESSION_CHARS:
            raise _AbortFixtureAnalysis

        node_type = str(node.type)
        if node_type == "parenthesized_expression":
            return (
                self._evaluate(node.named_children[0], depth + 1)
                if len(node.named_children) == 1
                else None
            )
        if node_type == "string":
            return _simple_string(node, self.source)
        if node_type == "member_expression":
            object_node = node.child_by_field_name("object")
            property_node = node.child_by_field_name("property")
            if (
                object_node is not None
                and property_node is not None
                and str(object_node.type) == "meta_property"
                and _node_text(object_node, self.source) == "import.meta"
                and _node_text(property_node, self.source) == "url"
            ):
                return _SourceUrl()
            return None
        if node_type == "identifier":
            return self._constant_value(node, _node_text(node, self.source), depth)
        if node_type != "call_expression":
            return None
        if any(str(child.type) == "optional_chain" for child in node.children):
            return None
        function = node.child_by_field_name("function")
        arguments = node.child_by_field_name("arguments")
        if (
            function is None
            or arguments is None
            or str(function.type) != "identifier"
        ):
            return None
        binding = self._resolve_binding(function, _node_text(function, self.source))
        if binding is None or binding.kind != "import" or binding.imported is None:
            return None
        values = [self._evaluate(item, depth + 1) for item in arguments.named_children]
        role = binding.imported.role
        if role == "file-url" and len(values) == 1 and isinstance(values[0], _SourceUrl):
            source_path = _safe_source_path(self.relative_path)
            return _StaticPath(source_path) if source_path is not None else None
        if role == "dirname" and len(values) == 1 and isinstance(values[0], _StaticPath):
            return _StaticPath(values[0].value.parent)
        if (
            role == "join"
            and len(values) >= 2
            and isinstance(values[0], _StaticPath)
            and all(isinstance(item, str) for item in values[1:])
        ):
            return _safe_static_join(
                values[0].value,
                [item for item in values[1:] if isinstance(item, str)],
            )
        return None


def _supported_import(module: str, imported_name: str) -> _ImportBinding | None:
    if module == "node:path" and imported_name in {"join", "dirname"}:
        return _ImportBinding(imported_name, 1.0)
    if module == "node:url" and imported_name == "fileURLToPath":
        return _ImportBinding("file-url", 1.0)
    if module == "node:fs" and imported_name in _NODE_FS_READERS:
        return _ImportBinding("reader:node-fs", 1.0)
    if module.startswith(".") and imported_name.startswith("read"):
        return _ImportBinding("reader:local", 0.9)
    return None


def _binding_names(node: Any, source: bytes) -> set[str]:
    node_type = str(node.type)
    if node_type in {"identifier", "shorthand_property_identifier_pattern"}:
        return {_node_text(node, source)}
    if node_type == "pair_pattern":
        value = node.child_by_field_name("value")
        if value is None:
            raise _AbortFixtureAnalysis
        return _binding_names(value, source)
    if node_type in {"assignment_pattern", "object_assignment_pattern"}:
        left = node.child_by_field_name("left")
        if left is None:
            left = node.child_by_field_name("name")
        if left is None:
            raise _AbortFixtureAnalysis
        return _binding_names(left, source)
    if node_type == "rest_pattern":
        if len(node.named_children) != 1:
            raise _AbortFixtureAnalysis
        return _binding_names(node.named_children[0], source)
    if node_type in {"required_parameter", "optional_parameter"}:
        pattern = node.child_by_field_name("pattern") or node.child_by_field_name("name")
        if pattern is None and node.named_children:
            pattern = node.named_children[0]
        if pattern is None:
            raise _AbortFixtureAnalysis
        return _binding_names(pattern, source)
    if node_type in {"object_pattern", "array_pattern", "formal_parameters"}:
        names: set[str] = set()
        for child in node.named_children:
            names.update(_binding_names(child, source))
        return names
    raise _AbortFixtureAnalysis


def _is_module_declaration(node: Any, root: Any) -> bool:
    parent = node.parent
    return parent == root or (
        parent is not None
        and str(parent.type) == "export_statement"
        and parent.parent == root
    )


def _scope_key(node: Any) -> ScopeKey:
    return (int(node.start_byte), int(node.end_byte), str(node.type))


def _node_text(node: Any, source: bytes) -> str:
    return source[int(node.start_byte) : int(node.end_byte)].decode("utf-8", errors="strict")


def _simple_string(node: Any | None, source: bytes) -> str | None:
    if node is None or str(node.type) != "string":
        return None
    raw = _node_text(node, source)
    if len(raw) < 2 or raw[0] not in {"'", '"'} or raw[-1] != raw[0]:
        return None
    value = raw[1:-1]
    if "\\" in value or "\n" in value or "\r" in value:
        return None
    return value


def _safe_source_path(relative_path: str) -> PurePosixPath | None:
    normalized = posixpath.normpath(relative_path.replace("\\", "/"))
    if (
        not normalized
        or normalized == "."
        or normalized == ".."
        or normalized.startswith("../")
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or len(normalized) > MAX_FIXTURE_PATH_CHARS
    ):
        return None
    return PurePosixPath(normalized)


def _safe_static_join(base: PurePosixPath, segments: list[str]) -> _StaticPath | None:
    current = base.as_posix()
    for segment in segments:
        if (
            "\x00" in segment
            or "\\" in segment
            or segment.startswith("/")
            or ":" in segment
            or any(character in segment for character in "*?[]{}")
        ):
            return None
        current = posixpath.normpath(posixpath.join(current, segment))
        if (
            current == ".."
            or current.startswith("../")
            or current.startswith("/")
            or len(current) > MAX_FIXTURE_PATH_CHARS
        ):
            return None
    return _StaticPath(PurePosixPath(current))
