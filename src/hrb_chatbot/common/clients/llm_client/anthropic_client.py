"""Anthropic client (chat + tools) - base URL is host-only, no "/v1"; temperature accepted but never sent."""

import anthropic

from src.hrb_chatbot.common.clients.llm_client.base_llm_client import BaseLLMClient
from src.hrb_chatbot.common.config.settings import read_setting, read_url_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.resiliency.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

logger = get_logger("anthropic_client")


class AnthropicChatClient(BaseLLMClient):
    """Talks to Anthropic's Claude models."""

    PROVIDER_NAME = "anthropic"
    ENV_KEY = "ANTHROPIC_API_KEY"

    # Host name only - see the note at the top of this file.
    DEFAULT_BASE_URL = "https://api.anthropic.com"
    DEFAULT_MODEL = "claude-haiku-4-5"

    # Real workspace ids always start with this. Used to spot a pasted name.
    WORKSPACE_ID_PREFIX = "wrkspc_"

    # ask()/ask_with_tools() fallback when the caller doesn't pass max_tokens -
    # Anthropic's API requires it, unlike OpenAI/Bedrock.
    DEFAULT_MAX_TOKENS = int(read_setting(None, "ANTHROPIC_DEFAULT_MAX_TOKENS", 1024))

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        workspace_id: str | None = None,
        base_url: str | None = None,
    ):
        """Create the client, reading anything not passed in from the .env file."""
        self.api_key = read_setting(api_key, "ANTHROPIC_API_KEY")
        self.model = read_setting(model, "ANTHROPIC_CHAT_MODEL", self.DEFAULT_MODEL)
        self.base_url = read_url_setting(base_url, "ANTHROPIC_BASE_URL", self.DEFAULT_BASE_URL)
        self.workspace_id = read_setting(workspace_id, "ANTHROPIC_WORKSPACE_ID")

        if not self.api_key:
            logger.warning("[ANTHROPIC] ANTHROPIC_API_KEY not set")

        self.warn_if_workspace_id_looks_wrong()

        # Only send the workspace header when we actually have an id.
        headers = {}
        if self.workspace_id:
            headers["anthropic-workspace-id"] = self.workspace_id

        # Only build the Anthropic object when we have a key. Without a key the
        # library raises an error here, which would crash the health endpoints.
        if self.api_key:
            self.client = anthropic.Anthropic(
                api_key=self.api_key,
                base_url=self.base_url,
                default_headers=headers,
            )
        else:
            self.client = None

        # Phase 259 - fails fast on a known, ongoing Anthropic outage
        # instead of paying a real network timeout on every call.
        self._circuit_breaker = CircuitBreaker("llm:anthropic")

    def warn_if_workspace_id_looks_wrong(self):
        """Warn if ANTHROPIC_WORKSPACE_ID looks like a pasted name rather than an id."""
        if not self.workspace_id:
            return

        if not self.workspace_id.startswith(self.WORKSPACE_ID_PREFIX):
            logger.warning(
                "[ANTHROPIC] ANTHROPIC_WORKSPACE_ID=%r does not start with %r - the "
                "Console shows the ID (not the name) in the ID column of "
                "Settings -> Workspaces",
                self.workspace_id,
                self.WORKSPACE_ID_PREFIX,
            )

    def get_client(self):
        """Return the Anthropic object, or raise a clear error if there is no key."""
        if self.client is None:
            raise RuntimeError(f"{self.ENV_KEY} is not configured")
        return self.client

    def get_configuration(self) -> dict:
        """Return the settings this client is using, with no secrets in it."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "workspace_id": self.workspace_id,
            "workspace_id_set": bool(self.workspace_id),
        }

    def ask(self, question, context=None, system_prompt=None, temperature=0.0, max_tokens=None):
        """Ask one question and return the answer text - `temperature` is accepted but ignored."""
        if context:
            message_text = f"Context:\n{context}\n\nQuestion:\n{question}"
        else:
            message_text = question

        # Claude takes the system prompt as its own argument, not as a message.
        extra_arguments = {}
        if system_prompt:
            extra_arguments["system"] = system_prompt

        if not self._circuit_breaker.check():
            raise CircuitBreakerOpenError("Anthropic is currently failing - circuit breaker open, not attempting the real call")

        # temperature deliberately not passed - the anthropic library rejects it now.
        with log_backend_call(logger, "anthropic", "messages.ask", model=self.model):
            try:
                response = self.get_client().messages.create(
                    model=self.model,
                    max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS,
                    messages=[{"role": "user", "content": message_text}],
                    **extra_arguments,
                )
            except Exception:
                self._circuit_breaker.record_failure()
                raise
            self._circuit_breaker.record_success()

        if response.usage:
            logger.info("[anthropic] tokens used: %s input + %s output", response.usage.input_tokens, response.usage.output_tokens)

        # Claude replies with a list of "blocks". Join the text ones together.
        answer = ""
        for block in response.content:
            if block.type == "text":
                answer = answer + block.text
        return answer

    def ask_with_tools(self, messages, tools, temperature=0.0, max_tokens=None, tool_choice="auto"):
        """Ask and let Claude call tools - takes/returns OpenAI-shaped messages, converted below."""
        claude_tools = self.convert_tools_to_claude_format(tools)
        system_text, chat_messages = self.split_out_system_message(messages)

        # Claude takes the system prompt as its own argument, not as a message.
        extra_arguments = {}
        if system_text:
            extra_arguments["system"] = system_text

        # temperature is deliberately not passed - see the note at the top of file.
        with log_backend_call(
            logger, "anthropic", "messages.ask_with_tools", model=self.model, tool_count=len(tools)
        ):
            response = self.get_client().messages.create(
                model=self.model,
                max_tokens=max_tokens or self.DEFAULT_MAX_TOKENS,
                messages=chat_messages,
                tools=claude_tools,
                **extra_arguments,
            )
        return self.convert_response_to_openai_format(response)

    @staticmethod
    def convert_tools_to_claude_format(tools: list[dict]) -> list[dict]:
        """Rewrite OpenAI-style tool defs into Claude's shape - top-level, not nested under "function"."""
        claude_tools = []
        for tool in tools:
            if tool.get("type") != "function":
                continue

            function = tool["function"]
            claude_tools.append(
                {
                    "name": function["name"],
                    "description": function.get("description", ""),
                    "input_schema": function.get("parameters", {}),
                }
            )
        return claude_tools

    @staticmethod
    def split_out_system_message(messages: list[dict]) -> tuple[str | None, list[dict]]:
        """Separate the system message, returning (system_text or None, remaining_messages)."""
        system_text = None
        chat_messages = []

        for message in messages:
            if message.get("role") == "system":
                system_text = message.get("content")
            else:
                chat_messages.append(message)

        return system_text, chat_messages

    @staticmethod
    def convert_response_to_openai_format(response) -> dict:
        """Rewrite Claude's reply into the OpenAI reply shape, so calling code understands one format."""
        answer_text = ""
        tool_calls = []

        for block in response.content:
            if block.type == "text":
                answer_text = answer_text + block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {"name": block.name, "arguments": str(block.input)},
                    }
                )

        # OpenAI uses None rather than an empty list when no tools were called.
        if not tool_calls:
            tool_calls = None

        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": answer_text,
                        "tool_calls": tool_calls,
                    }
                }
            ],
            "usage": {
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
        }

    def health_check(self) -> dict:
        """Report whether this client is usable - calls GET /v1/models to confirm key/URL/workspace together."""
        result = {"provider": self.PROVIDER_NAME}
        result.update(self.get_configuration())

        if not self.api_key:
            result["status"] = "unhealthy"
            result["message"] = "API key not configured"
            return result

        try:
            available_model_names = []
            for model in self.get_client().models.list():
                available_model_names.append(model.id)

            # Model ids carry a date on the end (claude-haiku-4-5-20251001), so
            # compare with startswith rather than looking for an exact match.
            model_is_available = False
            for name in available_model_names:
                if name.startswith(self.model):
                    model_is_available = True

            result["status"] = "healthy"
            result["models_visible"] = len(available_model_names)
            result["chat_model_available"] = model_is_available
        except Exception as error:
            # A health check must never crash - report the problem instead.
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
