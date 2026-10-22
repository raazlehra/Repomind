from __future__ import annotations

import codecs
from pathlib import Path

from repomind.parsers import ParserRegistry
from repomind.parsers.fallback import FallbackParser
from repomind.parsers.javascript import JavaScriptParser
from repomind.parsers.python import PythonParser
from repomind.parsers.treesitter import TreeSitterJavaScriptParser


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


def _fixture_result(source: str):
    return TreeSitterJavaScriptParser("javascript").parse(
        Path("test/redstamp-adapter.test.mjs"),
        "test/redstamp-adapter.test.mjs",
        source,
    )


def _fixture_targets(source: str) -> list[str]:
    result = _fixture_result(source)
    return [edge.target for edge in result.edges if edge.kind == "fixture-reference"]


def test_javascript_extracts_source_anchored_static_fixture_references() -> None:
    source = """import { readFileSync as readText } from 'node:fs';
import { dirname as directory, join as combine } from 'node:path';
import { fileURLToPath as pathFromUrl } from 'node:url';
import { readRedstampAudit as readAudit } from '../src/adapters/redstamp.mjs';

const HERE = directory(pathFromUrl(import.meta.url));
const CORPUS = combine(HERE, '..', 'corpus', 'redstamp');
const CHECKPOINT = combine(CORPUS, 'approve-path.checkpoint.json');

readText(CHECKPOINT, 'utf8');
readText(combine(CORPUS, 'approve-path.host-observation.jsonl'), 'utf8');
readAudit(combine(CORPUS, 'approve-path.jsonl'), {});
"""

    result = _fixture_result(source)
    fixtures = [edge for edge in result.edges if edge.kind == "fixture-reference"]

    assert [(edge.target, edge.confidence) for edge in fixtures] == [
        ("corpus/redstamp/approve-path.checkpoint.json", 1.0),
        ("corpus/redstamp/approve-path.host-observation.jsonl", 1.0),
        ("corpus/redstamp/approve-path.jsonl", 0.9),
    ]
    assert all(edge.source_symbol is None for edge in fixtures)



def test_typescript_fixture_references_respect_typed_shadowing() -> None:
    source = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS: string = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
function shadow(readFileSync: (path: string) => unknown): void {
  readFileSync(join(CORPUS, 'fake.jsonl'));
}
readFileSync(join(CORPUS, 'real.jsonl'));
"""

    result = TreeSitterJavaScriptParser("typescript").parse(
        Path("test/fixture.test.ts"), "test/fixture.test.ts", source
    )

    assert [
        (edge.target, edge.confidence)
        for edge in result.edges
        if edge.kind == "fixture-reference"
    ] == [("corpus/real.jsonl", 1.0)]

def test_javascript_fixture_references_require_direct_reader_calls() -> None:
    source = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readRedstampAudit } from '../src/adapters/redstamp.mjs';

const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
const obj = { readFileSync() { return null; }, readRedstampAudit() { return null; } };
obj.readFileSync(join(CORPUS, 'object.jsonl'));
this.readFileSync(join(CORPUS, 'this.jsonl'));
obj?.readFileSync(join(CORPUS, 'optional.jsonl'));
obj.readRedstampAudit(join(CORPUS, 'adapter.jsonl'));
"""

    assert _fixture_targets(source) == []


def test_javascript_fixture_references_mask_regex_character_classes_and_escapes() -> None:
    source = r"""import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
const characterClass = /[/]readFileSync(join(CORPUS, 'class.jsonl'))/;
const escapedDelimiter = /readFileSync\(join\(CORPUS, 'escaped.jsonl'\)\)\/suffix/;
"""

    assert _fixture_targets(source) == []


def test_javascript_fixture_references_reject_unproven_and_malicious_paths() -> None:
    source = r"""import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readRedstampAudit } from '../src/adapters/redstamp.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const CORPUS = join(HERE, '..', 'corpus');
const REASSIGNED = join(CORPUS, 'before.jsonl');
REASSIGNED = join(CORPUS, 'after.jsonl');
const dynamicName = 'dynamic.jsonl';

// readFileSync(join(CORPUS, 'commented.jsonl'), 'utf8');
const note = "readFileSync(join(CORPUS, 'quoted.jsonl'), 'utf8')";
readFileSync('./cwd-relative.jsonl', 'utf8');
readFileSync(join(UNKNOWN, 'unknown.jsonl'), 'utf8');
readFileSync(REASSIGNED, 'utf8');
readFileSync(join(CORPUS, dynamicName), 'utf8');
readFileSync(join(CORPUS, '*.jsonl'), 'utf8');
readFileSync(join(CORPUS, `template.jsonl`), 'utf8');
readFileSync(join(HERE, '..', '..', 'outside.json'), 'utf8');
readFileSync(join(CORPUS, '/absolute.json'), 'utf8');
readFileSync(join(CORPUS, '\\server\share\fixture.jsonl'), 'utf8');
readFileSync(join(CORPUS, 'C:relative.jsonl'), 'utf8');
const corpus = (name) => readFileSync(join(CORPUS, name), 'utf8');
corpus('wrapped.jsonl');
readRedstampAudit(join(CORPUS, unknownFilename), {});
"""

    assert _fixture_targets(source) == []


def test_javascript_fixture_references_reject_shadowed_import_bindings() -> None:
    source = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
function inspect(readFileSync) {
  readFileSync(join(CORPUS, 'function-parameter.jsonl'), 'utf8');
}
const inspectAgain = (join) => {
  readFileSync(join(CORPUS, 'arrow-parameter.jsonl'), 'utf8');
};
"""

    assert _fixture_targets(source) == []


def test_javascript_fixture_references_reject_destructured_reader_bindings() -> None:
    header = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
"""
    sources = [
        header
        + """function run() {
  const { readFileSync } = { readFileSync: () => null };
  readFileSync(join(CORPUS, 'object.jsonl'));
}
""",
        header
        + """function run(source) {
  const { reader: readFileSync } = source;
  readFileSync(join(CORPUS, 'alias.jsonl'));
}
""",
        header
        + """function run() {
  const [readFileSync] = [() => null];
  readFileSync(join(CORPUS, 'array.jsonl'));
}
""",
    ]

    assert [_fixture_targets(source) for source in sources] == [[], [], []]


def test_javascript_binding_detection_preserves_property_keys_and_control_flow() -> None:
    source = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
const { readFileSync: localReader } = { readFileSync: () => null };

if (CORPUS) {
  readFileSync(join(CORPUS, 'if.jsonl'));
}
while (CORPUS) {
  readFileSync(join(CORPUS, 'while.jsonl'));
  break;
}
switch (CORPUS) {
  default:
    readFileSync(join(CORPUS, 'switch.jsonl'));
}
"""

    assert _fixture_targets(source) == [
        "corpus/if.jsonl",
        "corpus/while.jsonl",
        "corpus/switch.jsonl",
    ]


def test_javascript_fixture_scan_rejects_malformed_oversized_and_long_expressions() -> None:
    imports = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
"""
    malformed = (
        imports
        + "const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus';\n"
        + "readFileSync(join(CORPUS, 'malformed.jsonl'), 'utf8');\n"
    )
    valid_prefix = (
        imports
        + "const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');\n"
        + "readFileSync(join(CORPUS, 'early.jsonl'), 'utf8');\n"
    )
    long_expression = (
        imports
        + "const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');\n"
        + "readFileSync(join(CORPUS, '"
        + ("x" * 8_300)
        + ".jsonl'), 'utf8');\n"
    )

    malformed_result = _fixture_result(malformed)
    assert any(item.module == "node:fs" for item in malformed_result.imports)
    assert not any(
        edge.kind == "fixture-reference" for edge in malformed_result.edges
    )
    assert _fixture_targets(valid_prefix + (" " * 256_001)) == []
    assert _fixture_targets(long_expression) == []


def test_javascript_fixture_edges_are_bounded_deduplicated_and_deterministic() -> None:
    header = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
"""
    calls = "\n".join(
        f"readFileSync(join(CORPUS, 'fixture-{index:03}.jsonl'), 'utf8');"
        for index in range(12)
    )
    source = header + calls + "\n" + calls

    first = _fixture_targets(source)
    second = _fixture_targets(source)

    assert first == second
    assert first == [f"corpus/fixture-{index:03}.jsonl" for index in range(12)]

    over_budget = header + "\n".join(
        f"readFileSync(join(CORPUS, 'fixture-{index:03}.jsonl'), 'utf8');"
        for index in range(257)
    )
    assert _fixture_targets(over_budget) == []
def test_javascript_fixture_references_reject_comma_separated_destructuring() -> None:
    header = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
"""
    sources = [
        header
        + """function run(source) {
  const marker = 1, { readFileSync } = source;
  readFileSync(join(CORPUS, 'object.jsonl'));
}
""",
        header
        + """function run(source) {
  const marker = 1, [readFileSync] = source;
  readFileSync(join(CORPUS, 'array.jsonl'));
}
""",
        header
        + """function run(source) {
  const marker = 1, { reader: readFileSync } = source;
  readFileSync(join(CORPUS, 'alias.jsonl'));
}
""",
    ]

    assert [_fixture_targets(source) for source in sources] == [[], [], []]


def test_javascript_fixture_references_preserve_named_anonymous_and_arrow_scopes() -> None:
    source = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');

function named() {
  if (CORPUS) readFileSync(join(CORPUS, 'named.jsonl'));
}
const anonymous = function () {
  while (CORPUS) {
    readFileSync(join(CORPUS, 'anonymous.jsonl'));
    break;
  }
};
const arrow = () => {
  switch (CORPUS) {
    default:
      readFileSync(join(CORPUS, 'arrow.jsonl'));
  }
};
"""

    assert _fixture_targets(source) == [
        "corpus/named.jsonl",
        "corpus/anonymous.jsonl",
        "corpus/arrow.jsonl",
    ]



def test_javascript_fixture_references_respect_class_and_method_name_scopes() -> None:
    source = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');

const Holder = class readFileSync {
  run() {
    readFileSync(join(CORPUS, 'class-fake.jsonl'));
  }
};
const object = {
  readFileSync() {
    readFileSync(join(CORPUS, 'method-real.jsonl'));
  }
};
"""

    assert _fixture_targets(source) == ["corpus/method-real.jsonl"]

def test_javascript_fixture_references_respect_block_function_and_catch_shadowing() -> None:
    source = """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');

readFileSync(join(CORPUS, 'outside.jsonl'));
{
  const readFileSync = () => null;
  readFileSync(join(CORPUS, 'block-fake.jsonl'));
}
function nested(readFileSync) {
  readFileSync(join(CORPUS, 'function-fake.jsonl'));
}
try {
  throw {};
} catch ({ readFileSync }) {
  readFileSync(join(CORPUS, 'catch-fake.jsonl'));
}
"""

    assert _fixture_targets(source) == ["corpus/outside.jsonl"]


def test_javascript_lexical_fallback_emits_no_fixture_references(
    tmp_path: Path, monkeypatch
) -> None:
    import repomind.parsers.treesitter as treesitter_module

    original_import = treesitter_module.importlib.import_module

    def unavailable(name: str):
        if name.startswith("tree_sitter"):
            raise ImportError(name)
        return original_import(name)

    monkeypatch.setattr(treesitter_module.importlib, "import_module", unavailable)
    registry = ParserRegistry()
    path = tmp_path / "fixture.test.mjs"
    path.write_text(
        """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
readFileSync(join(CORPUS, 'fixture.jsonl'));
""",
        encoding="utf-8",
    )

    result = registry.parse(path, "fixture.test.mjs", "javascript")

    assert "javascript" not in registry.tree_sitter_languages
    assert any(item.module == "node:fs" for item in result.imports)
    assert not any(edge.kind == "fixture-reference" for edge in result.edges)


def test_javascript_fixture_ast_budget_and_failure_are_isolated(
    tmp_path: Path, monkeypatch
) -> None:
    import repomind.parsers.javascript_fixtures as fixture_module
    import repomind.parsers.treesitter as treesitter_module

    path = tmp_path / "fixture.test.mjs"
    path.write_text(
        """import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const CORPUS = join(dirname(fileURLToPath(import.meta.url)), '..', 'corpus');
readFileSync(join(CORPUS, 'fixture.jsonl'));
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(fixture_module, "MAX_FIXTURE_AST_NODES", 10)
    result = ParserRegistry().parse(path, "fixture.test.mjs", "javascript")
    assert any(item.module == "node:fs" for item in result.imports)
    assert not any(edge.kind == "fixture-reference" for edge in result.edges)

    monkeypatch.setattr(
        treesitter_module,
        "extract_fixture_references",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("isolated")),
    )
    result = ParserRegistry().parse(path, "fixture.test.mjs", "javascript")
    assert any(item.module == "node:fs" for item in result.imports)
    assert not any(edge.kind == "fixture-reference" for edge in result.edges)
