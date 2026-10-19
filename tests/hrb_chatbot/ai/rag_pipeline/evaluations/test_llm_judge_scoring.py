"""Tests for Phase 62's LLM-as-judge groundedness/completeness scoring -
course's own "Score: X" parse logic, verified with this project's existing
fake-client pattern (no network, no real cost)."""

import pytest

from src.hrb_chatbot.ai.rag_pipeline.evaluations import golden_dataset_harness
from tests.conftest import FakeChatClient, FakeClientGateway


def test_groundedness_parses_a_high_score_as_grounded(monkeypatch):
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="Score: 9\nReasoning: fully supported."))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_groundedness("The plan matches 100%.", ["401k plan matches 100%."])

    assert result["score"] == 0.9
    assert result["verdict"] == "GROUNDED"
    assert result["model_used"] == "fake-chat-model"  # Phase 215 - the client's own default, no override given


def test_groundedness_judge_model_override_is_passed_through_and_echoed_back(monkeypatch):
    fake_chat_client = FakeChatClient(model="fake-chat-model", answer="Score: 9\nReasoning: fully supported.")
    fake_gateway = FakeClientGateway(chat_client=fake_chat_client)
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_groundedness(
        "The plan matches 100%.", ["401k plan matches 100%."], judge_model="gpt-4.1-mini"
    )

    assert result["model_used"] == "gpt-4.1-mini"
    assert fake_chat_client.calls[0]["model_name_override"] == "gpt-4.1-mini"


def test_groundedness_parses_a_low_score_as_hallucinated(monkeypatch):
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="Score: 2\nReasoning: not in context."))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_groundedness("Unrelated claim.", ["401k plan matches 100%."])

    assert result["score"] == 0.2
    assert result["verdict"] == "HALLUCINATED"


def test_groundedness_falls_back_to_half_score_on_unparseable_output(monkeypatch):
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="I refuse to answer in the expected format."))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_groundedness("Some answer.", ["Some context."])

    assert result["score"] == 0.5
    assert result["verdict"] == "PARTIAL"


def test_completeness_without_reference_answer_still_scores(monkeypatch):
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="Score: 8\nReasoning: covers the question."))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_completeness("What is the match?", "100% up to 5%.", reference_answer=None)

    assert result["score"] == 0.8
    assert result["verdict"] == "COMPLETE"
    call = fake_gateway.openai_chat().calls[0]
    assert "REFERENCE ANSWER" not in call["question"]


def test_completeness_with_reference_answer_includes_it_in_the_prompt(monkeypatch):
    fake_gateway = FakeClientGateway(chat_client=FakeChatClient(answer="Score: 4\nReasoning: missing detail."))
    monkeypatch.setattr(golden_dataset_harness, "get_client_gateway", lambda: fake_gateway)

    result = golden_dataset_harness.evaluate_completeness(
        "What is the match?", "100%.", reference_answer="100% up to 5% of compensation."
    )

    assert result["score"] == 0.4
    assert result["verdict"] == "PARTIAL"
    call = fake_gateway.openai_chat().calls[0]
    assert "REFERENCE ANSWER" in call["question"]
    assert "100% up to 5% of compensation." in call["question"]


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
