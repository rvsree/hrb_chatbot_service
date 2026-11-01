"""Tests for POST /v1/auth/sign-out (Phase 286) - public, no role gating.
AppRunnerClient and the session-presence signal are faked."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.auth import login
from src.hrb_chatbot.main import app

client = TestClient(app)

_RUNNING_SERVICE = {
    "service_name": "hrb-api-gateway",
    "display_name": "API Gateway",
    "status": "RUNNING",
    "url": "x",
    "error": None,
}


class _FakeAppRunnerClient:
    def __init__(self, describe_result=None, pause_result=None):
        self._describe_result = describe_result if describe_result is not None else [_RUNNING_SERVICE]
        self._pause_result = pause_result

    def describe_all(self):
        return self._describe_result

    def pause(self, service_names=None):
        if self._pause_result is None:
            raise AssertionError("pause should not have been called")
        return self._pause_result


def test_sign_out_is_a_noop_outside_production(monkeypatch):
    removed = {}

    async def _fake_remove(employee_id):
        removed["employee_id"] = employee_id

    monkeypatch.setattr(login, "remove_session_presence", _fake_remove)
    monkeypatch.setattr(login, "AppRunnerClient", lambda: (_ for _ in ()).throw(AssertionError("must not be constructed")))

    response = client.post("/v1/auth/sign-out", json={"employee_id": "EMP052"})

    assert response.status_code == 200
    assert response.json() == {"paused": False}
    assert removed["employee_id"] == "EMP052"


def test_sign_out_does_not_pause_when_someone_else_is_still_active(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")

    async def _fake_remove(employee_id):
        pass

    async def _fake_count(excluding_employee_id):
        return 1

    monkeypatch.setattr(login, "remove_session_presence", _fake_remove)
    monkeypatch.setattr(login, "count_other_active_sessions", _fake_count)
    monkeypatch.setattr(login, "AppRunnerClient", lambda: (_ for _ in ()).throw(AssertionError("must not be constructed")))

    response = client.post("/v1/auth/sign-out", json={"employee_id": "EMP052"})

    assert response.status_code == 200
    assert response.json() == {"paused": False}


def test_sign_out_pauses_when_truly_the_last_active_session(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    captured = {}

    async def _fake_remove(employee_id):
        pass

    async def _fake_count(excluding_employee_id):
        return 0

    class _CapturingClient(_FakeAppRunnerClient):
        def pause(self, service_names=None):
            captured["service_names"] = service_names
            return [{**_RUNNING_SERVICE, "status": "OPERATION_IN_PROGRESS"}]

    monkeypatch.setattr(login, "remove_session_presence", _fake_remove)
    monkeypatch.setattr(login, "count_other_active_sessions", _fake_count)
    monkeypatch.setattr(login, "AppRunnerClient", lambda: _CapturingClient(describe_result=[_RUNNING_SERVICE]))

    response = client.post("/v1/auth/sign-out", json={"employee_id": "EMP052"})

    assert response.status_code == 200
    assert response.json() == {"paused": True}
    assert captured["service_names"] == ["hrb-api-gateway"]


def test_sign_out_can_now_pause_hrb_chatbot_like_any_other_service(monkeypatch):
    """Phase 287 - hrb-chatbot is a normal, auto-pausable service again:
    the standalone wake-up Lambda (its own Function URL, independent of
    hrb-chatbot's own runtime state) replaces Phase 262/286's "never
    pause it" stopgap with a real fix, so this route no longer needs to
    special-case it."""
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    hrb_chatbot_running = {
        "service_name": "hrb-chatbot", "display_name": "Chatbot Backend", "status": "RUNNING", "url": "x", "error": None,
    }
    captured = {}

    async def _fake_remove(employee_id):
        pass

    async def _fake_count(excluding_employee_id):
        return 0

    class _CapturingClient(_FakeAppRunnerClient):
        def pause(self, service_names=None):
            captured["service_names"] = service_names
            return [{**hrb_chatbot_running, "status": "OPERATION_IN_PROGRESS", "error": None}]

    monkeypatch.setattr(login, "remove_session_presence", _fake_remove)
    monkeypatch.setattr(login, "count_other_active_sessions", _fake_count)
    monkeypatch.setattr(login, "AppRunnerClient", lambda: _CapturingClient(describe_result=[hrb_chatbot_running]))

    response = client.post("/v1/auth/sign-out", json={"employee_id": "EMP052"})

    assert response.status_code == 200
    assert response.json() == {"paused": True}
    assert captured["service_names"] == ["hrb-chatbot"]


def test_sign_out_skips_pause_when_everything_is_already_paused(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    paused_service = {**_RUNNING_SERVICE, "status": "PAUSED"}

    async def _fake_remove(employee_id):
        pass

    async def _fake_count(excluding_employee_id):
        return 0

    monkeypatch.setattr(login, "remove_session_presence", _fake_remove)
    monkeypatch.setattr(login, "count_other_active_sessions", _fake_count)
    monkeypatch.setattr(login, "AppRunnerClient", lambda: _FakeAppRunnerClient(describe_result=[paused_service]))

    response = client.post("/v1/auth/sign-out", json={"employee_id": "EMP052"})

    assert response.status_code == 200
    assert response.json() == {"paused": False}


def test_sign_out_uses_tab_session_id_over_employee_id_when_sent(monkeypatch):
    """Phase 286 - the real fix for multi-tab-same-persona: when the
    caller sends a tab_session_id, that (not employee_id) is the key
    removed/checked, so a 2nd tab on the same persona isn't collapsed."""
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    captured = {}

    async def _fake_remove(key):
        captured["removed_key"] = key

    async def _fake_count(excluding_employee_id):
        captured["excluded_key"] = excluding_employee_id
        return 0

    monkeypatch.setattr(login, "remove_session_presence", _fake_remove)
    monkeypatch.setattr(login, "count_other_active_sessions", _fake_count)
    monkeypatch.setattr(login, "AppRunnerClient", lambda: _FakeAppRunnerClient(describe_result=[]))

    response = client.post("/v1/auth/sign-out", json={"employee_id": "EMP052", "tab_session_id": "tab-abc-123"})

    assert response.status_code == 200
    assert captured["removed_key"] == "tab-abc-123"
    assert captured["excluded_key"] == "tab-abc-123"


def test_sign_out_fails_closed_on_an_unexpected_error(monkeypatch):
    monkeypatch.setenv("APP_ENVIRONMENT", "production")

    async def _raise(employee_id):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(login, "remove_session_presence", _raise)

    response = client.post("/v1/auth/sign-out", json={"employee_id": "EMP052"})

    assert response.status_code == 200
    assert response.json() == {"paused": False}
