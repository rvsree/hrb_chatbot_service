"""Phase 168 - request/response contracts for the admin dashboard
(view + hard-delete across KB documents, conversations, feedback, and
leave requests/HITL reviews). KB documents and feedback reuse the
existing DocumentRecord/FeedbackRecord models unchanged - only
conversations and leave requests needed new shapes here (an
employee_id-carrying conversation summary the normal per-user endpoint
has no reason to expose, and a delete-result summary with no existing
equivalent anywhere)."""

from pydantic import BaseModel


class AdminConversationSummary(BaseModel):
    conversation_id: str
    employee_id: str | None
    title: str
    started_at: str
    last_updated_at: str


class AdminConversationListResponse(BaseModel):
    count: int
    conversations: list[AdminConversationSummary]


class AdminDeleteConversationResponse(BaseModel):
    conversation_id: str
    turns_deleted: int


class AdminDeleteFeedbackResponse(BaseModel):
    feedback_id: int
    deleted: bool


class AdminDeleteLeaveRequestResponse(BaseModel):
    hitl_request_context_id: int
    deleted_hitl_request: bool
    deleted_specialist_leave_reviews: int
    deleted_leave_request: bool
    deleted_document_count: int


class AdminDocSummary(BaseModel):
    """Phase 170 (round 1) - one row of the admin-only docs viewer."""

    id: int
    feature_name: str
    doc_title: str
    doc_type: str
    doc_version: int
    created_at: str
    updated_at: str
    last_synced_at: str


class AdminDocListResponse(BaseModel):
    count: int
    docs: list[AdminDocSummary]


class AdminDocContentResponse(BaseModel):
    download_url: str
    expires_in_seconds: int
