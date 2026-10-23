"""Phase 240 - the auto-router's own classifier: single-agentic-rag vs.
multi-agentic-rag, decided before either pipeline runs. Real LLM call
(same model-tiering convention as Phase 243's Planner/decompose steps),
not a heuristic - see RAG-ROADMAP.md Phase 240's resolved decisions."""

import asyncio
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from src.hrb_chatbot.ai.agents._llm_helpers import AGENT_LLM_TIMEOUT_SECONDS, build_agent_llm
from src.hrb_chatbot.ai.prompts.agent_prompts import ROUTER_SYSTEM_PROMPT
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("search_pre_processing.mode_router")


class ModeClassification(BaseModel):
    mode: Literal["single", "multi"]


def _build_llm(router_model: str | None = None):
    return build_agent_llm("OPENAI_ROUTER_MODEL", model_override=router_model)


async def classify_query_complexity(query: str, router_model: str | None = None) -> Literal["single", "multi"]:
    """Returns "single" or "multi". Never raises - falls back to "single"
    (the cheaper, safer default) on any classifier failure, same "a
    routing mechanism must never become the reason every request fails"
    principle already applied elsewhere in this project."""
    try:
        llm = _build_llm(router_model).with_structured_output(ModeClassification, include_raw=True)
        messages = [SystemMessage(content=ROUTER_SYSTEM_PROMPT), HumanMessage(content=query)]
        with log_backend_call(logger, "mode_router", "classify_query_complexity"):
            result = await asyncio.wait_for(llm.ainvoke(messages), timeout=AGENT_LLM_TIMEOUT_SECONDS)
    except Exception as error:
        logger.warning("Mode classification failed for %r, defaulting to single: %s: %s", query, type(error).__name__, error)
        return "single"

    usage = result["raw"].usage_metadata
    if usage:
        logger.info("[mode_router] tokens used: %s prompt + %s completion", usage["input_tokens"], usage["output_tokens"])

    output: ModeClassification | None = result["parsed"]
    if output is None:
        logger.warning("Mode classification didn't parse for %r, defaulting to single", query)
        return "single"
    return output.mode
