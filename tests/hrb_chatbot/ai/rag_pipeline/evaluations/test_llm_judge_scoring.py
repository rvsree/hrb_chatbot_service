"""Tests for evaluate_retrieval_relevance() - the live per-query retrieval
judge, hand-rolled on purpose, untouched by Phase 249's DeepEval swap (see
RAG-ROADMAP.md's Phase 249 entry for why: it's a different, still-unmatched
methodology, not a drop-in). groundedness/completeness's own tests moved to
test_golden_dataset_harness_judges.py - Phase 249 replaced their "Score: X"
hand-rolled-prompt internals with DeepEval, so those tests no longer applied
to anything real."""

import pytest

from src.hrb_chatbot.ai.rag_pipeline.evaluations import golden_dataset_harness
from tests.conftest import FakeChatClient, FakeClientGateway


def test_retrieval_relevance_parses_which_chunks_were_marked_relevant(monkeypatch):
    fake_gateway = FakeClientGateway(
        chat_client=FakeChatClient(answer="Relevant: 1, 3\nReasoning: chunks 1 and 3 cover the match percentage.")
    )
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_retrieval_relevance(
        "What is the 401k match?", ["chunk about matching", "chunk about tuition", "chunk about vesting"]
    )

    assert result["relevant_chunk_indices"] == [1, 3]
    assert result["precision"] == 2 / 3


def test_retrieval_relevance_handles_none_relevant(monkeypatch):
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="Relevant: none\nReasoning: nothing matches."))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_retrieval_relevance("Unrelated question", ["chunk one", "chunk two"])

    assert result["relevant_chunk_indices"] == []
    assert result["precision"] == 0.0


def test_retrieval_relevance_returns_none_precision_for_no_chunks(monkeypatch):
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="Relevant: none"))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_retrieval_relevance("Any question", [])

    assert result["precision"] is None
    assert result["relevant_chunk_indices"] == []


def test_retrieval_relevance_clamps_a_hallucinated_out_of_range_index(monkeypatch):
    """A real bug caught live: the judge is free text, not constrained output -
    it can name a chunk number that doesn't exist (or repeat one), which made
    precision come back as 2.0 (mathematically impossible) before this fix."""
    fake_gateway = FakeClientGateway(
        chat_client=FakeChatClient(answer="Relevant: 1, 3, 2, 5\nReasoning: judge hallucinated chunks 3 and 5.")
    )
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_retrieval_relevance("What is the 401k match?", ["chunk one", "chunk two"])

    assert result["relevant_chunk_indices"] == [1, 2]
    assert result["precision"] == 1.0


def test_retrieval_relevance_dedupes_a_repeated_index(monkeypatch):
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="Relevant: 1, 1, 1\nReasoning: repeated."))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_retrieval_relevance("Question", ["chunk one", "chunk two", "chunk three"])

    assert result["relevant_chunk_indices"] == [1]
    assert result["precision"] == pytest.approx(1 / 3)


# Phase 219 - live recall/F1 estimate, judged against a wider pool (the
# originally-retrieved chunks, positions 1..len(chunk_texts), plus extra
# exact-KNN candidates beyond them).


def test_recall_estimate_computed_against_the_wider_pool_not_just_original_chunks(monkeypatch):
    fake_gateway = FakeClientGateway(
        chat_client=FakeChatClient(answer="Relevant: 1, 2, 4\nReasoning: 1 and 2 answer it directly, 4 is related.")
    )
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)
    original = ["chunk about matching", "chunk about vesting"]
    wider_pool = original + ["unrelated chunk", "another relevant chunk found only via exact-KNN"]

    result = golden_dataset_harness.evaluate_retrieval_relevance(
        "What is the 401k match?", original, wider_pool_texts=wider_pool
    )

    # Precision stays scoped to the original 2 chunks (both judged relevant).
    assert result["precision"] == 1.0
    assert result["relevant_chunk_indices"] == [1, 2]
    # Recall estimate: 2 of the original chunks relevant, out of 3 relevant total in the pool.
    assert result["recall_estimate"] == pytest.approx(2 / 3)
    assert result["f1_estimate"] == pytest.approx(2 * 1.0 * (2 / 3) / (1.0 + 2 / 3))
    assert result["pool_size"] == 4
    # Phase 225 - the real denominator behind recall_estimate (2/3 above),
    # previously computed but never returned.
    assert result["relevant_pool_count"] == 3


def test_recall_estimate_is_none_when_no_wider_pool_given(monkeypatch):
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="Relevant: 1\nReasoning: direct match."))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_retrieval_relevance("Question", ["chunk one"])

    assert result["precision"] == 1.0
    assert result["recall_estimate"] is None
    assert result["f1_estimate"] is None
    assert result["pool_size"] is None
    assert result["relevant_pool_count"] is None


def test_recall_estimate_is_none_not_fabricated_as_zero_when_pool_has_no_relevant_chunks(monkeypatch):
    """Nothing in the whole wider pool was judged relevant - recall is
    undefined (0 relevant found / 0 relevant total), not fabricated as 0.0
    or 1.0 - same "never fabricate" ethic the function's own docstring
    already holds for true recall."""
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="Relevant: none\nReasoning: nothing matches."))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_retrieval_relevance(
        "Unrelated question", ["chunk one"], wider_pool_texts=["chunk one", "chunk two"]
    )

    assert result["precision"] == 0.0
    assert result["recall_estimate"] is None
    assert result["f1_estimate"] is None
    assert result["pool_size"] == 2
    # relevant_pool_count stays None too (undefined, same "never fabricate"
    # reasoning) - nothing in the pool was judged relevant at all.
    assert result["relevant_pool_count"] is None
