"""Checks a query against NeMo Guardrails' input rails before retrieval -
Gate 1 (Firewall) of the six-gate validation pattern. See RAG-ROADMAP.md Phase 7."""

from pathlib import Path

from nemoguardrails import LLMRails, RailsConfig

from src.hrb_chatbot.ai.search_pre_processing.safe_terms import protect_known_safe_terms
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("guardrails_input")

CONFIG_PATH = Path(__file__).resolve().parents[1] / "guardrails_config"

_rails = None


def get_rails() -> LLMRails:
    """Load the guardrails config once and reuse it - matches the lazy,
    cached singleton pattern this project's other gateways already use."""
    global _rails
    if _rails is None:
        config = RailsConfig.from_path(str(CONFIG_PATH))
        _rails = LLMRails(config)
    return _rails


class GuardrailBlockedError(Exception):
    """Raised when a guardrail blocks a query - the route turns this into a 422."""


def activated_rails_to_dicts(activated_rails) -> list[dict]:
    """Shared by check_input()/check_output() (Phase 229) - NeMo's own
    per-rail activation log, trimmed to what's worth surfacing. Real data:
    live-verified against this project's own guardrails_config to include
    EVERY configured rail that ran, not just the one that blocked/modified
    something - a rail that found nothing wrong still shows up here with
    its own real decision trace, which is the whole point (demonstrating
    the validation logic actually ran, not just its end result)."""
    return [{"name": rail.name, "decisions": list(rail.decisions), "stop": rail.stop} for rail in activated_rails]


async def check_input(query: str) -> tuple[str, dict]:
    """Runs input rails on the query. Returns (content, status) - content is
    the query to actually use (masked if NeMo redacted PII); status is
    {"status": "pass"|"modified", "rail": str | None, "activated_rails":
    list[dict]} (Phase 224 - status/rail were silently dropped before, a
    MODIFIED result was indistinguishable from an untouched PASS to every
    caller. Phase 229 - activated_rails added, see its own module-level
    docstring note above). Raises GuardrailBlockedError if blocked - still
    never returns in that case, unchanged.

    Phase 229 - calls generate_async() directly instead of NeMo's own
    check_async() convenience wrapper, which (confirmed by reading NeMo's
    own source) already computes this same per-rail log internally on
    every call and then discards it before returning. The status logic
    below (compare original vs. final content; a blocked rail is any
    activated rail with stop=True) replicates check_async()'s own real
    logic - verified simple and self-contained, not a dependency on NeMo's
    private helper functions."""
    protected_query = protect_known_safe_terms(query)
    response = await get_rails().generate_async(
        messages=[{"role": "user", "content": protected_query}],
        options={"rails": ["input"], "log": {"activated_rails": True}},
    )
    activated_rails = response.log.activated_rails if response.log else []
    blocking_rail = next((rail.name for rail in activated_rails if rail.stop), None)
    result_content = response.response[-1]["content"] if isinstance(response.response, list) else response.response

    if blocking_rail:
        logger.warning("Input blocked by guardrail %s", blocking_rail)
        raise GuardrailBlockedError(f"This request was blocked by a safety check ({blocking_rail}).")

    if result_content != protected_query:
        logger.info("Input modified by guardrail - sensitive data masked")
        return result_content, {
            "status": "modified",
            "rail": None,
            "activated_rails": activated_rails_to_dicts(activated_rails),
        }

    return result_content, {"status": "pass", "rail": None, "activated_rails": activated_rails_to_dicts(activated_rails)}
