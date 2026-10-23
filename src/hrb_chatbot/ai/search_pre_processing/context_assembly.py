"""Phase 248 - the Search Pre-Processing Layer's own entry point: "what do
we know before we start answering," gathered once instead of scattered
across callers. See docs/dev-reference/search-pre-processing-layer/ for the
full design. Only POST /v1/rag-retrieval/query (the Phase 240 auto-router)
calls this today - genai-rag/single-agentic-rag-retrieval/
multi-agentic-rag-retrieval are untouched."""

from typing import Literal

from langchain_core.messages import BaseMessage

from src.hrb_chatbot.ai.search_pre_processing import conversation_memory
from src.hrb_chatbot.ai.search_pre_processing.mode_router import classify_query_complexity
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway


class RequestContext:
    """Everything the chosen pipeline needs, assembled once. Not a Pydantic
    model - never serialized to a response, just passed around in-process."""

    def __init__(
        self,
        user_profile,
        conversation_id: str | None,
        query: str,
        stm: list[BaseMessage],
        feedback: dict | None,
        classification: Literal["single", "multi"],
    ):
        self.user_profile = user_profile
        self.conversation_id = conversation_id
        self.query = query
        self.stm = stm
        self.feedback = feedback
        self.classification = classification


async def assemble_context(user_profile, conversation_id: str | None, query: str, router_model: str | None = None) -> RequestContext:
    """One call, gathers STM (this conversation's recent turns), the latest
    feedback signal on this conversation (surfaced only - not acted on by
    any routing decision yet, see the design's own Decisions doc), and the
    Reflex-vs-Agentic classification that feeds the router's own decision."""
    stm = await conversation_memory.load_history(conversation_id) if conversation_id else []
    feedback = await get_db_gateway().feedback_store().get_latest_feedback_for_conversation(conversation_id)
    classification = await classify_query_complexity(query, router_model)

    return RequestContext(user_profile, conversation_id, query, stm, feedback, classification)
