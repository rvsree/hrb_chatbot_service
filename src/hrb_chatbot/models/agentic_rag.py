"""Request/response contracts for single-agentic-rag (Phase 55) - same
Phase 45 identity-via-payload pattern as models/rag.py, not headers."""

from typing import Literal

from pydantic import BaseModel, Field

from src.hrb_chatbot.models.common import ToolCallInfo, UserProfile
from src.hrb_chatbot.models.rag import DemoLimitInfo, EvalOptions, ExplainabilityInfo, RetrievedChunk


class AgenticRagRequest(BaseModel):
    user_profile: UserProfile | None = None
    query: str = Field(..., min_length=1, max_length=2000, description="The question to ask the agent.")
    max_iterations: int | None = Field(
        None, ge=1, le=10, description="Upper bound on tool-call rounds before giving up - defaults to 5, matching the course reference."
    )
    search_strategy: Literal["similarity", "mmr"] | None = Field(
        None,
        description="Phase 228 - a DEFAULT the agent's own SearchKnowledgeBase tool call falls back to when it "
        "doesn't choose one itself (Phase 216 already lets the agent pick per call - this doesn't override that). "
        "Narrower than genai-rag's SearchOptions.search_strategy on purpose - search_knowledge_base() only ever "
        "understands these 2 values.",
    )
    eval_options: EvalOptions | None = None
    guardrails_model: str | None = Field(
        None,
        max_length=100,
        description="Phase 244 - override the model running NeMo Guardrails' input/output safety checks. "
        "Validated against GUARDRAILS_SUPPORTED_MODELS - 422 if given but not listed.",
    )
    enable_conversation_memory: bool = Field(
        False, description="Carry conversation history across calls, server-side, keyed by conversation_id."
    )
    conversation_id: str | None = Field(
        None,
        description="Pass back the value from a prior response to continue that conversation. Ignored if "
        "enable_conversation_memory is false; a new one is generated if true and this is omitted.",
    )



class AgenticRagResponse(BaseModel):
    """What POST /query returns."""

    query: str = Field(..., description="The question that was asked.")
    answer: str = Field(..., description="The agent's final answer.")
    tools_used: list[ToolCallInfo] = Field(..., description="Every tool call the agent made, in order.")
    sources: list[RetrievedChunk] = Field(
        default_factory=list, description="Phase 115 - real chunks from SearchKnowledgeBase calls, if any."
    )
    iterations: int = Field(..., description="How many reasoning rounds the agent actually took.")
    explainability_info: ExplainabilityInfo = Field(..., description="Phase 110 - same shape as genai-rag's own.")
    conversation_id: str | None = Field(
        None,
        description="Echoed/generated when enable_conversation_memory was true - pass it back on the next "
        "call to continue this conversation. Null when memory wasn't enabled.",
    )
    resolved_mode: str | None = Field(
        None,
        description="Phase 240 - set only when this model is returned from POST /v1/rag-retrieval/query "
        "(the auto-router). Null on this endpoint's own direct, forced-mode calls.",
    )
    demo_limit: DemoLimitInfo | None = Field(
        None, description="Phase 265 - null for an exempt caller (ADMIN/EMPLOYEE_ADMIN/HR_SUPPORT)."
    )
