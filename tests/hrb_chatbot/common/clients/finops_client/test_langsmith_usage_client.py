"""Tests for LangSmithUsageClient (Phase 283) - requests.get is faked, no
real network call, matching every other HTTP-based client test in this
project."""

from src.hrb_chatbot.common.clients.finops_client import langsmith_usage_client as langsmith_usage_client_module
from src.hrb_chatbot.common.clients.finops_client.langsmith_usage_client import LangSmithUsageClient


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_data


def _build_client(monkeypatch, fake_response, captured_calls=None):
    def _fake_get(url, headers=None, params=None, timeout=None):
        if captured_calls is not None:
            captured_calls.append({"url": url, "headers": headers, "params": params})
        return fake_response

    monkeypatch.setattr(langsmith_usage_client_module.requests, "get", _fake_get)
    return LangSmithUsageClient(api_key="fake-key")


def test_get_current_month_usage_parses_a_daily_usage_list(monkeypatch):
    fake_response = _FakeResponse({"usage": [{"date": "2026-10-01", "trace_count": 5}, {"date": "2026-10-02", "trace_count": 7}]})
    client = _build_client(monkeypatch, fake_response)

    result = client.get_current_month_usage()

    assert result["status"] == "ok"
    assert result["total_cost"] is None
    assert result["cost_breakdown"] == {"2026-10-01": 5, "2026-10-02": 7}


def test_get_current_month_usage_sends_the_api_key_header(monkeypatch):
    fake_response = _FakeResponse({"usage": []})
    calls = []
    client = _build_client(monkeypatch, fake_response, captured_calls=calls)

    client.get_current_month_usage()

    assert calls[0]["headers"] == {"x-api-key": "fake-key"}
    assert "granular-usage" in calls[0]["url"]
    # Confirmed live this session: LangSmith 422s without these - a past
    # version of this client computed them and never sent them.
    assert "start_time" in calls[0]["params"]
    assert "end_time" in calls[0]["params"]


def test_get_current_month_usage_falls_back_to_raw_body_on_unrecognized_shape(monkeypatch):
    fake_response = _FakeResponse({"something_else": "unexpected shape"})
    client = _build_client(monkeypatch, fake_response)

    result = client.get_current_month_usage()

    assert result["status"] == "ok"
    assert result["cost_breakdown"] == {"something_else": "unexpected shape"}


def test_get_current_month_usage_http_failure_returns_unavailable_not_raise(monkeypatch):
    fake_response = _FakeResponse({}, status_code=401)
    client = _build_client(monkeypatch, fake_response)

    result = client.get_current_month_usage()

    assert result["status"] == "unavailable"
    assert "401" in result["message"]
    assert result["cost_breakdown"] == {}


def test_missing_api_key_returns_unavailable_without_a_network_call(monkeypatch):
    calls = []
    monkeypatch.setattr(
        langsmith_usage_client_module.requests, "get", lambda *a, **kw: calls.append(1)
    )
    client = LangSmithUsageClient(api_key=None)
    # Force a clean slate - a real .env may have LANGSMITH_API_KEY set.
    client.api_key = None

    result = client.get_current_month_usage()

    assert result["status"] == "unavailable"
    assert "LANGSMITH_API_KEY" in result["message"]
    assert calls == []
