from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from repomind.models import EdgeCandidate, ImportRecord, ParseResult, Route, Symbol


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Subscript):
        return _name(node.value)
    try:
        return ast.unparse(node)
    except Exception:
        return "unknown"


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    try:
        args = ast.unparse(node.args)
        returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
    except Exception:
        args, returns = "...", ""
    return f"{prefix} {node.name}({args}){returns}"


class PythonParser:
    languages = frozenset({"python"})

    def parse(self, path: Path, relative_path: str, source: str) -> ParseResult:
        result = ParseResult()
        try:
            tree = ast.parse(source, filename=relative_path, type_comments=True)
        except (SyntaxError, ValueError) as exc:
            result.parse_error = f"{type(exc).__name__}: {exc}"
            result.summary = "Python source (parse error; indexed as file only)"
            return result
        visitor = _PythonVisitor(result)
        visitor.visit(tree)
        counts: dict[str, int] = {}
        for symbol in result.symbols:
            counts[symbol.kind] = counts.get(symbol.kind, 0) + 1
        result.summary = ", ".join(
            f"{count} {kind}{'' if count == 1 else 's'}" for kind, count in sorted(counts.items())
        )
        return result


class _PythonVisitor(ast.NodeVisitor):
    def __init__(self, result: ParseResult) -> None:
        self.result = result
        self.parents: list[str] = []
        self.current_callable: list[str] = []

    def _qualified(self, name: str) -> str:
        return ".".join([*self.parents, name])

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.result.imports.append(ImportRecord(alias.name, None, alias.asname, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            self.result.imports.append(
                ImportRecord(module, alias.name, alias.asname, node.lineno, bool(node.level))
            )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified = self._qualified(node.name)
        bases = [_name(base) for base in node.bases]
        signature = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
        self.result.symbols.append(
            Symbol(
                name=node.name,
                qualified_name=qualified,
                kind="class",
                signature=signature,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                exported=not node.name.startswith("_"),
                parent=".".join(self.parents) or None,
                documentation=(ast.get_docstring(node) or "")[:400] or None,
            )
        )
        for base in bases:
            self.result.edges.append(
                EdgeCandidate("inherits", qualified, base, node.lineno, 0.9, f"class base {base}")
            )
        self.parents.append(node.name)
        self.generic_visit(node)
        self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified = self._qualified(node.name)
        kind = "method" if self.parents else "function"
        decorators = [
            _name(item.func if isinstance(item, ast.Call) else item) for item in node.decorator_list
        ]
        decorated_signature = _signature(node)
        if decorators:
            decorated_signature = f"@{', @'.join(decorators)} {decorated_signature}"
        self.result.symbols.append(
            Symbol(
                name=node.name,
                qualified_name=qualified,
                kind=kind,
                signature=decorated_signature,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                exported=not node.name.startswith("_") and not self.parents,
                parent=".".join(self.parents) or None,
                documentation=(ast.get_docstring(node) or "")[:400] or None,
            )
        )
        self._extract_routes(node, qualified)
        self.current_callable.append(qualified)
        # Visit decorators/defaults and body while preserving the callable scope.
        self.generic_visit(node)
        self.current_callable.pop()

    def _extract_routes(self, node: ast.FunctionDef | ast.AsyncFunctionDef, qualified: str) -> None:
        methods = {"get", "post", "put", "patch", "delete", "options", "head", "route", "websocket"}
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            decorator_name = _name(decorator.func)
            method = decorator_name.rsplit(".", 1)[-1].lower()
            if method not in methods or not decorator.args:
                continue
            first = decorator.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self.result.routes.append(
                    Route(method.upper(), first.value, qualified, node.lineno, 0.95)
                )
                self.result.edges.append(
                    EdgeCandidate(
                        "route-handler", None, qualified, node.lineno, 0.95, decorator_name
                    )
                )

    def visit_Call(self, node: ast.Call) -> None:
        target = _name(node.func)
        if target and self.current_callable:
            self.result.edges.append(
                EdgeCandidate(
                    "calls",
                    self.current_callable[-1],
                    target,
                    getattr(node, "lineno", None),
                    0.7 if "." in target else 0.6,
                    f"call expression {target}",
                )
            )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if not self.parents and not self.current_callable:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    self.result.symbols.append(
                        Symbol(
                            target.id,
                            target.id,
                            "constant",
                            target.id,
                            node.lineno,
                            node.end_lineno or node.lineno,
                            True,
                        )
                    )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if (
            not self.parents
            and not self.current_callable
            and isinstance(node.target, ast.Name)
            and node.target.id.isupper()
        ):
            annotation: Any = node.annotation
            self.result.symbols.append(
                Symbol(
                    node.target.id,
                    node.target.id,
                    "constant",
                    f"{node.target.id}: {_name(annotation)}",
                    node.lineno,
                    node.end_lineno or node.lineno,
                    True,
                )
            )
        self.generic_visit(node)
