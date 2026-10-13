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
        None,
        description=(
            "Phase 161 - set whenever an email was attempted this turn, sent or failed. Phase 163: this can now be "
            "either the model's own in-text SendEmailWithAnswer decision or the checkbox-driven auto-email path - "
            "if both fired this turn, the checkbox-driven one takes priority here (the more deterministic, "
            "explicitly-requested one); every attempt from either path is still persisted separately. None only "
            "when no email was attempted at all."
        ),
    )
    session_id: str = Field(..., description="Phase 163 - always present now; send it back on the next turn to continue this session's memory.")
    model_used: str
    iterations: int
    llm_call_count: int
    token_usage: TokenUsageInfo | None
    latency_ms: LatencyInfo


class AdhocSessionSummary(BaseModel):
    """Phase 165 - the sidebar's own "GenAI Chat Workflow History" section,
    same shape as ConversationSummary (api/conversations/) but for this
    workflow's separate chat_workflow_store memory."""

    session_id: str
    session_title: str
    started_at: str
    last_active: str
    turn_count_total: int


class AdhocSessionListResponse(BaseModel):
    count: int
    sessions: list[AdhocSessionSummary]


class AdhocSessionTurn(BaseModel):
    role: str = Field(..., description="'human' or 'ai'.")
    content: str
    created_at: str


class AdhocSessionDetailResponse(BaseModel):
    session_id: str
    turns: list[AdhocSessionTurn]
