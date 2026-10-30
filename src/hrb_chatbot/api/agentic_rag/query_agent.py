"""Single-agentic-rag - a tool-calling agent, not a fixed retrieve-then-generate pipeline."""

from fastapi import APIRouter, Request

from src.hrb_chatbot.ai.agents.workflow_agents.orchestration_agent import run_agent
from src.hrb_chatbot.ai.rag_core.demo_query_limiter import DemoQueryLimitExceededError
from src.hrb_chatbot.ai.search_pre_processing.guardrails_input import GuardrailBlockedError
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.observability.response_metrics import time_and_log
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.common.utils.request_ip import resolve_client_ip
from src.hrb_chatbot.models.agentic_rag import AgenticRagRequest, AgenticRagResponse
from src.hrb_chatbot.models.common import ToolCallInfo
from src.hrb_chatbot.models.rag import DemoLimitInfo, EvalScores, ExplainabilityInfo, LatencyInfo, LlmContextInfo, TokenUsageInfo

logger = get_logger("query_agent")

router_query_agent = APIRouter(tags=["single-agentic-rag"])


@router_query_agent.post("/query", response_model=AgenticRagResponse)
async def query(payload: AgenticRagRequest, request: Request):
    userProfile = require_role(payload.user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)
    await enforce_rate_limit(request)

    try:
        result = await time_and_log(
            "/v1/single-agentic-rag-retrieval/query",
            "single-agentic-rag",
            lambda request_id: run_agent(
                payload.query,
                userProfile.employee_id,
                payload.max_iterations,
                enable_conversation_memory=payload.enable_conversation_memory,
                conversation_id=payload.conversation_id,
                request_id=request_id,
                judge_model=payload.eval_options.judge_model if payload.eval_options else None,
                eval_score_threshold=payload.eval_options.eval_score_threshold if payload.eval_options else None,
                search_strategy=payload.search_strategy,
                role=userProfile.role,
                department=userProfile.department,
                guardrails_model=payload.guardrails_model,
                full_name=userProfile.full_name,
                ip_address=resolve_client_ip(request),
                timezone=userProfile.timezone,
            ),
            lambda r: (r.get("token_usage") or {}).get("total_tokens"),
        )
    except GuardrailBlockedError as error:
        return json_error(422, str(error), code=error_codes.INPUT_GUARDRAIL_BLOCKED)
    except DemoQueryLimitExceededError as error:
        return json_error(429, str(error), code=error_codes.DEMO_QUERY_LIMIT_REACHED)
    except ValueError as error:
        return json_error(422, str(error), code=error_codes.VALIDATION_ERROR)

    token_usage = result.get("token_usage")
    eval_scores = result.get("eval_scores")
    llm_context = result.get("llm_context")
    return AgenticRagResponse(
        query=result.get("query", payload.query),
        answer=result["answer"],
        tools_used=[ToolCallInfo(**call) for call in result["tools_used"]],
        sources=result.get("sources") or [],
        iterations=result["iterations"],
        explainability_info=ExplainabilityInfo(
            request_id=result["request_id"],
            served_from_cache=result["served_from_cache"],
            llm_call_count=result["llm_call_count"],
            latency_ms=LatencyInfo(**result["latency_ms"]),
            token_usage=TokenUsageInfo(**token_usage) if token_usage else None,
            llm_context=LlmContextInfo(**llm_context) if llm_context else None,
            routed_to=None,
            eval_scores=EvalScores(**eval_scores) if eval_scores else None,
            guardrails=result["guardrails"],
            guardrails_model_used=result.get("guardrails_model_used"),
        ),
        conversation_id=result.get("conversation_id"),
        demo_limit=DemoLimitInfo(**result["demo_limit"]) if result.get("demo_limit") else None,
    )
