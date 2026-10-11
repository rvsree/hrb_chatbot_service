"""Ask the knowledge-base a question - spends real money per query (one embedding call, one chat completion)."""

from fastapi import APIRouter, Request

from src.hrb_chatbot.ai.pre_processing.guardrails_input import GuardrailBlockedError
from src.hrb_chatbot.ai.rag_pipeline import pipeline
from src.hrb_chatbot.api.dependencies import json_error
from src.hrb_chatbot.api.gateway.rbac import require_role
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rag_query_params import RagQueryParams
from src.hrb_chatbot.common.rate_limiting.rate_limiter import enforce_rate_limit
from src.hrb_chatbot.models.common import ToolCallInfo
from src.hrb_chatbot.models.rag import (
    AnswerInfo,
    EvalScores,
    ExplainabilityInfo,
    LatencyInfo,
    LlmContextInfo,
    RagQueryRequest,
    RagQueryResponse,
    RetrievalInfo,
    TokenUsageInfo,
)

logger = get_logger("retrieve_document")

router_retrieve_document = APIRouter(tags=["query"])


def _params_from_request(payload: RagQueryRequest, employee_id: str | None = None) -> RagQueryParams:
    """Map the nested request into the flat dataclass ai/rag_pipeline/ actually uses."""
    search_options = payload.search_options
    generation_options = payload.generation_options
    return RagQueryParams(
        query=payload.query,
        top_k=search_options.top_k if search_options else None,
        vector_db=search_options.vector_db if search_options else None,
        search_strategy=search_options.search_strategy if search_options else None,
        model_name=generation_options.model_name if generation_options else None,
        temperature=generation_options.temperature if generation_options else None,
        max_tokens=generation_options.max_tokens if generation_options else None,
        use_multi_query=search_options.use_multi_query if search_options else False,
        use_self_query=search_options.use_self_query if search_options else False,
        llm_provider=search_options.llm_provider if search_options else None,
        lambda_mult=search_options.lambda_mult if search_options else None,
        employee_id=employee_id,
        enable_conversation_memory=payload.enable_conversation_memory,
        conversation_id=payload.conversation_id,
    )


async def _answer_query(payload: RagQueryRequest, employee_id: str | None = None) -> RagQueryResponse | object:
    params = _params_from_request(payload, employee_id)
    try:
        result = await pipeline.answer_query(params)
    except NotImplementedError as error:
        return json_error(501, str(error), code=error_codes.NOT_IMPLEMENTED)
    except GuardrailBlockedError as error:
        return json_error(422, str(error), code=error_codes.INPUT_GUARDRAIL_BLOCKED)
    except ValueError as error:
        return json_error(422, str(error), code=error_codes.VALIDATION_ERROR)
    except Exception as error:
        logger.error("Query failed for %r: %s: %s", payload.query, type(error).__name__, error)
        return json_error(
            500, "The query could not be answered. Please try again.", code=error_codes.QUERY_FAILED
        )

    token_usage = result.get("token_usage")
    eval_scores = result.get("eval_scores")
    return RagQueryResponse(
        query=result["query"],
        answer_info=AnswerInfo(answer=result["answer"], model_used=result["model_used"]),
        retrieval_info=RetrievalInfo(
            vector_db=result["vector_db"],
            search_strategy=result["search_strategy"],
            applied_filter=result.get("applied_filter"),
            sources=result["sources"],
        ),
        explainability_info=ExplainabilityInfo(
            served_from_cache=result["served_from_cache"],
            llm_call_count=result["llm_call_count"],
            latency_ms=LatencyInfo(**result["latency_ms"]),
            token_usage=TokenUsageInfo(**token_usage) if token_usage else None,
            routed_to=result.get("routed_to"),
            eval_scores=EvalScores(**eval_scores) if eval_scores else None,
            temperature=result.get("temperature"),
            llm_context=LlmContextInfo(**result["llm_context"]) if result.get("llm_context") else None,
        ),
        tools_used=[ToolCallInfo(**call) for call in result.get("tools_used", [])],
        conversation_id=result.get("conversation_id"),
    )


@router_retrieve_document.post("/query", response_model=RagQueryResponse)
async def query(payload: RagQueryRequest, request: Request):
    userProfile = require_role(payload.user_profile, Role.EMPLOYEE, Role.MANAGER, Role.HR_SUPPORT)
    await enforce_rate_limit(request)
    return await _answer_query(payload, employee_id=userProfile.employee_id)
