from __future__ import annotations

import codecs
from pathlib import Path

from repomind.parsers import ParserRegistry
from repomind.parsers.fallback import FallbackParser
from repomind.parsers.javascript import JavaScriptParser
from repomind.parsers.python import PythonParser


def test_python_extracts_symbols_imports_calls_routes() -> None:
    source = """from fastapi import APIRouter
from .models import User
router = APIRouter()

class Base: pass
class AuthService(Base):
    def login(self, user: User) -> str:
        return issue(user)

@router.post("/login")
def login_route() -> str:
    return AuthService().login(User())
"""
    result = PythonParser().parse(Path("auth.py"), "auth.py", source)
    names = {symbol.qualified_name for symbol in result.symbols}
    assert {"Base", "AuthService", "AuthService.login", "login_route"} <= names
    assert any(item.module == ".models" and item.name == "User" for item in result.imports)
    assert any(edge.kind == "inherits" and edge.target == "Base" for edge in result.edges)
    assert any(edge.kind == "calls" and edge.target.endswith("login") for edge in result.edges)
    assert result.routes[0].path == "/login"
    assert result.routes[0].method == "POST"


def test_python_registry_parses_normal_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "normal.py"
    path.write_text("def plain() -> str:\n    return 'ok'\n", encoding="utf-8")

    result = ParserRegistry().parse(path, "normal.py", "python")

    assert result.parse_error is None
    assert any(symbol.name == "plain" for symbol in result.symbols)


def test_python_registry_parses_utf8_bom_file(tmp_path: Path) -> None:
    path = tmp_path / "bom.py"
    path.write_bytes(codecs.BOM_UTF8 + b"class BomService:\n    pass\n")

    result = ParserRegistry().parse(path, "bom.py", "python")

    assert result.parse_error is None
    assert any(symbol.name == "BomService" for symbol in result.symbols)


def test_python_parser_only_removes_leading_bom() -> None:
    result = PythonParser().parse(Path("middle_bom.py"), "middle_bom.py", "x = 1\n\ufeffy = 2\n")

    assert result.parse_error
    assert "U+FEFF" in result.parse_error


def test_python_bom_file_extracts_imports(tmp_path: Path) -> None:
    path = tmp_path / "imports.py"
    path.write_bytes(codecs.BOM_UTF8 + b"from .models import User\nimport os as operating_system\n")

    result = ParserRegistry().parse(path, "imports.py", "python")

    assert result.parse_error is None
    assert any(item.module == ".models" and item.name == "User" for item in result.imports)
    assert any(item.module == "os" and item.alias == "operating_system" for item in result.imports)


def test_python_bom_file_extracts_fastapi_routes(tmp_path: Path) -> None:
    path = tmp_path / "routes.py"
    path.write_bytes(
        codecs.BOM_UTF8
        + b"""from fastapi import APIRouter
router = APIRouter()

@router.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
"""
    )

    result = ParserRegistry().parse(path, "routes.py", "python")

    assert result.parse_error is None
    assert any(symbol.name == "health" for symbol in result.symbols)
    assert result.routes[0].method == "GET"
    assert result.routes[0].path == "/health"


def test_python_syntax_error_is_nonfatal() -> None:
    result = PythonParser().parse(Path("bad.py"), "bad.py", "def nope(")
    assert result.parse_error
    assert not result.symbols


def test_typescript_extracts_structure_imports_and_routes() -> None:
    source = """import React from "react";
import { save as persist } from './api';
export interface User { email: string }
export class UserService extends Base implements Store {
  save(user: User) { return persist(user); }
}
export const Dashboard = () => save();
app.post('/users', createUser);
"""
    result = JavaScriptParser().parse(Path("Dashboard.tsx"), "Dashboard.tsx", source)
    names = {symbol.name for symbol in result.symbols}
    assert {"User", "UserService", "Dashboard"} <= names
    assert any(item.module == "./api" and item.name == "save" for item in result.imports)
    assert any(edge.kind == "inherits" and edge.target == "Base" for edge in result.edges)
    assert result.routes[0].path == "/users"


def test_optional_tree_sitter_extracts_typescript_spans(tmp_path: Path) -> None:
    registry = ParserRegistry()
    if "typescript" not in registry.tree_sitter_languages:
        return
    path = tmp_path / "service.ts"
    path.write_text("export class Service {\n  run(): boolean { return true; }\n}\n")
    result = registry.parse(path, "service.ts", "typescript")
    service = next(symbol for symbol in result.symbols if symbol.name == "Service")
    method = next(symbol for symbol in result.symbols if symbol.name == "run")
    assert service.line_end == 3
    assert method.qualified_name == "Service.run"


def test_fallback_extracts_java_class_and_method() -> None:
    source = """import java.util.List;
public class PaymentService extends BaseService {
  public boolean process(Payment payment) { return true; }
}
"""
    result = FallbackParser().parse(Path("PaymentService.java"), "PaymentService.java", source)
    assert any(symbol.name == "PaymentService" for symbol in result.symbols)
    assert any(symbol.name == "process" for symbol in result.symbols)
    assert any(edge.kind == "inherits" for edge in result.edges)


def test_fallback_extracts_kotlin_object_and_enum_class() -> None:
    source = """package com.moneycompanion.domain

object REPOMIND_FRESHNESS_TEST_MODIFIED

enum class TransactionType { EXPENSE, INCOME }
"""
    result = FallbackParser().parse(Path("TransactionParser.kt"), "TransactionParser.kt", source)

    symbols = {symbol.name: symbol for symbol in result.symbols}
    assert symbols["REPOMIND_FRESHNESS_TEST_MODIFIED"].kind == "object"
    assert symbols["TransactionType"].kind == "enum"


def test_javascript_extracts_multiline_and_one_line_static_imports() -> None:
    source = """import defaultValue from './default.mjs'; import { inlineValue } from './inline.mjs';
import {
  recordsToTrajectory,
  verifyChain as checkChain,
} from '../src/adapters/redstamp.mjs';
import * as helpers from './helpers.mjs';
import './side-effect.mjs';
export {
  publicValue,
} from './exports.mjs';
"""

    result = JavaScriptParser().parse(
        Path("test/redstamp-adapter.test.mjs"),
        "test/redstamp-adapter.test.mjs",
        source,
    )

    imports = {
        (item.module, item.name, item.alias, item.line, item.is_relative) for item in result.imports
    }
    assert ("./default.mjs", "default", "defaultValue", 1, True) in imports
    assert ("./inline.mjs", "inlineValue", None, 1, True) in imports
    assert (
        "../src/adapters/redstamp.mjs",
        "recordsToTrajectory",
        None,
        2,
        True,
    ) in imports
    assert (
        "../src/adapters/redstamp.mjs",
        "verifyChain",
        "checkChain",
        2,
        True,
    ) in imports
    assert ("./helpers.mjs", "*", "helpers", 6, True) in imports
    assert ("./side-effect.mjs", None, None, 7, True) in imports
    assert ("./exports.mjs", "publicValue", None, 8, True) in imports


def test_javascript_ignores_non_static_import_text_and_invalid_declarations() -> None:
    source = """// import { commented } from './commented.mjs';
/*
import {
  blocked,
} from './block-comment.mjs';
*/
const note = "import { quoted } from './quoted.mjs'";
const lazyLiteral = import('./dynamic-literal.mjs');
const moduleName = './dynamic-expression.mjs';
const lazyExpression = import(moduleName);
import.meta.resolve('./metadata-only.mjs');
import {
  malformed
from './invalid.mjs';
"""

    result = JavaScriptParser().parse(Path("sample.mjs"), "sample.mjs", source)

    assert result.imports == []


def test_javascript_malformed_import_does_not_absorb_following_declaration() -> None:
    source = """import { orphan }
import { real } from './real.mjs';
"""

    result = JavaScriptParser().parse(Path("sample.mjs"), "sample.mjs", source)

    assert [
        (item.module, item.name, item.alias, item.line) for item in result.imports
    ] == [("./real.mjs", "real", None, 2)]


def test_javascript_detects_static_import_after_same_line_block_boundary() -> None:
    source = """function greet() {} import { join } from 'node:path';
function load() {} import('./dynamic.mjs');
function documented() {} // import { commented } from './commented.mjs';
const note = "} import { quoted } from './quoted.mjs';";
"""

    result = JavaScriptParser().parse(Path("sample.mjs"), "sample.mjs", source)

    assert [
        (
            item.module,
            item.name,
            item.alias,
            item.line,
            item.is_relative,
        )
        for item in result.imports
    ] == [("node:path", "join", None, 1, False)]


def test_javascript_allows_block_comment_trivia_before_static_imports() -> None:
    source = """/* license */ import { x } from './x.mjs';
const a = 1; /* note */ import { x } from './x.mjs';
/* initialization */ import './setup.mjs';
"""

    result = JavaScriptParser().parse(Path("sample.mjs"), "sample.mjs", source)

    assert [
        (
            item.module,
            item.name,
            item.alias,
            item.line,
        )
        for item in result.imports
    ] == [
        ("./x.mjs", "x", None, 1),
        ("./x.mjs", "x", None, 2),
        ("./setup.mjs", None, None, 3),
    ]


def test_javascript_block_comment_trivia_preserves_non_static_exclusions() -> None:
    source = """/* import { blocked } from './blocked.mjs'; */
const note = "/* note */ import { quoted } from './quoted.mjs'";
const lazy = 1; /* note */ import('./dynamic.mjs');
const meta = 1; /* note */ import.meta.resolve('./meta.mjs');
"""

    result = JavaScriptParser().parse(Path("sample.mjs"), "sample.mjs", source)

    assert result.imports == []


def test_javascript_static_import_scan_is_bounded() -> None:
    sources = [
        "import {\n" + ("  repeatedName,\n" * 1_000) + "} from './too-far.mjs';\n",
        "/*" + ("x" * 8_192) + "*/ import { tooFar } from './too-far.mjs';\n",
    ]
    for source in sources:
        result = JavaScriptParser().parse(Path("oversized.mjs"), "oversized.mjs", source)

        assert result.imports == []
