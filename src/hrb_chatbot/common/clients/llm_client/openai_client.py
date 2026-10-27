"""OpenAI clients: chat (+ tools) and embeddings - base URL must include "/v1" or it 404s."""

from openai import OpenAI

from src.hrb_chatbot.common.clients.llm_client.base_llm_client import BaseLLMClient
from src.hrb_chatbot.common.config.settings import read_setting, read_url_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.resiliency.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

logger = get_logger("openai_client")

# The public OpenAI endpoint. Both clients in this file use it.
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAIChatClient(BaseLLMClient):
    """Talks to OpenAI's chat models, for example gpt-4.1-mini."""

    PROVIDER_NAME = "openai"
    ENV_KEY = "OPENAI_API_KEY"

    DEFAULT_BASE_URL = DEFAULT_OPENAI_BASE_URL
    DEFAULT_MODEL = "gpt-4.1-mini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
    ):
        """Create the client, reading anything not passed in from the .env file."""
        self.api_key = read_setting(api_key, "OPENAI_API_KEY")
        self.model = read_setting(model, "OPENAI_CHAT_MODEL", self.DEFAULT_MODEL)
        self.base_url = read_url_setting(base_url, "OPENAI_BASE_URL", self.DEFAULT_BASE_URL)
        self.organization = read_setting(organization, "OPENAI_ORG_ID")
        self.project = read_setting(project, "OPENAI_PROJECT_ID")

        if not self.api_key:
            logger.warning("[OPENAI] OPENAI_API_KEY not set")

        # Only build when we have a key - passing api_key=None makes the OpenAI
        # library raise immediately, which would crash the health endpoint that reports it's missing.
        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                organization=self.organization,
                project=self.project,
            )
        else:
            self.client = None

        # Phase 107: the token usage of the most recent ask() call - a
        # side-channel, not a return-type change, since ask() is the one
        # shared interface every provider client implements identically
        # and every existing caller expects a plain string back.
        self.last_token_usage: dict | None = None

        # Phase 259 - fails fast on a known, ongoing OpenAI outage instead
        # of paying a real network timeout on every call.
        self._circuit_breaker = CircuitBreaker("llm:openai")

    def get_client(self):
        """Return the OpenAI object, or raise a clear error if there is no key."""
        if self.client is None:
            raise RuntimeError(f"{self.ENV_KEY} is not configured")
        return self.client

    def get_configuration(self) -> dict:
        """Return the settings this client is using, with no secrets in it."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "organization": self.organization,
            "project": self.project,
        }

    def ask(self, question, context=None, system_prompt=None, temperature=0.0, max_tokens=None, model_name_override=None):
        """Ask one question and return the answer text."""
        if context:
            message_text = f"Context:\n{context}\n\nQuestion:\n{question}"
        else:
            message_text = question

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message_text})

        resolved_model = model_name_override or self.model

        if not self._circuit_breaker.check():
            raise CircuitBreakerOpenError("OpenAI is currently failing - circuit breaker open, not attempting the real call")

        with log_backend_call(logger, "openai", "chat.ask", model=resolved_model, temperature=temperature):
            try:
                response = self.get_client().chat.completions.create(
                    model=resolved_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception:
                self._circuit_breaker.record_failure()
                raise
            self._circuit_breaker.record_success()

        if response.usage:
            logger.info("[openai] tokens used: %s prompt + %s completion", response.usage.prompt_tokens, response.usage.completion_tokens)
            self.last_token_usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        else:
            self.last_token_usage = None

        answer = response.choices[0].message.content
        if answer is None:
            return ""
        return answer

    def ask_with_tools(self, messages, tools, temperature=0.0, max_tokens=None, tool_choice="auto"):
        """Ask a question and let the model call tools. Returns the raw OpenAI reply."""
        with log_backend_call(
            logger, "openai", "chat.ask_with_tools", model=self.model, tool_count=len(tools)
        ):
            response = self.get_client().chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return response.model_dump()

    def health_check(self) -> dict:
        """Report whether this client is usable - calls GET /models, free but proves the key/URL/network work."""
        result = {"provider": self.PROVIDER_NAME}
        result.update(self.get_configuration())

        if not self.api_key:
            result["status"] = "unhealthy"
            result["message"] = "API key not configured"
            return result

        try:
            model_list = list(self.get_client().models.list())
            result["status"] = "healthy"
            result["models_visible"] = len(model_list)
        except Exception as error:
            # A health check must never crash - report the problem instead.
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result


class OpenAIEmbeddingClient:
    """Turns text into embeddings - doesn't inherit BaseLLMClient, has no `ask` method."""

    PROVIDER_NAME = "openai_embedding"
    ENV_KEY = "OPENAI_API_KEY"

    DEFAULT_BASE_URL = DEFAULT_OPENAI_BASE_URL
    DEFAULT_MODEL = "text-embedding-3-small"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
    ):
        """Same settings as OpenAIChatClient, but the model comes from OPENAI_EMBED_MODEL."""
        self.api_key = read_setting(api_key, "OPENAI_API_KEY")
        self.model = read_setting(model, "OPENAI_EMBED_MODEL", self.DEFAULT_MODEL)
        self.base_url = read_url_setting(base_url, "OPENAI_BASE_URL", self.DEFAULT_BASE_URL)
        self.organization = read_setting(organization, "OPENAI_ORG_ID")
        self.project = read_setting(project, "OPENAI_PROJECT_ID")

        if not self.api_key:
            logger.warning("[OPENAI] OPENAI_API_KEY not set")

        # See OpenAIChatClient.__init__ for why this is not built unconditionally.
        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                organization=self.organization,
                project=self.project,
            )
        else:
            self.client = None

    def get_client(self):
        """Return the OpenAI object, or raise a clear error if there is no key."""
        if self.client is None:
            raise RuntimeError(f"{self.ENV_KEY} is not configured")
        return self.client

    def get_configuration(self) -> dict:
        """Return the settings this client is using, with no secrets in it."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "organization": self.organization,
            "project": self.project,
        }

    def get_embeddings(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Turn texts into embeddings, same order as input - `model` must match the target index's dimension."""
        if not texts:
            return []

        resolved_model = model or self.model
        with log_backend_call(
            logger, "openai", "embeddings.create", model=resolved_model, text_count=len(texts)
        ):
            response = self.get_client().embeddings.create(model=resolved_model, input=texts)

        embeddings = []
        for item in response.data:
            embeddings.append(item.embedding)
        return embeddings

    def health_check(self) -> dict:
        """Report whether this client is usable, including that the configured model is visible to this key."""
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

            result["status"] = "healthy"
            result["models_visible"] = len(available_model_names)
            result["embed_model_available"] = self.model in available_model_names
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
