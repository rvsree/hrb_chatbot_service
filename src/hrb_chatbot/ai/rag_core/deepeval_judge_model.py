"""Phase 249 - wraps this project's own multi-provider ask() clients so
DeepEval's metrics call through the existing gateway instead of a separate,
bypassing OpenAI integration. Mirrors common/clients/llm_client/
langchain_chat_model.py's GatewayChatModel adapter pattern - same "no real
async HTTP exists in this codebase, offload the sync call" choice, not a
new one.

Phase 256 - judge_provider, when given, routes judge calls through
Anthropic instead of OpenAI (cost-effective preference, user-confirmed
2026-10-25). Default stays OpenAI (None), preserving every existing
caller's exact behavior unchanged. Anthropic's own ask() has no
model_name_override parameter (unlike OpenAI's) - judge_model is only
applied to the OpenAI path; the Anthropic path always uses whichever
model ANTHROPIC_CHAT_MODEL is configured as (claude-haiku-4-5 today),
matching the spec's own "no new config surface" decision."""

import asyncio

from deepeval.models import DeepEvalBaseLLM
from langsmith import traceable

from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway
from src.hrb_chatbot.common.enums import LlmProvider


class GatewayDeepEvalModel(DeepEvalBaseLLM):
    """A non-native DeepEval judge model - generate() returns plain text,
    not a (text, cost) tuple, so DeepEval treats it as a generic model and
    parses its own JSON-instructed prompts out of that text itself."""

    def __init__(self, judge_model: str | None = None, judge_provider: LlmProvider | None = None):
        self.judge_model = judge_model
        self.judge_provider = judge_provider
        super().__init__(model=judge_model)

    def load_model(self):
        return self

    @traceable(name="deepeval_judge_call")
    def generate(self, prompt: str) -> str:
        """Phase 270 - @traceable: every DeepEval metric (groundedness/
        completeness/answer-relevancy) calls raw .ask() here, not a
        LangChain component, so without this it was invisible in LangSmith
        on every live query that runs eval scoring - a_generate()'s
        asyncio.to_thread() path routes through this same method, so one
        decoration covers both (contextvars propagate into the thread)."""
        if self.judge_provider == LlmProvider.ANTHROPIC:
            return get_client_gateway().anthropic_chat().ask(prompt, temperature=0.0)
        client = get_client_gateway().openai_chat()
        return client.ask(prompt, temperature=0.0, model_name_override=self.judge_model)

    async def a_generate(self, prompt: str) -> str:
        return await asyncio.to_thread(self.generate, prompt)

    def get_model_name(self) -> str:
        if self.judge_provider == LlmProvider.ANTHROPIC:
            return self.judge_model or get_client_gateway().anthropic_chat().model
        return self.judge_model or get_client_gateway().openai_chat().model
