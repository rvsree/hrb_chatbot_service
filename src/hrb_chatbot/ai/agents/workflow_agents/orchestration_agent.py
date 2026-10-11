"""Single-agentic-rag's tool-calling loop - uses ChatOpenAI directly, not GatewayChatModel (see RAG-ROADMAP.md Phase 55)."""

import asyncio
import time

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI

from src.hrb_chatbot.ai.agents._llm_helpers import AGENT_LLM_TIMEOUT_SECONDS, build_agent_llm
from src.hrb_chatbot.ai.pre_processing import conversation_memory
from src.hrb_chatbot.ai.prompts.agent_prompts import ORCHESTRATION_SYSTEM_PROMPT
from src.hrb_chatbot.ai.rag_core.guarded_pipeline import run_guarded_pipeline
from src.hrb_chatbot.ai.rag_core.response_format import TABULAR_FORMAT_INSTRUCTION, should_use_tabular_format
from src.hrb_chatbot.ai.rag_core.tool_classification import classify_tool
from src.hrb_chatbot.ai.rag_pipeline.evaluations.golden_dataset_harness import evaluate_completeness, evaluate_groundedness
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


async def _score_live_answer(query: str, answer: str, context_texts: list[str]) -> tuple[dict | None, float | None]:
    """Same approach as pipeline.py's own _score_live_answer() (Phase 109) -
    skipped when there's no tool-retrieved context to check groundedness
    against, both judge calls run in parallel via asyncio.to_thread()."""
    if not context_texts:
        return None, None

    eval_started_at = time.perf_counter()
    groundedness, completeness = await asyncio.gather(
        asyncio.to_thread(evaluate_groundedness, answer, context_texts),
        asyncio.to_thread(evaluate_completeness, query, answer),
    )
    eval_scores = {
        "groundedness": groundedness["score"],
        "groundedness_verdict": groundedness["verdict"],
        "completeness": completeness["score"],
        "completeness_verdict": completeness["verdict"],
    }
    return eval_scores, _elapsed_ms(eval_started_at)

# Phase 71: moved into ai/prompts/agent_prompts.py - kept as a module-level
# name here too, since this is the agent's own public prompt constant.
SYSTEM_PROMPT = ORCHESTRATION_SYSTEM_PROMPT

TOOL_FUNCTIONS = {
    # SearchKnowledgeBase also takes the tool call's own search_strategy arg (the agent's own choice).
    "SearchKnowledgeBase": lambda args, employee_id: search_knowledge_base(
        args.get("input", ""), args.get("search_strategy")
    ),
    "GetLeaveBalance": lambda args, employee_id: get_leave_balance_tool(employee_id),
    "GetLeaveHistory": lambda args, employee_id: get_leave_history_tool(employee_id),
}


def _build_llm() -> ChatOpenAI:
    return build_agent_llm()


async def run_agent(
    query: str,
    employee_id: str | None,
    max_iterations: int | None = None,
    enable_conversation_memory: bool = False,
    conversation_id: str | None = None,
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
    ones are not."""
    started_at = time.perf_counter()
    resolved_max_iterations = max_iterations or DEFAULT_MAX_ITERATIONS
    llm = _build_llm().bind(tools=AGENTIC_TOOL_DEFINITIONS)

    resolved_conversation_id = None
    if enable_conversation_memory:
        resolved_conversation_id = conversation_id or conversation_memory.new_conversation_id()

    cache_key = build_cache_key(query, pipeline="single-agentic-rag", max_iterations=resolved_max_iterations)
    cached_result = await get_db_gateway().answer_cache().get(cache_key)
    if cached_result is not None:
        logger.info("Answer cache hit for %r (single-agentic-rag)", query)
        result = dict(cached_result)
        result["conversation_id"] = resolved_conversation_id
        if resolved_conversation_id:
            await conversation_memory.save_turn(resolved_conversation_id, employee_id, query, result["answer"])
            await get_db_gateway().answer_cache().tag_conversation(resolved_conversation_id, cache_key)
        result["served_from_cache"] = True
        result["llm_call_count"] = 0
        result["token_usage"] = None
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

        for i in range(resolved_max_iterations):
            with log_backend_call(logger, "orchestration_agent", "ainvoke", iteration=i + 1):
                response = await asyncio.wait_for(llm.ainvoke(messages), timeout=AGENT_LLM_TIMEOUT_SECONDS)
            llm_call_count += 1

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
                    "latency_ms": {"total": None, "retrieval": None, "generation": _elapsed_ms(generation_started_at)},
                }

            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_input = tool_args.get("input", "")

                tool_function = TOOL_FUNCTIONS.get(tool_name)
                tool_call_started_at = time.perf_counter()
                if tool_function is None:
                    tool_output, tool_chunks = f"Error: unknown tool {tool_name!r}", []
                else:
                    tool_output, tool_chunks = await tool_function(tool_args, employee_id)
                tool_call_latency_ms = _elapsed_ms(tool_call_started_at)

                tools_used.append(
                    {
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                        "tool_type": classify_tool(tool_name),
                        "latency_ms": tool_call_latency_ms,
                        "success": not tool_output.startswith("Error:"),
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
            "latency_ms": {"total": None, "retrieval": None, "generation": _elapsed_ms(generation_started_at)},
        }

    result = await run_guarded_pipeline(query, employee_id, enable_conversation_memory, conversation_id, generate)

    result["served_from_cache"] = False
    eval_scores, eval_ms = await _score_live_answer(query, result["answer"], result.get("tool_outputs") or [])
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
        and not is_leave_balance_query(query)
        and not is_leave_history_query(query)
    )
    if cache_eligible:
        await get_db_gateway().answer_cache().set(cache_key, query, result)
        if result.get("conversation_id"):
            await get_db_gateway().answer_cache().tag_conversation(result["conversation_id"], cache_key)

    return result
