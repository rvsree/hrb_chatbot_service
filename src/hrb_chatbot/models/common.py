"""Shapes shared across more than one endpoint's request/response contract."""

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    employee_id: str = Field(..., max_length=50)
    full_name: str = Field(..., max_length=200)
    role: str = Field(..., max_length=50)
    department: str | None = Field(None, max_length=100, description="Phase 231 - self-asserted, like role.")


class IdentityPayload(BaseModel):
    """The JSON body for GET/DELETE endpoints - identity only, deliberately never a query param or header."""

    user_profile: UserProfile | None = None


class ToolCallInfo(BaseModel):
    """Phase 126: moved here from models/agentic_rag.py - genai-rag's
    RagQueryResponse needs it too, and agentic_rag.py already imports
    FROM models/rag.py, so defining it there instead would circular-import."""

    tool_name: str = Field(..., description="Which tool the agent called.")
    tool_input: str = Field(..., description="What the agent passed to it.")
    tool_type: str = Field(
        "other", description="Phase 126 - which kind of backend this hit: vector_db/mcp/web_search/sql_db/other."
    )
    latency_ms: float | None = Field(None, description="Phase 126 - how long this one call took, if measured.")
    success: bool = Field(True, description="Phase 126 - false if this call returned an 'Error: ...' result.")
    iteration: int | None = Field(
        None, description="Phase 206 - which ReAct iteration (1-indexed) made this call. Single-agentic-rag only."
    )
    search_strategy: str | None = Field(
        None,
        description="Phase 216 - the agent's own strategy choice for a search_knowledge_base call "
        "('similarity'/'mmr'). Null for every other tool.",
    )
