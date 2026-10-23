"""Phase 240 - auto-routes to single-agentic-rag or multi-agentic-rag based on
a cheap classification step (ai/search_pre_processing/mode_router.py), with
escalation to multi-agentic-rag if single-agentic-rag's own result looks weak.
Additive - single-agentic-rag-retrieval/multi-agentic-rag-retrieval stay
exactly as they are, forced-mode. See RAG-ROADMAP.md Phase 240 /
endpoint-request-response-contracts.md."""

from fastapi import APIRouter, Request

from src.hrb_chatbot.ai.agents.workflow_agents import multi_agent_pipeline
from src.hrb_chatbot.ai.agents.workflow_agents.orchestration_agent import run_agent
from src.hrb_chatbot.ai.search_pre_processing.context_assembly import assemble_context
from src.hrb_chatbot.ai.search_pre_processing.guardrails_input import GuardrailBlockedError
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.observability.response_metrics import time_and_log
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.agentic_rag import AgenticRagRequest, AgenticRagResponse
from src.hrb_chatbot.models.common import ToolCallInfo
from src.hrb_chatbot.models.multi_agentic_rag import AgentTaskInfo, MultiAgenticRagResponse
from src.hrb_chatbot.models.rag import EvalScores, ExplainabilityInfo, LatencyInfo, LlmContextInfo, TokenUsageInfo

logger = get_logger("rag.auto_route_query")

router_auto_route_query = APIRouter(tags=["rag-retrieval"])


def _should_escalate(result: dict) -> bool:
    """Phase 240's resolved escalation rule: no tool calls at all, or a live
    groundedness/completeness score below AUTO_ROUTER_ESCALATION_THRESHOLD -
    a separate, internal-only setting from eval_options.eval_score_threshold,
    which is a caller-facing flag, not a routing trigger."""
    if not result.get("tools_used"):
        return True
    eval_scores = result.get("eval_scores")
    if not eval_scores:
        return False
    threshold = float(read_setting(None, "AUTO_ROUTER_ESCALATION_THRESHOLD", 0.5))
    groundedness = eval_scores.get("groundedness")
    completeness = eval_scores.get("completeness")
    if groundedness is not None and groundedness < threshold:
        return True
    if completeness is not None and completeness < threshold:
        return True
    return False


def _build_agentic_response(result: dict, resolved_mode: str) -> AgenticRagResponse:
    token_usage = result.get("token_usage")
    eval_scores = result.get("eval_scores")
    llm_context = result.get("llm_context")
    return AgenticRagResponse(
        query=result.get("query"),
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
        resolved_mode=resolved_mode,
    )


def _build_multi_agentic_response(result: dict, resolved_mode: str) -> MultiAgenticRagResponse:
    eval_scores = result.get("eval_scores")
    llm_context = result.get("llm_context")
    return MultiAgenticRagResponse(
        query=result.get("query"),
        answer=result["answer"],
        tasks=[AgentTaskInfo(**task) for task in result["tasks"]],
        suggested_follow_up_questions=result.get("follow_up_questions") or [],
        tools_used=[ToolCallInfo(**call) for call in result["tools_used"]],
        sources=result.get("sources") or [],
        iterations=result["iterations"],
        explainability_info=ExplainabilityInfo(
            request_id=result["request_id"],
            served_from_cache=result["served_from_cache"],
            llm_call_count=result["llm_call_count"],
            latency_ms=LatencyInfo(**result["latency_ms"]),
            token_usage=None,
            llm_context=LlmContextInfo(**llm_context) if llm_context else None,
            routed_to=None,
            eval_scores=EvalScores(**eval_scores) if eval_scores else None,
            guardrails=result["guardrails"],
            planner_model_used=result.get("planner_model_used"),
            guardrails_model_used=result.get("guardrails_model_used"),
        ),
        conversation_id=result.get("conversation_id"),
        resolved_mode=resolved_mode,
    )


@router_auto_route_query.post("/query", response_model=AgenticRagResponse | MultiAgenticRagResponse)
async def query(payload: AgenticRagRequest, request: Request):
    userProfile = require_role(payload.user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)
    await enforce_rate_limit(request)

    context = await assemble_context(userProfile, payload.conversation_id, payload.query)
    mode = context.classification

    try:
        if mode == "single":
            single_result = await time_and_log(
                "/v1/rag-retrieval/query",
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
                ),
                lambda r: (r.get("token_usage") or {}).get("total_tokens"),
            )
            if not _should_escalate(single_result):
                return _build_agentic_response(single_result, "single-agentic-rag")
            logger.info("Escalating %r from single- to multi-agentic-rag", payload.query)

        multi_result = await time_and_log(
            "/v1/rag-retrieval/query",
            "multi-agentic-rag",
            lambda request_id: multi_agent_pipeline.run_multi_agent(
                payload.query,
                userProfile.employee_id,
                enable_conversation_memory=payload.enable_conversation_memory,
                conversation_id=payload.conversation_id,
                request_id=request_id,
                judge_model=payload.eval_options.judge_model if payload.eval_options else None,
                eval_score_threshold=payload.eval_options.eval_score_threshold if payload.eval_options else None,
                search_strategy=payload.search_strategy,
                role=userProfile.role,
                department=userProfile.department,
                guardrails_model=payload.guardrails_model,
            ),
            lambda r: None,
        )
        return _build_multi_agentic_response(multi_result, "multi-agentic-rag")
    except GuardrailBlockedError as error:
        return json_error(422, str(error), code=error_codes.INPUT_GUARDRAIL_BLOCKED)
