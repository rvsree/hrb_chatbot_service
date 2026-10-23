"""Tests for dynamic_strategy_selector.py (Phase 252) - pure heuristic, no
I/O, so no fakes needed."""

from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.dynamic_strategy_selector import (
    DynamicStrategySelector,
    resolve_dynamic_strategy,
)


def test_short_acronym_heavy_query_resolves_to_keyword():
    assert DynamicStrategySelector().select("401k FMLA") == "keyword"


def test_long_query_with_an_acronym_resolves_to_hybrid():
    query = "Can you explain how the FMLA leave process works for new hires joining this quarter"
    assert DynamicStrategySelector().select(query) == "hybrid"


def test_broad_overview_query_resolves_to_mmr():
    assert DynamicStrategySelector().select("Tell me about my benefits options") == "mmr"


def test_plain_natural_language_query_resolves_to_similarity():
    assert DynamicStrategySelector().select("How many vacation days do I get this year") == "similarity"


def test_module_level_wrapper_matches_the_class():
    query = "What is COBRA"
    assert resolve_dynamic_strategy(query) == DynamicStrategySelector().select(query)


def test_never_returns_knn_or_dynamic_itself():
    queries = [
        "401k",
        "Tell me about everything about my 401k and FMLA options",
        "How do I request unpaid leave for a family emergency situation",
        "",
    ]
    for query in queries:
        result = resolve_dynamic_strategy(query)
        assert result not in ("knn", "dynamic")
