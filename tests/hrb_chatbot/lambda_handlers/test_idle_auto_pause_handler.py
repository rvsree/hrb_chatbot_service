"""Tests for the idle-timeout auto-pause Lambda (RAG-ROADMAP.md Phase 262).
AppRunnerClient and the Postgres-backed activity signal are faked - no real
AWS/network call, matching this project's existing fake-based convention."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from src.hrb_chatbot.lambda_handlers import idle_auto_pause_handler
from tests.conftest import FakeAppSettingsStore, FakeDBGateway


@pytest.fixture(autouse=True)
def _pretend_secrets_already_loaded():
    """Every test below exercises the idle-check logic, not the Secrets
    Manager fetch itself (that has its own dedicated tests further down,
    with boto3 explicitly faked) - forcing _secrets_loaded = True here
    means lambda_handler's own call to _load_postgres_env_from_secrets_manager()
    is always a no-op in these tests, regardless of whether this machine's
    ambient environment happens to have real Postgres env vars set. Without
    this, a clean CI environment with no local .env would attempt a real,
    unfaked boto3 Secrets Manager call - the exact zero-API-key guarantee
    this project's test suite otherwise holds everywhere else."""
    idle_auto_pause_handler._secrets_loaded = True
    yield
    idle_auto_pause_handler._secrets_loaded = False

_RUNNING_A = {"service_name": "hrb-chatbot", "display_name": "Chatbot Backend", "status": "RUNNING", "url": "x", "error": None}
_RUNNING_B = {"service_name": "hrb-api-gateway", "display_name": "API Gateway", "status": "RUNNING", "url": "x", "error": None}
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
    gateway = FakeDBGateway(app_settings_store=FakeAppSettingsStore(settings))
    monkeypatch.setattr(idle_auto_pause_handler, "get_db_gateway", lambda: gateway)
    if apprunner_client is not None:
        monkeypatch.setattr(idle_auto_pause_handler, "AppRunnerClient", lambda: apprunner_client)
    if threshold_minutes is not None:
        monkeypatch.setenv("IDLE_AUTO_PAUSE_THRESHOLD_MINUTES", str(threshold_minutes))


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


# _load_postgres_env_from_secrets_manager() itself - boto3 explicitly
# faked in every one of these, real AWS call never possible.


class _FakeSecretsManagerClient:
    def __init__(self):
        self.requested_secret_ids = []

    def get_secret_value(self, SecretId):
        self.requested_secret_ids.append(SecretId)
        return {"SecretString": f"fake-value-for-{SecretId}"}


def test_fetches_each_postgres_secret_when_none_are_already_set(monkeypatch):
    idle_auto_pause_handler._secrets_loaded = False  # override the autouse fixture above - testing the fetch itself
    for env_name in idle_auto_pause_handler._SECRET_ENV_MAP:
        monkeypatch.delenv(env_name, raising=False)
    fake_client = _FakeSecretsManagerClient()
    monkeypatch.setattr(idle_auto_pause_handler.boto3, "client", lambda service: fake_client)

    idle_auto_pause_handler._load_postgres_env_from_secrets_manager()

    assert sorted(fake_client.requested_secret_ids) == sorted(idle_auto_pause_handler._SECRET_ENV_MAP.values())
    assert os.environ["POSTGRES_DB_HOST"] == "fake-value-for-hrb-chatbot/POSTGRES_DB_HOST"


def test_skips_any_key_already_set_without_calling_secrets_manager_for_it(monkeypatch):
    idle_auto_pause_handler._secrets_loaded = False
    for env_name in idle_auto_pause_handler._SECRET_ENV_MAP:
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("POSTGRES_DB_HOST", "already-set-locally")
    fake_client = _FakeSecretsManagerClient()
    monkeypatch.setattr(idle_auto_pause_handler.boto3, "client", lambda service: fake_client)

    idle_auto_pause_handler._load_postgres_env_from_secrets_manager()

    assert "hrb-chatbot/POSTGRES_DB_HOST" not in fake_client.requested_secret_ids
    assert os.environ["POSTGRES_DB_HOST"] == "already-set-locally"


def test_only_fetches_once_per_warm_container_not_on_every_call(monkeypatch):
    idle_auto_pause_handler._secrets_loaded = False
    for env_name in idle_auto_pause_handler._SECRET_ENV_MAP:
        monkeypatch.delenv(env_name, raising=False)
    fake_client = _FakeSecretsManagerClient()
    monkeypatch.setattr(idle_auto_pause_handler.boto3, "client", lambda service: fake_client)

    idle_auto_pause_handler._load_postgres_env_from_secrets_manager()
    first_call_count = len(fake_client.requested_secret_ids)
    idle_auto_pause_handler._load_postgres_env_from_secrets_manager()

    assert len(fake_client.requested_secret_ids) == first_call_count
