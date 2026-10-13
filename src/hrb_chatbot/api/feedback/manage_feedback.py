"""Feedback storage (Phase 104). POST takes identity in the body, same as
every other POST route. GET takes identity as query params (Phase 96) - a
real browser GET can't carry a body at all."""

from fastapi import APIRouter, Depends, Request

from src.hrb_chatbot.api.gateway.rbac import identity_from_query_params, require_role
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.common import UserProfile
from src.hrb_chatbot.models.feedback import (
    FeedbackCreateRequest,
    FeedbackCreateResponse,
    FeedbackListResponse,
    FeedbackRecord,
)

logger = get_logger("feedback.manage_feedback")

router_manage_feedback = APIRouter(tags=["feedback"])


@router_manage_feedback.post("", response_model=FeedbackCreateResponse)
async def create_feedback(payload: FeedbackCreateRequest, request: Request):
    userProfile = require_role(payload.user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)
    await enforce_rate_limit(request)

    feedback_id = await get_db_gateway().feedback_store().save_feedback(
        userProfile.employee_id,
        payload.conversation_id,
        payload.message_id,
        payload.vote.value,
        payload.reason_tags,
        payload.notes,
        payload.question,
        payload.answer,
    )

    return FeedbackCreateResponse(id=feedback_id)


@router_manage_feedback.get("", response_model=FeedbackListResponse)
async def list_feedback(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """hr_support/admin see everyone's feedback; employee/manager only see their own."""
    userProfile = require_role(user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)

    scope_employee_id = None if userProfile.role in (Role.HR_SUPPORT, Role.ADMIN) else userProfile.employee_id
    rows = await get_db_gateway().feedback_store().list_feedback(scope_employee_id)

    return FeedbackListResponse(count=len(rows), feedback=[FeedbackRecord(**row) for row in rows])
