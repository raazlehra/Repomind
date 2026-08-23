from __future__ import annotations

from pathlib import Path

from repomind.models import ParseResult
from repomind.parsers.base import StructuralParser
from repomind.parsers.fallback import FallbackParser, PlainTextParser
from repomind.parsers.javascript import JavaScriptParser
from repomind.parsers.python import PythonParser
from repomind.parsers.treesitter import TreeSitterJavaScriptParser


class ParserRegistry:
    def __init__(self) -> None:
        parsers: list[StructuralParser] = [
            PythonParser(),
            JavaScriptParser(),
            FallbackParser(),
            PlainTextParser(),
        ]
        self._by_language: dict[str, StructuralParser] = {}
        self.backend_by_language: dict[str, str] = {}
        for parser in parsers:
            for language in parser.languages:
                self._by_language[language] = parser
                self.backend_by_language[language] = type(parser).__name__
        for language in ("javascript", "jsx", "typescript", "tsx"):
            try:
                parser = TreeSitterJavaScriptParser(language)
            except (ImportError, AttributeError, TypeError, ValueError):
                continue
            self._by_language[language] = parser
            self.backend_by_language[language] = type(parser).__name__
        self._plain = PlainTextParser()

    @property
    def supported_languages(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_language))

    @property
    def tree_sitter_languages(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                language
                for language, backend in self.backend_by_language.items()
                if backend == "TreeSitterJavaScriptParser"
            )
        )

    def parse(self, path: Path, relative_path: str, language: str) -> ParseResult:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ParseResult(parse_error=f"Unable to read: {exc}")
        parser = self._by_language.get(language, self._plain)
        return parser.parse(path, relative_path, source)


__all__ = ["ParserRegistry", "StructuralParser"]
