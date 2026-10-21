"""Server-side conversation history for multi-turn support, keyed by
conversation_id - Postgres-backed (Phase 76), STM and LTM are the same
durable store, not two tiers. Replaces the old in-memory dict, which was
wiped on every restart."""

import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway


def new_conversation_id() -> str:
    return uuid.uuid4().hex


async def load_history(conversation_id: str) -> list[BaseMessage]:
    """Returns [] for an unknown/new conversation_id - never raises."""
    turns = await get_db_gateway().conversation_store().load_turns(conversation_id)
    messages: list[BaseMessage] = []
    for turn in turns:
        if turn["role"] == "human":
            messages.append(HumanMessage(content=turn["content"]))
        else:
            messages.append(AIMessage(content=turn["content"]))
    return messages


async def save_turn(conversation_id: str, employee_id: str | None, human_content: str, ai_content: str) -> None:
    store = get_db_gateway().conversation_store()
    await store.save_turn(conversation_id, employee_id, "human", human_content)
    await store.save_turn(conversation_id, employee_id, "ai", ai_content)


async def delete_conversation(conversation_id: str, employee_id: str) -> int:
    """Deletes every turn for one conversation - the NFR delete-my-data endpoint's own logic."""
    return await get_db_gateway().conversation_store().delete_conversation(conversation_id, employee_id)


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
    return await get_db_gateway().conversation_store().delete_conversation_any(conversation_id)


async def get_conversation_turns_any(conversation_id: str) -> list[dict]:
    """Phase 168 (round 3) - admin-only: the full transcript for any
    conversation regardless of owner."""
    return await get_db_gateway().conversation_store().get_conversation_turns_any(conversation_id)
