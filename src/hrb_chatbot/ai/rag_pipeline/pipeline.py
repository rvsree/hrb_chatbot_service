"""Orchestrates answering one question against the indexed knowledge base."""

import asyncio
import time

from src.hrb_chatbot.ai.agents.workflow_agents import reviewer_agent
from src.hrb_chatbot.ai.pre_processing import conversation_memory
from src.hrb_chatbot.ai.pre_processing.guardrails_input import check_input
from src.hrb_chatbot.ai.pre_processing.query_decompose import decompose
from src.hrb_chatbot.ai.pre_processing.query_normalize import normalize_query
from src.hrb_chatbot.ai.rag_core.eval_threshold import check_eval_threshold
from src.hrb_chatbot.ai.rag_core.guarded_pipeline import run_guarded_pipeline
from src.hrb_chatbot.ai.rag_core.tool_classification import classify_tool
from src.hrb_chatbot.ai.rag_pipeline.evaluations.golden_dataset_harness import (
    evaluate_completeness,
    evaluate_groundedness,
    evaluate_retrieval_relevance,
)
from src.hrb_chatbot.ai.rag_pipeline.helper.access_control import build_acl_filter
from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.exact_knn_search import search_knn
from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.retriever import retrieve_chunks
from src.hrb_chatbot.ai.rag_pipeline.response_generation.response_generator import generate_answer
from src.hrb_chatbot.ai.rag_pipeline.tools.mcp_tools import try_route_to_mcp
from src.hrb_chatbot.common.clients.cache_client.answer_cache import build_cache_key
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import get_active_llm_provider, get_active_vector_db, read_setting
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rag_query_params import RagQueryParams

logger = get_logger("rag_pipeline.pipeline")

# Phase 140: a decomposed sub-question that used live MCP data must not
# have the overall result cached - a multi-sub-question query's MERGED
# result was being cached unconditionally even when one sub-question's
# answer came from here (Phase 151 removed the separate top-level MCP
# shortcut this comment used to also cover; every MCP call now goes
# through this same per-sub-question path, so this is the only guard
# needed). snake_case to match try_route_to_mcp()'s own tool_name
# convention (mcp_tools/__init__.py), distinct from orchestration_agent.py's
# PascalCase LIVE_DATA_TOOLS.
LIVE_DATA_MCP_TOOLS = {"get_leave_balance", "get_leave_history"}


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)


# Phase 219 - the wider candidate pool evaluate_retrieval_relevance() judges
# alongside the originally-retrieved chunks, to produce a real (if bounded,
# clearly-labeled-as-an-estimate) live recall/F1 instead of none at all.
# Capped, not top_k*WIDER_POOL_MULTIPLIER unbounded - a judge prompt over an
# uncapped pool on a high top_k would get expensive and slow fast.
WIDER_POOL_MULTIPLIER = 4
WIDER_POOL_MAX = 20


def _chunk_key(chunk: dict) -> tuple:
    return (chunk.get("document_id"), chunk.get("chunk_index"))


async def _fetch_wider_pool_texts(
    query: str, original_sources: list[dict], top_k: int, vector_db: str | None
) -> list[str]:
    """Original chunks first (so they occupy positions 1..len(original) of
    the judged list, the invariant evaluate_retrieval_relevance() relies on
    to split precision from the recall estimate), then extra exact-KNN
    candidates beyond them, deduped by (document_id, chunk_index) - exact
    KNN specifically, not whatever search_strategy produced original_sources,
    so the reference pool isn't just re-confirming the same approximation
    that produced the answer being scored."""
    wider_k = min(top_k * WIDER_POOL_MULTIPLIER, WIDER_POOL_MAX)
    original_keys = {_chunk_key(chunk) for chunk in original_sources}
    extra_chunks = await asyncio.to_thread(search_knn, query, wider_k, vector_db)
    deduped_extra = [chunk for chunk in extra_chunks if _chunk_key(chunk) not in original_keys]
    return [chunk["text"] for chunk in original_sources] + [chunk["text"] for chunk in deduped_extra]


async def _score_live_answer(
    query: str,
    answer: str,
    sources: list[dict],
    judge_model: str | None = None,
    eval_score_threshold: float | None = None,
    top_k: int = 5,
    vector_db: str | None = None,
) -> tuple[dict | None, float | None]:
    """Phase 109: live eval-judge scoring for one just-generated answer -
    skipped when there's no retrieved context to check groundedness
    against. Both judge calls are synchronous (evaluate_groundedness/
    evaluate_completeness make a real blocking HTTP call) - run via
    asyncio.to_thread() so one slow judge call can't stall the whole
    event loop, and in parallel via gather() so the two don't add up.

    Phase 215: judge_model overrides which model all 3 judge calls use;
    eval_score_threshold, when given, flags the result via
    below_threshold/below_threshold_metrics - see ai/rag_core/eval_threshold.py.

    Phase 219: top_k/vector_db are new - used only to fetch the wider
    candidate pool (_fetch_wider_pool_texts) evaluate_retrieval_relevance()
    needs for its recall_estimate/f1_estimate. Adds one real retrieval call
    (exact-KNN) before the 3 parallel judge calls, on every answer that has
    retrieved context - a real cost/latency increase, confirmed acceptable
    by the user (2026-10-18) over the alternative of no live recall/F1 at
    all, given the estimate is clearly labeled as such everywhere it's shown."""
    if not sources:
        return None, None

    eval_started_at = time.perf_counter()
    context_texts = [chunk["text"] for chunk in sources]
    wider_pool_texts = await _fetch_wider_pool_texts(query, sources, top_k, vector_db)
    groundedness, completeness, retrieval = await asyncio.gather(
        asyncio.to_thread(evaluate_groundedness, answer, context_texts, judge_model),
        asyncio.to_thread(evaluate_completeness, query, answer, None, judge_model),
        asyncio.to_thread(evaluate_retrieval_relevance, query, context_texts, judge_model, wider_pool_texts),
    )
    eval_scores = {
        "groundedness": groundedness["score"],
        "groundedness_verdict": groundedness["verdict"],
        "groundedness_explanation": groundedness["explanation"],
        "groundedness_prompt": groundedness["prompt"],
        "completeness": completeness["score"],
        "completeness_verdict": completeness["verdict"],
        "completeness_explanation": completeness["explanation"],
        "completeness_prompt": completeness["prompt"],
        "retrieval_precision": retrieval["precision"],
        "retrieval_relevant_chunk_indices": retrieval["relevant_chunk_indices"],
        "retrieval_precision_explanation": retrieval["explanation"],
        "retrieval_precision_prompt": retrieval["prompt"],
        "retrieval_recall_estimate": retrieval["recall_estimate"],
        "retrieval_f1_estimate": retrieval["f1_estimate"],
        "retrieval_recall_pool_size": retrieval["pool_size"],
        "retrieval_recall_relevant_count": retrieval["relevant_pool_count"],
        "judge_model_used": groundedness["model_used"],
    }
    eval_scores["below_threshold"], eval_scores["below_threshold_metrics"] = check_eval_threshold(
        eval_scores, eval_score_threshold
    )
    return eval_scores, _elapsed_ms(eval_started_at)


async def _answer_sub_question(
    sub_question: str,
    employee_id: str | None,
    resolved_top_k: int,
    resolved_vector_db: str,
    resolved_search_strategy: str,
    resolved_llm_provider: str,
    resolved_temperature: float,
    model_name: str | None,
    max_tokens: int | None,
    use_multi_query: bool,
    use_self_query: bool,
    chat_history: list,
    lambda_mult: float | None = None,
    request_id: str | None = None,
    enable_corrective_retry: bool = False,
    judge_model: str | None = None,
    eval_score_threshold: float | None = None,
    role: str | None = None,
    department: str | None = None,
) -> dict:
    """Phase 130: one sub-question's own MCP-check-then-retrieve-or-generate -
    the same two-path logic answer_query() always had, just run once per
    sub-question instead of once per whole (possibly compound) query.

    Phase 226: enable_corrective_retry/judge_model/eval_score_threshold -
    when both the retry flag and a threshold are set, the retrieved
    chunks' own live precision is checked BEFORE generation; if it's
    below threshold, retrieval runs once more with a doubled top_k. This
    retries RETRIEVAL only, never generation - see
    endpoint-request-response-contracts.md's Phase 226 entry for why:
    the shared guarded_pipeline core already saves whatever generate()
    returns to conversation memory, so a generated answer must never be
    silently replaced after the fact."""
    mcp_result = await try_route_to_mcp(sub_question, employee_id)
    if mcp_result is not None:
        return {
            "answer": mcp_result["answer"],
            "model_used": mcp_result["model_used"],
            "sources": [],
            "applied_filter": None,
            "tool_call": {
                "tool_name": mcp_result["routed_to"],
                "tool_input": sub_question,
                "tool_type": classify_tool(mcp_result["routed_to"]),
                "latency_ms": mcp_result.get("tool_latency_ms"),
                "success": True,
            },
            "token_usage": None,
            "llm_call_count": 0,
            "acl_denied_count": 0,
            "retrieval_ms": 0.0,
            "generation_ms": 0.0,
            "llm_context_turn": None,  # no LLM call - nothing to capture
            "mcp_tool_call": {
                "tool_name": mcp_result["routed_to"],
                "arguments": mcp_result["mcp_arguments"],
                "raw_result": mcp_result["mcp_raw_result"],
            },
        }

    retrieval_started_at = time.perf_counter()
    chunks, applied_filter = await retrieve_chunks(
        sub_question,
        top_k=resolved_top_k,
        vector_db=resolved_vector_db,
        search_strategy=resolved_search_strategy,
        use_multi_query=use_multi_query,
        use_self_query=use_self_query,
        llm_provider=resolved_llm_provider,
        lambda_mult=lambda_mult,
        role=role,
        department=department,
    )

    # Phase 232 - a second, independent build_acl_filter() call just to
    # report a count back to the caller, same "its own self-contained
    # call, not threaded out of retrieve_chunks()'s own return value"
    # choice Phase 231's own spec already made for keeping this out of
    # applied_filter - never raises further than build_acl_filter() itself
    # already doesn't (best-effort, same as retrieve_chunks()'s own ACL
    # resolution one level down).
    try:
        acl_filter_for_count = await build_acl_filter(get_db_gateway(), role, department)
    except Exception:
        acl_filter_for_count = None
    acl_denied_count = len(acl_filter_for_count["document_id"]["$nin"]) if acl_filter_for_count else 0

    # Phase 226 - a real, bounded (exactly one) corrective retry: check the
    # chunks' own live precision before generation ever happens, and if
    # it's below the caller's threshold, retrieve again with more
    # candidates. No wider pool here (unlike _score_live_answer's own
    # evaluate_retrieval_relevance call) - this is a precision-only
    # pre-generation gate, not the post-generation recall estimate.
    retry_attempted = False
    if enable_corrective_retry and eval_score_threshold is not None and chunks:
        precision_check = await asyncio.to_thread(
            evaluate_retrieval_relevance, sub_question, [chunk["text"] for chunk in chunks], judge_model
        )
        if precision_check["precision"] is not None and precision_check["precision"] < eval_score_threshold:
            retry_top_k = min(resolved_top_k * 2, WIDER_POOL_MAX)
            retried_chunks, retried_filter = await retrieve_chunks(
                sub_question,
                top_k=retry_top_k,
                vector_db=resolved_vector_db,
                search_strategy=resolved_search_strategy,
                use_multi_query=use_multi_query,
                use_self_query=use_self_query,
                llm_provider=resolved_llm_provider,
                lambda_mult=lambda_mult,
                role=role,
                department=department,
            )
            if retried_chunks:
                chunks, applied_filter = retried_chunks, retried_filter
                retry_attempted = True
    retrieval_ms = _elapsed_ms(retrieval_started_at)

    generation_started_at = time.perf_counter()
    generation = generate_answer(
        sub_question, chunks, model_name=model_name, temperature=resolved_temperature,
        max_tokens=max_tokens, chat_history=chat_history, request_id=request_id,
    )
    generation_ms = _elapsed_ms(generation_started_at)

    return {
        "answer": generation["answer"],
        "model_used": generation["model_used"],
        "sources": chunks,
        "applied_filter": applied_filter,
        "acl_denied_count": acl_denied_count,
        "tool_call": None,
        "token_usage": generation.get("token_usage"),
        "llm_call_count": 1,
        "retrieval_ms": retrieval_ms,
        "generation_ms": generation_ms,
        "llm_context_turn": generation.get("llm_context_turn"),
        "mcp_tool_call": None,
        "retry_attempted": retry_attempted,
    }


async def answer_query(params: RagQueryParams, request_id: str | None = None) -> dict:
    """Run the full pipeline: guardrail/decompose/(MCP-route-or-retrieve+
    generate per sub-question)/merge/guardrail/save via the Phase 98
    shared core - GuardrailBlockedError becomes a 422 upstream.

    Phase 151: there used to be a second, top-level MCP fast-path here,
    checked against the whole undecomposed query before decompose() ever
    ran - it matched on a leave-balance/leave-history keyword anywhere in
    the query and returned that MCP call's raw result as the ENTIRE
    answer, silently discarding the rest of a compound question (e.g.
    "look up my PTO balance, and also tell me about caregiver leave"
    answered only the PTO half). Removed - decompose() already returns a
    single-item list unchanged for a genuinely single-part question, so a
    plain "what's my PTO balance?" still reaches _answer_sub_question()'s
    own try_route_to_mcp() call below and gets the identical raw-MCP-data
    answer, at the cost of one added decompose() LLM call it didn't
    previously make. A compound question now gets decomposed first, so
    each part is routed - MCP or RAG - on its own merits."""
    started_at = time.perf_counter()
    normalized_query = await normalize_query(params.query)
    checked_query, input_guardrail_status = await check_input(normalized_query)

    resolved_conversation_id = None
    if params.enable_conversation_memory:
        resolved_conversation_id = params.conversation_id or conversation_memory.new_conversation_id()

    resolved_vector_db = get_active_vector_db(params.vector_db)
    resolved_search_strategy = params.search_strategy or read_setting(
        None, "RAG_DEFAULT_SEARCH_STRATEGY", "similarity"
    )
    resolved_llm_provider = get_active_llm_provider(params.llm_provider)
    resolved_top_k = params.top_k or int(read_setting(None, "RAG_DEFAULT_TOP_K", 5))
    if params.temperature is None:
        resolved_temperature = float(read_setting(None, "RAG_DEFAULT_TEMPERATURE", 0.0))
    else:
        resolved_temperature = params.temperature

    # Phase 78/101/105: answer cache, exact match only, checked on every
    # turn - not just the first message of a fresh conversation. User
    # confirmed this tradeoff explicitly: a cache hit on a repeated
    # question mid-conversation (or asked by a different employee entirely
    # - the key never includes employee_id, see build_cache_key()) serves
    # the earlier answer verbatim, ignoring whatever conversation context
    # has accumulated since. Faster/cheaper, at the cost of a cached answer
    # occasionally not reflecting a mid-conversation follow-up's context.
    # Phase 231: role/department now added to the cache key - a cached
    # answer's own sources/citations can depend on which documents the
    # ORIGINAL caller's role/department could see (Document ACL), so a
    # more-restricted caller must not be served another caller's cached
    # answer. Deliberately narrower than "never includes employee_id"
    # above - role/department are coarse categories (5 roles, a handful of
    # departments), not per-individual, so this doesn't reintroduce the
    # cache fragmentation that decision was avoiding.
    cache_key = build_cache_key(
        checked_query,
        top_k=resolved_top_k,
        vector_db=resolved_vector_db,
        search_strategy=resolved_search_strategy,
        model_name=params.model_name,
        temperature=resolved_temperature,
        max_tokens=params.max_tokens,
        use_multi_query=params.use_multi_query,
        use_self_query=params.use_self_query,
        llm_provider=resolved_llm_provider,
        lambda_mult=params.lambda_mult,
        role=params.role,
        department=params.department,
    )
    cached_result = await get_db_gateway().answer_cache().get(cache_key)
    if cached_result is not None:
        logger.info("Answer cache hit for %r", checked_query)
        # Never reuse the cached result's own conversation_id - it could be
        # a different caller's conversation entirely. This caller gets its
        # own (possibly freshly-generated) id, and the turn is saved under
        # it, so a follow-up still has this in its history.
        result = dict(cached_result)
        result["conversation_id"] = resolved_conversation_id
        if resolved_conversation_id:
            await conversation_memory.save_turn(
                resolved_conversation_id, params.employee_id, checked_query, result["answer"]
            )
            # Phase 112: this conversation's history now depends on this
            # cache entry - deleting the conversation can purge it later.
            await get_db_gateway().answer_cache().tag_conversation(resolved_conversation_id, cache_key)
        # Phase 107/109: this call made zero LLM/retrieval/eval-judge
        # calls - overwrite whatever latency_ms/token_usage the cached
        # dict carried from when it was FIRST generated, since those
        # describe that earlier call, not this one. The eval SCORES
        # themselves are the one exception - left as-is, reused rather
        # than recomputed, since they're a property of the (question,
        # context, answer) triple, which is identical for an exact cache
        # hit (re-running the judge LLM would cost a real call for a
        # result that should already match, modulo LLM nondeterminism).
        #
        # Phase 223: below_threshold/below_threshold_metrics are NOT part
        # of that "identical" set, though, and were a real bug before this
        # fix - they're a property of THIS call's eval_score_threshold,
        # not the cached one from whenever this entry was first written.
        # A caller who raises their threshold in Settings and re-asks the
        # exact same question (same retrieval/generation config, so same
        # cache key) must see the re-evaluated flag, not a stale one from
        # a looser (or absent) threshold set the first time.
        if result.get("eval_scores") is not None:
            result["eval_scores"] = dict(result["eval_scores"])
            result["eval_scores"]["below_threshold"], result["eval_scores"]["below_threshold_metrics"] = (
                check_eval_threshold(result["eval_scores"], params.eval_score_threshold)
            )
        result["served_from_cache"] = True
        result["llm_call_count"] = 0
        result["token_usage"] = None
        result["latency_ms"] = {"total": _elapsed_ms(started_at), "retrieval": None, "generation": None, "eval": None}
        # Phase 132: the cached llm_context describes the ORIGINAL call that
        # populated this cache entry, not this one - nothing was actually
        # sent to anything this call, so this must not carry it forward.
        result["llm_context"] = None
        return result

    logger.info(
        "Answering query %r (top_k=%s, vector_db=%s, search_strategy=%s, use_multi_query=%s, "
        "use_self_query=%s, llm_provider=%s)",
        checked_query,
        resolved_top_k,
        resolved_vector_db,
        resolved_search_strategy,
        params.use_multi_query,
        params.use_self_query,
        resolved_llm_provider,
    )

    async def generate(generate_query: str, chat_history: list) -> dict:
        decomposition_started_at = time.perf_counter()
        sub_questions = await decompose(generate_query)
        decomposition_ms = _elapsed_ms(decomposition_started_at)

        sub_results = []
        for sub_question in sub_questions:
            sub_results.append(
                await _answer_sub_question(
                    sub_question,
                    params.employee_id,
                    resolved_top_k,
                    resolved_vector_db,
                    resolved_search_strategy,
                    resolved_llm_provider,
                    resolved_temperature,
                    params.model_name,
                    params.max_tokens,
                    params.use_multi_query,
                    params.use_self_query,
                    chat_history,
                    lambda_mult=params.lambda_mult,
                    request_id=request_id,
                    enable_corrective_retry=params.enable_corrective_retry,
                    judge_model=params.judge_model,
                    eval_score_threshold=params.eval_score_threshold,
                    role=params.role,
                    department=params.department,
                )
            )
        retrieval_ms = sum(sub_result["retrieval_ms"] for sub_result in sub_results)
        generation_ms = sum(sub_result["generation_ms"] for sub_result in sub_results)
        retry_attempted = any(sub_result.get("retry_attempted", False) for sub_result in sub_results)

        sources = [chunk for sub_result in sub_results for chunk in sub_result["sources"]]
        applied_filter = next((sub_result["applied_filter"] for sub_result in sub_results if sub_result["applied_filter"]), None)
        # Phase 232 - role/department (and so the ACL deny-list) don't vary
        # across one request's own sub-questions, so every sub_result's
        # count is already identical - max() just picks one, not an
        # aggregation. Unlike applied_filter above, 0 is a real, meaningful
        # value here, not "nothing happened" - can't use the same
        # skip-falsy next() pattern.
        acl_denied_count = max((sub_result.get("acl_denied_count", 0) for sub_result in sub_results), default=0)
        tools_used = [sub_result["tool_call"] for sub_result in sub_results if sub_result["tool_call"] is not None]
        llm_call_count = 1 + sum(sub_result["llm_call_count"] for sub_result in sub_results)  # 1 = the decompose call itself

        # Phase 132: one LLM-context turn per sub-question that actually
        # called the LLM, labeled by its sub-question when there's more than
        # one (otherwise generate_answer()'s own generic "answer" label is
        # fine, there's nothing to disambiguate from).
        llm_context_turns = []
        mcp_tool_calls = []
        for sub_question, sub_result in zip(sub_questions, sub_results, strict=True):
            if sub_result["llm_context_turn"] is not None:
                turn = dict(sub_result["llm_context_turn"])
                if len(sub_results) > 1:
                    turn["label"] = sub_question
                llm_context_turns.append(turn)
            if sub_result["mcp_tool_call"] is not None:
                mcp_tool_calls.append(sub_result["mcp_tool_call"])

        if len(sub_results) == 1:
            answer = sub_results[0]["answer"]
            model_used = sub_results[0]["model_used"]
            token_usage = sub_results[0]["token_usage"]
        else:
            logger.info("Query %r decomposed into %d sub-questions", generate_query, len(sub_results))
            agent_results = [
                {"agent": "genai-rag", "focus": sub_question, "result": sub_result["answer"]}
                for sub_question, sub_result in zip(sub_questions, sub_results, strict=True)
            ]
            answer, merge_turn = await reviewer_agent.review(generate_query, agent_results, request_id=request_id)
            llm_call_count += 1  # the merge call
            # Phase 140: relabeled to something a user can understand on its
            # own - the old label ("reviewer merge (prompt capture not yet
            # built for this step)") was an internal TODO note leaking into
            # user-facing UI. Phase 160: that TODO is now resolved -
            # merge_turn carries the real system_prompt/human_message
            # reviewer_agent.review() actually sent, not a placeholder.
            llm_context_turns.append(
                {
                    "label": f"Merging {len(sub_results)} sub-answers into one response",
                    "system_prompt": merge_turn["system_prompt"] if merge_turn else None,
                    "human_message": merge_turn["human_message"] if merge_turn else None,
                    "chat_history": [],
                    "response": answer,
                }
            )
            models_used = {sub_result["model_used"] for sub_result in sub_results}
            model_used = ", ".join(sorted(models_used))
            prompt_tokens = sum(sub_result["token_usage"]["prompt_tokens"] for sub_result in sub_results if sub_result["token_usage"])
            completion_tokens = sum(
                sub_result["token_usage"]["completion_tokens"] for sub_result in sub_results if sub_result["token_usage"]
            )
            token_usage = (
                {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}
                if any(sub_result["token_usage"] for sub_result in sub_results)
                else None
            )

        logger.info("Query %r answered using %d chunk(s) across %d sub-question(s)", generate_query, len(sources), len(sub_results))
        return {
            "query": generate_query,
            "answer": answer,
            "model_used": model_used,
            "sources": sources,
            "vector_db": resolved_vector_db,
            "search_strategy": resolved_search_strategy,
            "applied_filter": applied_filter,
            "acl_denied_count": acl_denied_count,
            "served_from_cache": False,
            "llm_call_count": llm_call_count,
            "token_usage": token_usage,
            "temperature": resolved_temperature,
            "tools_used": tools_used,
            "retry_attempted": retry_attempted,
            "llm_context": {"turns": llm_context_turns, "mcp_tool_calls": mcp_tool_calls},
            "latency_ms": {
                "total": None,
                "retrieval": retrieval_ms,
                "generation": generation_ms,
                "decomposition": decomposition_ms,
            },
        }

    result = await run_guarded_pipeline(
        checked_query,
        params.employee_id,
        params.enable_conversation_memory,
        params.conversation_id,
        generate,
        pre_checked_query=checked_query,
        pre_checked_input_status=input_guardrail_status,
    )
    result["eval_scores"], result["latency_ms"]["eval"] = await _score_live_answer(
        checked_query, result["answer"], result["sources"],
        judge_model=params.judge_model, eval_score_threshold=params.eval_score_threshold,
        top_k=resolved_top_k, vector_db=resolved_vector_db,
    )
    # Phase 226 - surfaced here, not just inside the merged dict, so it's
    # discoverable alongside below_threshold/eval_score_threshold rather
    # than a separate top-level field a caller would have to know to check.
    if result["eval_scores"] is not None:
        result["eval_scores"]["retrieval_retry_attempted"] = result.get("retry_attempted", False)

    # total_ms covers the whole call (guardrails, cache check, retrieval,
    # generation, eval scoring, conversation-memory save) -
    # retrieval_ms/generation_ms/eval_ms above are the sub-steps timed
    # individually.
    result["latency_ms"]["total"] = _elapsed_ms(started_at)

    # Phase 140: don't cache a result where any sub-question's answer came
    # from live MCP data - see LIVE_DATA_MCP_TOOLS above.
    cache_eligible = not any(call["tool_name"] in LIVE_DATA_MCP_TOOLS for call in result["tools_used"])
    if cache_eligible:
        await get_db_gateway().answer_cache().set(cache_key, checked_query, result)
        if result.get("conversation_id"):
            await get_db_gateway().answer_cache().tag_conversation(result["conversation_id"], cache_key)

    return result
