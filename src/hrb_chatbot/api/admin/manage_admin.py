"""Phase 168 - the admin dashboard's own routes: view + hard-delete across
KB documents, conversations, feedback, and leave requests/HITL reviews.
ADMIN or EMPLOYEE_ADMIN throughout (2026-10-15 - both admin tiers), except
/docs and /docs/{id}/content below, which stay ADMIN ("Engineering Admin")
only - deliberately separate from HR_SUPPORT (reviews leave requests) and
from every other role. KB documents aren't duplicated here at all - the
existing ingest_document.py routes were widened to also accept ADMIN
instead, since they already did unscoped list/delete with nothing left to
add. This router exists for the 3 categories that didn't already have an
admin-usable list+delete: conversations, feedback, leave requests/HITL."""

import asyncio

from fastapi import APIRouter, Depends, Request

from src.hrb_chatbot.ai.pre_processing import conversation_memory
from src.hrb_chatbot.ai.rag_pipeline.tools.mcp_tools import _call_mcp_tool_json, admin_delete_hitl_request
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import identity_from_query_params, require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway
from src.hrb_chatbot.common.clients.storage_client.s3_upload_client import (
    delete_leave_document_object,
    generate_admin_doc_download_url,
)
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.admin import (
    AdminConversationListResponse,
    AdminConversationSummary,
    AdminDeleteConversationResponse,
    AdminDeleteFeedbackResponse,
    AdminDeleteLeaveRequestResponse,
    AdminDocContentResponse,
    AdminDocListResponse,
    AdminDocSummary,
    CiStatusResponse,
    EvalRunCaseDetail,
    EvalRunDetail,
    EvalRunListResponse,
    EvalRunSummary,
    GoldenDatasetCaseSummary,
    GoldenDatasetListResponse,
    PipelineMetricsRow,
    RequestMetricsResponse,
    WorkflowRunSummary,
    WorkflowStatus,
)
from src.hrb_chatbot.models.common import IdentityPayload, UserProfile
from src.hrb_chatbot.models.conversations import ConversationDetailResponse, ConversationTurn
from src.hrb_chatbot.models.faq import (
    FaqRestructureRequest,
    FaqReviewRequest,
    FaqSubmissionListResponse,
    FaqSubmissionRecord,
)
from src.hrb_chatbot.models.interview_qa import (
    CreateInterviewQaRequest,
    DeleteInterviewQaResponse,
    InterviewQaCard,
    InterviewQaListResponse,
    UpdateInterviewQaRequest,
)
from src.hrb_chatbot.models.feedback import FeedbackListResponse, FeedbackRecord
from src.hrb_chatbot.models.unpaid_leave import HitlRequestSummary, PendingHitlRequestsResponse

logger = get_logger("admin.manage_admin")

router_manage_admin = APIRouter(tags=["admin"])


@router_manage_admin.get("/conversations", response_model=AdminConversationListResponse)
async def list_all_conversations(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Every conversation across every employee - the one legitimate
    "see everyone's" case for this data. Both admin tiers (2026-10-15)."""
    require_role(user_profile, Role.ADMIN, Role.EMPLOYEE_ADMIN)

    rows = await conversation_memory.list_all_conversations()
    return AdminConversationListResponse(count=len(rows), conversations=[AdminConversationSummary(**row) for row in rows])


@router_manage_admin.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
async def get_any_conversation(
    conversation_id: str, user_profile: UserProfile | None = Depends(identity_from_query_params)
):
    """Phase 168 (round 3) - the full transcript for any conversation
    regardless of owner, for the admin dashboard's own review-before-
    delete popup. An unknown conversation_id returns an empty turns list,
    same non-disclosure shape as the per-employee route this mirrors."""
    require_role(user_profile, Role.ADMIN, Role.EMPLOYEE_ADMIN)

    turns = await conversation_memory.get_conversation_turns_any(conversation_id)
    return ConversationDetailResponse(
        conversation_id=conversation_id, turns=[ConversationTurn(**turn) for turn in turns]
    )


@router_manage_admin.delete("/conversations/{conversation_id}", response_model=AdminDeleteConversationResponse)
async def delete_any_conversation(conversation_id: str, identity: IdentityPayload, request: Request):
    """Deletes a conversation regardless of which employee it belongs to."""
    require_role(identity.user_profile, Role.ADMIN, Role.EMPLOYEE_ADMIN)
    await enforce_rate_limit(request)

    turns_deleted = await conversation_memory.delete_conversation_any(conversation_id)
    return AdminDeleteConversationResponse(conversation_id=conversation_id, turns_deleted=turns_deleted)


@router_manage_admin.get("/feedback", response_model=FeedbackListResponse)
async def list_all_feedback(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Every feedback entry across every employee - reuses the existing
    list_feedback(employee_id=None) path hr_support already gets."""
    require_role(user_profile, Role.ADMIN, Role.EMPLOYEE_ADMIN)

    rows = await get_db_gateway().feedback_store().list_feedback(None)
    return FeedbackListResponse(count=len(rows), feedback=[FeedbackRecord(**row) for row in rows])


@router_manage_admin.delete("/feedback/{feedback_id}", response_model=AdminDeleteFeedbackResponse)
async def delete_feedback_entry(feedback_id: int, identity: IdentityPayload, request: Request):
    """Hard-deletes one feedback entry - nothing else in the app can
    delete feedback at all, this is the first and only such path."""
    require_role(identity.user_profile, Role.ADMIN, Role.EMPLOYEE_ADMIN)
    await enforce_rate_limit(request)

    rows_deleted = await get_db_gateway().feedback_store().delete_feedback(feedback_id)
    return AdminDeleteFeedbackResponse(feedback_id=feedback_id, deleted=rows_deleted > 0)


@router_manage_admin.get("/leave-requests", response_model=PendingHitlRequestsResponse)
async def list_all_leave_requests(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Every leave-request HITL request regardless of status - unlike
    /v1/unpaid-leave/pending, which only ever shows PENDING unpaid-leave
    ones. Reuses the existing list_hitl_requests MCP tool's own
    status='all' support - already there, never wired to an admin-wide
    route until now."""
    require_role(user_profile, Role.ADMIN, Role.EMPLOYEE_ADMIN)

    try:
        data = await _call_mcp_tool_json("list_hitl_requests", {"status": "all", "request_type": "UNPAID_LEAVE_REQUEST"})
    except Exception as error:
        logger.error("Listing all leave requests failed: %s: %s", type(error).__name__, error)
        return json_error(500, "Could not load leave requests. Please try again.", code=error_codes.ADMIN_OPERATION_FAILED)

    return PendingHitlRequestsResponse(
        total=data["total"],
        requests=[
            HitlRequestSummary(
                hitl_request_context_id=item["hitlRequestId"],
                request_type=item["requestType"],
                employee_id=item["employeeId"],
                query=item["query"],
                context=item["context"] or {},
                status=item["status"],
                assigned_to=item["assignedTo"],
                created_at=item["createdAt"],
            )
            for item in data["requests"]
        ],
    )


@router_manage_admin.delete("/leave-requests/{hitl_request_context_id}", response_model=AdminDeleteLeaveRequestResponse)
async def delete_any_leave_request(hitl_request_context_id: int, identity: IdentityPayload, request: Request):
    """Hard-deletes a HITL request and its full cascade (its
    SpecialistLeaveReview, its related LeaveRequest, its
    UnpaidLeaveDocument manifest rows) via hrb_lms_mcp, then deletes the
    real S3 objects for any documents that were linked - best-effort,
    since the database-side delete has already succeeded by that point."""
    require_role(identity.user_profile, Role.ADMIN, Role.EMPLOYEE_ADMIN)
    await enforce_rate_limit(request)

    try:
        result = await admin_delete_hitl_request(hitl_request_context_id)
    except Exception as error:
        logger.error("Deleting HITL request %s failed: %s: %s", hitl_request_context_id, type(error).__name__, error)
        return json_error(500, "The delete could not be completed. Please try again.", code=error_codes.ADMIN_OPERATION_FAILED)

    for s3_key in result.get("deletedDocumentS3Keys", []):
        try:
            delete_leave_document_object(s3_key)
        except Exception as error:
            logger.warning(
                "Deleting S3 object %r for leave request %s failed: %s", s3_key, hitl_request_context_id, error
            )

    return AdminDeleteLeaveRequestResponse(
        hitl_request_context_id=result["hitlRequestId"],
        deleted_hitl_request=result["deletedHitlRequest"],
        deleted_specialist_leave_reviews=result["deletedSpecialistLeaveReviews"],
        deleted_leave_request=result["deletedLeaveRequest"],
        deleted_document_count=len(result.get("deletedDocumentS3Keys", [])),
    )


@router_manage_admin.get("/docs", response_model=AdminDocListResponse)
async def list_admin_docs(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 170 (round 1) - the admin-only docs viewer's own list, backed
    by doc_metadata (populated by scripts/sync_admin_docs.py, not this
    route). Query-param identity (Phase 96) - a GET can't carry a body."""
    require_role(user_profile, Role.ADMIN)

    docs = await get_db_gateway().doc_metadata_store().list_docs()
    return AdminDocListResponse(
        count=len(docs),
        docs=[
            AdminDocSummary(
                id=doc["id"],
                feature_name=doc["feature_name"],
                doc_title=doc["doc_title"],
                doc_type=doc["doc_type"],
                doc_version=doc["doc_version"],
                created_at=doc["created_at"],
                updated_at=doc["updated_at"],
                last_synced_at=doc["last_synced_at"],
            )
            for doc in docs
        ],
    )


@router_manage_admin.get("/docs/{doc_id}/content", response_model=AdminDocContentResponse)
async def get_admin_doc_content(doc_id: int, user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 170 (round 1) - a presigned download URL, not raw content -
    the frontend opens it in a new tab. Query-param identity (Phase 96)."""
    require_role(user_profile, Role.ADMIN)

    doc = await get_db_gateway().doc_metadata_store().get_doc(doc_id)
    if doc is None:
        return json_error(404, f"No doc found with id {doc_id}.", code=error_codes.ADMIN_DOC_NOT_FOUND)

    result = generate_admin_doc_download_url(doc["s3_key"])
    return AdminDocContentResponse(download_url=result["download_url"], expires_in_seconds=result["expires_in_seconds"])


@router_manage_admin.get("/golden-dataset", response_model=GoldenDatasetListResponse)
async def list_golden_dataset(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 181 - the Deployment Dashboard's golden-dataset viewer, read
    from the Postgres mirror scripts/sync_golden_dataset.py keeps in sync
    with resources/golden_dataset/*.json. ADMIN only (Engineering Admin) -
    the Deployment Dashboard is exclusive to that tier, same split as
    /docs. Query-param identity (Phase 96)."""
    require_role(user_profile, Role.ADMIN)

    cases = await get_db_gateway().golden_dataset_store().list_cases()
    return GoldenDatasetListResponse(
        count=len(cases),
        cases=[
            GoldenDatasetCaseSummary(
                id=case["id"],
                case_key=case["case_key"],
                dataset=case["dataset"],
                category=case["category"],
                query=case["query"],
                raw_case=case["raw_case"],
                created_at=case["created_at"],
                updated_at=case["updated_at"],
            )
            for case in cases
        ],
    )


@router_manage_admin.get("/eval-runs", response_model=EvalRunListResponse)
async def list_eval_runs(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 182 - the Deployment Dashboard's Eval Runs list, read from the
    history scripts/run_release_gate.py persists on every real run. ADMIN
    only (Engineering Admin), query-param identity (Phase 96)."""
    require_role(user_profile, Role.ADMIN)

    runs = await get_db_gateway().eval_run_store().list_runs()
    return EvalRunListResponse(
        count=len(runs),
        runs=[
            EvalRunSummary(
                id=run["id"],
                run_at=run["run_at"],
                decision=run["decision"],
                flags=run["flags"],
                aggregated_scores=run["aggregated_scores"],
                total_cases=run["total_cases"],
                scored_cases=run["scored_cases"],
                failed_case_ids=run["failed_case_ids"],
                retrieval_k=run["retrieval_k"],
            )
            for run in runs
        ],
    )


@router_manage_admin.get("/eval-runs/{run_id}", response_model=EvalRunDetail)
async def get_eval_run(run_id: int, user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 182 - one run's full per-case detail. ADMIN only."""
    require_role(user_profile, Role.ADMIN)

    run = await get_db_gateway().eval_run_store().get_run(run_id)
    if run is None:
        return json_error(404, f"No eval run found with id {run_id}.", code=error_codes.ADMIN_EVAL_RUN_NOT_FOUND)

    return EvalRunDetail(
        id=run["id"],
        run_at=run["run_at"],
        decision=run["decision"],
        flags=run["flags"],
        aggregated_scores=run["aggregated_scores"],
        total_cases=run["total_cases"],
        scored_cases=run["scored_cases"],
        failed_case_ids=run["failed_case_ids"],
        retrieval_k=run["retrieval_k"],
        cases=[
            EvalRunCaseDetail(case_id=case["case_id"], category=case["category"], scores=case["scores"], status=case["status"])
            for case in run["cases"]
        ],
    )


def _to_workflow_status(result: dict) -> WorkflowStatus:
    return WorkflowStatus(
        runs=[WorkflowRunSummary(**run) for run in result["runs"]],
        error=result["error"],
    )


@router_manage_admin.get("/ci-status", response_model=CiStatusResponse)
async def get_ci_status(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 183 - the Deployment Dashboard's CI/Build Status tab, a live
    read of this repo's own ci.yml/deploy.yml GitHub Actions runs. ADMIN
    only. Never 500s on a GitHub-side failure (unset token, rate limit,
    network) - each workflow's own `error` field carries that instead,
    same error-as-data convention every external client here follows."""
    require_role(user_profile, Role.ADMIN)

    github = get_client_gateway().github_actions()
    ci_result = github.list_workflow_runs("ci.yml")
    deploy_result = github.list_workflow_runs("deploy.yml")

    return CiStatusResponse(ci=_to_workflow_status(ci_result), deploy=_to_workflow_status(deploy_result))


@router_manage_admin.get("/request-metrics", response_model=RequestMetricsResponse)
async def get_request_metrics(
    window: int = 24, user_profile: UserProfile | None = Depends(identity_from_query_params)
):
    """Phase 184 - the Deployment Dashboard's Live Metrics tab, aggregated
    over the last `window` hours (default 24). ADMIN only. cost_usd is
    intentionally absent from this response - no verified per-model price
    table exists in this project yet, so it's never estimated here."""
    require_role(user_profile, Role.ADMIN)

    result = await get_db_gateway().request_metrics_store().aggregate(window)
    return RequestMetricsResponse(
        window_hours=result["window_hours"],
        rows=[
            PipelineMetricsRow(
                pipeline=row["pipeline"],
                status=row["status"],
                request_count=row["request_count"],
                avg_latency_ms=row["avg_latency_ms"],
                p50_latency_ms=row["p50_latency_ms"],
                p95_latency_ms=row["p95_latency_ms"],
                total_tokens=row["total_tokens"],
            )
            for row in result["rows"]
        ],
    )


FAQ_REVIEW_ROLES = (Role.HR_SUPPORT, Role.ADMIN, Role.EMPLOYEE_ADMIN)

RESTRUCTURE_SYSTEM_PROMPT = (
    "You restructure a raw, real-time LLM answer into a clean, publishable FAQ entry for an HR benefits "
    "chatbot. Keep every real fact from the original answer - never add, remove, or guess a fact. Write "
    "in plain, concise language a new employee could follow. Return only the restructured answer text, "
    "no preamble, no markdown headers."
)


@router_manage_admin.get("/faq-submissions", response_model=FaqSubmissionListResponse)
async def list_faq_submissions(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 186 - the FAQ-submission review queue. HR Support reviews
    content same as it already does for leave requests; both admin tiers
    see everything. Query-param identity (Phase 96)."""
    require_role(user_profile, *FAQ_REVIEW_ROLES)

    rows = await get_db_gateway().faq_submission_store().list_submissions()
    return FaqSubmissionListResponse(count=len(rows), submissions=[FaqSubmissionRecord(**row) for row in rows])


@router_manage_admin.post("/faq-submissions/{submission_id}/restructure", response_model=FaqSubmissionRecord)
async def restructure_faq_submission(submission_id: int, payload: FaqRestructureRequest):
    """Phase 186 - asks Claude to turn the raw real-time answer into a
    publishable draft. Never auto-published - the reviewer's own /review
    call is still required to accept, edit, or reject it."""
    require_role(payload.user_profile, *FAQ_REVIEW_ROLES)

    store = get_db_gateway().faq_submission_store()
    submission = await store.get_submission(submission_id)
    if submission is None:
        return json_error(404, f"No FAQ submission found with id {submission_id}.", code=error_codes.ADMIN_FAQ_SUBMISSION_NOT_FOUND)
    if not submission.get("external_llm_answer"):
        return json_error(
            422,
            "This submission has no first-pass answer to restructure yet.",
            code=error_codes.VALIDATION_ERROR,
        )

    try:
        # ask() is a blocking SDK call (same as every other LLM client
        # here) - run off the event loop, not inline in an async route.
        restructured = await asyncio.to_thread(
            get_client_gateway().anthropic_chat().ask,
            submission["query"],
            submission["external_llm_answer"],
            RESTRUCTURE_SYSTEM_PROMPT,
        )
    except Exception as error:
        logger.error("FAQ restructuring failed for submission %s: %s: %s", submission_id, type(error).__name__, error)
        return json_error(500, "Could not restructure this answer. Please try again.", code=error_codes.QUERY_FAILED)

    updated = await store.update_restructured_answer(submission_id, restructured)
    return FaqSubmissionRecord(**updated)


@router_manage_admin.post("/faq-submissions/{submission_id}/review", response_model=FaqSubmissionRecord)
async def review_faq_submission(submission_id: int, payload: FaqReviewRequest):
    """Phase 186 - the human's own decision, overwriting or confirming
    whatever /restructure suggested."""
    user = require_role(payload.user_profile, *FAQ_REVIEW_ROLES)

    store = get_db_gateway().faq_submission_store()
    submission = await store.get_submission(submission_id)
    if submission is None:
        return json_error(404, f"No FAQ submission found with id {submission_id}.", code=error_codes.ADMIN_FAQ_SUBMISSION_NOT_FOUND)

    # "human_edited" if the reviewer changed what /restructure suggested
    # (or wrote one from scratch when restructuring was never run),
    # "finalized" if they accepted it as-is.
    restructuring_status = (
        "human_edited"
        if payload.final_answer != submission.get("final_answer")
        else submission.get("answer_restructuring_status", "finalized")
    )
    if restructuring_status == "claude_restructured" and payload.final_answer == submission.get("final_answer"):
        restructuring_status = "finalized"

    updated = await store.review_submission(
        submission_id,
        internal_review_status=payload.internal_review_status,
        final_answer=payload.final_answer,
        published=payload.published,
        reviewed_by=user.employee_id,
        restructuring_status=restructuring_status,
    )
    return FaqSubmissionRecord(**updated)


@router_manage_admin.get("/interview-qa", response_model=InterviewQaListResponse)
async def list_interview_qa_cards(
    topic: str | None = None, user_profile: UserProfile | None = Depends(identity_from_query_params)
):
    """Phase 187 - Interview Q&A as real, editable rows (not a static-file
    mirror). ADMIN only (Engineering Admin) - dev-reference content
    management, not HR-facing. Query-param identity (Phase 96)."""
    require_role(user_profile, Role.ADMIN)

    rows = await get_db_gateway().interview_qa_store().list_cards(topic)
    return InterviewQaListResponse(count=len(rows), cards=[InterviewQaCard(**row) for row in rows])


@router_manage_admin.get("/interview-qa/{card_id}", response_model=InterviewQaCard)
async def get_interview_qa_card(card_id: int, user_profile: UserProfile | None = Depends(identity_from_query_params)):
    require_role(user_profile, Role.ADMIN)

    row = await get_db_gateway().interview_qa_store().get_card(card_id)
    if row is None:
        return json_error(404, f"No interview Q&A card found with id {card_id}.", code=error_codes.ADMIN_INTERVIEW_QA_NOT_FOUND)
    return InterviewQaCard(**row)


@router_manage_admin.post("/interview-qa", response_model=InterviewQaCard)
async def create_interview_qa_card(payload: CreateInterviewQaRequest):
    require_role(payload.user_profile, Role.ADMIN)

    row = await get_db_gateway().interview_qa_store().create_card(payload.fields.model_dump())
    return InterviewQaCard(**row)


@router_manage_admin.put("/interview-qa/{card_id}", response_model=InterviewQaCard)
async def update_interview_qa_card(card_id: int, payload: UpdateInterviewQaRequest):
    require_role(payload.user_profile, Role.ADMIN)

    row = await get_db_gateway().interview_qa_store().update_card(card_id, payload.fields.model_dump())
    if row is None:
        return json_error(404, f"No interview Q&A card found with id {card_id}.", code=error_codes.ADMIN_INTERVIEW_QA_NOT_FOUND)
    return InterviewQaCard(**row)


@router_manage_admin.delete("/interview-qa/{card_id}", response_model=DeleteInterviewQaResponse)
async def delete_interview_qa_card(card_id: int, identity: IdentityPayload, request: Request):
    require_role(identity.user_profile, Role.ADMIN)
    await enforce_rate_limit(request)

    deleted = await get_db_gateway().interview_qa_store().delete_card(card_id)
    return DeleteInterviewQaResponse(id=card_id, deleted=deleted)
