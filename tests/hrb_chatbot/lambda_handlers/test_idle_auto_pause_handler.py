"""Tests for the idle-timeout auto-pause Lambda (RAG-ROADMAP.md Phase 262).
AppRunnerClient and the Postgres-backed activity signal are faked - no real
AWS/network call, matching this project's existing fake-based convention."""

from datetime import UTC, datetime, timedelta

import pytest

from src.hrb_chatbot.lambda_handlers import idle_auto_pause_handler
from tests.conftest import FakeAppSettingsStore, FakeDBGateway


@pytest.fixture(autouse=True)
def _skip_real_secrets_fetch(monkeypatch):
    """Every test below exercises the idle-check logic, not the shared
    Secrets Manager bootstrap itself (that has its own dedicated tests in
    test_lambda_secrets_bootstrap.py, with boto3 explicitly faked) -
    no-op it here so a clean CI environment with no local .env can never
    attempt a real, unfaked AWS call."""
    monkeypatch.setattr(idle_auto_pause_handler, "load_secrets_into_env", lambda secret_env_map: None)


_RUNNING_A = {"service_name": "rag-ingestion-service", "display_name": "RAG Ingestion", "status": "RUNNING", "url": "x", "error": None}
_RUNNING_B = {"service_name": "hrb-platform-components", "display_name": "Platform/Admin", "status": "RUNNING", "url": "x", "error": None}
_PAUSED_A = {"service_name": "hrb-lms-mcp", "display_name": "MCP Server", "status": "PAUSED", "url": None, "error": None}


class _FakeAppRunnerClient:
    def __init__(self, describe_result=None, pause_result=None):
        self._describe_result = describe_result if describe_result is not None else []
        self._pause_result = pause_result

    def describe_all(self):
        return self._describe_result

    def pause(self, service_names=None):
        if self._pause_result is None:
            raise AssertionError("pause should not have been called")
        return self._pause_result


def _wire(monkeypatch, last_seen_iso, apprunner_client=None, threshold_minutes=None):
    settings = {"active_user_last_seen_at": last_seen_iso} if last_seen_iso is not None else {}
    if threshold_minutes is not None:
        settings["idle_auto_pause_threshold_minutes"] = threshold_minutes
    gateway = FakeDBGateway(app_settings_store=FakeAppSettingsStore(settings))
    monkeypatch.setattr(idle_auto_pause_handler, "get_db_gateway", lambda: gateway)
    if apprunner_client is not None:
        monkeypatch.setattr(idle_auto_pause_handler, "AppRunnerClient", lambda: apprunner_client)


def test_no_activity_signal_skips_without_constructing_apprunner_client(monkeypatch):
    class _ExplodingClient:
        def __init__(self):
            raise AssertionError("AppRunnerClient must not be constructed with no activity signal")

    _wire(monkeypatch, last_seen_iso=None)
    monkeypatch.setattr(idle_auto_pause_handler, "AppRunnerClient", _ExplodingClient)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result == {"action": "skipped", "reason": "no_activity_signal"}


def test_still_active_within_threshold_skips_and_never_pauses(monkeypatch):
    recent = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()

    class _ExplodingClient:
        def __init__(self):
            raise AssertionError("AppRunnerClient must not be constructed while still active")

    _wire(monkeypatch, last_seen_iso=recent, threshold_minutes=60)
    monkeypatch.setattr(idle_auto_pause_handler, "AppRunnerClient", _ExplodingClient)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result["action"] == "skipped"
    assert result["reason"] == "not_idle"


def test_idle_past_threshold_with_nothing_running_skips_without_pausing(monkeypatch):
    stale = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
    fake_client = _FakeAppRunnerClient(describe_result=[_PAUSED_A])
    _wire(monkeypatch, last_seen_iso=stale, apprunner_client=fake_client, threshold_minutes=60)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result == {"action": "skipped", "reason": "already_paused", "idle_minutes": result["idle_minutes"]}


def test_idle_past_threshold_pauses_only_the_running_services(monkeypatch):
    stale = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
    paused_results = [
        {**_RUNNING_A, "status": "OPERATION_IN_PROGRESS", "error": None},
        {**_RUNNING_B, "status": "OPERATION_IN_PROGRESS", "error": None},
    ]
    fake_client = _FakeAppRunnerClient(describe_result=[_RUNNING_A, _RUNNING_B, _PAUSED_A], pause_result=paused_results)
    _wire(monkeypatch, last_seen_iso=stale, apprunner_client=fake_client, threshold_minutes=60)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result["action"] == "paused"
    assert result["results"] == paused_results


def test_hrb_chatbot_and_gateway_are_never_auto_paused(monkeypatch):
    """Phase 290 - reinstated, widened from Phase 262/286's original
    1-name version: the real, measured end-to-end wake time for these 2
    specific, highest-traffic services (App Runner's own RESUME_SERVICE
    transition plus the app's own cold start, ~90-100s in practice) was
    judged not worth the FinOps saving, even though the standalone
    wake-up Lambda (Phase 287/289) correctly resumes both when asked."""
    hrb_chatbot_running = {
        "service_name": "hrb-chatbot", "display_name": "Chatbot Backend", "status": "RUNNING", "url": "x", "error": None,
    }
    hrb_gateway_running = {
        "service_name": "hrb-api-gateway", "display_name": "API Gateway", "status": "RUNNING", "url": "x", "error": None,
    }

    class _ExplodingClient(_FakeAppRunnerClient):
        def pause(self, service_names=None):
            raise AssertionError("pause should never be called - both services are excluded")

    stale = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
    fake_client = _ExplodingClient(describe_result=[hrb_chatbot_running, hrb_gateway_running])
    _wire(monkeypatch, last_seen_iso=stale, apprunner_client=fake_client, threshold_minutes=60)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result == {"action": "skipped", "reason": "already_paused", "idle_minutes": result["idle_minutes"]}


def test_a_failed_pause_call_is_reported_in_the_result_but_does_not_raise(monkeypatch):
    # This project's lambda_handlers loggers set propagate = False (same
    # convention as index_document_handler.py), so pytest's caplog never
    # observes them - that file's own tests check return values only,
    # not log content, for the same reason. Matching that here.
    stale = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
    paused_results = [{**_RUNNING_A, "status": "ERROR", "error": "boom"}]
    fake_client = _FakeAppRunnerClient(describe_result=[_RUNNING_A], pause_result=paused_results)
    _wire(monkeypatch, last_seen_iso=stale, apprunner_client=fake_client, threshold_minutes=60)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result["action"] == "paused"
    assert result["results"][0]["error"] == "boom"


def test_threshold_reads_from_app_settings_not_an_env_var(monkeypatch):
    """Phase 288 - configurable via the Settings UI (app_settings table)
    now, not a Lambda env var. 30-minute threshold + 45-minute idle gap
    triggers a pause; the old default (60) would not have."""
    stale = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()
    fake_client = _FakeAppRunnerClient(describe_result=[_RUNNING_A], pause_result=[{**_RUNNING_A, "status": "OPERATION_IN_PROGRESS", "error": None}])
    _wire(monkeypatch, last_seen_iso=stale, apprunner_client=fake_client, threshold_minutes=30)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result["action"] == "paused"


def test_threshold_falls_back_to_the_documented_default_when_unset(monkeypatch):
    recent = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()

    class _ExplodingClient:
        def __init__(self):
            raise AssertionError("AppRunnerClient must not be constructed - still active against the 60 min default")

    _wire(monkeypatch, last_seen_iso=recent)  # no threshold_minutes -> app_settings has no key -> default 60
    monkeypatch.setattr(idle_auto_pause_handler, "AppRunnerClient", _ExplodingClient)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result["reason"] == "not_idle"


def test_malformed_timestamp_is_treated_as_missing_not_an_error(monkeypatch):
    class _ExplodingClient:
        def __init__(self):
            raise AssertionError("AppRunnerClient must not be constructed on a malformed timestamp")

    _wire(monkeypatch, last_seen_iso="not-a-real-timestamp")
    monkeypatch.setattr(idle_auto_pause_handler, "AppRunnerClient", _ExplodingClient)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result == {"action": "skipped", "reason": "no_activity_signal"}


def test_naive_timestamp_with_no_timezone_is_treated_as_missing(monkeypatch):
    class _ExplodingClient:
        def __init__(self):
            raise AssertionError("AppRunnerClient must not be constructed on a naive timestamp")

    naive = datetime.now().isoformat()  # noqa: DTZ005 - deliberately naive, testing this exact case
    _wire(monkeypatch, last_seen_iso=naive)
    monkeypatch.setattr(idle_auto_pause_handler, "AppRunnerClient", _ExplodingClient)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result == {"action": "skipped", "reason": "no_activity_signal"}


def test_an_unexpected_exception_is_caught_and_returned_not_raised(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("unexpected")

    gateway = FakeDBGateway(app_settings_store=FakeAppSettingsStore({}))
    monkeypatch.setattr(gateway.app_settings_store(), "get_setting", _raise)
    monkeypatch.setattr(idle_auto_pause_handler, "get_db_gateway", lambda: gateway)

    result = idle_auto_pause_handler.lambda_handler({}, None)

    assert result["action"] == "error"
    assert "unexpected" in result["message"]


def test_lambda_handler_calls_the_shared_secrets_bootstrap(monkeypatch):
    """Integration-style check that the wiring to the shared bootstrap
    (test_lambda_secrets_bootstrap.py covers its own internals) is
    actually correct - this test deliberately does NOT use the autouse
    no-op fixture above, so it would fail loudly if lambda_handler ever
    stopped calling load_secrets_into_env with the right map."""
    captured = {}
    monkeypatch.setattr(
        idle_auto_pause_handler, "load_secrets_into_env", lambda secret_env_map: captured.setdefault("map", secret_env_map)
    )
    _wire(monkeypatch, last_seen_iso=None)

    idle_auto_pause_handler.lambda_handler({}, None)

    assert captured["map"] == idle_auto_pause_handler._SECRET_ENV_MAP
