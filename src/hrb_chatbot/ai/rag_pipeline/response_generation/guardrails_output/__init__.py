"""Checks a generated answer against NeMo Guardrails' output rails (Gate 6) - faithfulness is DeepEval's job."""

from src.hrb_chatbot.ai.search_pre_processing.guardrails_input import (
    activated_rails_to_dicts,
    get_rails,
    resolve_guardrails_model,
)
from src.hrb_chatbot.ai.search_pre_processing.safe_terms import protect_known_safe_terms
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("guardrails_output")

SAFE_FALLBACK_ANSWER = "I'm not able to share that response. Please rephrase your question."


async def check_output(query: str, answer: str, guardrails_model: str | None = None) -> tuple[str, dict]:
    """Runs output rails. Returns (content, status) - content is masked text
    if PII was redacted, or a safe fallback if blocked; status is
    {"status": "pass"|"modified"|"blocked", "rail": str | None,
    "activated_rails": list[dict], "model_used": str}. Phase 224 - a
    BLOCKED result used to silently swap in SAFE_FALLBACK_ANSWER with zero
    signal reaching the caller - a real bug, not just "not observable".
    Phase 229 - activated_rails added; see guardrails_input.py's
    check_input() for why this calls generate_async() directly instead of
    check_async() - same reasoning, same replicated status logic. Phase
    244 - guardrails_model/model_used, same reasoning as check_input()."""
    resolved_model = resolve_guardrails_model(guardrails_model)
    protected_answer = protect_known_safe_terms(answer)
    messages = [{"role": "user", "content": query}, {"role": "assistant", "content": protected_answer}]
    response = await get_rails(resolved_model).generate_async(
        messages=messages, options={"rails": ["output"], "log": {"activated_rails": True}}
    )
    activated_rails = response.log.activated_rails if response.log else []
    blocking_rail = next((rail.name for rail in activated_rails if rail.stop), None)
    result_content = response.response[-1]["content"] if isinstance(response.response, list) else response.response

    if blocking_rail:
        logger.warning("Output blocked by guardrail %s", blocking_rail)
        return SAFE_FALLBACK_ANSWER, {
            "status": "blocked",
            "rail": blocking_rail,
            "activated_rails": activated_rails_to_dicts(activated_rails),
            "model_used": resolved_model,
        }

    if result_content != protected_answer:
        logger.info("Output modified by guardrail - sensitive data masked")
        return result_content, {
            "status": "modified",
            "rail": None,
            "activated_rails": activated_rails_to_dicts(activated_rails),
            "model_used": resolved_model,
        }

    return result_content, {
        "status": "pass",
        "rail": None,
        "activated_rails": activated_rails_to_dicts(activated_rails),
        "model_used": resolved_model,
    }
