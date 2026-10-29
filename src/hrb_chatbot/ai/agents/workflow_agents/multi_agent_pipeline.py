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

from src.hrb_chatbot.ai.agents._llm_helpers import resolve_agent_model
from src.hrb_chatbot.ai.agents.domain_agents import (
    lms_analytics_agent,
    lms_ops_agent,
    sql_db_agent,
    vector_kb_agent,
    web_search_agent,
)
from src.hrb_chatbot.ai.agents.workflow_agents import planner_agent, reviewer_agent
from src.hrb_chatbot.ai.search_pre_processing import conversation_memory
from src.hrb_chatbot.ai.search_pre_processing.guardrails_input import check_input
from src.hrb_chatbot.ai.search_pre_processing.query_normalize import normalize_query
from src.hrb_chatbot.ai.rag_core.eval_threshold import (
    build_eval_scores,
    maybe_capture_live_query,
    retrieval_relevance_enabled,
    run_enabled_eval_judges,
)
from src.hrb_chatbot.ai.rag_core.guarded_pipeline import run_guarded_pipeline
from src.hrb_chatbot.ai.rag_core.tool_classification import classify_tool
from src.hrb_chatbot.ai.rag_pipeline.query_retrieval.exact_knn_search import search_knn
from src.hrb_chatbot.common.clients.cache_client.answer_cache import build_cache_key
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("agents.multi_agent_pipeline")

# Phase 115: mirrors orchestration_agent.py's own LIVE_DATA_TOOLS, one
# level up at the agent-dispatch granularity - every domain agent except
# vector_kb_agent, which only queries the same static document index
# genai-rag's own retrieval does.
LIVE_DATA_AGENTS = {"lms_ops_agent", "sql_db_agent", "lms_analytics_agent", "web_search_agent"}

# Phase 259 - same value LangGraph's own implicit default already uses (25),
# now an explicit, reviewed constant in this project's own code rather than
# relying on the library default never being looked at again.
GRAPH_RECURSION_LIMIT = 25


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 1)


# Phase 220 - same wider-pool approach pipeline.py/orchestration_agent.py's
# own _score_live_answer() already use (Phase 219/220): agent_result_texts
# mixes KB-chunk content with web-search/MCP/other agent text, which isn't
# something exact-KNN can compare against, so the retrieval judge
# (precision/recall/f1) scopes to `sources` - the structured, real KB-chunk
# list Phase 115/120 already built for citations - instead of that mixed
# text. Groundedness/completeness are unaffected, still judged against the
# full agent_result_texts.
WIDER_POOL_MULTIPLIER = 4
WIDER_POOL_MAX = 20
# vector_kb_agent.run() calls search_knowledge_base(focus) with no top_k
# override, which itself hardcodes top_k=3 (agentic_tools.py) - mirrored
# here, not guessed.
VECTOR_KB_AGENT_TOP_K = 3


def _chunk_key(chunk: dict) -> tuple:
    return (chunk.get("document_id"), chunk.get("chunk_index"))


async def _fetch_wider_pool_texts(query: str, original_sources: list[dict]) -> list[str]:
    wider_k = min(VECTOR_KB_AGENT_TOP_K * WIDER_POOL_MULTIPLIER, WIDER_POOL_MAX)
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
    """Same approach as pipeline.py/orchestration_agent.py's own
    _score_live_answer() (Phase 109/110). Phase 215: judge_model/
    eval_score_threshold - see ai/rag_core/eval_threshold.py.
    Phase 220: sources (real KB chunks, may be empty even when
    context_texts isn't - e.g. an LMS/web-only answer) drives
    retrieval_precision/recall_estimate/f1_estimate now, instead of
    context_texts - see the module comment above _fetch_wider_pool_texts.
    Phase 246: EVAL_*_ENABLED switches - see pipeline.py's own docstring
    note, same reasoning applies here."""
    if not context_texts:
        return None, None

    kb_chunk_texts = [chunk["text"] for chunk in sources] if sources else []
    wider_pool_texts = (
        await _fetch_wider_pool_texts(query, sources) if sources and retrieval_relevance_enabled() else None
    )

    eval_started_at = time.perf_counter()
    groundedness, completeness, retrieval, answer_relevancy = await run_enabled_eval_judges(
        query, answer, context_texts, kb_chunk_texts, judge_model, wider_pool_texts
    )
    eval_scores = build_eval_scores(groundedness, completeness, retrieval, eval_score_threshold, answer_relevancy)
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
    request_id: str | None
    # Phase 228 - only vector_kb_agent_node reads this; other domain
    # agents ignore it, harmless to thread through all of them uniformly.
    search_strategy: str | None
    # Phase 231 (Document ACL) - same reasoning as search_strategy above:
    # only vector_kb_agent_node uses these, harmless to thread uniformly.
    role: str | None
    department: str | None
    # Phase 243 - per-request override for the Planner's own model.
    planner_model: str | None
    tasks: list[dict]
    agent_results: Annotated[list[dict], operator.add]
    answer: str
    follow_up_questions: list[str]
    # Phase 160 - the only 2 of 7 nodes that make a real LLM call.
    planner_turn: dict | None
    reviewer_turn: dict | None


async def planner_node(state: MultiAgentState) -> dict:
    tasks, turn = await planner_agent.plan(
        state["query"], request_id=state.get("request_id"), planner_model=state.get("planner_model")
    )
    return {"tasks": tasks, "planner_turn": turn}


def dispatch_to_agents(state: MultiAgentState) -> list[Send]:
    """The Orchestration Agent's dispatch step - fans each task out to its domain
    agent in parallel via LangGraph's own Send() API, not asyncio.gather()."""
    return [
        Send(
            task["agent"],
            {
                "query": state["query"],
                "employee_id": state["employee_id"],
                "focus": task["focus"],
                "search_strategy": state.get("search_strategy"),
                "role": state.get("role"),
                "department": state.get("department"),
            },
        )
        for task in state["tasks"]
    ]


async def vector_kb_agent_node(state: dict) -> dict:
    started_at = time.perf_counter()
    result, chunks = await vector_kb_agent.run(
        state["focus"],
        search_strategy=state.get("search_strategy"),
        role=state.get("role"),
        department=state.get("department"),
    )
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
    answer, turn = await reviewer_agent.review(state["query"], state["agent_results"], request_id=state.get("request_id"))
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
    request_id: str | None = None,
    judge_model: str | None = None,
    eval_score_threshold: float | None = None,
    search_strategy: str | None = None,
    role: str | None = None,
    department: str | None = None,
    planner_model: str | None = None,
    guardrails_model: str | None = None,
    full_name: str | None = None,
    ip_address: str | None = None,
    timezone: str | None = None,
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
    logged gap (BACKLOG.md), not silently skipped.

    Phase 228: search_strategy only affects vector_kb_agent - unlike
    single-agentic-rag, there's no agent-level choice to defer to here,
    this is the only lever."""
    started_at = time.perf_counter()
    normalized_query = await normalize_query(query)
    checked_query, input_guardrail_status = await check_input(normalized_query, guardrails_model=guardrails_model)

    resolved_conversation_id = None
    if enable_conversation_memory:
        resolved_conversation_id = conversation_id or conversation_memory.new_conversation_id()

    # Phase 231: role/department added - same reasoning as pipeline.py's
    # own cache key (a cached answer's citations can depend on which
    # documents the ORIGINAL caller's role/department could see).
    cache_key = build_cache_key(
        checked_query, pipeline="multi-agentic-rag", search_strategy=search_strategy, role=role, department=department
    )
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
        # Phase 243: the Planner didn't run this call either - same reasoning.
        result["planner_model_used"] = None
        # Phase 173 - the cache key is itself normalized-query-based, so a
        # hit always implies this same normalized text, regardless of
        # whether the cached entry predates this field.
        result["query"] = checked_query
        return result

    # Phase 245 - the graph-invoke-through-result-shaping block below is now
    # this closure, run through the shared Phase 98 core (ai/rag_core/
    # guarded_pipeline.py) instead of calling check_input()/check_output()
    # directly - removes the direct-call exception CLAUDE.md used to
    # document for this file. chat_history is accepted (required by the
    # shared GenerateFn signature) but deliberately unused - preserves
    # today's real behavior (confirmed by grep before this phase: no
    # chat_history reference anywhere in this file previously) rather than
    # silently wiring conversation-context-aware answers as a side effect.
    async def generate(generate_query: str, chat_history: list | None) -> dict:
        graph = get_graph()
        # Phase 201: request_id in both the graph's own state (so planner_node/
        # reviewer_node can thread it to their own LLM calls) and this config -
        # tags the whole graph run's own LangSmith trace, if tracing is on.
        # Phase 259: recursion_limit explicit, not LangGraph's own implicit
        # default (25) - same value, but now a reviewed constant in this
        # project's own code, matching DEFAULT_MAX_ITERATIONS already being
        # explicit for the other 2 agentic loops (orchestration_agent.py/
        # adhoc_document_agent.py).
        graph_config = {"recursion_limit": GRAPH_RECURSION_LIMIT}
        if request_id:
            graph_config["metadata"] = {"request_id": request_id}
        final_state = await graph.ainvoke(
            {
                "query": generate_query,
                "employee_id": employee_id,
                "request_id": request_id,
                "search_strategy": search_strategy,
                "role": role,
                "department": department,
                "planner_model": planner_model,
                "tasks": [],
                "agent_results": [],
                "answer": "",
                "follow_up_questions": [],
                "planner_turn": None,
                "reviewer_turn": None,
            },
            config=graph_config,
        )

        agent_results = final_state["agent_results"]
        tools_used = [
            {
                "tool_name": agent_result["agent"],
                "tool_input": agent_result["focus"],
                "tool_type": classify_tool(agent_result["agent"]),
                "latency_ms": agent_result.get("latency_ms"),
                "success": not agent_result["result"].startswith("Error:"),
            }
            for agent_result in agent_results
        ]
        # Raw per-domain-agent result text, kept alongside tools_used - needed to eval
        # groundedness against what was actually retrieved (Phase 69), not just the final answer.
        agent_result_texts = [agent_result["result"] for agent_result in agent_results]
        # Real citations (Phase 115/120) - always [] except vector_kb_agent/lms_ops_agent.
        sources = [chunk for agent_result in agent_results for chunk in agent_result.get("sources", [])]

        # Phase 160 - only planner/reviewer make a real LLM call; every domain
        # agent is LLM-free (retrieval/MCP/web-search calls, or a stub) - their
        # own activity already surfaces via tools_used, not duplicated here.
        turns = [turn for turn in (final_state.get("planner_turn"), final_state.get("reviewer_turn")) if turn]
        llm_context = {"turns": turns, "mcp_tool_calls": []} if turns else None

        return {
            "answer": final_state["answer"],
            "tasks": final_state["tasks"],
            "follow_up_questions": final_state["follow_up_questions"],
            "tools_used": tools_used,
            "agent_result_texts": agent_result_texts,
            "sources": sources,
            # Domain agents dispatched in this one-shot fan-out, not reasoning rounds -
            # multi-agentic-rag has no retry loop.
            "iterations": len(agent_results),
            "served_from_cache": False,
            # Only planner_turn/reviewer_turn are real LLM calls (see the comment
            # above `turns`) - domain agents are LLM-free, so this must not count them.
            "llm_call_count": len(turns),
            "token_usage": None,
            "planner_model_used": resolve_agent_model("OPENAI_PLANNER_MODEL", planner_model),
            "llm_context": llm_context,
            "latency_ms": {"total": None, "retrieval": None, "generation": None, "eval": None},
        }

    result = await run_guarded_pipeline(
        checked_query, employee_id, enable_conversation_memory, conversation_id, generate,
        pre_checked_query=checked_query, pre_checked_input_status=input_guardrail_status,
        guardrails_model=guardrails_model,
        full_name=full_name, role=role, ip_address=ip_address, timezone=timezone,
    )
    result["query"] = checked_query

    eval_scores, eval_ms = await _score_live_answer(
        checked_query, result["answer"], result["agent_result_texts"], sources=result["sources"],
        judge_model=judge_model, eval_score_threshold=eval_score_threshold,
    )
    result["eval_scores"] = eval_scores
    result["latency_ms"]["eval"] = eval_ms
    result["latency_ms"]["total"] = _elapsed_ms(started_at)

    await maybe_capture_live_query(
        checked_query, result["answer"], eval_scores, "multi-agentic-rag", request_id, employee_id
    )

    cache_eligible = not any(task["agent"] in LIVE_DATA_AGENTS for task in result["tasks"])
    if cache_eligible:
        await get_db_gateway().answer_cache().set(cache_key, checked_query, result)
        if result.get("conversation_id"):
            await get_db_gateway().answer_cache().tag_conversation(result["conversation_id"], cache_key)

    return result
