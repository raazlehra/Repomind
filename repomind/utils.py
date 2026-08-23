from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from pathlib import Path

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.blake2b(digest_size=20)
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def tokenize(value: str) -> set[str]:
    parts: set[str] = set()
    for raw in _TOKEN_RE.findall(value):
        lowered_raw = raw.lower()
        if len(lowered_raw) > 1:
            parts.add(lowered_raw)
        for piece in _CAMEL_RE.sub(" ", raw).replace("_", " ").split():
            lowered = piece.lower()
            if len(lowered) > 1:
                parts.add(lowered)
    return parts


def approximate_tokens(text: str) -> int:
    """Conservative local approximation; no tokenizer/API dependency."""
    if not text:
        return 0
    words = len(re.findall(r"\S+", text))
    return max((len(text) + 3) // 4, int(words * 1.3))


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output
