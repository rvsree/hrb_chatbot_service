"""Phase 162 - "Request Unpaid Leave". Deliberately separate from both the
GenAI Chat Workflow (not touched this phase, per explicit user direction)
and the other 3 RAG pipelines - this is a structured form submission routed
through a small LangGraph graph + hrb_lms_mcp's HITL machinery, not a chat
question.

Phase 165 expanded this past UNPAID-only (CRITICAL_CAREGIVER/STD/LTD added),
closed the no-notification/no-document-review gaps (email on resolve + a
real download link), and added an employee-facing "My Requests" view."""

import json
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from src.hrb_chatbot.ai.agents.workflow_agents.unpaid_leave_agent import (
    resume_unpaid_leave_decision,
    run_unpaid_leave_request,
)
from src.hrb_chatbot.ai.rag_pipeline.tools.mcp_tools import (
    _call_mcp_tool,
    list_all_leave_requests,
    list_leave_documents,
    list_my_leave_requests,
    register_leave_document,
)
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import identity_from_query_params, require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.clients.storage_client.s3_upload_client import (
    generate_leave_document_download_url,
    generate_leave_document_upload_url,
)
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.common import UserProfile
from src.hrb_chatbot.models.unpaid_leave import (
    HitlRequestSummary,
    HrLeaveRequestsResponse,
    HrLeaveRequestSummary,
    LeaveDocumentDownloadUrlResponse,
    LeaveDocumentUploadUrlRequest,
    LeaveDocumentUploadUrlResponse,
    MyLeaveRequestsResponse,
    MyLeaveRequestSummary,
    PendingHitlRequestsResponse,
    ResolveHitlRequestBody,
    ResolveHitlRequestResponse,
    UnpaidLeaveRequestBody,
    UnpaidLeaveRequestResponse,
)

logger = get_logger("leave.unpaid_leave")

router_unpaid_leave = APIRouter(tags=["unpaid-leave"])


@router_unpaid_leave.post("/upload-url", response_model=LeaveDocumentUploadUrlResponse)
async def get_leave_document_upload_url(payload: LeaveDocumentUploadUrlRequest, request: Request):
    # Phase 165 (round 2) - HR_SUPPORT deliberately excluded. Confirmed
    # live as a real gap, not theoretical: an hr_support persona could
    # submit a leave request through this same flow before this fix -
    # they review requests (see /pending, /resolve below), they don't
    # file their own through this entry point. Phase 178 added ADMIN -
    # the superuser role, unlike HR_SUPPORT, is meant to reach every
    # feature including this one; HR_SUPPORT's own exclusion is untouched.
    user = require_role(payload.user_profile, Role.EMPLOYEE, Role.MANAGER, Role.ADMIN)
    await enforce_rate_limit(request)

    token = uuid.uuid4().hex
    result = generate_leave_document_upload_url(token, payload.filename, payload.content_type)

    # Phase 165 - registers the manifest row immediately, before the leave
    # request it will belong to exists - closes a real orphan-upload gap
    # (the employee-side flow uploads to S3 before calling /request; a
    # failed submit after a successful upload used to leave nothing in any
    # database pointing at the file). Best-effort: the upload itself has
    # already succeeded by this point (the presigned URL is already
    # returned below either way), so a manifest-registration failure here
    # shouldn't block the upload flow - it just means this one file won't
    # be orphan-trackable, not that the whole feature breaks.
    try:
        await register_leave_document(user.employee_id, result["key"], payload.filename, payload.content_type)
    except Exception as error:
        logger.warning("Registering leave document manifest for key=%r failed: %s", result["key"], error)

    return LeaveDocumentUploadUrlResponse(**result)


@router_unpaid_leave.post("/request", response_model=UnpaidLeaveRequestResponse)
async def submit_unpaid_leave(payload: UnpaidLeaveRequestBody, request: Request):
    # Phase 165 (round 2) - same HR_SUPPORT exclusion as /upload-url above.
    # Phase 178 - same ADMIN addition as /upload-url above.
    user = require_role(payload.user_profile, Role.EMPLOYEE, Role.MANAGER, Role.ADMIN)
    await enforce_rate_limit(request)

    try:
        result = await run_unpaid_leave_request(
            employee_id=user.employee_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            purpose=payload.purpose,
            leave_type_code=payload.leave_type_code.value,
            document_reference=payload.document_reference,
        )
    except Exception as error:
        logger.error("Unpaid leave request failed for %r: %s: %s", user.employee_id, type(error).__name__, error)
        return json_error(500, "The leave request could not be submitted. Please try again.", code=error_codes.LEAVE_REQUEST_FAILED)

    return UnpaidLeaveRequestResponse(
        request_id=result["requestId"],
        employee_id=result["employeeId"],
        leave_type=result["leaveType"],
        status=result["status"],
        is_repeat_within_12_months=result["isRepeatWithin12Months"],
        hitl_request_context_id=result["hitlRequestId"],
        hitl_status=result["hitlStatus"],
        days=result["days"],
    )


@router_unpaid_leave.get("/pending", response_model=PendingHitlRequestsResponse)
async def list_pending_unpaid_leave_requests(user_profile: str, request: Request):
    """Query-param identity, matching ingest_document.py's 3 GET routes
    (Phase 96) - a GET route can't carry a body at all."""
    try:
        parsed_profile = UserProfile.model_validate_json(user_profile)
    except ValidationError:
        return json_error(422, "user_profile is not valid JSON, or doesn't match the expected shape.", code=error_codes.VALIDATION_ERROR)

    require_role(parsed_profile, Role.HR_SUPPORT, Role.ADMIN)
    await enforce_rate_limit(request)

    try:
        mcp_result = await _call_mcp_tool(
            "list_hitl_requests", {"status": "PENDING", "request_type": "UNPAID_LEAVE_REQUEST"}
        )
        data = json.loads(mcp_result["content"][0])
    except Exception as error:
        logger.error("Listing pending unpaid leave requests failed: %s: %s", type(error).__name__, error)
        return json_error(500, "Could not load pending leave requests. Please try again.", code=error_codes.LEAVE_REQUEST_FAILED)

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


@router_unpaid_leave.get("/all", response_model=HrLeaveRequestsResponse)
async def list_all_unpaid_leave_requests(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 168 (round 2) - the HR specialist grid: every leave request
    across every employee, any status, with full review detail -
    /pending above only ever shows PENDING unpaid-leave ones. Query-param
    identity (Phase 96), same as every other GET route here. Also ADMIN-
    accessible (round 3) - the admin dashboard's own Leave Requests tab
    reuses this exact route/shape rather than the narrower generic-HITL
    one /v1/admin/leave-requests returns, for the same richer popup."""
    require_role(user_profile, Role.HR_SUPPORT, Role.ADMIN)

    try:
        data = await list_all_leave_requests(status="all")
    except Exception as error:
        logger.error("Listing all leave requests failed: %s: %s", type(error).__name__, error)
        return json_error(500, "Could not load leave requests. Please try again.", code=error_codes.LEAVE_REQUEST_FAILED)

    return HrLeaveRequestsResponse(
        total=data["total"],
        requests=[
            HrLeaveRequestSummary(
                hitl_request_context_id=item["hitlRequestId"],
                request_id=item["requestId"],
                employee_id=item["employeeId"],
                employee_name=item["employeeName"],
                leave_type=item["leaveType"],
                start_date=item["startDate"],
                end_date=item["endDate"],
                days=item["days"],
                purpose=item["purpose"],
                status=item["status"],
                decision=item["decision"],
                hr_comments=item["hrComments"],
                hr_specialist_name=item["hrSpecialistName"],
                created_at=item["createdAt"],
                responded_at=item["respondedAt"],
                task_state=item.get("taskState"),
                review_brief=item.get("reviewBrief"),
                decision_message=item.get("decisionMessage"),
                produced_artifacts=item.get("producedArtifacts") or [],
            )
            for item in data["requests"]
        ],
    )


@router_unpaid_leave.post("/resolve", response_model=ResolveHitlRequestResponse)
async def resolve_unpaid_leave_request(payload: ResolveHitlRequestBody, request: Request):
    # Phase 178 - deliberately NOT widened to ADMIN here, unlike the other
    # routes in this file. This is the actual HR-decision action
    # LeaveReviewModal.tsx's Phase 168-round-3 design keeps admin out of
    # ("admins manage/clean up data, they don't make HR decisions") -
    # flagged as a conflict with "admin is a superuser," not resolved yet.
    user = require_role(payload.user_profile, Role.HR_SUPPORT)
    await enforce_rate_limit(request)

    try:
        # Phase 172 - resumes the SAME paused graph run run_unpaid_leave_request()
        # left checkpointed (not a fresh unrelated call). finalize_node, run
        # as part of this resume, now also sends the decision email and
        # records it as a produced artifact - moved out of this route and
        # into the graph itself, since that's genuinely part of the
        # resumed Task's own work.
        result = await resume_unpaid_leave_decision(
            hitl_request_context_id=payload.hitl_request_context_id,
            decision=payload.decision,
            response_text=payload.response_text,
            resolved_by=user.full_name,
            resolved_by_employee_id=user.employee_id,
        )
    except Exception as error:
        logger.error(
            "Resolving HITL request %s failed: %s: %s", payload.hitl_request_context_id, type(error).__name__, error
        )
        return json_error(500, "The decision could not be recorded. Please try again.", code=error_codes.HITL_RESOLUTION_FAILED)

    return ResolveHitlRequestResponse(
        hitl_request_context_id=result["hitlRequestId"],
        status=result["status"],
        decision=result["decision"],
        response=result["response"],
        related_leave_request_updated=result["relatedLeaveRequestUpdated"],
    )


@router_unpaid_leave.get("/my-requests", response_model=MyLeaveRequestsResponse)
async def list_my_unpaid_leave_requests(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 165 - the employee's own "My Requests" view. Query-param
    identity (Phase 96), same as /pending above - a GET can't carry a body.
    HR_SUPPORT excluded (round 2) - same reasoning as /upload-url and
    /request above, they never submit their own requests through this flow.
    Phase 178 - same ADMIN addition as /upload-url above."""
    user = require_role(user_profile, Role.EMPLOYEE, Role.MANAGER, Role.ADMIN)

    try:
        data = await list_my_leave_requests(user.employee_id)
    except Exception as error:
        logger.error("Listing my leave requests failed for %r: %s: %s", user.employee_id, type(error).__name__, error)
        return json_error(500, "Could not load your leave requests. Please try again.", code=error_codes.LEAVE_REQUEST_FAILED)

    return MyLeaveRequestsResponse(
        total=data["total"],
        requests=[
            MyLeaveRequestSummary(
                request_id=item["requestId"],
                leave_type=item["leaveType"],
                start_date=item["startDate"],
                end_date=item["endDate"],
                days=item["days"],
                purpose=item["purpose"],
                status=item["status"],
                decision=item["decision"],
                hr_comments=item["hrComments"],
                hr_specialist_name=item["hrSpecialistName"],
                created_at=item["createdAt"],
                responded_at=item["respondedAt"],
                task_state=item.get("taskState"),
                review_brief=item.get("reviewBrief"),
                decision_message=item.get("decisionMessage"),
                produced_artifacts=item.get("producedArtifacts") or [],
            )
            for item in data["requests"]
        ],
    )


@router_unpaid_leave.get("/documents/{leave_request_id}", response_model=LeaveDocumentDownloadUrlResponse)
async def get_leave_document_download_url(
    leave_request_id: int, user_profile: UserProfile | None = Depends(identity_from_query_params)
):
    """Phase 165 - closes the "HR reviewers can't actually open the
    attached document" gap. Ownership-checked on top of the role check
    (Role alone only proves "an employee" or "hr_support," never "this
    specific caller may see this specific request's document") - without
    it, any employee could fetch any other employee's document just by
    guessing a leave_request_id."""
    user = require_role(user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)

    try:
        data = await list_leave_documents(leave_request_id)
    except Exception as error:
        logger.error("Listing documents for leave_request_id=%s failed: %s: %s", leave_request_id, type(error).__name__, error)
        return json_error(500, "Could not load the document. Please try again.", code=error_codes.LEAVE_REQUEST_FAILED)

    is_owner = data.get("ownerEmployeeId") == user.employee_id
    # Phase 178 - ADMIN sees every document the same way HR_SUPPORT does,
    # matching list_all_unpaid_leave_requests()'s own ADMIN-visibility.
    is_specialist = user.role in (Role.HR_SUPPORT, Role.ADMIN)
    if not (is_owner or is_specialist):
        return json_error(403, "You don't have access to this document.", code=error_codes.FORBIDDEN)

    documents = data.get("documents") or []
    if not documents:
        return json_error(404, "No document found for that leave request.", code=error_codes.LEAVE_DOCUMENT_NOT_FOUND)

    # One document per request in practice today (the upload form takes a
    # single file) - the manifest table itself supports more than one, so
    # this takes the most recently uploaded if there's ever more than one.
    document = documents[-1]
    download = generate_leave_document_download_url(document["s3Key"])

    return LeaveDocumentDownloadUrlResponse(
        download_url=download["download_url"],
        original_filename=document["originalFilename"],
        expires_in_seconds=download["expires_in_seconds"],
    )
