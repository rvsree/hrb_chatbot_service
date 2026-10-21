"""Tests for Phase 76's Postgres-backed conversation history
(ai/search_pre_processing/conversation_memory.py) - the real ConversationStore is
faked (FakeConversationStore), no real database involved."""

from langchain_core.messages import AIMessage, HumanMessage

from src.hrb_chatbot.ai.search_pre_processing import conversation_memory
from tests.conftest import FakeConversationStore, FakeDBGateway


def _patch_gateway(monkeypatch, conversation_store=None):
    gateway = FakeDBGateway(conversation_store=conversation_store or FakeConversationStore())
    monkeypatch.setattr(conversation_memory, "get_db_gateway", lambda: gateway)
    return gateway


async def test_unknown_conversation_id_returns_empty_history(monkeypatch):
    _patch_gateway(monkeypatch)
    assert await conversation_memory.load_history("never-seen-before") == []


def test_new_conversation_id_returns_a_non_empty_string():
    first = conversation_memory.new_conversation_id()
    second = conversation_memory.new_conversation_id()

    assert first and second
    assert first != second


async def test_save_turn_then_load_history_round_trips_as_human_then_ai_message(monkeypatch):
    _patch_gateway(monkeypatch)
    await conversation_memory.save_turn("conv-1", "EMP052", "what database issues have we had?", "Two timeout tickets.")

    history = await conversation_memory.load_history("conv-1")

    assert history == [
        HumanMessage(content="what database issues have we had?"),
        AIMessage(content="Two timeout tickets."),
    ]


async def test_multiple_turns_accumulate_in_order(monkeypatch):
    _patch_gateway(monkeypatch)
    await conversation_memory.save_turn("conv-1", "EMP052", "question one", "answer one")
    await conversation_memory.save_turn("conv-1", "EMP052", "question two", "answer two")

    history = await conversation_memory.load_history("conv-1")

    assert [message.content for message in history] == ["question one", "answer one", "question two", "answer two"]


async def test_different_conversation_ids_stay_isolated(monkeypatch):
    _patch_gateway(monkeypatch)
    await conversation_memory.save_turn("conv-a", "EMP052", "a question", "a answer")
    await conversation_memory.save_turn("conv-b", "EMP052", "b question", "b answer")

    assert [m.content for m in await conversation_memory.load_history("conv-a")] == ["a question", "a answer"]
    assert [m.content for m in await conversation_memory.load_history("conv-b")] == ["b question", "b answer"]


async def test_delete_conversation_removes_the_callers_own_turns(monkeypatch):
    _patch_gateway(monkeypatch)
    await conversation_memory.save_turn("conv-1", "EMP052", "a question", "a answer")

    deleted_count = await conversation_memory.delete_conversation("conv-1", "EMP052")

    assert deleted_count == 2  # one human turn + one ai turn
    assert await conversation_memory.load_history("conv-1") == []


async def test_delete_conversation_does_not_delete_someone_elses_conversation(monkeypatch):
    _patch_gateway(monkeypatch)
    await conversation_memory.save_turn("conv-1", "EMP052", "a question", "a answer")

    deleted_count = await conversation_memory.delete_conversation("conv-1", "EMP999")

    assert deleted_count == 0
    assert len(await conversation_memory.load_history("conv-1")) == 2
