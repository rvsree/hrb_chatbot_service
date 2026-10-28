"""Checks a query against NeMo Guardrails' input rails before retrieval -
Gate 1 (Firewall) of the six-gate validation pattern. See RAG-ROADMAP.md Phase 7."""

import copy
from pathlib import Path

from nemoguardrails import LLMRails, RailsConfig

from src.hrb_chatbot.ai.rag_core.company_name_filter import contains_real_company_reference
from src.hrb_chatbot.ai.search_pre_processing.safe_terms import protect_known_safe_terms
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("guardrails_input")

CONFIG_PATH = Path(__file__).resolve().parents[1] / "guardrails_config"

# Phase 243's own real default - must match ai/guardrails_config/config.yml's
# models[0].model exactly, since this is what "no override given" resolves to.
# 2026-10-23 HOTFIX: was "gpt-4.1-nano" - OpenAI shut that model down today
# (confirmed live: GET /v1/models/gpt-4.1-nano returns shutdown_date
# 2026-10-23, and every real guardrail call started 404ing in production
# within hours of that). gpt-4.1-mini has a shutdown_date of 2027-01-14 -
# confirmed live the same way before picking it.
DEFAULT_GUARDRAILS_MODEL = "gpt-4.1-mini"


def supported_guardrails_models() -> list[str]:
    """Phase 244 - exposed (not private) so GET /health (api/admin/health_checks.py)
    can surface the same real allow-list the frontend's Settings -> Model dropdown
    reads from and this module validates guardrails_model against."""
    raw = read_setting(None, "GUARDRAILS_SUPPORTED_MODELS", f"{DEFAULT_GUARDRAILS_MODEL},gpt-4.1")
    return [model.strip() for model in raw.split(",") if model.strip()]


def resolve_guardrails_model(override: str | None = None) -> str:
    """Phase 244 - override wins if given and listed in GUARDRAILS_SUPPORTED_MODELS,
    else the configured default. Raises ValueError (-> 422 at the route layer) for
    an override that isn't on the real allow-list - never silently accepted or
    silently ignored."""
    if override is None:
        return DEFAULT_GUARDRAILS_MODEL
    supported = supported_guardrails_models()
    if override not in supported:
        raise ValueError(f"guardrails_model {override!r} is not supported - choose one of {supported}.")
    return override


_base_config: RailsConfig | None = None
_rails_by_model: dict[str, LLMRails] = {}


def get_rails(model: str | None = None) -> LLMRails:
    """Phase 244 - one LLMRails instance per distinct model actually requested
    (bounded by GUARDRAILS_SUPPORTED_MODELS' own size), not a single unconditional
    singleton. The YAML itself is still loaded from disk only once (_base_config),
    matching the original lazy-load-once reasoning - only the LLMRails build
    (and its own LLM client) is now per-model."""
    global _base_config
    resolved_model = model or DEFAULT_GUARDRAILS_MODEL
    if resolved_model not in _rails_by_model:
        if _base_config is None:
            _base_config = RailsConfig.from_path(str(CONFIG_PATH))
        config = _base_config
        if resolved_model != _base_config.models[0].model:
            config = copy.deepcopy(_base_config)
            config.models[0].model = resolved_model
        _rails_by_model[resolved_model] = LLMRails(config)
    return _rails_by_model[resolved_model]


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


async def check_input(query: str, guardrails_model: str | None = None) -> tuple[str, dict]:
    """Runs input rails on the query. Returns (content, status) - content is
    the query to actually use (masked if NeMo redacted PII); status is
    {"status": "pass"|"modified", "rail": str | None, "activated_rails":
    list[dict], "model_used": str} (Phase 224 - status/rail were silently
    dropped before, a MODIFIED result was indistinguishable from an
    untouched PASS to every caller. Phase 229 - activated_rails added, see
    its own module-level docstring note above. Phase 244 - model_used,
    extracted by callers into their own top-level guardrails_model_used
    field, same verifiability reasoning as judge_model_used). Raises
    GuardrailBlockedError if blocked - still never returns in that case,
    unchanged. guardrails_model (Phase 244): a per-call override, validated
    against GUARDRAILS_SUPPORTED_MODELS - raises ValueError if given but
    not listed.

    Phase 229 - calls generate_async() directly instead of NeMo's own
    check_async() convenience wrapper, which (confirmed by reading NeMo's
    own source) already computes this same per-rail log internally on
    every call and then discards it before returning. The status logic
    below (compare original vs. final content; a blocked rail is any
    activated rail with stop=True) replicates check_async()'s own real
    logic - verified simple and self-contained, not a dependency on NeMo's
    private helper functions."""
    if contains_real_company_reference(query):
        logger.warning("Input blocked by guardrail real_company_name_check")
        raise GuardrailBlockedError("This request was blocked by a safety check (real_company_name_check).")

    resolved_model = resolve_guardrails_model(guardrails_model)
    protected_query = protect_known_safe_terms(query)
    response = await get_rails(resolved_model).generate_async(
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
            "model_used": resolved_model,
        }

    return result_content, {
        "status": "pass",
        "rail": None,
        "activated_rails": activated_rails_to_dicts(activated_rails),
        "model_used": resolved_model,
    }
