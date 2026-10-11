"""Loads .env with override=True - beats a stale shell/Windows env value that python-dotenv's default wouldn't replace."""

import os

from dotenv import dotenv_values, find_dotenv, load_dotenv


def load_env_file_and_report_overrides() -> list[str]:
    """Load .env, returning the names of any values it replaced - never the values, which are secrets."""
    env_file_path = find_dotenv(usecwd=True)

    if not env_file_path:
        # No .env file at all. Fall back to whatever the environment provides.
        load_dotenv()
        return []

    # Work out what we are about to replace, before we replace it.
    replaced_settings = []
    for setting_name, value_in_file in dotenv_values(env_file_path).items():
        value_on_machine = os.environ.get(setting_name)

        both_have_a_value = value_in_file and value_on_machine
        if both_have_a_value and value_on_machine != value_in_file:
            replaced_settings.append(setting_name)

    replaced_settings.sort()

    # override=True is the important part - see the note at the top of this file.
    load_dotenv(env_file_path, override=True)

    return replaced_settings


# The names of settings where .env replaced a different value already set on this
# computer. Usually empty. A health check can read this to explain what happened.
SETTINGS_TAKEN_FROM_ENV_FILE = load_env_file_and_report_overrides()


def read_setting(passed_in_value: str | None, env_variable_name: str, default_value=None):
    """Passed-in value, then .env/environment, then default - an empty-string .env line counts as unset."""
    if passed_in_value:
        return passed_in_value

    value_from_env_file = os.getenv(env_variable_name)
    if value_from_env_file:
        return value_from_env_file

    return default_value


def read_url_setting(
    passed_in_value: str | None, env_variable_name: str, default_value: str
) -> str:
    """Same as read_setting, but strips a trailing "/" to avoid a doubled "//" when callers append a path."""
    url = read_setting(passed_in_value, env_variable_name, default_value)
    return url.rstrip("/")


def get_active_vector_db(override: str | None = None) -> str:
    """Which vector store to use - override wins, else .env's ACTIVE_VECTOR_DB, else chromadb."""
    return read_setting(override, "ACTIVE_VECTOR_DB", "chromadb")


def get_active_llm_provider(override: str | None = None) -> str:
    """Which LLM provider powers retrieval-time reasoning - not the final answer's model."""
    return read_setting(override, "ACTIVE_LLM_PROVIDER", "openai")


def get_app_environment() -> str:
    """"production" in AWS, else "development" - see Phase 137 (db_gateway.py's
    production lockdown of the local-disk-only chromadb/sqlite stores)."""
    return read_setting(None, "APP_ENVIRONMENT", "development")
