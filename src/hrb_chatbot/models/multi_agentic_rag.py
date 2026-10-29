"""Request/response contracts for multi-agentic-rag - see
docs/agent-reference/endpoint-request-response-contracts.md. Phase 61: the contract is real, the pipeline behind it is stubbed."""

from typing import Literal

from pydantic import BaseModel, Field

from src.hrb_chatbot.models.common import ToolCallInfo
from src.hrb_chatbot.models.common import UserProfile
from src.hrb_chatbot.models.rag import ClassificationOptions, DemoLimitInfo, EvalOptions, ExplainabilityInfo, RetrievedChunk


class MultiAgenticRagRequest(BaseModel):
    user_profile: UserProfile | None = None
    query: str = Field(..., min_length=1, max_length=2000, description="The question to ask the multi-agent system.")
    search_strategy: Literal["similarity", "mmr"] | None = Field(
        None,
        description="Phase 228 - vector_kb_agent never exposed a choice before this (always indirectly "
        "'similarity' via search_knowledge_base()'s own default) - this is the only way to influence it. "
        "Narrower than genai-rag's SearchOptions.search_strategy on purpose - search_knowledge_base() only ever "
        "understands these 2 values.",
    )
    eval_options: EvalOptions | None = None
    classification_options: ClassificationOptions | None = None
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


class AgentTaskInfo(BaseModel):
    agent: str = Field(..., description="Which sub-agent handled this task.")
    focus: str = Field(..., description="What the router asked this sub-agent to do.")
    reasoning: str = Field(..., description="Phase 209 - the Planner's own stated reason for routing this part of the question to this agent.")


class MultiAgenticRagResponse(BaseModel):
    """What POST /query returns."""

    query: str = Field(..., description="The question that was asked.")
    answer: str = Field(..., description="The final, synthesized answer.")
    tasks: list[AgentTaskInfo] = Field(..., description="Which sub-agent(s) the router dispatched to, and why.")
    suggested_follow_up_questions: list[str] = Field(
        default_factory=list,
        description="Phase 123 - Reviewer Agent-generated, 2-3 questions. Empty when no domain agent ran.",
    )
    tools_used: list[ToolCallInfo] = Field(
        ..., description="Every tool call any sub-agent made, in order, aggregated across all of them."
    )
    sources: list[RetrievedChunk] = Field(
        default_factory=list, description="Phase 115 - real chunks from vector_kb_agent dispatches, if any."
    )
    iterations: int = Field(
        ...,
        description="How many domain agents the Planner dispatched to for this query - a one-shot "
        "fan-out, not a reasoning-round count (multi-agentic-rag has no retry loop, unlike "
        "single-agentic-rag's own iterations field).",
    )
    explainability_info: ExplainabilityInfo = Field(
        ...,
        description="Phase 110/115 - total latency + llm_call_count + eval scores + real caching "
        "(cache-eligible only when every dispatched task was vector_kb_agent, see RAG-ROADMAP.md "
        "Phase 115). token_usage is still always null - not yet captured per-domain-agent (BACKLOG.md).",
    )
    conversation_id: str | None = Field(
        None,
        description="Echoed/generated when enable_conversation_memory was true - pass it back on the next "
        "call to continue this conversation. Null when memory wasn't enabled.",
    )
    resolved_mode: str | None = Field(
        None,
        description="Phase 240 - set only when this model is returned from POST /v1/rag-retrieval/query "
        "(the auto-router, including an escalation from single-agentic-rag). Null on this endpoint's own "
        "direct, forced-mode calls.",
    )
    demo_limit: DemoLimitInfo | None = Field(
        None, description="Phase 265 - null for an exempt caller (ADMIN/EMPLOYEE_ADMIN/HR_SUPPORT)."
    )
