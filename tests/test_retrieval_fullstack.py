from __future__ import annotations

from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.retrieval import ContextRetriever


def test_fullstack_dashboard_api_selection(tmp_path: Path) -> None:
    # Use the deterministic fixture in tests/fixtures
    repo = Path("tests/fixtures/realistic_c_fullstack")
    # Initialize index (force to ensure fresh DB)
    idx = Indexer(repo)
    idx.initialize(force=True)

    with IndexDatabase(repo) as db:
        retriever = ContextRetriever(db)
        query = "Change dashboard API response"
        target = "frontend/src/apiClient.ts"
        for budget in (500, 1000, 2000, 5000):
            for level in (1, 2, 3):
                package = retriever.build_context(query, budget, level)
                selected = [f["path"] for f in package.get("relevant_files", [])]
                assert target in selected, f"Expected {target} in selected files for budget={budget}, level={level}"
