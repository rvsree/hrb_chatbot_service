"""Shapes shared across more than one endpoint's request/response contract."""

from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    # Phase 282 - character-class restriction, defense-in-depth - the real
    # gate is login.py's own known-personas allowlist, not this pattern.
    employee_id: str = Field(..., max_length=50, pattern=r"^[A-Za-z0-9]+$")
    full_name: str = Field(..., max_length=200, pattern=r"^[A-Za-z\s'\-]+$")
    role: str = Field(..., max_length=50)
    department: str | None = Field(None, max_length=100, description="Phase 231 - self-asserted, like role.")
    timezone: str | None = Field(
        None, max_length=100,
        description="Phase 265 - browser-reported (Intl.DateTimeFormat), not server-inferred - there is no reliable way to get this from HTTP alone.",
    )


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
    validation_failed: bool = Field(
        False,
        description="Phase 277 - true if the Dynamic Tool Router rejected this call's own arguments "
        "before the tool ever ran (a self-correctable mistake, distinct from a real backend failure).",
    )
