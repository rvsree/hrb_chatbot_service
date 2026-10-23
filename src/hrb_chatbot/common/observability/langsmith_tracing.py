"""Turns on LangSmith tracing for LangChain chains, if configured -
off by default. See .env's LangSmith section for the flag."""

import os

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("langsmith_tracing")


def _setting_is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


def _resolve_project_name() -> str:
    """HRB_CHATBOT_LOCAL/HRB_CHATBOT_PROD keep local-dev and production
    traces in two separate LangSmith projects, so they never land mixed
    together under the same LANGSMITH_PROJECT name - every checked-out
    .env defaults to LOCAL=true/PROD=false; production's own App Runner
    config sets the opposite. Prod wins if both are somehow true - a
    misconfigured prod deploy should still get correctly labeled, not
    silently mistaken for local traffic."""
    base_name = read_setting(None, "LANGSMITH_PROJECT", "hrb_chatbot_service")
    is_prod = _setting_is_true(read_setting(None, "HRB_CHATBOT_PROD", "false"))
    is_local = _setting_is_true(read_setting(None, "HRB_CHATBOT_LOCAL", "true"))

    if is_prod:
        return f"{base_name}_prod"
    if is_local:
        return f"{base_name}_local"
    return base_name


def enable_tracing_if_configured() -> bool:
    """If LANGSMITH_ENABLED is true, set the env vars LangChain's own
    chains already check to send traces. Returns whether tracing turned on."""
    enabled = _setting_is_true(read_setting(None, "LANGSMITH_ENABLED", "false"))
    api_key = read_setting(None, "LANGSMITH_API_KEY")

    if not enabled or not api_key:
        logger.info("LangSmith tracing is off")
        return False

    project_name = _resolve_project_name()
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project_name

    logger.info("LangSmith tracing is on (project=%s)", project_name)
    return True
