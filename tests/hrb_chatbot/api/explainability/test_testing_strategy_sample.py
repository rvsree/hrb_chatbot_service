"""Tests for GET /v1/explainability/testing-strategy/{dataset}/sample
(Phase 285) - public, no role gating, no identity params. Store calls are
faked, no real database call, matching every other route test here."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.explainability import testing_strategy_sample
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.main import app
from tests.conftest import FakeDBGateway, FakeGoldenDatasetStore, FakeLiveQueryStore, FakeSyntheticDatasetStore

client = TestClient(app)

_GOLDEN_CASE = {
    "id": 1, "case_key": "401k-001", "dataset": "golden_v1", "category": "benefits",
    "query": "What's the 401k match?", "raw_case": {"expected_answer": "6%"},
    "created_at": "2026-10-26T00:00:00Z", "updated_at": "2026-10-26T00:00:00Z",
    "source": "curated", "source_live_query_id": None, "promoted_by": None, "promoted_at": None,
}

_SYNTHETIC_CASE = {
    "id": 1, "case_key": "synth-001", "dataset": "synthetic_v1", "category": "benefits",
    "query": "How do I enroll in health insurance?", "raw_case": {"answer": "Use the enrollment portal."},
    "created_at": "2026-10-26T00:00:00Z", "updated_at": "2026-10-26T00:00:00Z",
    "source": "curated", "source_live_query_id": None, "promoted_by": None, "promoted_at": None,
}

_LIVE_QUERY = {
    "id": 1, "query_text": "What's my PTO balance?", "answer_text": "You have 10 days.",
    "pipeline": "genai-rag", "request_id": "req-1", "employee_id": "EMP052", "eval_score": 0.9,
    "is_ltm": True, "category": "leave", "created_at": "2026-10-26T00:00:00Z",
}


def test_golden_dataset_sample_returns_real_count_and_rows(monkeypatch):
    store = FakeGoldenDatasetStore([{**_GOLDEN_CASE, "id": i} for i in range(1, 13)])
    monkeypatch.setattr(testing_strategy_sample, "get_db_gateway", lambda: FakeDBGateway(golden_dataset_store=store))

    response = client.get("/v1/explainability/testing-strategy/golden/sample")

    assert response.status_code == 200
    body = response.json()
    assert body["dataset"] == "golden"
    assert body["total_count"] == 12
    assert len(body["sample"]) == 10
    assert body["sample"][0]["case_key"] == "401k-001"


def test_synthetic_dataset_sample_returns_real_count_and_rows(monkeypatch):
    store = FakeSyntheticDatasetStore([_SYNTHETIC_CASE])
    monkeypatch.setattr(testing_strategy_sample, "get_db_gateway", lambda: FakeDBGateway(synthetic_dataset_store=store))

    response = client.get("/v1/explainability/testing-strategy/synthetic/sample")

    assert response.status_code == 200
    body = response.json()
    assert body["dataset"] == "synthetic"
    assert body["total_count"] == 1
    assert len(body["sample"]) == 1
    assert body["sample"][0]["case_key"] == "synth-001"


def test_live_queries_sample_returns_real_count_and_rows(monkeypatch):
    store = FakeLiveQueryStore([_LIVE_QUERY])
    monkeypatch.setattr(testing_strategy_sample, "get_db_gateway", lambda: FakeDBGateway(live_query_store=store))

    response = client.get("/v1/explainability/testing-strategy/live-queries/sample")

    assert response.status_code == 200
    body = response.json()
    assert body["dataset"] == "live-queries"
    assert body["total_count"] == 1
    assert len(body["sample"]) == 1
    assert body["sample"][0]["query_text"] == "What's my PTO balance?"


def test_sample_is_capped_at_ten_even_with_more_rows(monkeypatch):
    store = FakeLiveQueryStore([{**_LIVE_QUERY, "id": i} for i in range(1, 16)])
    monkeypatch.setattr(testing_strategy_sample, "get_db_gateway", lambda: FakeDBGateway(live_query_store=store))

    response = client.get("/v1/explainability/testing-strategy/live-queries/sample")

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 15
    assert len(body["sample"]) == 10


def test_unknown_dataset_value_is_a_422():
    response = client.get("/v1/explainability/testing-strategy/not-a-real-dataset/sample")
    assert response.status_code == 422


def test_requires_no_role_or_identity_params(monkeypatch):
    """No user_profile/employee_id query params at all - a bare, anonymous
    call must still succeed, unlike every admin-only equivalent route."""
    store = FakeGoldenDatasetStore([_GOLDEN_CASE])
    monkeypatch.setattr(testing_strategy_sample, "get_db_gateway", lambda: FakeDBGateway(golden_dataset_store=store))

    response = client.get("/v1/explainability/testing-strategy/golden/sample")

    assert response.status_code == 200


def test_store_error_degrades_to_json_error_not_a_500(monkeypatch):
    store = FakeGoldenDatasetStore([_GOLDEN_CASE])

    async def _boom():
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(store, "list_cases", _boom)
    monkeypatch.setattr(testing_strategy_sample, "get_db_gateway", lambda: FakeDBGateway(golden_dataset_store=store))

    response = client.get("/v1/explainability/testing-strategy/golden/sample")

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == error_codes.EXPLAINABILITY_SAMPLE_FAILED
