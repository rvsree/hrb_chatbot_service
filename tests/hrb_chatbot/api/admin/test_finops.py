"""Tests for GET /v1/admin/finops/* (Phase 283) - finops_snapshot_store
and the 2 live clients (AwsCostClient/LangSmithUsageClient) are faked, no
real AWS/LangSmith/database call, matching every other admin route test
in this project."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.admin import finops
from src.hrb_chatbot.main import app
from tests.conftest import FakeDBGateway, FakeFinopsSnapshotStore

client = TestClient(app)

ADMIN_PROFILE = {"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin"}
EMPLOYEE_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}

_AWS_OK_RESULT = {
    "status": "ok", "message": None,
    "period_start": "2026-10-01", "period_end": "2026-10-31",
    "total_cost": 17.35, "cost_breakdown": {"ECS": 12.35, "Route53": 5.0},
}
_AWS_UNAVAILABLE_RESULT = {
    "status": "unavailable", "message": "AccessDeniedException: ce:GetCostAndUsage",
    "period_start": "2026-10-01", "period_end": "2026-10-31",
    "total_cost": None, "cost_breakdown": {},
}


class _FakeAwsCostClient:
    def __init__(self, *args, **kwargs):
        pass

    def get_current_month_cost(self):
        return _AWS_OK_RESULT


class _FailingAwsCostClient:
    def __init__(self, *args, **kwargs):
        pass

    def get_current_month_cost(self):
        return _AWS_UNAVAILABLE_RESULT


def test_non_admin_cannot_get_finops_cost():
    response = client.get("/v1/admin/finops/aws/cost", params=EMPLOYEE_PROFILE)
    assert response.status_code == 403


def test_non_admin_cannot_get_finops_history():
    response = client.get("/v1/admin/finops/aws/history", params=EMPLOYEE_PROFILE)
    assert response.status_code == 403


def test_non_admin_cannot_get_other_services():
    response = client.get("/v1/admin/finops/other-services", params=EMPLOYEE_PROFILE)
    assert response.status_code == 403


def test_unknown_provider_returns_422():
    response = client.get("/v1/admin/finops/not-a-real-provider/cost", params=ADMIN_PROFILE)
    assert response.status_code == 422


def test_get_cost_with_force_refresh_fetches_live_and_stores_a_snapshot(monkeypatch):
    monkeypatch.setattr(finops, "AwsCostClient", _FakeAwsCostClient)
    store = FakeFinopsSnapshotStore()
    monkeypatch.setattr(finops, "get_db_gateway", lambda: FakeDBGateway(finops_snapshot_store=store))

    response = client.get("/v1/admin/finops/aws/cost", params={**ADMIN_PROFILE, "force_refresh": "true"})

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "aws"
    assert body["total_cost"] == 17.35
    assert body["cost_breakdown"] == {"ECS": 12.35, "Route53": 5.0}
    assert body["created_by"] == "ADM001"


def test_get_cost_without_force_refresh_returns_the_latest_stored_snapshot_without_a_live_call(monkeypatch):
    class _ExplodingAwsCostClient:
        def __init__(self, *a, **kw):
            raise AssertionError("should not have made a live call")

    monkeypatch.setattr(finops, "AwsCostClient", _ExplodingAwsCostClient)
    store = FakeFinopsSnapshotStore(
        snapshots=[{
            "id": 1, "provider": "aws", "captured_at": "2026-10-30T00:00:00+00:00",
            "period_start": "2026-10-01", "period_end": "2026-10-31",
            "total_cost": 9.99, "cost_breakdown": {}, "created_by": "ADM001",
        }]
    )
    monkeypatch.setattr(finops, "get_db_gateway", lambda: FakeDBGateway(finops_snapshot_store=store))

    response = client.get("/v1/admin/finops/aws/cost", params=ADMIN_PROFILE)

    assert response.status_code == 200
    assert response.json()["total_cost"] == 9.99


def test_get_cost_fetches_live_when_no_snapshot_exists_yet(monkeypatch):
    monkeypatch.setattr(finops, "AwsCostClient", _FakeAwsCostClient)
    store = FakeFinopsSnapshotStore()
    monkeypatch.setattr(finops, "get_db_gateway", lambda: FakeDBGateway(finops_snapshot_store=store))

    response = client.get("/v1/admin/finops/aws/cost", params=ADMIN_PROFILE)

    assert response.status_code == 200
    assert response.json()["total_cost"] == 17.35


def test_aws_failure_returns_finops_provider_unavailable_not_a_500(monkeypatch):
    monkeypatch.setattr(finops, "AwsCostClient", _FailingAwsCostClient)
    store = FakeFinopsSnapshotStore()
    monkeypatch.setattr(finops, "get_db_gateway", lambda: FakeDBGateway(finops_snapshot_store=store))

    response = client.get("/v1/admin/finops/aws/cost", params={**ADMIN_PROFILE, "force_refresh": "true"})

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "FINOPS_PROVIDER_UNAVAILABLE"
    assert "AccessDeniedException" in body["error"]


def test_get_finops_history_returns_stored_snapshots_newest_first(monkeypatch):
    store = FakeFinopsSnapshotStore(
        snapshots=[
            {
                "id": 1, "provider": "aws", "captured_at": "2026-10-01T00:00:00+00:00",
                "period_start": "2026-10-01", "period_end": "2026-10-31",
                "total_cost": 10.0, "cost_breakdown": {}, "created_by": "ADM001",
            },
            {
                "id": 2, "provider": "aws", "captured_at": "2026-10-02T00:00:00+00:00",
                "period_start": "2026-10-01", "period_end": "2026-10-31",
                "total_cost": 12.0, "cost_breakdown": {}, "created_by": "ADM001",
            },
        ]
    )
    monkeypatch.setattr(finops, "get_db_gateway", lambda: FakeDBGateway(finops_snapshot_store=store))

    response = client.get("/v1/admin/finops/aws/history", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["snapshots"][0]["id"] == 2  # newest first


def test_get_other_services_returns_static_content_for_the_three_services():
    response = client.get("/v1/admin/finops/other-services", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    providers = {service["provider"] for service in body["services"]}
    assert providers == {"pinecone", "upstash_redis", "neon"}
    assert all(service["pause_available"] is False for service in body["services"])
