"""Phase 168 - request/response contracts for the admin dashboard
(view + hard-delete across KB documents, conversations, feedback, and
leave requests/HITL reviews). KB documents and feedback reuse the
existing DocumentRecord/FeedbackRecord models unchanged - only
conversations and leave requests needed new shapes here (an
employee_id-carrying conversation summary the normal per-user endpoint
has no reason to expose, and a delete-result summary with no existing
equivalent anywhere)."""

from pydantic import BaseModel

from src.hrb_chatbot.common.enums import Application


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


class GoldenDatasetCaseSummary(BaseModel):
    """Phase 181 - one row of the Deployment Dashboard's golden-dataset
    viewer. raw_case carries the full original JSON case object verbatim,
    so a new field in either source file renders without a model change."""

    id: int
    case_key: str
    dataset: str
    category: str | None
    query: str | None
    raw_case: dict
    created_at: str
    updated_at: str


class GoldenDatasetListResponse(BaseModel):
    count: int
    cases: list[GoldenDatasetCaseSummary]


class EvalRunSummary(BaseModel):
    """Phase 182 - one row of the Deployment Dashboard's Eval Runs list."""

    id: int
    run_at: str
    decision: str
    flags: list[str]
    aggregated_scores: dict[str, float]
    total_cases: int
    scored_cases: int
    failed_case_ids: list[str]
    retrieval_k: int


class EvalRunListResponse(BaseModel):
    count: int
    runs: list[EvalRunSummary]


class EvalRunCaseDetail(BaseModel):
    case_id: str
    category: str | None
    scores: dict[str, float]
    status: str


class EvalRunDetail(EvalRunSummary):
    cases: list[EvalRunCaseDetail]


class WorkflowRunSummary(BaseModel):
    """Phase 183 - one GitHub Actions run, as the CI/Build Status tab shows it."""

    id: int
    run_number: int
    status: str
    conclusion: str | None
    head_sha: str
    head_commit_message: str
    html_url: str
    created_at: str


class WorkflowStatus(BaseModel):
    """Phase 235 - one workflow file's own paged run history, with a
    plain-language `display_name` alongside the real `workflow_file` (the
    real file name moves to a "?" popover on the frontend, not removed)."""

    workflow_file: str
    display_name: str
    runs: list[WorkflowRunSummary]
    total_count: int
    has_more: bool
    error: str | None


class CiStatusResponse(BaseModel):
    """Phase 235 - `workflows` replaces the old fixed `ci`/`deploy` pair,
    which only ever fit `backend`'s own 2 workflow files - a generic list
    so it naturally renders however many workflow files the selected
    `application` actually has (1 for ingestion_lambda/lms_mcp, 2 for
    backend)."""

    application: Application
    page: int
    workflows: list[WorkflowStatus]
    error: str | None


class PipelineStepDetail(BaseModel):
    """Phase 188 - one real GitHub Actions step, as the Pipeline stepper shows it."""

    name: str
    status: str
    conclusion: str | None
    started_at: str | None
    completed_at: str | None


class PipelineJobDetail(BaseModel):
    name: str
    status: str
    conclusion: str | None
    html_url: str
    steps: list[PipelineStepDetail]


class PipelineWorkflowRun(BaseModel):
    """One workflow file's run (ci.yml / deploy.yml) for a single commit."""

    workflow_file: str
    id: int
    run_number: int
    status: str
    conclusion: str | None
    html_url: str
    created_at: str
    jobs: list[PipelineJobDetail]


class PipelineStatusResponse(BaseModel):
    head_sha: str
    head_commit_message: str
    head_branch: str
    event: str
    actor_login: str
    runs: list[PipelineWorkflowRun]
    eval_gate: EvalRunSummary | None
    error: str | None


class PipelineSnapshotSummary(BaseModel):
    """Phase 189 - one persisted pipeline snapshot, as the history picker
    lists it - not the full stage detail, just enough to pick one."""

    id: int
    head_sha: str
    head_commit_message: str
    captured_at: str


class PipelineSnapshotListResponse(BaseModel):
    count: int
    snapshots: list[PipelineSnapshotSummary]


class PipelineMetricsRow(BaseModel):
    """Phase 184 - one (pipeline, status) group from request_metrics,
    aggregated over the requested time window."""

    pipeline: str
    status: str
    request_count: int
    avg_latency_ms: float | None
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    total_tokens: int | None


class RequestMetricsResponse(BaseModel):
    window_hours: int
    rows: list[PipelineMetricsRow]
