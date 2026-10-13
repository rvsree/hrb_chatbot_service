"""Multi-agentic-rag's real LangGraph graph (Phase 64): Planner Agent ->
Orchestration Agent dispatch (Send fan-out) -> 4 domain agents in parallel ->
Reviewer Agent. Hierarchical/LangGraph-supervisor pattern, per the user's
explicit, final direction - not Azure's flat single-agent-many-tools pattern."""

import asyncio
import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from src.hrb_chatbot.ai.agents.domain_agents import (
    lms_analytics_agent,
    lms_ops_agent,
    sql_db_agent,
    vector_kb_agent,
    web_search_agent,
)
from src.hrb_chatbot.ai.agents.workflow_agents import planner_agent, reviewer_agent
from src.hrb_chatbot.ai.pre_processing import conversation_memory
from src.hrb_chatbot.ai.pre_processing.guardrails_input import check_input
from src.hrb_chatbot.ai.pre_processing.query_normalize import normalize_query
from src.hrb_chatbot.ai.rag_core.tool_classification import classify_tool
from src.hrb_chatbot.ai.rag_pipeline.evaluations.golden_dataset_harness import evaluate_completeness, evaluate_groundedness
from src.hrb_chatbot.ai.rag_pipeline.response_generation.guardrails_output import check_output
from src.hrb_chatbot.common.clients.cache_client.answer_cache import build_cache_key
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("agents.multi_agent_pipeline")

# Phase 115: mirrors orchestration_agent.py's own LIVE_DATA_TOOLS, one
# level up at the agent-dispatch granularity - every domain agent except
# vector_kb_agent, which only queries the same static document index
# genai-rag's own retrieval does.
LIVE_DATA_AGENTS = {"lms_ops_agent", "sql_db_agent", "lms_analytics_agent", "web_search_agent"}


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)


async def _score_live_answer(query: str, answer: str, context_texts: list[str]) -> tuple[dict | None, float | None]:
    """Same approach as pipeline.py/orchestration_agent.py's own
    _score_live_answer() (Phase 109/110)."""
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

DOMAIN_AGENT_NODES = [
    "vector_kb_agent",
    "lms_ops_agent",
    "sql_db_agent",
    "lms_analytics_agent",
    "web_search_agent",
]


class MultiAgentState(TypedDict):
    query: str
    employee_id: str | None
    tasks: list[dict]
    agent_results: Annotated[list[dict], operator.add]
    answer: str
    follow_up_questions: list[str]
    # Phase 160 - the only 2 of 7 nodes that make a real LLM call.
    planner_turn: dict | None
    reviewer_turn: dict | None


async def planner_node(state: MultiAgentState) -> dict:
    tasks, turn = await planner_agent.plan(state["query"])
    return {"tasks": tasks, "planner_turn": turn}


def dispatch_to_agents(state: MultiAgentState) -> list[Send]:
    """The Orchestration Agent's dispatch step - fans each task out to its domain
    agent in parallel via LangGraph's own Send() API, not asyncio.gather()."""
    return [
        Send(task["agent"], {"query": state["query"], "employee_id": state["employee_id"], "focus": task["focus"]})
        for task in state["tasks"]
    ]


async def vector_kb_agent_node(state: dict) -> dict:
    started_at = time.perf_counter()
    result, chunks = await vector_kb_agent.run(state["focus"])
    return {
        "agent_results": [
            {
                "agent": "vector_kb_agent",
                "focus": state["focus"],
                "result": result,
                "sources": chunks,
                "latency_ms": _elapsed_ms(started_at),
            }
        ]
    }


async def lms_ops_agent_node(state: dict) -> dict:
    started_at = time.perf_counter()
    result, chunks = await lms_ops_agent.run(state["focus"], state["employee_id"])
    return {
        "agent_results": [
            {
                "agent": "lms_ops_agent",
                "focus": state["focus"],
                "result": result,
                "sources": chunks,
                "latency_ms": _elapsed_ms(started_at),
            }
        ]
    }


async def sql_db_agent_node(state: dict) -> dict:
    started_at = time.perf_counter()
    result = await sql_db_agent.run(state["focus"])
    return {
        "agent_results": [
            {"agent": "sql_db_agent", "focus": state["focus"], "result": result, "latency_ms": _elapsed_ms(started_at)}
        ]
    }


async def lms_analytics_agent_node(state: dict) -> dict:
    started_at = time.perf_counter()
    result = await lms_analytics_agent.run(state["focus"])
    return {
        "agent_results": [
            {
                "agent": "lms_analytics_agent",
                "focus": state["focus"],
                "result": result,
                "latency_ms": _elapsed_ms(started_at),
            }
        ]
    }


async def web_search_agent_node(state: dict) -> dict:
    started_at = time.perf_counter()
    result = await web_search_agent.run(state["focus"])
    return {
        "agent_results": [
            {
                "agent": "web_search_agent",
                "focus": state["focus"],
                "result": result,
                "latency_ms": _elapsed_ms(started_at),
            }
        ]
    }


async def reviewer_node(state: MultiAgentState) -> dict:
    answer, turn = await reviewer_agent.review(state["query"], state["agent_results"])
    follow_up_questions = (
        await reviewer_agent.generate_follow_ups(state["query"], answer) if state["agent_results"] else []
    )
    return {"answer": answer, "follow_up_questions": follow_up_questions, "reviewer_turn": turn}


def _build_graph():
    graph = StateGraph(MultiAgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("vector_kb_agent", vector_kb_agent_node)
    graph.add_node("lms_ops_agent", lms_ops_agent_node)
    graph.add_node("sql_db_agent", sql_db_agent_node)
    graph.add_node("lms_analytics_agent", lms_analytics_agent_node)
    graph.add_node("web_search_agent", web_search_agent_node)
    graph.add_node("reviewer", reviewer_node)

    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", dispatch_to_agents, DOMAIN_AGENT_NODES)
    for node_name in DOMAIN_AGENT_NODES:
        graph.add_edge(node_name, "reviewer")
    graph.add_edge("reviewer", END)
    return graph.compile()


_GRAPH = None


def get_graph():
    """Builds the compiled graph once and reuses it - same lazy-singleton shape as this project's client gateways."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = _build_graph()
    return _GRAPH


async def run_multi_agent(
    query: str,
    employee_id: str | None,
    enable_conversation_memory: bool = False,
    conversation_id: str | None = None,
) -> dict:
    """Runs the Planner -> Orchestration -> domain agents -> Reviewer graph for one query.
    Guardrails run here, same layer as genai-rag's pipeline.answer_query() - the route
    (api/multi_agentic_rag/query_agent.py) only catches GuardrailBlockedError.

    Phase 110/115: total latency + llm_call_count + eval scores + real
    citations + caching, same shape as genai-rag/single-agentic-rag's own
    ExplainabilityInfo. Caching mirrors single-agentic-rag's own
    LIVE_DATA_TOOLS pattern one level up, at agent-dispatch granularity
    (LIVE_DATA_AGENTS) - see RAG-ROADMAP.md's Phase 115 entry. Per-
    domain-agent token capture is still not done (would touch all 7
    agent files this phase doesn't otherwise need to change) - a real,
    logged gap (BACKLOG.md), not silently skipped."""
    started_at = time.perf_counter()
    normalized_query = await normalize_query(query)
    checked_query = await check_input(normalized_query)

    resolved_conversation_id = None
    if enable_conversation_memory:
        resolved_conversation_id = conversation_id or conversation_memory.new_conversation_id()

    cache_key = build_cache_key(checked_query, pipeline="multi-agentic-rag")
    cached_result = await get_db_gateway().answer_cache().get(cache_key)
    if cached_result is not None:
        logger.info("Answer cache hit for %r (multi-agentic-rag)", checked_query)
        result = dict(cached_result)
        result["conversation_id"] = resolved_conversation_id
        if resolved_conversation_id:
            await conversation_memory.save_turn(resolved_conversation_id, employee_id, checked_query, result["answer"])
            await get_db_gateway().answer_cache().tag_conversation(resolved_conversation_id, cache_key)
        result["served_from_cache"] = True
        result["llm_call_count"] = 0
        result["token_usage"] = None
        result["latency_ms"] = {"total": _elapsed_ms(started_at), "retrieval": None, "generation": None, "eval": None}
        # Phase 160: a cached result's turns describe the ORIGINAL call that
        # populated this cache entry, not this one - nothing was actually
        # sent to the LLM this call, same discipline genai-rag's own
        # cache-hit path already applies to its own llm_context.
        result["llm_context"] = None
        # Phase 173 - the cache key is itself normalized-query-based, so a
        # hit always implies this same normalized text, regardless of
        # whether the cached entry predates this field.
        result["query"] = checked_query
        return result

    graph = get_graph()
    final_state = await graph.ainvoke(
        {
            "query": checked_query,
            "employee_id": employee_id,
            "tasks": [],
            "agent_results": [],
            "answer": "",
            "follow_up_questions": [],
            "planner_turn": None,
            "reviewer_turn": None,
        }
    )

    answer = await check_output(checked_query, final_state["answer"])
    if resolved_conversation_id:
        await conversation_memory.save_turn(resolved_conversation_id, employee_id, checked_query, answer)

    agent_results = final_state["agent_results"]
    tools_used = [
        {
            "tool_name": result["agent"],
            "tool_input": result["focus"],
            "tool_type": classify_tool(result["agent"]),
            "latency_ms": result.get("latency_ms"),
            "success": not result["result"].startswith("Error:"),
        }
        for result in agent_results
    ]
    # Raw per-domain-agent result text, kept alongside tools_used - needed to eval
    # groundedness against what was actually retrieved (Phase 69), not just the final answer.
    agent_result_texts = [result["result"] for result in agent_results]
    # Real citations (Phase 115/120) - always [] except vector_kb_agent/lms_ops_agent.
    sources = [chunk for result in agent_results for chunk in result.get("sources", [])]

    eval_scores, eval_ms = await _score_live_answer(checked_query, answer, agent_result_texts)

    # Phase 160 - only planner/reviewer make a real LLM call; every domain
    # agent is LLM-free (retrieval/MCP/web-search calls, or a stub) - their
    # own activity already surfaces via tools_used, not duplicated here.
    turns = [turn for turn in (final_state.get("planner_turn"), final_state.get("reviewer_turn")) if turn]
    llm_context = {"turns": turns, "mcp_tool_calls": []} if turns else None

    result = {
        "query": checked_query,
        "answer": answer,
        "tasks": final_state["tasks"],
        "follow_up_questions": final_state["follow_up_questions"],
        "tools_used": tools_used,
        "agent_result_texts": agent_result_texts,
        "sources": sources,
        "iterations": len(agent_results),
        "conversation_id": resolved_conversation_id,
        "served_from_cache": False,
        # Planner + each dispatched domain agent + Reviewer - a real count
        # of this run's own LLM calls, not a guess.
        "llm_call_count": len(agent_results) + 2,
        "token_usage": None,
        "llm_context": llm_context,
        "eval_scores": eval_scores,
        "latency_ms": {"total": _elapsed_ms(started_at), "retrieval": None, "generation": None, "eval": eval_ms},
    }

    cache_eligible = not any(task["agent"] in LIVE_DATA_AGENTS for task in final_state["tasks"])
    if cache_eligible:
        await get_db_gateway().answer_cache().set(cache_key, checked_query, result)
        if resolved_conversation_id:
            await get_db_gateway().answer_cache().tag_conversation(resolved_conversation_id, cache_key)

    return result
