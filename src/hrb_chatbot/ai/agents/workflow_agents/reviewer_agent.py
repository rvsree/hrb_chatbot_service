"""Reviewer Agent - multi-agentic-rag's merge step. 0/1/2+ branching matches the
IK FDE Travel Planner reference notebook's own synthesizer_node() pattern."""

import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.hrb_chatbot.ai.agents._llm_helpers import AGENT_LLM_TIMEOUT_SECONDS, build_agent_llm
from src.hrb_chatbot.ai.pre_processing.context_builder import build_context_from_agent_results
from src.hrb_chatbot.ai.prompts.agent_prompts import FOLLOW_UP_QUESTIONS_SYSTEM_PROMPT, REVIEWER_SYSTEM_PROMPT
from src.hrb_chatbot.ai.rag_core.response_format import TABULAR_FORMAT_INSTRUCTION, should_use_tabular_format
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("agents.reviewer_agent")


def _build_llm() -> ChatOpenAI:
    return build_agent_llm()


async def review(query: str, agent_results: list[dict]) -> str:
    """Merges every domain agent's result into one final answer. Always goes
    through the LLM, even for exactly one result (Phase 150) - a domain
    agent's raw output (e.g. vector_kb_agent's "Found relevant knowledge
    base content:\n\n--- Source 1 ..." dump) is meta/intermediate text, not
    a presentable answer on its own, so skipping synthesis for the 1-result
    case surfaced that raw dump directly to the user."""
    if not agent_results:
        return "I wasn't able to find an answer to that question."

    combined = build_context_from_agent_results(agent_results)
    llm = _build_llm()
    system_prompt = REVIEWER_SYSTEM_PROMPT
    if should_use_tabular_format(query):
        system_prompt = f"{REVIEWER_SYSTEM_PROMPT}\n\n{TABULAR_FORMAT_INSTRUCTION}"
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Original question: {query}\n\nDomain agent results:\n{combined}"),
    ]

    with log_backend_call(logger, "reviewer_agent", "review"):
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=AGENT_LLM_TIMEOUT_SECONDS)

    if response.usage_metadata:
        logger.info(
            "[reviewer_agent] tokens used: %s prompt + %s completion",
            response.usage_metadata["input_tokens"],
            response.usage_metadata["output_tokens"],
        )

    return response.content


async def generate_follow_ups(query: str, answer: str) -> list[str]:
    """Phase 123: 2-3 suggested follow-up questions - a nice-to-have, so any
    failure here returns [] rather than failing the whole request."""
    llm = _build_llm()
    messages = [
        SystemMessage(content=FOLLOW_UP_QUESTIONS_SYSTEM_PROMPT),
        HumanMessage(content=f"Question: {query}\n\nAnswer: {answer}"),
    ]

    try:
        with log_backend_call(logger, "reviewer_agent", "generate_follow_ups"):
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=AGENT_LLM_TIMEOUT_SECONDS)
    except Exception as error:
        logger.warning("Follow-up question generation failed: %s: %s", type(error).__name__, error)
        return []

    return [line.strip() for line in response.content.splitlines() if line.strip()]
