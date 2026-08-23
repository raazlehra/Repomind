from __future__ import annotations

from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.retrieval import ContextRetriever


def test_agent_style_progressive_workflow(tmp_path: Path) -> None:
    repo = Path("tests/fixtures/realistic_c_fullstack")
    idx = Indexer(repo)
    idx.initialize(force=True)

    # Step 2: RepoMind generates Level 1 context for the task
    with IndexDatabase(repo) as db:
        retriever = ContextRetriever(db)
        l1 = retriever.build_context("Change dashboard API response", 500, 1)
        selected_l1 = [f["path"] for f in l1.get("relevant_files", [])]
        assert "frontend/src/apiClient.ts" in selected_l1

    # Agent inspects files and decides deeper context needed -> request L3
    with IndexDatabase(repo) as db:
        retriever = ContextRetriever(db)
        l3 = retriever.build_context("Change dashboard API response", 2000, 3)
        selected_l3 = [f["path"] for f in l3.get("relevant_files", [])]
        # L3 should include backend pieces in our fixture
        assert "backend/services.py" in selected_l3

    # Agent modifies backend model (simulated): add new field to backend/models.py
    models = repo / "backend" / "models.py"
    text = models.read_text()
    models.write_text(text + "\n# agent change: add field 'new_flag'\n")

    # RepoMind refreshes incrementally
    changes = idx.refresh()
    assert changes.changes.total >= 1

    # Agent requests impact info: rebuild L3 and ensure modified file is present
    with IndexDatabase(repo) as db:
        retriever = ContextRetriever(db)
        l3b = retriever.build_context("Change dashboard API response", 2000, 3)
        selected_l3b = [f["path"] for f in l3b.get("relevant_files", [])]
        assert "backend/models.py" in selected_l3b
