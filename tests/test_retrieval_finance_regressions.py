from __future__ import annotations

from pathlib import Path

from repomind.database import IndexDatabase
from repomind.indexer import Indexer
from repomind.queries import snippets
from repomind.retrieval import ContextRetriever

FIXTURE = Path("tests/fixtures/retrieval_finance_app")


def test_scanner_universe_query_includes_symbols_without_agent_skill_noise() -> None:
    Indexer(FIXTURE).initialize(force=True)

    with IndexDatabase(FIXTURE) as database:
        package = ContextRetriever(database).build_context(
            "Explain how the stock universe is selected or loaded.", 6000, 3
        )

    selected = {item["path"] for item in package["relevant_files"]}
    assert "backend/scanner_engine/engine.py" in selected
    assert "backend/scanner_symbols.py" in selected
    assert not any(path.startswith(".agents/skills/") for path in selected)


def test_conceptual_snippets_fallback_finds_recommendation_label_code() -> None:
    Indexer(FIXTURE).initialize(force=True)

    with IndexDatabase(FIXTURE) as database:
        data = snippets(database, "Bullish Confluence Score recommendation label")

    files = {item["file"] for item in data["snippets"]}
    assert "src/lib/confidence/calculateConfidence.ts" in files
    assert "src/lib/optionChainModel.ts" in files
    assert "src/components/MarketBiasCard.tsx" in files
    assert not any(path.startswith(".agents/skills/") for path in files)


def test_generated_analysis_display_query_follows_react_import_path() -> None:
    Indexer(FIXTURE).initialize(force=True)

    with IndexDatabase(FIXTURE) as database:
        package = ContextRetriever(database).build_context(
            "Find the backend and frontend code involved in displaying a generated analysis result.",
            6000,
            3,
        )

    selected = {item["path"] for item in package["relevant_files"]}
    assert {
        "backend/analysis.py",
        "backend/routes.py",
        "src/hooks.ts",
        "src/lib/apiClient.ts",
        "src/pages/optionchain/useOptionChainModel.ts",
        "src/lib/optionChainModel.ts",
        "src/pages/OptionChain.tsx",
        "src/components/MarketBiasCard.tsx",
    }.issubset(selected)
    assert "src/components/StatusCard.tsx" not in selected
    assert "src/pages/Reports.tsx" not in selected
    assert not any(path.startswith(".agents/skills/") for path in selected)


def test_root_agents_instructions_remain_retrievable() -> None:
    Indexer(FIXTURE).initialize(force=True)

    with IndexDatabase(FIXTURE) as database:
        selected = [
            item.path
            for item in ContextRetriever(database).rank_files(
                "read AGENTS instructions for skill guidance", 10
            )
        ]

    assert "AGENTS.md" in selected
