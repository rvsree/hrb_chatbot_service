"""One place that hands out every client the project uses - built lazily,
cached, so nothing re-reads the same settings twice."""

from src.hrb_chatbot.common.clients.ci_client.github_actions_client import GitHubActionsClient
from src.hrb_chatbot.common.clients.llm_client.anthropic_client import AnthropicChatClient
from src.hrb_chatbot.common.clients.llm_client.bedrock_client import BedrockChatClient
from src.hrb_chatbot.common.clients.llm_client.open_router_client import OpenRouterChatClient
from src.hrb_chatbot.common.clients.llm_client.openai_client import (
    OpenAIChatClient,
    OpenAIEmbeddingClient,
)
from src.hrb_chatbot.common.clients.web_client.tavily_client import TavilyClient


class ClientGateway:
    """Creates each client once, then returns that same client every time."""

    def __init__(self):
        """Start with no clients built yet - each stays None until first requested,
        so a project that only needs Tavily never sees OpenAI key warnings."""
        self.openai_chat_client = None
        self.openai_embedding_client = None
        self.anthropic_chat_client = None
        self.openrouter_chat_client = None
        self.bedrock_chat_client = None
        self.tavily_search_client = None
        # Phase 233 - keyed by repo (not a single shared instance), so a
        # second repo (hrb_lms_mcp) gets its own cached client instead of
        # fighting over the default's self.repo.
        self.github_actions_clients: dict[str, GitHubActionsClient] = {}

    def openai_chat(self) -> OpenAIChatClient:
        """Return the shared OpenAI chat client, building it on first use."""
        if self.openai_chat_client is None:
            self.openai_chat_client = OpenAIChatClient()
        return self.openai_chat_client

    def openai_embedding(self) -> OpenAIEmbeddingClient:
        """Return the shared OpenAI embedding client, building it on first use."""
        if self.openai_embedding_client is None:
            self.openai_embedding_client = OpenAIEmbeddingClient()
        return self.openai_embedding_client

    def anthropic_chat(self) -> AnthropicChatClient:
        """Return the shared Anthropic chat client, building it on first use."""
        if self.anthropic_chat_client is None:
            self.anthropic_chat_client = AnthropicChatClient()
        return self.anthropic_chat_client

    def openrouter_chat(self) -> OpenRouterChatClient:
        """Return the shared OpenRouter chat client, building it on first use."""
        if self.openrouter_chat_client is None:
            self.openrouter_chat_client = OpenRouterChatClient()
        return self.openrouter_chat_client

    def bedrock_chat(self) -> BedrockChatClient:
        """Return the shared Bedrock client, building it on first use."""
        if self.bedrock_chat_client is None:
            self.bedrock_chat_client = BedrockChatClient()
        return self.bedrock_chat_client

    def tavily(self) -> TavilyClient:
        """Return the shared Tavily search client, building it on first use."""
        if self.tavily_search_client is None:
            self.tavily_search_client = TavilyClient()
        return self.tavily_search_client

    def github_actions(self, repo: str | None = None) -> GitHubActionsClient:
        """Return the shared GitHub Actions client for the given repo,
        building it on first use (Phase 183; Phase 233 added the repo
        param). `repo=None` keeps this project's own default
        (GITHUB_REPO / rvsree/hrb_chatbot_service) - same GITHUB_TOKEN either
        way, just pointed at a different repo's Actions API."""
        key = repo or "default"
        if key not in self.github_actions_clients:
            self.github_actions_clients[key] = GitHubActionsClient(repo=repo)
        return self.github_actions_clients[key]


# Module-level singleton, not a DI container - `global` below reuses this
# one shared instance each call (same effect as a Spring singleton bean).
_shared_gateway: ClientGateway | None = None


def get_client_gateway() -> ClientGateway:
    """Return the one shared ClientGateway, creating it on the first call."""
    global _shared_gateway

    if _shared_gateway is None:
        _shared_gateway = ClientGateway()

    return _shared_gateway


def reset_client_gateway():
    """Throw away the shared gateway so the next call builds a fresh one - only
    needed in tests, since clients read settings once, at construction time."""
    global _shared_gateway
    _shared_gateway = None
