"""Index and run quick retrieval checks on real repositories.

Usage: python -m tools.evaluate_real_repos
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.retrieval import ContextRetriever


def run_for_repo(root: Path, query: str):
    print("Indexing:", root)
    idx = Indexer(root)
    idx.initialize(force=True)
    results = []
    with IndexDatabase(root) as db:
        retriever = ContextRetriever(db)
        for budget in (500, 1000, 2000):
            for level in (1, 2, 3):
                s = time.time()
                pkg = retriever.build_context(query, budget, level)
                selected = [f["path"] for f in pkg.get("relevant_files", [])]
                results.append({"budget": budget, "level": level, "selected": selected, "elapsed_ms": int((time.time()-s)*1000)})
    print(json.dumps({"repo": str(root), "query": query, "results": results}, indent=2))


def main():
    base = Path("benchmarks/real_repos")
    targets = [
        (base / "starlette", "add websocket endpoint"),
        (base / "fastapi", "fix authentication refresh token"),
        (base / "pydantic", "change model validation"),
    ]
    for root, query in targets:
        if not root.exists():
            print("Skipping missing repo:", root)
            continue
        try:
            run_for_repo(root, query)
        except Exception as exc:
            print("Error evaluating", root, exc)


if __name__ == "__main__":
    main()
