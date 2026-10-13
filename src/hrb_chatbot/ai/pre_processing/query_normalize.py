"""Phase 173 - the "sanity" pass every pipeline runs on the raw query
before anything else: check_input(), decompose(), cache-key building, and
guardrail/keyword-routing logic (e.g. decompose()'s own required exact
"What is my leave balance?" phrasing) all assume reasonably clean text -
a typo'd or garbled question degrades those silently today. Same
structured-output pattern as query_decompose.py."""

import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from src.hrb_chatbot.ai.agents._llm_helpers import AGENT_LLM_TIMEOUT_SECONDS, build_agent_llm
from src.hrb_chatbot.ai.prompts.agent_prompts import NORMALIZE_SYSTEM_PROMPT
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("pre_processing.query_normalize")


class NormalizedQuery(BaseModel):
    normalized_query: str


def _build_llm() -> ChatOpenAI:
    # Same cheap-tier precedent as query_decompose.py's own _build_llm().
    return build_agent_llm("OPENAI_NORMALIZE_MODEL")


async def normalize_query(query: str) -> str:
    """Fixes spelling/grammar and standardizes phrasing - never changes
    meaning, never answers, never adds/removes a fact. Falls back to the
    original query unchanged on a parse failure, an empty result, or a
    result that looks like a refusal/non-rewrite (e.g. the model answering
    instead of rewriting) - so a normalization hiccup degrades to today's
    exact single-question behavior, never a crash or an altered meaning."""
    if not query.strip():
        return query

    llm = _build_llm().with_structured_output(NormalizedQuery, include_raw=True)
    messages = [SystemMessage(content=NORMALIZE_SYSTEM_PROMPT), HumanMessage(content=query)]

    try:
        with log_backend_call(logger, "query_normalize", "normalize"):
            result = await asyncio.wait_for(llm.ainvoke(messages), timeout=AGENT_LLM_TIMEOUT_SECONDS)
    except Exception as error:
        logger.warning("Normalization failed for %r, using the original query: %s: %s", query, type(error).__name__, error)
        return query

    usage = result["raw"].usage_metadata
    if usage:
        logger.info("[query_normalize] tokens used: %s prompt + %s completion", usage["input_tokens"], usage["output_tokens"])

    output: NormalizedQuery | None = result["parsed"]
    normalized = output.normalized_query.strip() if output else ""
    if not normalized:
        return query

    if normalized != query.strip():
        logger.info("Normalized query: %r -> %r", query, normalized)
    return normalized
