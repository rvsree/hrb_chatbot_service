"""Tests for rerank_chunks() (Phase 279) - the LLM reorders chunks by
relevance to the query before generation, one call for the whole batch.
retrieve_chunks/the vector store itself are never involved here - this
only tests the reorder/fail-safe logic against a fake chat client."""

import pytest

from src.hrb_chatbot.ai.rag_pipeline.query_retrieval import reranker
from tests.conftest import FakeChatClient, FakeClientGateway


def _chunks(*texts: str) -> list[dict]:
    return [{"filename": "x.pdf", "chunk_index": i, "text": text} for i, text in enumerate(texts)]


async def test_reorders_chunks_by_the_llm_s_ranked_order(monkeypatch):
    fake_client = FakeChatClient(answer="Ranked: 3, 1, 2")
    monkeypatch.setattr(reranker, "get_client_gateway", lambda: FakeClientGateway(chat_client=fake_client))

    chunks = _chunks("first", "second", "third")
    result = await reranker.rerank_chunks("a question", chunks)

    assert [c["text"] for c in result] == ["third", "first", "second"]


async def test_omitted_chunk_numbers_are_appended_not_dropped(monkeypatch):
    """The LLM's own response only mentioned chunk 2 - chunks 1 and 3 must
    still appear in the output, in their original relative order, not
    silently disappear."""
    fake_client = FakeChatClient(answer="Ranked: 2")
    monkeypatch.setattr(reranker, "get_client_gateway", lambda: FakeClientGateway(chat_client=fake_client))

    chunks = _chunks("first", "second", "third")
    result = await reranker.rerank_chunks("a question", chunks)

    assert [c["text"] for c in result] == ["second", "first", "third"]
    assert len(result) == 3


async def test_hallucinated_duplicate_and_out_of_range_numbers_are_ignored(monkeypatch):
    """Same hallucination guard as evaluate_retrieval_relevance() - a
    free-text LLM response can repeat a number or invent one outside the
    real chunk range."""
    fake_client = FakeChatClient(answer="Ranked: 2, 2, 99, 1")
    monkeypatch.setattr(reranker, "get_client_gateway", lambda: FakeClientGateway(chat_client=fake_client))

    chunks = _chunks("first", "second")
    result = await reranker.rerank_chunks("a question", chunks)

    assert [c["text"] for c in result] == ["second", "first"]


async def test_malformed_response_fails_safe_to_original_order(monkeypatch):
    fake_client = FakeChatClient(answer="I don't understand the task.")
    monkeypatch.setattr(reranker, "get_client_gateway", lambda: FakeClientGateway(chat_client=fake_client))

    chunks = _chunks("first", "second", "third")
    result = await reranker.rerank_chunks("a question", chunks)

    assert [c["text"] for c in result] == ["first", "second", "third"]


async def test_llm_call_failure_fails_safe_to_original_order(monkeypatch):
    class _BoomChatClient:
        model = "fake-chat-model"

        def ask(self, *args, **kwargs):
            raise RuntimeError("provider down")

    monkeypatch.setattr(reranker, "get_client_gateway", lambda: FakeClientGateway(chat_client=_BoomChatClient()))

    chunks = _chunks("first", "second")
    result = await reranker.rerank_chunks("a question", chunks)

    assert [c["text"] for c in result] == ["first", "second"]


async def test_single_chunk_is_not_sent_to_the_llm_at_all(monkeypatch):
    """No point spending an LLM call to "rank" a list of one."""
    call_count = {"n": 0}

    class _CountingChatClient:
        model = "fake-chat-model"

        def ask(self, *args, **kwargs):
            call_count["n"] += 1
            return "Ranked: 1"

    monkeypatch.setattr(reranker, "get_client_gateway", lambda: FakeClientGateway(chat_client=_CountingChatClient()))

    chunks = _chunks("only one")
    result = await reranker.rerank_chunks("a question", chunks)

    assert call_count["n"] == 0
    assert result == chunks


async def test_empty_chunk_list_is_returned_unchanged(monkeypatch):
    result = await reranker.rerank_chunks("a question", [])
    assert result == []


def test_reranking_enabled_defaults_to_true(monkeypatch):
    monkeypatch.delenv("RAG_RERANK_ENABLED", raising=False)
    assert reranker.reranking_enabled() is True


def test_reranking_enabled_respects_the_kill_switch(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_ENABLED", "false")
    assert reranker.reranking_enabled() is False


async def test_disabled_reranking_returns_chunks_unchanged_without_calling_the_llm(monkeypatch):
    monkeypatch.setenv("RAG_RERANK_ENABLED", "false")
    call_count = {"n": 0}

    class _CountingChatClient:
        model = "fake-chat-model"

        def ask(self, *args, **kwargs):
            call_count["n"] += 1
            return "Ranked: 2, 1"

    monkeypatch.setattr(reranker, "get_client_gateway", lambda: FakeClientGateway(chat_client=_CountingChatClient()))

    chunks = _chunks("first", "second")
    result = await reranker.rerank_chunks("a question", chunks)

    assert call_count["n"] == 0
    assert result == chunks
