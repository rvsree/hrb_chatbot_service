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


class EmailEvidence(BaseModel):
    """Phase 161 - real evidence of one SendEmailWithAnswer attempt, sent or
    failed - captured so a failure (e.g. SES_SENDER_EMAIL not configured)
    is visible instead of silently indistinguishable from "no email asked
    for at all"."""

    recipient_email: str
    subject: str
    sent: bool
    message: str = Field(..., description="send_email()'s own success/failure text - never re-derived.")
    attached_files: list[str] = Field(default_factory=list, description="Empty unless attach_files was set on the tool call.")
    sent_at: str = Field(..., description="UTC ISO-8601, captured right before calling send_email().")


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
    email_evidence: EmailEvidence | None = Field(
        None, description="Phase 161 - set whenever SendEmailWithAnswer was called this turn, sent or failed. None only when no email was attempted at all."
    )
    model_used: str
    iterations: int
    llm_call_count: int
    token_usage: TokenUsageInfo | None
    latency_ms: LatencyInfo
