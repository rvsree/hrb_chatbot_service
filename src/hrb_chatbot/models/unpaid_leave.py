"""Phase 162 - "Request Unpaid Leave": a second A2A/HITL workflow, explicitly
separate from the GenAI Chat Workflow. No vector_db/search_strategy fields -
none apply, this is a structured form submission, not a RAG question."""

from pydantic import BaseModel, Field

from src.hrb_chatbot.common.enums import LeaveTypeCode
from src.hrb_chatbot.models.common import UserProfile


class LeaveDocumentUploadUrlRequest(BaseModel):
    user_profile: UserProfile
    filename: str
    content_type: str


class LeaveDocumentUploadUrlResponse(BaseModel):
    upload_url: str
    key: str = Field(..., description="Pass this back as document_reference on the actual submit call.")
    expires_in_seconds: int


class UnpaidLeaveRequestBody(BaseModel):
    user_profile: UserProfile
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    purpose: str = Field(..., min_length=1, max_length=2000)
    leave_type_code: LeaveTypeCode = Field(LeaveTypeCode.UNPAID, description="Phase 165 - UNPAID, CRITICAL_CAREGIVER, STD, or LTD.")
    document_reference: str | None = Field(None, description="S3 key from the upload-url step, if a document was attached.")


class UnpaidLeaveRequestResponse(BaseModel):
    request_id: int
    employee_id: str
    leave_type: str
    status: str
    is_repeat_within_12_months: bool
    hitl_request_context_id: int
    hitl_status: str
    days: float


class HitlRequestSummary(BaseModel):
    hitl_request_context_id: int
    request_type: str
    employee_id: str | None
    query: str
    context: dict
    status: str
    assigned_to: str | None
    created_at: str | None


class PendingHitlRequestsResponse(BaseModel):
    total: int
    requests: list[HitlRequestSummary]


class ResolveHitlRequestBody(BaseModel):
    user_profile: UserProfile
    hitl_request_context_id: int
    decision: str = Field(..., description="APPROVED or REJECTED")
    response_text: str = Field(..., min_length=1, max_length=2000)


class ResolveHitlRequestResponse(BaseModel):
    hitl_request_context_id: int
    status: str
    decision: str
    response: str
    related_leave_request_updated: bool


class LeaveDocumentDownloadUrlResponse(BaseModel):
    download_url: str
    original_filename: str
    expires_in_seconds: int


class MyLeaveRequestSummary(BaseModel):
    """Phase 165 - one row of the employee's own "My Requests" view."""

    request_id: int
    leave_type: str
    start_date: str
    end_date: str
    days: float
    purpose: str
    status: str
    decision: str | None
    hr_comments: str | None
    hr_specialist_name: str | None
    created_at: str | None
    responded_at: str | None
    # Phase 172 - additive A2A-shaped fields alongside status/decision/
    # hr_comments above (unchanged) - task_state is the real Task
    # lifecycle value; review_brief/decision_message/produced_artifacts
    # are null until the agent graph actually produces them.
    task_state: str | None = None
    review_brief: str | None = None
    decision_message: dict | None = None
    produced_artifacts: list[dict] = []


class MyLeaveRequestsResponse(BaseModel):
    total: int
    requests: list[MyLeaveRequestSummary]


class HrLeaveRequestSummary(BaseModel):
    """Phase 168 (round 2) - one row of the HR specialist grid - every
    employee's leave requests, any status, with the same review detail
    MyLeaveRequestSummary shows the employee, plus employee_id/name and
    hitl_request_context_id (needed for the grid's own resolve action)."""

    hitl_request_context_id: int
    request_id: int
    employee_id: str | None
    employee_name: str | None
    leave_type: str
    start_date: str
    end_date: str
    days: float
    purpose: str
    status: str
    decision: str | None
    hr_comments: str | None
    hr_specialist_name: str | None
    created_at: str | None
    responded_at: str | None
    # Phase 172 - see MyLeaveRequestSummary's own comment above.
    task_state: str | None = None
    review_brief: str | None = None
    decision_message: dict | None = None
    produced_artifacts: list[dict] = []


class HrLeaveRequestsResponse(BaseModel):
    total: int
    requests: list[HrLeaveRequestSummary]
