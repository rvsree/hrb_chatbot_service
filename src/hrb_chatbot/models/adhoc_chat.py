"""Phase 136 - the Chat GenAI Workflow's own request/response contracts.
Deliberately NOT RagQueryRequest/RagQueryResponse - no vector_db/
search_strategy/citations fields exist here because none of that applies
(no vector store, no persisted KB). See
docs/dev-reference/genai_chat_workflow.md for the full design."""

from pydantic import BaseModel, ConfigDict, Field

from src.hrb_chatbot.models.rag import LatencyInfo, TokenUsageInfo

MAX_FILES = 3
ALLOWED_EXTENSIONS = (".pdf", ".docx", ".csv")
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


class AdhocDocumentChatResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    question: str
    answer: str
    files_used: list[str] = Field(..., description="Which attached files the agent actually read via ReadDocument.")
    web_searches: list[str] = Field(
        default_factory=list,
        description="Phase 145 - which queries the agent actually ran via SearchWeb, reusing multi-agentic-rag's Tavily integration. Empty when the question didn't need the web.",
    )
    email_sent_to: str | None = Field(None, description="Set only if SendEmailWithAnswer actually succeeded.")
    model_used: str
    iterations: int
    llm_call_count: int
    token_usage: TokenUsageInfo | None
    latency_ms: LatencyInfo
