"""Phase 249 - wraps this project's own multi-provider ask() clients so
DeepEval's metrics call through the existing gateway instead of a separate,
bypassing OpenAI integration. Mirrors common/clients/llm_client/
langchain_chat_model.py's GatewayChatModel adapter pattern - same "no real
async HTTP exists in this codebase, offload the sync call" choice, not a
new one."""

import asyncio

from deepeval.models import DeepEvalBaseLLM

from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway


class GatewayDeepEvalModel(DeepEvalBaseLLM):
    """A non-native DeepEval judge model - generate() returns plain text,
    not a (text, cost) tuple, so DeepEval treats it as a generic model and
    parses its own JSON-instructed prompts out of that text itself."""

    def __init__(self, judge_model: str | None = None):
        self.judge_model = judge_model
        super().__init__(model=judge_model)

    def load_model(self):
        return self

    def generate(self, prompt: str) -> str:
        client = get_client_gateway().openai_chat()
        return client.ask(prompt, temperature=0.0, model_name_override=self.judge_model)

    async def a_generate(self, prompt: str) -> str:
        return await asyncio.to_thread(self.generate, prompt)

    def get_model_name(self) -> str:
        return self.judge_model or get_client_gateway().openai_chat().model
