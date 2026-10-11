"""Phase 130: genai-rag's own query-decomposition step - reopens the gap
Phase 68 (2026-10-04) left explicitly open (agentic modes' Planner already
splits compound questions; genai-rag's non-agentic pipeline had nothing).
Same structured-output pattern as planner_agent.py's plan()."""

import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from src.hrb_chatbot.ai.agents._llm_helpers import AGENT_LLM_TIMEOUT_SECONDS, build_agent_llm
from src.hrb_chatbot.ai.prompts.agent_prompts import DECOMPOSE_SYSTEM_PROMPT
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("pre_processing.query_decompose")


class DecomposedQuery(BaseModel):
    sub_questions: list[str]


def _build_llm() -> ChatOpenAI:
    # Phase 65's own precedent (Planner) - cheap enough to tier onto its own model.
    return build_agent_llm("OPENAI_DECOMPOSE_MODEL")


async def decompose(query: str) -> list[str]:
    """Splits a compound question into independent sub-questions. Never
    returns an empty list - falls back to [query] unchanged on a parse
    failure or an empty result, so a decomposition hiccup degrades to
    today's exact single-question behavior, never a crash or a lost ask."""
    llm = _build_llm().with_structured_output(DecomposedQuery, include_raw=True)
    messages = [SystemMessage(content=DECOMPOSE_SYSTEM_PROMPT), HumanMessage(content=query)]

    try:
        with log_backend_call(logger, "query_decompose", "decompose"):
            result = await asyncio.wait_for(llm.ainvoke(messages), timeout=AGENT_LLM_TIMEOUT_SECONDS)
    except Exception as error:
        logger.warning("Decomposition failed for %r, answering as one question: %s: %s", query, type(error).__name__, error)
        return [query]

    usage = result["raw"].usage_metadata
    if usage:
        logger.info("[query_decompose] tokens used: %s prompt + %s completion", usage["input_tokens"], usage["output_tokens"])

    output: DecomposedQuery | None = result["parsed"]
    sub_questions = [q.strip() for q in output.sub_questions if q.strip()] if output else []
    if not sub_questions:
        return [query]

    if len(sub_questions) > 1:
        logger.info("Decomposed %r into %d sub-questions", query, len(sub_questions))
    return sub_questions
