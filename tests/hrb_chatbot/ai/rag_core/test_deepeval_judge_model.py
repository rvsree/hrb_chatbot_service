"""Tests for Phase 249's GatewayDeepEvalModel (ai/rag_core/deepeval_judge_model.py) -
the DeepEvalBaseLLM wrapper around this project's own ask() clients. Uses
FakeChatClient/FakeClientGateway from conftest.py - no real network call."""

from src.hrb_chatbot.ai.rag_core import deepeval_judge_model
from src.hrb_chatbot.ai.rag_core.deepeval_judge_model import GatewayDeepEvalModel
from src.hrb_chatbot.common.enums import LlmProvider
from tests.conftest import FakeChatClient, FakeClientGateway


def test_generate_calls_ask_and_returns_its_raw_text(monkeypatch):
    fake_chat = FakeChatClient(answer='{"verdicts": []}')
    monkeypatch.setattr(deepeval_judge_model, "get_client_gateway", lambda: FakeClientGateway(chat_client=fake_chat))

    model = GatewayDeepEvalModel()
    result = model.generate("some prompt")

    assert result == '{"verdicts": []}'
    assert fake_chat.calls[0]["question"] == "some prompt"
    assert fake_chat.calls[0]["temperature"] == 0.0


def test_generate_does_not_accept_a_schema_kwarg():
    """DeepEvalBaseLLM.generate_with_schema()'s own fallback relies on
    generate() raising TypeError when given schema= - confirms this wrapper
    stays a plain, non-native model rather than silently accepting and
    ignoring it."""
    model = GatewayDeepEvalModel()
    raised = False
    try:
        model.generate("a prompt", schema=object())
    except TypeError:
        raised = True
    assert raised


async def test_a_generate_calls_the_sync_client_without_blocking(monkeypatch):
    fake_chat = FakeChatClient(answer="an async answer")
    monkeypatch.setattr(deepeval_judge_model, "get_client_gateway", lambda: FakeClientGateway(chat_client=fake_chat))

    model = GatewayDeepEvalModel()
    result = await model.a_generate("some prompt")

    assert result == "an async answer"


def test_judge_model_override_is_threaded_through_to_ask(monkeypatch):
    fake_chat = FakeChatClient(answer="an answer")
    monkeypatch.setattr(deepeval_judge_model, "get_client_gateway", lambda: FakeClientGateway(chat_client=fake_chat))

    model = GatewayDeepEvalModel(judge_model="gpt-4.1-nano")
    model.generate("a prompt")

    assert fake_chat.calls[0]["model_name_override"] == "gpt-4.1-nano"


def test_get_model_name_reports_the_override_when_given():
    model = GatewayDeepEvalModel(judge_model="gpt-4.1-nano")
    assert model.get_model_name() == "gpt-4.1-nano"


def test_get_model_name_falls_back_to_the_clients_own_default_model(monkeypatch):
    fake_chat = FakeChatClient(model="fake-default-model")
    monkeypatch.setattr(deepeval_judge_model, "get_client_gateway", lambda: FakeClientGateway(chat_client=fake_chat))

    model = GatewayDeepEvalModel()

    assert model.get_model_name() == "fake-default-model"


def test_load_model_returns_itself():
    model = GatewayDeepEvalModel()
    assert model.load_model() is model


class TestJudgeProvider:
    """Phase 256 - judge_provider routes judge calls through Anthropic
    instead of OpenAI. Default (None) stays OpenAI, unchanged."""

    def test_default_provider_still_calls_openai(self, monkeypatch):
        openai_chat = FakeChatClient(answer="openai answer")
        anthropic_chat = FakeChatClient(answer="anthropic answer")
        monkeypatch.setattr(
            deepeval_judge_model,
            "get_client_gateway",
            lambda: FakeClientGateway(chat_client=openai_chat, anthropic_chat_client=anthropic_chat),
        )

        model = GatewayDeepEvalModel()
        result = model.generate("a prompt")

        assert result == "openai answer"
        assert len(openai_chat.calls) == 1
        assert len(anthropic_chat.calls) == 0

    def test_anthropic_provider_calls_anthropic_not_openai(self, monkeypatch):
        openai_chat = FakeChatClient(answer="openai answer")
        anthropic_chat = FakeChatClient(answer="anthropic answer")
        monkeypatch.setattr(
            deepeval_judge_model,
            "get_client_gateway",
            lambda: FakeClientGateway(chat_client=openai_chat, anthropic_chat_client=anthropic_chat),
        )

        model = GatewayDeepEvalModel(judge_provider=LlmProvider.ANTHROPIC)
        result = model.generate("a prompt")

        assert result == "anthropic answer"
        assert len(anthropic_chat.calls) == 1
        assert len(openai_chat.calls) == 0

    def test_anthropic_provider_does_not_pass_model_name_override(self, monkeypatch):
        """Anthropic's real ask() has no model_name_override param - judge_model
        is only ever applied on the OpenAI path, confirmed here."""
        anthropic_chat = FakeChatClient(answer="anthropic answer")
        monkeypatch.setattr(
            deepeval_judge_model,
            "get_client_gateway",
            lambda: FakeClientGateway(anthropic_chat_client=anthropic_chat),
        )

        model = GatewayDeepEvalModel(judge_model="some-model", judge_provider=LlmProvider.ANTHROPIC)
        model.generate("a prompt")

        assert "model_name_override" not in anthropic_chat.calls[0] or anthropic_chat.calls[0]["model_name_override"] is None

    def test_get_model_name_falls_back_to_anthropics_own_default_when_provider_is_anthropic(self, monkeypatch):
        anthropic_chat = FakeChatClient(model="fake-anthropic-model")
        monkeypatch.setattr(
            deepeval_judge_model, "get_client_gateway", lambda: FakeClientGateway(anthropic_chat_client=anthropic_chat)
        )

        model = GatewayDeepEvalModel(judge_provider=LlmProvider.ANTHROPIC)

        assert model.get_model_name() == "fake-anthropic-model"

    def test_get_model_name_still_honors_an_explicit_override_with_anthropic_provider(self):
        model = GatewayDeepEvalModel(judge_model="claude-haiku-4-5", judge_provider=LlmProvider.ANTHROPIC)

        assert model.get_model_name() == "claude-haiku-4-5"
