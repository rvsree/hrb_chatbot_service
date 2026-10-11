"""Phase 128 - check_all_backend_services() reports the configured embedding
model as a plain config value, no real call (unlike the 3 checks beside it)."""

from src.hrb_chatbot.api.admin import health_checks
from tests.conftest import FakeClientGateway, FakeEmbeddingClient


def test_health_reports_the_configured_embedding_model(monkeypatch):
    fake_gateway = FakeClientGateway(embedding_client=FakeEmbeddingClient(model="text-embedding-3-large"))
    monkeypatch.setattr(health_checks, "get_client_gateway", lambda: fake_gateway)

    result = health_checks.check_all_backend_services()

    assert result["embedding_model"] == "text-embedding-3-large"
