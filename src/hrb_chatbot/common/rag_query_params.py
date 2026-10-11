"""Plain, framework-free container for one /query request - not Pydantic, since only routes/ owns request models."""

from dataclasses import dataclass


@dataclass
class RagQueryParams:
    query: str
    top_k: int | None = None
    vector_db: str | None = None
    search_strategy: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    use_multi_query: bool = False
    use_self_query: bool = False
    llm_provider: str | None = None
    lambda_mult: float | None = None  # Phase 131 - 'mmr' only
    employee_id: str | None = None  # Phase 49: caller's own id, for MCP tool routing
    enable_conversation_memory: bool = False  # Phase 58
    conversation_id: str | None = None  # Phase 58
