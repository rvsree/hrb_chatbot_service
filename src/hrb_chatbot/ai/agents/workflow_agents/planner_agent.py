"""Planner Agent - multi-agentic-rag's classification step. One structured-output
LLM call, same ChatOpenAI-direct pattern as orchestration_agent.py."""

import asyncio
import time
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from src.hrb_chatbot.ai.agents._llm_helpers import AGENT_LLM_TIMEOUT_SECONDS, build_agent_llm
from src.hrb_chatbot.ai.prompts.agent_prompts import PLANNER_SYSTEM_PROMPT
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("agents.planner_agent")

AgentName = Literal[
    "vector_kb_agent", "lms_ops_agent", "sql_db_agent", "lms_analytics_agent", "web_search_agent"
]


class PlannerTask(BaseModel):
    agent: AgentName
    focus: str
    reasoning: str


class PlannerOutput(BaseModel):
    tasks: list[PlannerTask]


def _build_llm() -> ChatOpenAI:
    # Classification is the simplest of this project's three agent LLM calls - cheap enough
    # to tier onto its own, overridable model (Phase 65) without touching Reviewer/orchestration.
    return build_agent_llm("OPENAI_PLANNER_MODEL")


async def plan(query: str, request_id: str | None = None) -> tuple[list[dict], dict]:
    """Classifies one query into one or more {agent, focus} tasks. Never returns an empty list.

    Phase 160: also returns the real LlmContextTurn-shaped dict for this
    call - the exact system_prompt/query/response actually sent, not a
    re-derived guess. Phase 201: request_id, when given, tags this call's
    own LangSmith trace metadata."""
    # include_raw=True (verified live) is what exposes the raw AIMessage's
    # usage_metadata - with_structured_output() alone returns only the parsed object.
    llm = _build_llm().with_structured_output(PlannerOutput, include_raw=True)
    messages = [SystemMessage(content=PLANNER_SYSTEM_PROMPT), HumanMessage(content=query)]
    config = {"metadata": {"request_id": request_id}} if request_id else None

    started_at = time.perf_counter()
    with log_backend_call(logger, "planner_agent", "plan", request_id=request_id):
        result = await asyncio.wait_for(llm.ainvoke(messages, config=config), timeout=AGENT_LLM_TIMEOUT_SECONDS)
    latency_ms = round((time.perf_counter() - started_at) * 1000, 1)

    usage = result["raw"].usage_metadata
    if usage:
        logger.info("[planner_agent] tokens used: %s prompt + %s completion", usage["input_tokens"], usage["output_tokens"])

    output: PlannerOutput | None = result["parsed"]
    tasks = (
        [{"agent": task.agent, "focus": task.focus, "reasoning": task.reasoning} for task in output.tasks]
        if output
        else []
    )
    if not tasks:
        tasks = [
            {
                "agent": "vector_kb_agent",
                "focus": query,
                "reasoning": "Fallback - the Planner's structured output didn't parse, so this defaulted to the knowledge base rather than a real Planner decision.",
            }
        ]

    logger.info("Planner routed query to %s", [task["agent"] for task in tasks])
    turn = {
        "label": "planner",
        "latency_ms": latency_ms,
        "system_prompt": PLANNER_SYSTEM_PROMPT,
        "human_message": query,
        "chat_history": [],
        "response": str(output) if output else (result["raw"].content or ""),
    }
    return tasks, turn
