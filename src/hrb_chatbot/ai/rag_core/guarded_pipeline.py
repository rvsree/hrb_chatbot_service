"""Phase 98: the guardrail/conversation-memory/logging wrapper every RAG
retrieval mode shares - extracted from genai-rag's own pipeline.py so
guardrails/memory/logging are a one-time decision, not one per pipeline
(the gap that let single-agentic-rag ship with no guardrails at all)."""

from collections.abc import Awaitable, Callable

from langchain_core.messages import BaseMessage

from src.hrb_chatbot.ai.rag_core.demo_query_limiter import DemoQueryLimitExceededError, check_and_record
from src.hrb_chatbot.ai.search_pre_processing import conversation_memory
from src.hrb_chatbot.ai.search_pre_processing.guardrails_input import check_input
from src.hrb_chatbot.ai.rag_pipeline.response_generation.guardrails_output import check_output
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_core.guarded_pipeline")

GenerateFn = Callable[[str, list[BaseMessage] | None], Awaitable[dict]]


async def run_guarded_pipeline(
    query: str,
    employee_id: str | None,
    enable_conversation_memory: bool,
    conversation_id: str | None,
    generate: GenerateFn,
    pre_checked_query: str | None = None,
    pre_checked_input_status: dict | None = None,
    guardrails_model: str | None = None,
    full_name: str | None = None,
    role: str | None = None,
    ip_address: str | None = None,
    timezone: str | None = None,
) -> dict:
    """Input guardrail -> load history -> generate (mode-specific) -> output
    guardrail -> save turn. `generate` returns at least {"answer": str} -
    every other key it returns (sources, tools_used, iterations, ...) passes
    through untouched, so each pipeline's own response shape is unaffected.

    `pre_checked_query`: only for a caller (genai-rag's MCP fast-path) that
    already ran check_input() itself for an earlier routing decision -
    skips a redundant second guardrail call. Must be that call's actual
    return value, never the raw query - omit it and this function checks
    the query itself, which is the right default for every other caller.
    `pre_checked_input_status`: that same earlier call's own status dict -
    required alongside pre_checked_query (Phase 224), so the real input
    guardrail outcome still reaches result["guardrails"] on the fast path
    too, not just a hardcoded "pass"."""
    if pre_checked_query is not None:
        checked_query = pre_checked_query
        input_status = pre_checked_input_status or {"status": "pass", "rail": None}
    else:
        checked_query, input_status = await check_input(query, guardrails_model=guardrails_model)

    resolved_conversation_id = None
    if enable_conversation_memory:
        resolved_conversation_id = conversation_id or conversation_memory.new_conversation_id()
    chat_history = await conversation_memory.load_history(resolved_conversation_id) if resolved_conversation_id else None

    # Phase 265 - after the input guardrail (a blocked query never reaches
    # here, so it never counts against the demo limit) and before
    # generation (so an over-limit visitor never triggers a wasted LLM
    # call). Keyed on conversation_id - falls back to a per-request id if
    # conversation memory is off, since the demo limit still applies.
    demo_limit_key = resolved_conversation_id or conversation_memory.new_conversation_id()
    demo_limit_result = await check_and_record(demo_limit_key, employee_id, full_name, role, ip_address, timezone)
    if demo_limit_result.blocked:
        raise DemoQueryLimitExceededError(
            f"You have reached the demo limit of {demo_limit_result.effective_limit} questions for this session. "
            "This is a demo environment with a capped number of questions per visitor."
        )

    with log_backend_call(logger, "rag_core", "generate"):
        result = await generate(checked_query, chat_history)

    checked_answer, output_status = await check_output(checked_query, result["answer"], guardrails_model=guardrails_model)

    if resolved_conversation_id:
        await conversation_memory.save_turn(resolved_conversation_id, employee_id, checked_query, checked_answer)

    result["answer"] = checked_answer
    result["conversation_id"] = resolved_conversation_id
    result["demo_limit"] = demo_limit_result.to_response_dict()
    result["guardrails"] = {"input": input_status, "output": output_status}
    # Phase 244 - output_status always has a real model_used (check_output ran
    # unconditionally above); input_status may be the pre_checked_input_status
    # fallback above, which has no model_used key, so output's is authoritative.
    result["guardrails_model_used"] = output_status.get("model_used")
    return result
