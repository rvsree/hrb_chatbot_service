"""Tests for AwsCostClient (Phase 283) - boto3.client is faked, no real
AWS call, matching every other client test in this project."""

from src.hrb_chatbot.common.clients.finops_client import aws_cost_client as aws_cost_client_module
from src.hrb_chatbot.common.clients.finops_client.aws_cost_client import AwsCostClient


class _FakeBoto3CostExplorerClient:
    def __init__(self, response=None, raise_error=None):
        self.response = response
        self.raise_error = raise_error
        self.calls = []

    def get_cost_and_usage(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_error is not None:
            raise self.raise_error
        return self.response


def _build_client(monkeypatch, fake_boto3_client):
    monkeypatch.setattr(aws_cost_client_module.boto3, "client", lambda *a, **kw: fake_boto3_client)
    return AwsCostClient()


_SUCCESS_RESPONSE = {
    "ResultsByTime": [
        {
            "Groups": [
                {"Keys": ["Amazon Elastic Container Service"], "Metrics": {"UnblendedCost": {"Amount": "12.35", "Unit": "USD"}}},
                {"Keys": ["Amazon Route 53"], "Metrics": {"UnblendedCost": {"Amount": "5.00", "Unit": "USD"}}},
            ]
        }
    ]
}


def test_get_current_month_cost_returns_total_and_breakdown(monkeypatch):
    fake = _FakeBoto3CostExplorerClient(response=_SUCCESS_RESPONSE)
    client = _build_client(monkeypatch, fake)

    result = client.get_current_month_cost()

    assert result["status"] == "ok"
    assert result["total_cost"] == 17.35
    assert result["cost_breakdown"] == {"Amazon Elastic Container Service": 12.35, "Amazon Route 53": 5.0}
    assert result["period_start"] is not None
    assert result["period_end"] is not None


def test_get_current_month_cost_calls_get_cost_and_usage_with_monthly_granularity(monkeypatch):
    fake = _FakeBoto3CostExplorerClient(response=_SUCCESS_RESPONSE)
    client = _build_client(monkeypatch, fake)

    client.get_current_month_cost()

    assert fake.calls[0]["Granularity"] == "MONTHLY"
    assert fake.calls[0]["Metrics"] == ["UnblendedCost"]


def test_get_current_month_cost_access_denied_returns_unavailable_not_raise(monkeypatch):
    fake = _FakeBoto3CostExplorerClient(raise_error=RuntimeError("AccessDeniedException: ce:GetCostAndUsage"))
    client = _build_client(monkeypatch, fake)

    result = client.get_current_month_cost()

    assert result["status"] == "unavailable"
    assert "AccessDeniedException" in result["message"]
    assert result["total_cost"] is None
    assert result["cost_breakdown"] == {}
