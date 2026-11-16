"""Bounded Go header/manifest extraction. No Go toolchain or repository code runs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repomind.models import EdgeCandidate, ImportRecord, ParseResult, Symbol

GO_REVISION = "Go v1 "
MAX_GO_SOURCE = 256_000
MAX_GO_TOKENS = 40_000
MAX_GO_IMPORTS = 256
MAX_GO_DIRECTIVES = 1_024
MAX_GO_DEPTH = 128
_TOKEN = re.compile(
    r"(?P<space>[^\S\n]+)|(?P<newline>\n)|(?P<comment>//[^\n]*|/\*.*?\*/)"  # comments first
    r'|(?P<string>"(?:\\[^\n]|[^"\\\n])*"|`[^`]*`|\'(?:\\[^\n]|[^\'\\\n])*\')'
    r"|(?P<word>[^\W\d]\w*|[0-9][\w.]*)|(?P<punct>.)",
    re.DOTALL,
)
_IDENTIFIER = re.compile(r"[^\W\d]\w*\Z")
_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~+/-]*\Z")
_KEYWORDS = frozenset(
    {
        "break",
        "case",
        "chan",
        "const",
        "continue",
        "default",
        "defer",
        "else",
        "fallthrough",
        "for",
        "func",
        "go",
        "goto",
        "if",
        "import",
        "interface",
        "map",
        "package",
        "range",
        "return",
        "select",
        "struct",
        "switch",
        "type",
        "var",
    }
)
_PLATFORMS = frozenset(
    [
        "aix",
        "android",
        "darwin",
        "dragonfly",
        "freebsd",
        "hurd",
        "illumos",
        "ios",
        "js",
        "linux",
        "nacl",
        "netbsd",
        "openbsd",
        "plan9",
        "solaris",
        "wasip1",
        "windows",
        "386",
        "amd64",
        "amd64p32",
        "arm",
        "arm64",
        "loong64",
        "mips",
        "mips64",
        "mips64le",
        "mipsle",
        "ppc",
        "ppc64",
        "ppc64le",
        "riscv64",
        "s390",
        "s390x",
        "sparc",
        "sparc64",
        "wasm",
    ]
)


class GoUnsupported(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    text: str
    line: int
    offset: int


def tokens(source: str) -> list[Token]:
    source = source.removeprefix("\ufeff")
    if len(source.encode("utf-8")) > MAX_GO_SOURCE:
        raise GoUnsupported("Go source byte budget exceeded")
    result: list[Token] = []
    line = 1
    for match in _TOKEN.finditer(source):
        kind, text = str(match.lastgroup), match.group()
        if kind == "punct" and (text in {'"', "'", "`"} or source.startswith("/*", match.start())):
            raise GoUnsupported("Unterminated Go literal or comment")
        if kind == "comment":
            if "\n" in text:
                result.append(Token("newline", "\n", line, match.start()))
        elif kind != "space":
            result.append(Token(kind, text, line, match.start()))
        line += text.count("\n")
        if len(result) > MAX_GO_TOKENS:
            raise GoUnsupported("Go token budget exceeded")
    return result


def import_path(value: str) -> bool:
    return bool(_PATH.fullmatch(value)) and all(
        part not in {"", ".", ".."} for part in value.split("/")
    )


def _string(token: Token) -> str:
    if token.kind != "string" or token.text[0] not in {'"', "`"}:
        raise GoUnsupported("Expected Go string literal")
    value = token.text[1:-1]
    if "\\" in value or any(ord(c) < 32 for c in value) or len(value) > 1_000:
        raise GoUnsupported("Escaped or oversized Go path is unsupported")
    return value


def _edge(kind: str, target: str, line: int, evidence: str) -> EdgeCandidate:
    return EdgeCandidate(f"go-{kind}", None, target, line, 1.0, evidence)


def is_go_path(path: str) -> bool:
    return path.lower().endswith(".go") or PurePosixPath(path).name in {"go.mod", "go.work"}


class GoParser:
    languages = frozenset({"go"})

    def parse(self, path: Path, relative_path: str, source: str) -> ParseResult:
        try:
            return self._parse(relative_path, source)
        except GoUnsupported as exc:
            return ParseResult(summary=GO_REVISION + "unsupported", parse_error=str(exc))

    def _parse(self, relative_path: str, source: str) -> ParseResult:
        source = source.removeprefix("\ufeff")
        items = tokens(source)
        code = [t for t in items if t.kind != "newline" and t.text != ";"]
        positions = {id(t): i for i, t in enumerate(code)}
        if (
            len(code) < 2
            or code[0].text != "package"
            or not _IDENTIFIER.fullmatch(code[1].text)
            or code[1].text == "_"
            or code[1].text in _KEYWORDS
        ):
            raise GoUnsupported("Missing or invalid Go package clause")
        package = code[1].text
        # A package clause must terminate before imports/declarations.
        start = next(i for i, t in enumerate(items) if t.text == "package")
        index = start + 2
        if index < len(items) and items[index].text not in {"\n", ";"}:
            raise GoUnsupported("Unterminated Go package clause")
        result = ParseResult(summary=f"{GO_REVISION}package {package}")
        result.edges.append(_edge("package", package, code[0].line, "Go package clause"))
        filename = PurePosixPath(relative_path).stem.removesuffix("_test")
        if (
            re.search(r"(?m)^\s*//\s*(?:go:build|\+build)\b", source)
            or filename.rsplit("_", 1)[-1] in _PLATFORMS
        ):
            result.edges.append(
                _edge(
                    "limitation",
                    "build-constraints",
                    1,
                    "Build/OS/architecture selection is unknown",
                )
            )
        if re.search(r"(?m)^// Code generated .* DO NOT EDIT\.", source):
            result.edges.append(
                _edge("limitation", "generated-source", 1, "Generated Go source is not qualified")
            )
        stack: list[str] = []
        declarations = False
        pairs = {")": "(", "]": "[", "}": "{"}
        while index < len(items):
            token = items[index]
            if token.text == "import" and not stack:
                if declarations:
                    raise GoUnsupported("Go import after declarations")
                index = self._imports(items, index + 1, result)
                continue
            if token.text == "package" and not stack:
                raise GoUnsupported("Multiple Go package clauses")
            if not stack and token.text in {"func", "type", "var", "const"}:
                declarations = True
                self._symbol(code, positions[id(token)], package, source, result)
                if len(result.symbols) > MAX_GO_DIRECTIVES:
                    raise GoUnsupported("Go declaration budget exceeded")
            if token.kind == "punct":
                if token.text in {"(", "[", "{"}:
                    stack.append(token.text)
                    if len(stack) > MAX_GO_DEPTH:
                        raise GoUnsupported("Go delimiter depth exceeded")
                elif token.text in pairs and (not stack or stack.pop() != pairs[token.text]):
                    raise GoUnsupported("Unbalanced Go delimiters")
            index += 1
        if stack:
            raise GoUnsupported("Unbalanced Go delimiters")
        return result

    @staticmethod
    def _symbol(code: list[Token], position: int, package: str, source: str, result: ParseResult) -> None:
        # Preserve useful declarations without claiming a Go call graph or type checker.
        token = code[position]
        index = position + 1
        receiver = ""
        if token.text == "func" and index < len(code) and code[index].text == "(":
            end = index + 1
            while end < len(code) and code[end].text != ")":
                end += 1
            receiver = ".".join(
                t.text for t in code[index + 1 : end] if _IDENTIFIER.fullmatch(t.text)
            )
            index = end + 1
        if index >= len(code) or not _IDENTIFIER.fullmatch(code[index].text):
            return
        name = code[index].text
        kind = "function" if token.text == "func" else token.text
        qualified = ".".join(filter(None, (package, receiver, name)))
        # Keep useful parameters/return types from the old fallback, bounded and
        # stopped before the body. This is a display header, not type validation.
        header = f"{token.text} {name}"
        if token.text == "func":
            header = source[token.offset:token.offset + 512].split("{", 1)[0].strip()
            header = re.split(r"\n\s*(?:func|type|var|const)\s", header, maxsplit=1)[0].strip()
        result.symbols.append(
            Symbol(
                name,
                qualified,
                kind,
                header,
                token.line,
                token.line,
                name[0].isupper(),
            )
        )

    @staticmethod
    def _imports(items: list[Token], index: int, result: ParseResult) -> int:
        grouped = index < len(items) and items[index].text == "("
        if grouped:
            index += 1
        while index < len(items):
            if grouped and items[index].text in {"\n", ";"}:
                index += 1
                continue
            if grouped and items[index].text == ")":
                return index + 1
            alias = None
            if items[index].kind != "string":
                alias = items[index].text
                if alias != "." and (not _IDENTIFIER.fullmatch(alias) or alias in _KEYWORDS):
                    raise GoUnsupported("Invalid Go import alias")
                index += 1
            if index >= len(items):
                raise GoUnsupported("Incomplete Go import")
            value = _string(items[index])
            if not import_path(value):
                raise GoUnsupported("Invalid Go import path")
            result.imports.append(ImportRecord(value, None, alias, items[index].line))
            if value == "C" or alias == ".":
                result.edges.append(
                    _edge(
                        "limitation",
                        "cgo" if value == "C" else "dot-import",
                        items[index].line,
                        "Go import requires unqualified semantics",
                    )
                )
            if len(result.imports) > MAX_GO_IMPORTS:
                raise GoUnsupported("Go import budget exceeded")
            index += 1
            if index < len(items) and items[index].text not in {"\n", ";", ")"}:
                raise GoUnsupported("Unterminated Go import")
            if not grouped:
                return index
        if grouped:
            raise GoUnsupported("Unterminated Go import block")
        return index


class GoManifestParser:
    languages: frozenset[str] = frozenset()

    def parse(self, path: Path, relative_path: str, source: str) -> ParseResult:
        try:
            return self._parse(path.name, source)
        except GoUnsupported as exc:
            return ParseResult(summary=GO_REVISION + "unsupported manifest", parse_error=str(exc))

    @staticmethod
    def _parse(name: str, source: str) -> ParseResult:
        # Manifest tokens differ from Go source: module paths and => are words.
        if len(source.encode("utf-8")) > MAX_GO_SOURCE:
            raise GoUnsupported("Go manifest byte budget exceeded")
        if "/*" in source or "`" in source or "\\" in source:
            raise GoUnsupported("Unsupported Go manifest syntax")
        result = ParseResult(summary=GO_REVISION + name)
        block: str | None = None
        directives = 0
        seen_single: set[str] = set()
        seen_require: set[str] = set()
        for number, line in enumerate(source.splitlines(), 1):
            # Only // comments are part of the Go module file grammar.
            values = re.findall(r'"[^"\n]*"|[^\s]+', line.split("//", 1)[0])
            if not values:
                continue
            if any(
                '"' in value
                and not (value.startswith('"') and value.endswith('"') and value.count('"') == 2)
                for value in values
            ):
                raise GoUnsupported("Malformed Go manifest string")
            values = [v[1:-1] if v.startswith('"') else v for v in values]
            if values == [")"] and block:
                block = None
                continue
            if block:
                directive, args = block, values
            else:
                directive, args = values[0], values[1:]
                if args == ["("] and directive in {
                    "require",
                    "replace",
                    "exclude",
                    "retract",
                    "use",
                }:
                    block = directive
                    continue
            directives += 1
            if directives > MAX_GO_DIRECTIVES:
                raise GoUnsupported("Go manifest directive budget exceeded")
            allowed = (
                {"go", "toolchain", "godebug", "use", "replace"}
                if name == "go.work"
                else {
                    "module",
                    "go",
                    "toolchain",
                    "godebug",
                    "require",
                    "replace",
                    "exclude",
                    "retract",
                    "tool",
                    "ignore",
                }
            )
            if directive not in allowed or not args:
                raise GoUnsupported("Unknown or incomplete Go manifest directive")
            if directive in {"module", "go", "toolchain"}:
                if directive in seen_single or len(args) != 1:
                    raise GoUnsupported("Duplicate or invalid Go manifest directive")
                seen_single.add(directive)
            if directive == "go" and not re.fullmatch(r"[1-9]\d*\.\d+(?:\.\d+)?", args[0]):
                raise GoUnsupported("Invalid Go version directive")
            if directive == "toolchain" and not re.fullmatch(
                r"default|go[1-9]\d*\.\d+(?:\.\d+)?(?:(?:beta|rc)\d+)?", args[0]
            ):
                raise GoUnsupported("Unqualified Go toolchain directive")
            if directive in {"exclude", "retract", "tool", "ignore", "godebug"}:
                raise GoUnsupported("Go manifest directive semantics are not qualified")
            if directive == "module":
                if not import_path(args[0]):
                    raise GoUnsupported("Invalid Go module path")
                result.edges.append(_edge("module", args[0], number, "Go module directive"))
            elif directive == "use":
                if len(args) != 1:
                    raise GoUnsupported("Invalid Go workspace use")
                result.edges.append(_edge("use", args[0], number, "Go workspace use directive"))
            elif directive == "require":
                if (
                    len(args) != 2
                    or not import_path(args[0])
                    or not re.fullmatch(
                        r"v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?(?:\+[A-Za-z0-9.-]+)?", args[1]
                    )
                    or args[0] in seen_require
                ):
                    raise GoUnsupported("Invalid Go module requirement")
                seen_require.add(args[0])
                result.edges.append(_edge("require", args[0], number, args[1]))
            elif directive == "replace":
                if "=>" not in args:
                    raise GoUnsupported("Invalid Go replacement")
                split = args.index("=>")
                old, new = args[:split], args[split + 1 :]
                if len(old) not in {1, 2} or len(new) not in {1, 2} or not import_path(old[0]):
                    raise GoUnsupported("Invalid Go replacement")
                data = {
                    "old_version": old[1] if len(old) == 2 else "",
                    "target": new[0],
                    "version": new[1] if len(new) == 2 else "",
                }
                result.edges.append(
                    _edge("replace", old[0], number, json.dumps(data, sort_keys=True))
                )
        if (
            block
            or (name == "go.mod" and "module" not in seen_single)
            or (name == "go.work" and "go" not in seen_single)
        ):
            raise GoUnsupported("Incomplete Go manifest")
        return result
