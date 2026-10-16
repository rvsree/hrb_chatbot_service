from src.hrb_chatbot.common.observability.langsmith_tracing import enable_tracing_if_configured


def test_tracing_off_when_not_enabled(monkeypatch):
    monkeypatch.setenv("LANGSMITH_ENABLED", "false")
    assert enable_tracing_if_configured() is False


def test_tracing_off_when_no_api_key(monkeypatch):
    monkeypatch.setenv("LANGSMITH_ENABLED", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert enable_tracing_if_configured() is False


def test_local_project_name_is_default(monkeypatch):
    monkeypatch.setenv("LANGSMITH_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "hrb_chatbot_v2")
    monkeypatch.delenv("HRB_CHATBOT_LOCAL", raising=False)
    monkeypatch.delenv("HRB_CHATBOT_PROD", raising=False)

    assert enable_tracing_if_configured() is True
    import os

    assert os.environ["LANGCHAIN_PROJECT"] == "hrb_chatbot_v2_local"


def test_prod_project_name_when_prod_flag_set(monkeypatch):
    monkeypatch.setenv("LANGSMITH_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "hrb_chatbot_v2")
    monkeypatch.setenv("HRB_CHATBOT_LOCAL", "false")
    monkeypatch.setenv("HRB_CHATBOT_PROD", "true")

    assert enable_tracing_if_configured() is True
    import os

    assert os.environ["LANGCHAIN_PROJECT"] == "hrb_chatbot_v2_prod"


def test_prod_wins_if_both_flags_true(monkeypatch):
    monkeypatch.setenv("LANGSMITH_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "hrb_chatbot_v2")
    monkeypatch.setenv("HRB_CHATBOT_LOCAL", "true")
    monkeypatch.setenv("HRB_CHATBOT_PROD", "true")

    assert enable_tracing_if_configured() is True
    import os

    assert os.environ["LANGCHAIN_PROJECT"] == "hrb_chatbot_v2_prod"
