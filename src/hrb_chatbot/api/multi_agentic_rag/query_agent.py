"""Multi-agentic-rag - Planner Agent -> Orchestration Agent dispatch -> 4 domain
agents -> Reviewer Agent, via a real LangGraph graph. See
ai/agents/workflow_agents/multi_agent_pipeline.py and RAG-ROADMAP.md Phase 64."""

from fastapi import APIRouter, Request

from src.hrb_chatbot.ai.agents.workflow_agents import multi_agent_pipeline
from src.hrb_chatbot.ai.search_pre_processing.guardrails_input import GuardrailBlockedError
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.observability.response_metrics import time_and_log
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.common import ToolCallInfo
from src.hrb_chatbot.models.multi_agentic_rag import AgentTaskInfo, MultiAgenticRagRequest, MultiAgenticRagResponse
from src.hrb_chatbot.models.rag import EvalScores, ExplainabilityInfo, LatencyInfo, LlmContextInfo

logger = get_logger("multi_agentic_rag.query_agent")

router_query_agent = APIRouter(tags=["multi-agentic-rag"])


@router_query_agent.post("/query", response_model=MultiAgenticRagResponse)
async def query(payload: MultiAgenticRagRequest, request: Request):
    userProfile = require_role(payload.user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT, Role.ADMIN)
    await enforce_rate_limit(request)

    try:
        # token_count always None here - no per-domain-agent token usage
        # exists yet (the real `token_usage=None` below, same known gap -
        # see BACKLOG.md's "multi-agentic-rag has no per-domain-agent
        # token usage" entry), not fabricated to make this tab look complete.
        result = await time_and_log(
            "/v1/multi-agentic-rag-retrieval/query",
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
            ),
            lambda r: None,
        )
    except GuardrailBlockedError as error:
        return json_error(422, str(error), code=error_codes.INPUT_GUARDRAIL_BLOCKED)

    eval_scores = result.get("eval_scores")
    llm_context = result.get("llm_context")
    return MultiAgenticRagResponse(
        query=result.get("query", payload.query),
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
        ),
        conversation_id=result.get("conversation_id"),
    )
