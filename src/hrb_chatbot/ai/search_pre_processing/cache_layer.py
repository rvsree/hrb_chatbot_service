"""CAG (answer cache) check/write - its own layer, not inter-mixed with the
RAG pipeline (user-directed, 2026-10-21). Pure extraction from pipeline.py's
own inline logic - same behavior, same cache entries, just a separate module
a reader can open without wading through retrieval/generation code to find it.

genai-rag only, same as before this extraction - single-/multi-agentic-rag's
tool-driven answers can depend on live data, which would make caching a real
correctness bug (see this project's own established reasoning on that)."""

import time

from src.hrb_chatbot.ai.rag_core.eval_threshold import check_eval_threshold
from src.hrb_chatbot.ai.search_pre_processing import conversation_memory
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("search_pre_processing.cache_layer")

# Phase 140: a decomposed sub-question that used live MCP data must not
# have the overall result cached - a multi-sub-question query's MERGED
# result was being cached unconditionally even when one sub-question's
# answer came from here (Phase 151 removed the separate top-level MCP
# shortcut this comment used to also cover; every MCP call now goes
# through this same per-sub-question path, so this is the only guard
# needed). snake_case to match try_route_to_mcp()'s own tool_name
# convention (mcp_tools/__init__.py), distinct from orchestration_agent.py's
# PascalCase LIVE_DATA_TOOLS. Moved here from pipeline.py (Phase 242) -
# genuinely a cache-eligibility concept, not core pipeline logic.
LIVE_DATA_MCP_TOOLS = {"get_leave_balance", "get_leave_history"}


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)


async def check_cache(
    cache_key: str,
    checked_query: str,
    resolved_conversation_id: str | None,
    employee_id: str,
    eval_score_threshold: float | None,
    started_at: float,
) -> dict | None:
    """Returns the shaped hit result, or None on a miss. Exact-match only,
    checked on every turn - not just the first message of a fresh
    conversation (Phase 78/101/105's own confirmed tradeoff, unchanged)."""
    cached_result = await get_db_gateway().answer_cache().get(cache_key)
    if cached_result is None:
        return None

    logger.info("Answer cache hit for %r", checked_query)
    # Never reuse the cached result's own conversation_id - it could be a
    # different caller's conversation entirely. This caller gets its own
    # (possibly freshly-generated) id, and the turn is saved under it.
    result = dict(cached_result)
    result["conversation_id"] = resolved_conversation_id
    if resolved_conversation_id:
        await conversation_memory.save_turn(resolved_conversation_id, employee_id, checked_query, result["answer"])
        # Phase 112: this conversation's history now depends on this cache
        # entry - deleting the conversation can purge it later.
        await get_db_gateway().answer_cache().tag_conversation(resolved_conversation_id, cache_key)

    # Phase 107/109: this call made zero LLM/retrieval/eval-judge calls -
    # overwrite whatever latency_ms/token_usage the cached dict carried from
    # when it was FIRST generated. Eval SCORES themselves are the one
    # exception - reused rather than recomputed, a property of the
    # (question, context, answer) triple, identical for an exact cache hit.
    #
    # Phase 223: below_threshold/below_threshold_metrics are NOT part of that
    # "identical" set - a property of THIS call's eval_score_threshold, not
    # the cached one from whenever this entry was first written.
    if result.get("eval_scores") is not None:
        result["eval_scores"] = dict(result["eval_scores"])
        result["eval_scores"]["below_threshold"], result["eval_scores"]["below_threshold_metrics"] = (
            check_eval_threshold(result["eval_scores"], eval_score_threshold)
        )
    result["served_from_cache"] = True
    result["llm_call_count"] = 0
    result["token_usage"] = None
    result["latency_ms"] = {"total": _elapsed_ms(started_at), "retrieval": None, "generation": None, "eval": None}
    # Phase 132: the cached llm_context describes the ORIGINAL call that
    # populated this cache entry, not this one.
    result["llm_context"] = None
    return result


def is_cache_eligible(tools_used: list[dict]) -> bool:
    """False if any sub-question's answer came from live MCP data - see
    LIVE_DATA_MCP_TOOLS above."""
    return not any(call["tool_name"] in LIVE_DATA_MCP_TOOLS for call in tools_used)


async def write_cache(cache_key: str, checked_query: str, result: dict) -> None:
    if not is_cache_eligible(result["tools_used"]):
        return
    await get_db_gateway().answer_cache().set(cache_key, checked_query, result)
    if result.get("conversation_id"):
        await get_db_gateway().answer_cache().tag_conversation(result["conversation_id"], cache_key)
