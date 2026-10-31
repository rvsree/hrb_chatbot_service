"""Tests for GET/POST /v1/auth/backend-activation/* (Phase 284) - public,
no role gating. AppRunnerClient and the new rate limiter are faked."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.auth import login
from src.hrb_chatbot.common import error_codes
from src.hrb_chatbot.common.rate_limiting import backend_activation_limiter
from src.hrb_chatbot.main import app
from tests.conftest import FakeAppSettingsStore, FakeDBGateway

client = TestClient(app)

_RUNNING_SERVICE = {
    "service_name": "hrb-chatbot",
    "display_name": "Chatbot Backend",
    "status": "RUNNING",
    "url": "https://hrb-chatbot.rvsree.dev",
    "error": None,
}

_PAUSED_SERVICE = {
    "service_name": "hrb-api-gateway",
    "display_name": "API Gateway",
    "status": "PAUSED",
    "url": None,
    "error": None,
}


class _FakeAppRunnerClient:
    def __init__(self, describe_result=None, resume_result=None):
        self._describe_result = describe_result if describe_result is not None else [_RUNNING_SERVICE]
        self._resume_result = resume_result

    def describe_all(self):
        return self._describe_result

    def resume(self, service_names=None):
        if self._resume_result is None:
            raise AssertionError("resume should not have been called")
        return self._resume_result


class _ExplodingAppRunnerClient:
    """Used to prove the non-production no-op path never even constructs
    a real client, let alone calls AWS."""

    def __init__(self, *args, **kwargs):
        raise AssertionError("AppRunnerClient must not be constructed outside production")


def _fail_if_called(*args, **kwargs):
    raise AssertionError("must not be called in this path")


# Non-production no-op - the real security boundary for this phase.


def test_status_is_a_noop_outside_production(monkeypatch):
    monkeypatch.setattr(login, "AppRunnerClient", _ExplodingAppRunnerClient)

    response = client.get("/v1/auth/backend-activation/status")

    assert response.status_code == 200
    assert response.json() == {"all_running": True, "services": []}


def test_resume_is_a_noop_outside_production(monkeypatch):
    monkeypatch.setattr(login, "AppRunnerClient", _ExplodingAppRunnerClient)
    monkeypatch.setattr(backend_activation_limiter, "check_and_record", _fail_if_called)

    response = client.post("/v1/auth/backend-activation/resume")

    assert response.status_code == 200
    assert response.json() == {"all_running": True, "services": []}


# Production - everything already running.


def test_status_reports_all_running_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setattr(login, "AppRunnerClient", lambda: _FakeAppRunnerClient(describe_result=[_RUNNING_SERVICE]))

    response = client.get("/v1/auth/backend-activation/status")

    assert response.status_code == 200
    body = response.json()
    assert body["all_running"] is True
    assert body["services"][0]["service_name"] == "hrb-chatbot"


def test_resume_when_everything_already_running_skips_resume_and_rate_limiter(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setattr(login, "AppRunnerClient", lambda: _FakeAppRunnerClient(describe_result=[_RUNNING_SERVICE]))
    monkeypatch.setattr(backend_activation_limiter, "check_and_record", _fail_if_called)

    response = client.post("/v1/auth/backend-activation/resume")

    assert response.status_code == 200
    body = response.json()
    assert body["all_running"] is True
    assert body["services"] == [_RUNNING_SERVICE]


# Production - some services paused.


def test_status_reports_not_all_running_when_one_service_is_paused(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setattr(
        login, "AppRunnerClient", lambda: _FakeAppRunnerClient(describe_result=[_RUNNING_SERVICE, _PAUSED_SERVICE])
    )

    response = client.get("/v1/auth/backend-activation/status")

    assert response.status_code == 200
    assert response.json()["all_running"] is False


def test_resume_only_resumes_the_non_running_subset_and_records_the_limiter(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    captured = {}

    class _CapturingClient(_FakeAppRunnerClient):
        def resume(self, service_names=None):
            captured["service_names"] = service_names
            return [{**_PAUSED_SERVICE, "status": "OPERATION_IN_PROGRESS"}]

    monkeypatch.setattr(
        login, "AppRunnerClient", lambda: _CapturingClient(describe_result=[_RUNNING_SERVICE, _PAUSED_SERVICE])
    )

    async def _fake_check_and_record(ip_address):
        captured["ip_address"] = ip_address
        return True

    monkeypatch.setattr(backend_activation_limiter, "check_and_record", _fake_check_and_record)

    response = client.post("/v1/auth/backend-activation/resume")

    assert response.status_code == 200
    assert captured["service_names"] == ["hrb-api-gateway"]
    assert "ip_address" in captured
    body = response.json()
    assert body["all_running"] is False
    assert body["services"][0]["status"] == "OPERATION_IN_PROGRESS"


def test_resume_over_the_daily_cap_returns_429(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    monkeypatch.setattr(
        login, "AppRunnerClient", lambda: _FakeAppRunnerClient(describe_result=[_PAUSED_SERVICE])
    )

    async def _fake_check_and_record(ip_address):
        return False

    monkeypatch.setattr(backend_activation_limiter, "check_and_record", _fake_check_and_record)

    response = client.post("/v1/auth/backend-activation/resume")

    assert response.status_code == 429
    assert response.json()["code"] == error_codes.BACKEND_ACTIVATION_RATE_LIMITED


def test_resume_proceeds_when_the_rate_limiters_own_redis_is_unreachable(monkeypatch):
    """Fail-open, matching every other limiter in this project."""
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    captured = {}

    class _CapturingClient(_FakeAppRunnerClient):
        def resume(self, service_names=None):
            captured["resumed"] = True
            return [{**_PAUSED_SERVICE, "status": "OPERATION_IN_PROGRESS"}]

    monkeypatch.setattr(login, "AppRunnerClient", lambda: _CapturingClient(describe_result=[_PAUSED_SERVICE]))

    class _RaisingRedisClient:
        async def incr(self, key):
            raise ConnectionError("redis unreachable")

        async def expire(self, key, seconds):
            pass

    monkeypatch.setattr(backend_activation_limiter, "_get_redis_client", lambda: _RaisingRedisClient())

    gateway = FakeDBGateway(app_settings_store=FakeAppSettingsStore({}))
    monkeypatch.setattr(backend_activation_limiter, "get_db_gateway", lambda: gateway)

    response = client.post("/v1/auth/backend-activation/resume")

    assert response.status_code == 200
    assert captured.get("resumed") is True
