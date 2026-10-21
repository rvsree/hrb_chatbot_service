"""Single-agentic-rag's tool-calling loop - uses ChatOpenAI directly, not GatewayChatModel (see RAG-ROADMAP.md Phase 55)."""

import asyncio
import time

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from src.hrb_chatbot.ai.agents._llm_helpers import AGENT_LLM_TIMEOUT_SECONDS, build_agent_llm
from src.hrb_chatbot.ai.search_pre_processing import conversation_memory
from src.hrb_chatbot.ai.search_pre_processing.query_normalize import normalize_query
from src.hrb_chatbot.ai.prompts.agent_prompts import ORCHESTRATION_SYSTEM_PROMPT
from src.hrb_chatbot.ai.rag_core.eval_threshold import check_eval_threshold
from src.hrb_chatbot.ai.rag_core.guarded_pipeline import run_guarded_pipeline
from src.hrb_chatbot.ai.rag_core.response_format import TABULAR_FORMAT_INSTRUCTION, should_use_tabular_format
from src.hrb_chatbot.ai.rag_core.tool_classification import classify_tool
from src.hrb_chatbot.ai.rag_pipeline.evaluations.golden_dataset_harness import (
    evaluate_completeness,
    evaluate_groundedness,
    evaluate_retrieval_relevance,
)
from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.exact_knn_search import search_knn
from src.hrb_chatbot.ai.rag_pipeline.tools.agentic_tools import (
    AGENTIC_TOOL_DEFINITIONS,
    get_leave_balance_tool,
    get_leave_history_tool,
    search_knowledge_base,
)
from src.hrb_chatbot.ai.rag_pipeline.tools.mcp_tools import is_leave_balance_query, is_leave_history_query
from src.hrb_chatbot.common.clients.cache_client.answer_cache import build_cache_key
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("agents.orchestration_agent")

DEFAULT_MAX_ITERATIONS = 5

# Phase 110: a cached answer can only ever be reused safely if no tool
# call in it could have returned live, per-employee data that's since
# changed - SearchKnowledgeBase queries the same static document index
# genai-rag's own retrieval does, so it's excluded from this set on purpose.
LIVE_DATA_TOOLS = {"GetLeaveBalance", "GetLeaveHistory"}


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)


def _message_role(message) -> str:
    kind = message.__class__.__name__
    return {"HumanMessage": "human", "AIMessage": "ai", "ToolMessage": "tool"}.get(kind, kind.lower())


def _render_turn(label: str, messages: list, response_text: str, latency_ms: float | None = None) -> dict:
    """Phase 160 - one ReAct iteration's real, exact prompt: messages[0] is
    always the SystemMessage; the last of the rest is "what's new this
    turn" (the original query on iteration 1, a tool result after that),
    same final-turn/chat_history split genai-rag's own captured turns
    already use, just generalized past "always a HumanMessage" since a
    later iteration's newest message is really a ToolMessage."""
    system_prompt = messages[0].content if messages else None
    rest = messages[1:]
    human_message = rest[-1].content if rest else None
    chat_history = [{"role": _message_role(message), "content": message.content} for message in rest[:-1]]
    return {
        "label": label,
        "latency_ms": latency_ms,
        "system_prompt": system_prompt,
        "human_message": human_message,
        "chat_history": chat_history,
        "response": response_text,
    }


# Phase 220 - same wider-pool approach pipeline.py's own _score_live_answer()
# uses (Phase 219), adapted here: context_texts (tool_outputs) mixes KB
# chunks with web-search/MCP text, which isn't something exact-KNN can
# compare against, so the retrieval judge (precision/recall/f1) now scopes
# to `sources` - the structured, real KB-chunk list Phase 115 already
# built for citations - instead of the mixed blob. Groundedness/
# completeness are unaffected, still judged against the full context_texts.
WIDER_POOL_MULTIPLIER = 4
WIDER_POOL_MAX = 20
# search_knowledge_base (agentic_tools.py) hardcodes top_k=3 for every
# call - mirrored here, not guessed, since that's the real size being
# widened from.
SEARCH_KNOWLEDGE_BASE_TOP_K = 3


def _chunk_key(chunk: dict) -> tuple:
    return (chunk.get("document_id"), chunk.get("chunk_index"))


async def _fetch_wider_pool_texts(query: str, original_sources: list[dict]) -> list[str]:
    wider_k = min(SEARCH_KNOWLEDGE_BASE_TOP_K * WIDER_POOL_MULTIPLIER, WIDER_POOL_MAX)
    original_keys = {_chunk_key(chunk) for chunk in original_sources}
    extra_chunks = await asyncio.to_thread(search_knn, query, wider_k, None)
    deduped_extra = [chunk for chunk in extra_chunks if _chunk_key(chunk) not in original_keys]
    return [chunk["text"] for chunk in original_sources] + [chunk["text"] for chunk in deduped_extra]


async def _score_live_answer(
    query: str,
    answer: str,
    context_texts: list[str],
    sources: list[dict] | None = None,
    judge_model: str | None = None,
    eval_score_threshold: float | None = None,
) -> tuple[dict | None, float | None]:
    """Same approach as pipeline.py's own _score_live_answer() (Phase 109) -
    skipped when there's no tool-retrieved context to check groundedness
    against, both judge calls run in parallel via asyncio.to_thread().
    Phase 215: judge_model/eval_score_threshold - see ai/rag_core/eval_threshold.py.
    Phase 220: sources (real KB chunks, may be empty even when context_texts
    isn't - e.g. an MCP-only or web-only answer) drives retrieval_precision/
    recall_estimate/f1_estimate now, instead of context_texts - see the
    module comment above _fetch_wider_pool_texts for why."""
    if not context_texts:
        return None, None

    kb_chunk_texts = [chunk["text"] for chunk in sources] if sources else []
    wider_pool_texts = await _fetch_wider_pool_texts(query, sources) if sources else None

    eval_started_at = time.perf_counter()
    groundedness, completeness, retrieval = await asyncio.gather(
        asyncio.to_thread(evaluate_groundedness, answer, context_texts, judge_model),
        asyncio.to_thread(evaluate_completeness, query, answer, None, judge_model),
        asyncio.to_thread(evaluate_retrieval_relevance, query, kb_chunk_texts, judge_model, wider_pool_texts),
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

# Phase 71: moved into ai/prompts/agent_prompts.py - kept as a module-level
# name here too, since this is the agent's own public prompt constant.
SYSTEM_PROMPT = ORCHESTRATION_SYSTEM_PROMPT

TOOL_FUNCTIONS = {
    # SearchKnowledgeBase also takes the tool call's own search_strategy arg
    # (the agent's own choice) plus role/department (Phase 231, Document
    # ACL - the caller's own enforced identity, never the agent's choice).
    "SearchKnowledgeBase": lambda args, employee_id, role, department: search_knowledge_base(
        args.get("input", ""), args.get("search_strategy"), role=role, department=department
    ),
    "GetLeaveBalance": lambda args, employee_id, role, department: get_leave_balance_tool(employee_id),
    "GetLeaveHistory": lambda args, employee_id, role, department: get_leave_history_tool(employee_id),
}


def _build_llm() -> ChatOpenAI:
    return build_agent_llm()


async def run_agent(
    query: str,
    employee_id: str | None,
    max_iterations: int | None = None,
    enable_conversation_memory: bool = False,
    conversation_id: str | None = None,
    request_id: str | None = None,
    judge_model: str | None = None,
    eval_score_threshold: float | None = None,
    search_strategy: str | None = None,
    role: str | None = None,
    department: str | None = None,
) -> dict:
    """Runs the tool-calling loop for one query - guardrailed and memory-
    tracked via the Phase 98 shared core (previously had neither: no
    check_input()/check_output() anywhere in this file). Every result is
    now saved to history, including the iteration-exhausted case - matches
    genai-rag's own behavior, which has no equivalent skip-save case.

    Phase 110: explainability/latency/token parity with genai-rag, plus
    caching for the correctness-safe subset of answers - see
    RAG-ROADMAP.md's Phase 110 entry for why GetLeaveBalance/
    GetLeaveHistory turns are excluded from the cache but SearchKnowledgeBase
    ones are not.

    Phase 228: search_strategy is a DEFAULT for SearchKnowledgeBase tool
    calls, used only when the agent's own tool call doesn't specify one
    (Phase 216 already lets it choose "mmr" per call) - never forces the
    agent's own live choice.

    Phase 231: role/department (Document ACL) are the caller's own
    enforced identity, passed to every tool call uniformly (unused by
    GetLeaveBalance/GetLeaveHistory) - unlike search_strategy, never a
    per-call agent choice, so there's no "default vs. override" nuance here."""
    started_at = time.perf_counter()
    normalized_query = await normalize_query(query)
    resolved_max_iterations = max_iterations or DEFAULT_MAX_ITERATIONS
    llm = _build_llm().bind(tools=AGENTIC_TOOL_DEFINITIONS)

    resolved_conversation_id = None
    if enable_conversation_memory:
        resolved_conversation_id = conversation_id or conversation_memory.new_conversation_id()

    # Phase 231: role/department added - same reasoning as pipeline.py's
    # own cache key (a cached answer's citations can depend on which
    # documents the ORIGINAL caller's role/department could see).
    cache_key = build_cache_key(
        normalized_query, pipeline="single-agentic-rag", max_iterations=resolved_max_iterations,
        search_strategy=search_strategy, role=role, department=department,
    )
    cached_result = await get_db_gateway().answer_cache().get(cache_key)
    if cached_result is not None:
        logger.info("Answer cache hit for %r (single-agentic-rag)", normalized_query)
        result = dict(cached_result)
        result["conversation_id"] = resolved_conversation_id
        if resolved_conversation_id:
            await conversation_memory.save_turn(resolved_conversation_id, employee_id, normalized_query, result["answer"])
            await get_db_gateway().answer_cache().tag_conversation(resolved_conversation_id, cache_key)
        # Phase 173 - the cache key is itself normalized-query-based, so a
        # hit always implies this same normalized text, regardless of
        # whether the cached entry predates this field.
        result["query"] = normalized_query
        result["served_from_cache"] = True
        result["llm_call_count"] = 0
        result["token_usage"] = None
        # Phase 160: a cached result's turns describe the ORIGINAL call that
        # populated this cache entry, not this one - same discipline
        # genai-rag's own cache-hit path already applies to its llm_context.
        result["llm_context"] = None
        result["latency_ms"] = {"total": _elapsed_ms(started_at), "retrieval": None, "generation": None, "eval": None}
        return result

    async def generate(checked_query: str, chat_history: list | None) -> dict:
        system_prompt = SYSTEM_PROMPT
        if should_use_tabular_format(checked_query):
            system_prompt = f"{SYSTEM_PROMPT}\n\n{TABULAR_FORMAT_INSTRUCTION}"
        messages = [SystemMessage(content=system_prompt), *(chat_history or []), HumanMessage(content=checked_query)]
        tools_used = []
        tool_outputs = []  # raw tool output text, kept alongside tools_used - needed to eval groundedness (Phase 69)
        sources = []  # structured RetrievedChunk-shaped dicts, for real citations (Phase 115)
        turns = []  # Phase 160 - one real LlmContextTurn per ReAct iteration
        total_prompt_tokens = 0
        total_completion_tokens = 0
        llm_call_count = 0
        generation_started_at = time.perf_counter()

        def _token_usage() -> dict | None:
            if llm_call_count == 0:
                return None
            return {
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
            }

        config = {"metadata": {"request_id": request_id}} if request_id else None
        for i in range(resolved_max_iterations):
            iteration_started_at = time.perf_counter()
            with log_backend_call(logger, "orchestration_agent", "ainvoke", iteration=i + 1, request_id=request_id):
                response = await asyncio.wait_for(llm.ainvoke(messages, config=config), timeout=AGENT_LLM_TIMEOUT_SECONDS)
            iteration_latency_ms = round((time.perf_counter() - iteration_started_at) * 1000, 1)
            llm_call_count += 1
            turns.append(_render_turn(f"iteration {i + 1}", messages, response.content, latency_ms=iteration_latency_ms))

            if response.usage_metadata:
                total_prompt_tokens += response.usage_metadata["input_tokens"]
                total_completion_tokens += response.usage_metadata["output_tokens"]
                logger.info(
                    "[orchestration_agent] tokens used: %s prompt + %s completion",
                    response.usage_metadata["input_tokens"],
                    response.usage_metadata["output_tokens"],
                )

            messages.append(response)

            if not response.tool_calls:
                return {
                    "answer": response.content,
                    "tools_used": tools_used,
                    "tool_outputs": tool_outputs,
                    "sources": sources,
                    "iterations": i + 1,
                    "llm_call_count": llm_call_count,
                    "token_usage": _token_usage(),
                    "llm_context": {"turns": turns, "mcp_tool_calls": []},
                    "latency_ms": {"total": None, "retrieval": None, "generation": _elapsed_ms(generation_started_at)},
                }

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_input = tool_args.get("input", "")

                # Phase 228 - the caller's own search_strategy DEFAULT only
                # fills in when the agent's own tool call didn't already
                # make its own choice (Phase 216) - never overrides it.
                if tool_name == "SearchKnowledgeBase" and "search_strategy" not in tool_args and search_strategy:
                    tool_args = {**tool_args, "search_strategy": search_strategy}

                tool_function = TOOL_FUNCTIONS.get(tool_name)
                tool_call_started_at = time.perf_counter()
                if tool_function is None:
                    tool_output, tool_chunks = f"Error: unknown tool {tool_name!r}", []
                else:
                    tool_output, tool_chunks = await tool_function(tool_args, employee_id, role, department)
                tool_call_latency_ms = _elapsed_ms(tool_call_started_at)

                tools_used.append(
                    {
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                        "tool_type": classify_tool(tool_name),
                        # Phase 216 - the agent's own search_strategy choice was
                        # being silently dropped here before (only "input" was
                        # captured from tool_args); None for every other tool.
                        "search_strategy": tool_args.get("search_strategy"),
                        "latency_ms": tool_call_latency_ms,
                        "success": not tool_output.startswith("Error:"),
                        "iteration": i + 1,
                    }
                )
                tool_outputs.append(tool_output)
                sources.extend(tool_chunks)
                logger.info("Agent called tool=%s input=%r args=%r", tool_name, tool_input[:80], tool_args)
                messages.append(ToolMessage(content=tool_output, tool_call_id=tool_call["id"]))

        return {
            "answer": "I wasn't able to finish reasoning about this within the allowed number of steps. Please rephrase or ask a more specific question.",
            "tools_used": tools_used,
            "tool_outputs": tool_outputs,
            "sources": sources,
            "iterations": resolved_max_iterations,
            "llm_call_count": llm_call_count,
            "token_usage": _token_usage(),
            "llm_context": {"turns": turns, "mcp_tool_calls": []},
            "latency_ms": {"total": None, "retrieval": None, "generation": _elapsed_ms(generation_started_at)},
        }

    result = await run_guarded_pipeline(
        normalized_query, employee_id, enable_conversation_memory, conversation_id, generate
    )

    # Phase 173 - so a caller can show what was actually processed (post-
    # normalization) rather than the raw submitted text, same as
    # genai-rag's and multi-agentic-rag's own result dicts already do.
    result["query"] = normalized_query
    result["served_from_cache"] = False
    eval_scores, eval_ms = await _score_live_answer(
        normalized_query, result["answer"], result.get("tool_outputs") or [],
        sources=result.get("sources") or [],
        judge_model=judge_model, eval_score_threshold=eval_score_threshold,
    )
    result["eval_scores"] = eval_scores
    result["latency_ms"]["eval"] = eval_ms
    result["latency_ms"]["total"] = _elapsed_ms(started_at)

    # Phase 140: a non-deterministic LLM tool choice must not get a free
    # pass into a 6h cache - if the query itself looks like it's asking for
    # live personal data (same heuristic genai-rag's MCP fast-path and
    # multi-agentic-rag's lms_ops_agent already use for this), it stays
    # uncached even when this one run happened not to call the live-data
    # tool. Closes the loophole where one wrong tool-skip gets served back
    # as "correct" for 6 hours to every identical future query.
    cache_eligible = (
        not any(call["tool_name"] in LIVE_DATA_TOOLS for call in result["tools_used"])
        and not is_leave_balance_query(normalized_query)
        and not is_leave_history_query(normalized_query)
    )
    if cache_eligible:
        await get_db_gateway().answer_cache().set(cache_key, normalized_query, result)
        if result.get("conversation_id"):
            await get_db_gateway().answer_cache().tag_conversation(result["conversation_id"], cache_key)

    return result
