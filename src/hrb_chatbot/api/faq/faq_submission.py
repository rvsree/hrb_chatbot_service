"""Phase 186 - employee-facing FAQ submission: a real-time tool-using LLM
first-pass answer now, a human/Claude review pass later (see
api/admin/manage_admin.py's own /faq-submissions routes for that side)."""

from fastapi import APIRouter, Depends, Request

from src.hrb_chatbot.ai.agents.workflow_agents.orchestration_agent import run_agent
from src.hrb_chatbot.api.gateway.rbac import identity_from_query_params, require_role
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.common import UserProfile
from src.hrb_chatbot.models.faq import (
    FaqSubmissionRecord,
    FaqSubmitRequest,
    PublishedFaq,
    PublishedFaqListResponse,
)

logger = get_logger("faq_submission")

router_faq_submission = APIRouter(tags=["faq"])


@router_faq_submission.post("/submit", response_model=FaqSubmissionRecord)
async def submit_faq_question(payload: FaqSubmitRequest, request: Request):
    """Any authenticated role can submit a question. Gets a real-time
    tool-using LLM first-pass answer (reusing single-agentic-rag's own
    run_agent() - no new LLM-calling path) before a human/Claude review
    pass makes it a published FAQ."""
    user = require_role(payload.user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN, Role.EMPLOYEE_ADMIN)
    await enforce_rate_limit(request)

    external_llm_answer = None
    try:
        result = await run_agent(payload.query, user.employee_id, enable_conversation_memory=False)
        external_llm_answer = result.get("answer")
    except Exception as error:
        # The employee's question is still recorded even if the real-time
        # first-pass answer fails - a lost LLM call must never lose the
        # submission itself.
        logger.warning("FAQ submission's first-pass answer failed for %r: %s", payload.query, error)

    row = await get_db_gateway().faq_submission_store().create_submission(
        user.employee_id, payload.query, external_llm_answer
    )
    return FaqSubmissionRecord(**row)


@router_faq_submission.get("/published", response_model=PublishedFaqListResponse)
async def list_published_faqs(user_profile: UserProfile | None = Depends(identity_from_query_params)):
    """Any authenticated role. Query-param identity (Phase 96) - a GET
    route can't carry a body. Only the 2 public-facing fields - none of
    the review-workflow internals."""
    require_role(user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN, Role.EMPLOYEE_ADMIN)

    rows = await get_db_gateway().faq_submission_store().list_published()
    return PublishedFaqListResponse(count=len(rows), faqs=[PublishedFaq(**row) for row in rows])
