"""Server-side conversation history for multi-turn support, keyed by
conversation_id - Postgres-backed (Phase 76), the durable system of record.
Phase 247 adds a Redis cache-aside STM layer in front of the Postgres read
(`load_history()`) - Postgres stays the only place history can be lost from;
Redis is a performance cache that degrades to a Postgres read on a miss or
outage, never the other way around. Replaces the old in-memory dict, which
was wiped on every restart."""

import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway


def new_conversation_id() -> str:
    return uuid.uuid4().hex


def _turns_to_messages(turns: list[dict]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for turn in turns:
        if turn["role"] == "human":
            messages.append(HumanMessage(content=turn["content"]))
        else:
            messages.append(AIMessage(content=turn["content"]))
    return messages


async def load_history(conversation_id: str) -> list[BaseMessage]:
    """Returns [] for an unknown/new conversation_id - never raises. Reads
    STM (Redis) first; on a miss, falls back to Postgres and backfills Redis
    so the next read is a hit."""
    gateway = get_db_gateway()
    cached_turns = await gateway.stm_cache().get_turns(conversation_id)
    if cached_turns is not None:
        return _turns_to_messages(cached_turns)

    turns = await gateway.conversation_store().load_turns(conversation_id)
    await gateway.stm_cache().backfill(conversation_id, turns)
    return _turns_to_messages(turns)


async def save_turn(conversation_id: str, employee_id: str | None, human_content: str, ai_content: str) -> None:
    store = get_db_gateway().conversation_store()
    await store.save_turn(conversation_id, employee_id, "human", human_content)
    await store.save_turn(conversation_id, employee_id, "ai", ai_content)

    cache = get_db_gateway().stm_cache()
    await cache.append_turn(conversation_id, "human", human_content)
    await cache.append_turn(conversation_id, "ai", ai_content)


async def delete_conversation(conversation_id: str, employee_id: str) -> int:
    """Deletes every turn for one conversation - the NFR delete-my-data endpoint's own logic."""
    deleted = await get_db_gateway().conversation_store().delete_conversation(conversation_id, employee_id)
    if deleted:
        await get_db_gateway().stm_cache().clear(conversation_id)
    return deleted


async def list_conversations(employee_id: str) -> list[dict]:
    """Phase 116 - one row per distinct conversation this employee has turns in."""
    return await get_db_gateway().conversation_store().list_conversations(employee_id)


async def get_conversation_turns(conversation_id: str, employee_id: str) -> list[dict]:
    """Phase 116 - [] if unknown or not this employee's own conversation."""
    return await get_db_gateway().conversation_store().get_conversation_turns(conversation_id, employee_id)


async def list_all_conversations() -> list[dict]:
    """Phase 168 - admin-only: every conversation across every employee."""
    return await get_db_gateway().conversation_store().list_all_conversations()


async def delete_conversation_any(conversation_id: str) -> int:
    """Phase 168 - admin-only: deletes a conversation regardless of owner."""
    deleted = await get_db_gateway().conversation_store().delete_conversation_any(conversation_id)
    if deleted:
        await get_db_gateway().stm_cache().clear(conversation_id)
    return deleted


async def get_conversation_turns_any(conversation_id: str) -> list[dict]:
    """Phase 168 (round 3) - admin-only: the full transcript for any
    conversation regardless of owner."""
    return await get_db_gateway().conversation_store().get_conversation_turns_any(conversation_id)
