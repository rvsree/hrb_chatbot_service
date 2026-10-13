"""Phase 168 - the admin dashboard's own routes: view + hard-delete across
KB documents, conversations, feedback, and leave requests/HITL reviews.
ADMIN role only, throughout - a "manage the application" super-user,
deliberately separate from HR_SUPPORT (reviews leave requests) and from
every other role. KB documents aren't duplicated here at all - the
existing ingest_document.py routes were widened to also accept ADMIN
instead, since they already did unscoped list/delete with nothing left to
add. This router exists for the 3 categories that didn't already have an
admin-usable list+delete: conversations, feedback, leave requests/HITL."""

import json

from fastapi import APIRouter, Depends, Request

from src.hrb_chatbot.ai.pre_processing import conversation_memory
from src.hrb_chatbot.ai.rag_pipeline.tools.mcp_tools import _call_mcp_tool, admin_delete_hitl_request
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import identity_from_query_params, require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
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
)
from src.hrb_chatbot.models.common import IdentityPayload, UserProfile
from src.hrb_chatbot.models.conversations import ConversationDetailResponse, ConversationTurn
from src.hrb_chatbot.models.feedback import FeedbackListResponse, FeedbackRecord
from src.hrb_chatbot.models.unpaid_leave import HitlRequestSummary, PendingHitlRequestsResponse

logger = get_logger("admin.manage_admin")

router_manage_admin = APIRouter(tags=["admin"])


@router_manage_admin.get("/conversations", response_model=AdminConversationListResponse)
async def list_all_conversations(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Every conversation across every employee - the one legitimate
    "see everyone's" case for this data, gated to ADMIN only."""
    require_role(user_profile, Role.ADMIN)

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
    require_role(user_profile, Role.ADMIN)

    turns = await conversation_memory.get_conversation_turns_any(conversation_id)
    return ConversationDetailResponse(
        conversation_id=conversation_id, turns=[ConversationTurn(**turn) for turn in turns]
    )


@router_manage_admin.delete("/conversations/{conversation_id}", response_model=AdminDeleteConversationResponse)
async def delete_any_conversation(conversation_id: str, identity: IdentityPayload, request: Request):
    """Deletes a conversation regardless of which employee it belongs to."""
    require_role(identity.user_profile, Role.ADMIN)
    await enforce_rate_limit(request)

    turns_deleted = await conversation_memory.delete_conversation_any(conversation_id)
    return AdminDeleteConversationResponse(conversation_id=conversation_id, turns_deleted=turns_deleted)


@router_manage_admin.get("/feedback", response_model=FeedbackListResponse)
async def list_all_feedback(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Every feedback entry across every employee - reuses the existing
    list_feedback(employee_id=None) path hr_support already gets."""
    require_role(user_profile, Role.ADMIN)

    rows = await get_db_gateway().feedback_store().list_feedback(None)
    return FeedbackListResponse(count=len(rows), feedback=[FeedbackRecord(**row) for row in rows])


@router_manage_admin.delete("/feedback/{feedback_id}", response_model=AdminDeleteFeedbackResponse)
async def delete_feedback_entry(feedback_id: int, identity: IdentityPayload, request: Request):
    """Hard-deletes one feedback entry - nothing else in the app can
    delete feedback at all, this is the first and only such path."""
    require_role(identity.user_profile, Role.ADMIN)
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
    require_role(user_profile, Role.ADMIN)

    try:
        mcp_result = await _call_mcp_tool("list_hitl_requests", {"status": "all", "request_type": "UNPAID_LEAVE_REQUEST"})
        data = json.loads(mcp_result["content"][0])
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
    require_role(identity.user_profile, Role.ADMIN)
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
