"""Tests for the public wake-up Lambda (RAG-ROADMAP.md Phase 287, widened
to 2 services in Phase 289). AppRunnerClient and wake_up_limiter are
faked - no real AWS/Redis/Postgres call, matching this project's existing
fake-based convention."""

import json

import pytest

from src.hrb_chatbot.lambda_handlers import wake_up_handler

_CHATBOT_RUNNING = {"service_name": "hrb-chatbot", "display_name": "Chatbot Backend", "status": "RUNNING", "url": "x", "error": None}
_CHATBOT_PAUSED = {**_CHATBOT_RUNNING, "status": "PAUSED", "url": None}
_CHATBOT_IN_PROGRESS = {**_CHATBOT_RUNNING, "status": "OPERATION_IN_PROGRESS", "url": None}
_CHATBOT_ERROR = {**_CHATBOT_RUNNING, "status": "ERROR", "error": "ThrottlingException"}
_GATEWAY_RUNNING = {"service_name": "hrb-api-gateway", "display_name": "API Gateway", "status": "RUNNING", "url": "y", "error": None}
_GATEWAY_PAUSED = {**_GATEWAY_RUNNING, "status": "PAUSED", "url": None}
_GATEWAY_IN_PROGRESS = {**_GATEWAY_RUNNING, "status": "OPERATION_IN_PROGRESS", "url": None}
_OTHER_SERVICE = {"service_name": "hrb-lms-mcp", "display_name": "MCP Server", "status": "RUNNING", "url": "x", "error": None}


@pytest.fixture(autouse=True)
def _skip_real_secrets_fetch(monkeypatch):
    """Secrets Manager bootstrap has its own dedicated tests
    (test_lambda_secrets_bootstrap.py) - no-op it here so a clean CI
    environment with no local .env can never attempt a real AWS call."""
    monkeypatch.setattr(wake_up_handler, "load_secrets_into_env", lambda secret_env_map: None)


class _FakeAppRunnerClient:
    def __init__(self, describe_result=None, resume_result=None):
        self._describe_result = describe_result if describe_result is not None else [_CHATBOT_PAUSED, _GATEWAY_PAUSED]
        self._resume_result = resume_result

    def describe_all(self):
        return self._describe_result

    def resume(self, service_names=None):
        if self._resume_result is None:
            raise AssertionError("resume should not have been called")
        self.resume_called_with = service_names
        return self._resume_result


def _wire(monkeypatch, apprunner_client, under_cap=True):
    monkeypatch.setattr(wake_up_handler, "AppRunnerClient", lambda: apprunner_client)

    async def _fake_check_and_record(ip_address):
        return under_cap

    monkeypatch.setattr(wake_up_handler.wake_up_limiter, "check_and_record", _fake_check_and_record)


def _event(source_ip="1.2.3.4"):
    return {"requestContext": {"http": {"sourceIp": source_ip}}}


def _body(response):
    return json.loads(response["body"])


def test_both_already_running_is_a_noop_and_never_checks_the_rate_limit(monkeypatch):
    class _ExplodingLimiter:
        async def check_and_record(self, ip_address):
            raise AssertionError("rate limiter must not be consulted when already RUNNING")

    monkeypatch.setattr(
        wake_up_handler, "AppRunnerClient", lambda: _FakeAppRunnerClient(describe_result=[_CHATBOT_RUNNING, _GATEWAY_RUNNING])
    )
    monkeypatch.setattr(wake_up_handler, "wake_up_limiter", _ExplodingLimiter())

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    assert _body(response) == {"resumed": False, "services": {"hrb-chatbot": "RUNNING", "hrb-api-gateway": "RUNNING"}}


def test_both_operation_in_progress_is_also_a_noop(monkeypatch):
    class _ExplodingLimiter:
        async def check_and_record(self, ip_address):
            raise AssertionError("rate limiter must not be consulted when already resuming")

    monkeypatch.setattr(
        wake_up_handler, "AppRunnerClient", lambda: _FakeAppRunnerClient(describe_result=[_CHATBOT_IN_PROGRESS, _GATEWAY_IN_PROGRESS])
    )
    monkeypatch.setattr(wake_up_handler, "wake_up_limiter", _ExplodingLimiter())

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    assert _body(response)["resumed"] is False


def test_only_chatbot_paused_resumes_only_chatbot_not_the_already_running_gateway(monkeypatch):
    fake_client = _FakeAppRunnerClient(
        describe_result=[_CHATBOT_PAUSED, _GATEWAY_RUNNING],
        resume_result=[{**_CHATBOT_IN_PROGRESS}],
    )
    _wire(monkeypatch, fake_client, under_cap=True)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    assert fake_client.resume_called_with == ["hrb-chatbot"]
    assert _body(response) == {"resumed": True, "services": {"hrb-api-gateway": "RUNNING", "hrb-chatbot": "OPERATION_IN_PROGRESS"}}


def test_only_gateway_paused_resumes_only_gateway_not_the_already_running_chatbot(monkeypatch):
    fake_client = _FakeAppRunnerClient(
        describe_result=[_CHATBOT_RUNNING, _GATEWAY_PAUSED],
        resume_result=[{**_GATEWAY_IN_PROGRESS}],
    )
    _wire(monkeypatch, fake_client, under_cap=True)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    assert fake_client.resume_called_with == ["hrb-api-gateway"]
    assert _body(response) == {"resumed": True, "services": {"hrb-chatbot": "RUNNING", "hrb-api-gateway": "OPERATION_IN_PROGRESS"}}


def test_both_paused_and_under_cap_resumes_both_in_one_call(monkeypatch):
    fake_client = _FakeAppRunnerClient(
        describe_result=[_CHATBOT_PAUSED, _GATEWAY_PAUSED],
        resume_result=[{**_CHATBOT_IN_PROGRESS}, {**_GATEWAY_IN_PROGRESS}],
    )
    _wire(monkeypatch, fake_client, under_cap=True)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    assert fake_client.resume_called_with == ["hrb-chatbot", "hrb-api-gateway"]
    assert _body(response) == {
        "resumed": True,
        "services": {"hrb-chatbot": "OPERATION_IN_PROGRESS", "hrb-api-gateway": "OPERATION_IN_PROGRESS"},
    }


def test_over_cap_returns_429_and_never_calls_resume(monkeypatch):
    fake_client = _FakeAppRunnerClient(describe_result=[_CHATBOT_PAUSED, _GATEWAY_PAUSED])  # resume_result=None -> raises if called
    _wire(monkeypatch, fake_client, under_cap=False)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 429
    body = _body(response)
    assert body["resumed"] is False
    assert body["error"] == "rate_limited"
    assert body["services"] == {"hrb-chatbot": "PAUSED", "hrb-api-gateway": "PAUSED"}


def test_resume_call_erroring_for_one_service_is_reported_not_raised(monkeypatch):
    errored_result = [{**_CHATBOT_IN_PROGRESS}, {**_GATEWAY_PAUSED, "status": "ERROR", "error": "AccessDenied"}]
    fake_client = _FakeAppRunnerClient(describe_result=[_CHATBOT_PAUSED, _GATEWAY_PAUSED], resume_result=errored_result)
    _wire(monkeypatch, fake_client, under_cap=True)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 502
    body = _body(response)
    assert body["resumed"] is False
    assert body["error"] == "AccessDenied"


def test_describe_service_error_on_either_target_fails_closed_without_attempting_resume(monkeypatch):
    fake_client = _FakeAppRunnerClient(describe_result=[_CHATBOT_ERROR, _GATEWAY_PAUSED])
    _wire(monkeypatch, fake_client, under_cap=True)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 502
    assert _body(response)["resumed"] is False


def test_hrb_chatbot_missing_from_describe_all_is_a_misconfiguration(monkeypatch):
    fake_client = _FakeAppRunnerClient(describe_result=[_GATEWAY_RUNNING, _OTHER_SERVICE])
    _wire(monkeypatch, fake_client, under_cap=True)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 500
    assert _body(response)["resumed"] is False


def test_hrb_api_gateway_missing_from_describe_all_is_also_a_misconfiguration(monkeypatch):
    """New in Phase 289 - the widened target list means a misconfiguration
    can now be missing either service, not just hrb-chatbot."""
    fake_client = _FakeAppRunnerClient(describe_result=[_CHATBOT_RUNNING, _OTHER_SERVICE])
    _wire(monkeypatch, fake_client, under_cap=True)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 500
    assert _body(response)["resumed"] is False


def test_an_unexpected_exception_fails_closed_with_200(monkeypatch):
    def _exploding_client():
        raise RuntimeError("boom")

    monkeypatch.setattr(wake_up_handler, "AppRunnerClient", _exploding_client)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert response["statusCode"] == 200
    assert _body(response) == {"resumed": False, "error": "unexpected_error"}


def test_missing_source_ip_is_treated_as_none_not_an_error(monkeypatch):
    fake_client = _FakeAppRunnerClient(
        describe_result=[_CHATBOT_PAUSED, _GATEWAY_PAUSED],
        resume_result=[{**_CHATBOT_IN_PROGRESS}, {**_GATEWAY_IN_PROGRESS}],
    )
    captured_ip = {}

    async def _fake_check_and_record(ip_address):
        captured_ip["value"] = ip_address
        return True

    monkeypatch.setattr(wake_up_handler, "AppRunnerClient", lambda: fake_client)
    monkeypatch.setattr(wake_up_handler.wake_up_limiter, "check_and_record", _fake_check_and_record)

    response = wake_up_handler.lambda_handler({}, None)

    assert response["statusCode"] == 200
    assert captured_ip["value"] is None


def test_malformed_event_shape_is_treated_as_missing_source_ip(monkeypatch):
    fake_client = _FakeAppRunnerClient(
        describe_result=[_CHATBOT_PAUSED, _GATEWAY_PAUSED],
        resume_result=[{**_CHATBOT_IN_PROGRESS}, {**_GATEWAY_IN_PROGRESS}],
    )
    captured_ip = {}

    async def _fake_check_and_record(ip_address):
        captured_ip["value"] = ip_address
        return True

    monkeypatch.setattr(wake_up_handler, "AppRunnerClient", lambda: fake_client)
    monkeypatch.setattr(wake_up_handler.wake_up_limiter, "check_and_record", _fake_check_and_record)

    response = wake_up_handler.lambda_handler({"requestContext": {"http": "not-a-dict"}}, None)

    assert response["statusCode"] == 200
    assert captured_ip["value"] is None


def test_response_shape_is_a_valid_lambda_function_url_response(monkeypatch):
    fake_client = _FakeAppRunnerClient(describe_result=[_CHATBOT_RUNNING, _GATEWAY_RUNNING])
    monkeypatch.setattr(wake_up_handler, "AppRunnerClient", lambda: fake_client)

    response = wake_up_handler.lambda_handler(_event(), None)

    assert set(response.keys()) == {"statusCode", "headers", "body"}
    assert isinstance(response["statusCode"], int)
    assert response["headers"]["Content-Type"] == "application/json"
    assert isinstance(response["body"], str)


def test_lambda_handler_calls_the_shared_secrets_bootstrap(monkeypatch):
    """Integration-style check mirroring
    test_idle_auto_pause_handler.py::test_lambda_handler_calls_the_shared_secrets_bootstrap
    - deliberately does NOT use the autouse no-op fixture above."""
    captured = {}
    monkeypatch.setattr(
        wake_up_handler, "load_secrets_into_env", lambda secret_env_map: captured.setdefault("map", secret_env_map)
    )
    monkeypatch.setattr(
        wake_up_handler, "AppRunnerClient", lambda: _FakeAppRunnerClient(describe_result=[_CHATBOT_RUNNING, _GATEWAY_RUNNING])
    )

    wake_up_handler.lambda_handler(_event(), None)

    assert captured["map"] == wake_up_handler._SECRET_ENV_MAP
