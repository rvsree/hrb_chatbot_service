"""Conversation history data management (Phase 76/116). Calls
ai/pre_processing/conversation_memory.py directly, same precedent as
retrieve_document.py - no service layer, since there's no logic beyond
the one function call each route makes (rag_service.py was removed for
exactly this reason - a pass-through with no logic of its own)."""

from fastapi import APIRouter, Depends, Request

from src.hrb_chatbot.ai.pre_processing import conversation_memory
from src.hrb_chatbot.api.gateway.rbac import identity_from_query_params, require_role
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.common import IdentityPayload, UserProfile
from src.hrb_chatbot.models.conversations import (
    ConversationDeleteResponse,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummary,
    ConversationTurn,
)

logger = get_logger("conversations.manage_conversations")

router_manage_conversations = APIRouter(tags=["conversations"])


@router_manage_conversations.get("", response_model=ConversationListResponse)
async def list_conversations(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Phase 116 - the caller's own conversations only, scoped by employee_id.
    No hr_support "everyone's conversations" view, unlike feedback - a chat
    history is more sensitive than a thumbs-up/down vote, and nothing asked
    for HR to browse other employees' conversations."""
    userProfile = require_role(user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)

    rows = await conversation_memory.list_conversations(userProfile.employee_id)
    return ConversationListResponse(count=len(rows), conversations=[ConversationSummary(**row) for row in rows])


@router_manage_conversations.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str, user_profile: UserProfile | None = Depends(identity_from_query_params)
):
    """Phase 116 - a conversation that isn't the caller's own (or doesn't
    exist) returns an empty turns list, same not-found-vs-not-yours
    non-disclosure as DELETE's own scoping."""
    userProfile = require_role(user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)

    turns = await conversation_memory.get_conversation_turns(conversation_id, userProfile.employee_id)
    return ConversationDetailResponse(
        conversation_id=conversation_id, turns=[ConversationTurn(**turn) for turn in turns]
    )


@router_manage_conversations.delete("/{conversation_id}", response_model=ConversationDeleteResponse)
async def delete_conversation(conversation_id: str, identity: IdentityPayload, request: Request):
    """Deletes every turn for one conversation - scoped to the caller's own employee_id,
    so one employee can never delete another's history even by knowing their conversation_id."""
    userProfile = require_role(identity.user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)
    await enforce_rate_limit(request)

    turns_deleted = await conversation_memory.delete_conversation(conversation_id, userProfile.employee_id)
    # Phase 112: purge whatever cache entries this conversation's own
    # turns depended on - best-effort, never raises (see answer_cache.py).
    await get_db_gateway().answer_cache().clear_for_conversation(conversation_id)

    return ConversationDeleteResponse(conversation_id=conversation_id, turns_deleted=turns_deleted)
