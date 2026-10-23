"""Tests for Phase 76's Postgres-backed conversation history
(ai/search_pre_processing/conversation_memory.py) - the real ConversationStore is
faked (FakeConversationStore), no real database involved. Phase 247 adds the
Redis STM cache-aside layer in front of it (FakeStmCache), also faked."""

from langchain_core.messages import AIMessage, HumanMessage

from src.hrb_chatbot.ai.search_pre_processing import conversation_memory
from tests.conftest import FakeConversationStore, FakeDBGateway, FakeStmCache


def _patch_gateway(monkeypatch, conversation_store=None, stm_cache=None):
    gateway = FakeDBGateway(conversation_store=conversation_store or FakeConversationStore(), stm_cache=stm_cache)
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


async def test_load_history_hits_stm_cache_without_touching_postgres(monkeypatch):
    """Phase 247 - a repeat read within the STM cache's TTL never reaches
    the Postgres store at all."""
    conversation_store = FakeConversationStore()
    gateway = _patch_gateway(monkeypatch, conversation_store=conversation_store)
    await conversation_memory.save_turn("conv-1", "EMP052", "what is the pto policy?", "15 days a year.")

    # Remove the turns from Postgres directly, bypassing conversation_memory,
    # so a read that still succeeds proves it came from the STM cache, not Postgres.
    conversation_store._turns["conv-1"] = []

    history = await conversation_memory.load_history("conv-1")

    assert [m.content for m in history] == ["what is the pto policy?", "15 days a year."]


async def test_load_history_falls_back_to_postgres_and_backfills_on_an_stm_cache_miss(monkeypatch):
    """Phase 247 - an expired/never-written STM key falls back to Postgres,
    then backfills the cache so the next read is a hit."""
    gateway = _patch_gateway(monkeypatch)
    # Write directly to the conversation store, bypassing conversation_memory.save_turn()
    # (which would also warm the STM cache) - simulates a cold/expired cache with real Postgres history.
    await gateway.conversation_store().save_turn("conv-1", "EMP052", "human", "q1")
    await gateway.conversation_store().save_turn("conv-1", "EMP052", "ai", "a1")
    assert await gateway.stm_cache().get_turns("conv-1") is None  # confirms the cache starts cold

    history = await conversation_memory.load_history("conv-1")

    assert [m.content for m in history] == ["q1", "a1"]
    assert await gateway.stm_cache().get_turns("conv-1") == [
        {"role": "human", "content": "q1"},
        {"role": "ai", "content": "a1"},
    ]  # backfilled, so the next read would be a cache hit


async def test_delete_conversation_clears_the_stm_cache_too(monkeypatch):
    gateway = _patch_gateway(monkeypatch)
    await conversation_memory.save_turn("conv-1", "EMP052", "a question", "a answer")
    assert await gateway.stm_cache().get_turns("conv-1") is not None

    await conversation_memory.delete_conversation("conv-1", "EMP052")

    assert await gateway.stm_cache().get_turns("conv-1") is None


async def test_delete_conversation_with_wrong_owner_leaves_the_stm_cache_untouched(monkeypatch):
    gateway = _patch_gateway(monkeypatch)
    await conversation_memory.save_turn("conv-1", "EMP052", "a question", "a answer")

    await conversation_memory.delete_conversation("conv-1", "EMP999")

    assert await gateway.stm_cache().get_turns("conv-1") is not None
