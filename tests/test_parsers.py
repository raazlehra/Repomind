from __future__ import annotations

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
