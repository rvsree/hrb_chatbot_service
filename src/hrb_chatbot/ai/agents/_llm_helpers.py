"""Shared ChatOpenAI builder + timeout constant for every agent LLM call
(Phase 71) - was identical, duplicated 3 times across planner_agent.py,
reviewer_agent.py, orchestration_agent.py."""

from langchain_openai import ChatOpenAI

from src.hrb_chatbot.common.config.settings import read_setting, read_url_setting

# How long one agent LLM call may run before giving up.
AGENT_LLM_TIMEOUT_SECONDS = 30


def resolve_agent_model(model_setting_name: str | None = None, model_override: str | None = None) -> str:
    """Same resolution order build_agent_llm applies (override > env setting > OPENAI_CHAT_MODEL),
    exposed standalone so a caller can report which model a call used (Phase 243) without
    constructing a ChatOpenAI client."""
    default_model = read_setting(None, "OPENAI_CHAT_MODEL", "gpt-4.1-mini")
    env_model = read_setting(None, model_setting_name, default_model) if model_setting_name else default_model
    return model_override or env_model


def build_agent_llm(model_setting_name: str | None = None, model_override: str | None = None) -> ChatOpenAI:
    """model_setting_name lets one caller (the Planner) use its own model
    setting, falling back to OPENAI_CHAT_MODEL like every other agent.
    model_override (Phase 243) is a per-request value that wins over both."""
    api_key = read_setting(None, "OPENAI_API_KEY")
    base_url = read_url_setting(None, "OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = resolve_agent_model(model_setting_name, model_override)
    return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0)
