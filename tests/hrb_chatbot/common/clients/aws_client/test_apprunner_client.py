"""Tests for AppRunnerClient (Phase 261) - boto3.client is faked, no real
AWS call, matching every other client test in this project."""

import json

from src.hrb_chatbot.common.clients.aws_client import apprunner_client as apprunner_client_module
from src.hrb_chatbot.common.clients.aws_client.apprunner_client import AppRunnerClient

_SERVICES_JSON = json.dumps([
    {
        "service_name": "hrb-chatbot",
        "display_name": "Chatbot Backend",
        "arn": "arn:aws:apprunner:us-east-1:111111111111:service/hrb-chatbot/abc",
        "public_url": "https://hrb-chatbot.rvsree.dev",
    },
    {
        "service_name": "hrb-lms-mcp",
        "display_name": "MCP Server",
        "arn": "arn:aws:apprunner:us-east-1:111111111111:service/hrb-lms-mcp/def",
        "public_url": "https://hrb-lms-mcp.rvsree.dev",
    },
])


class _FakeBoto3AppRunnerClient:
    def __init__(self, responses=None, raise_for=None):
        self.responses = responses or {}
        self.raise_for = raise_for or {}
        self.calls = []

    def describe_service(self, ServiceArn):
        self.calls.append(("describe_service", ServiceArn))
        if ServiceArn in self.raise_for:
            raise self.raise_for[ServiceArn]
        return {"Service": {"Status": self.responses.get(ServiceArn, "RUNNING")}}

    def resume_service(self, ServiceArn):
        self.calls.append(("resume_service", ServiceArn))
        if ServiceArn in self.raise_for:
            raise self.raise_for[ServiceArn]
        return {"Service": {"Status": "OPERATION_IN_PROGRESS"}}

    def pause_service(self, ServiceArn):
        self.calls.append(("pause_service", ServiceArn))
        if ServiceArn in self.raise_for:
            raise self.raise_for[ServiceArn]
        return {"Service": {"Status": "OPERATION_IN_PROGRESS"}}


def _build_client(monkeypatch, fake_boto3_client):
    monkeypatch.setattr(apprunner_client_module.boto3, "client", lambda *a, **kw: fake_boto3_client)
    return AppRunnerClient(services_json=_SERVICES_JSON)


def test_describe_all_reports_every_configured_service(monkeypatch):
    fake = _FakeBoto3AppRunnerClient(responses={
        "arn:aws:apprunner:us-east-1:111111111111:service/hrb-chatbot/abc": "RUNNING",
        "arn:aws:apprunner:us-east-1:111111111111:service/hrb-lms-mcp/def": "PAUSED",
    })
    client = _build_client(monkeypatch, fake)

    statuses = client.describe_all()

    assert len(statuses) == 2
    assert statuses[0]["service_name"] == "hrb-chatbot"
    assert statuses[0]["status"] == "RUNNING"
    assert statuses[0]["url"] == "https://hrb-chatbot.rvsree.dev"
    assert statuses[1]["status"] == "PAUSED"
    assert statuses[1]["url"] is None  # not RUNNING - url withheld


def test_describe_one_service_failing_does_not_block_the_others(monkeypatch):
    fake = _FakeBoto3AppRunnerClient(
        raise_for={"arn:aws:apprunner:us-east-1:111111111111:service/hrb-chatbot/abc": RuntimeError("AccessDenied")}
    )
    client = _build_client(monkeypatch, fake)

    statuses = client.describe_all()

    assert statuses[0]["status"] == "ERROR"
    assert "AccessDenied" in statuses[0]["error"]
    assert statuses[1]["status"] == "RUNNING"  # the other service still reported normally


def test_resume_with_no_service_names_targets_all_configured_services(monkeypatch):
    fake = _FakeBoto3AppRunnerClient()
    client = _build_client(monkeypatch, fake)

    statuses = client.resume()

    assert len(statuses) == 2
    assert all(s["status"] == "OPERATION_IN_PROGRESS" for s in statuses)
    assert {call[0] for call in fake.calls} == {"resume_service"}


def test_resume_with_specific_service_names_targets_only_those(monkeypatch):
    fake = _FakeBoto3AppRunnerClient()
    client = _build_client(monkeypatch, fake)

    statuses = client.resume(service_names=["hrb-chatbot"])

    assert len(statuses) == 1
    assert statuses[0]["service_name"] == "hrb-chatbot"
    assert len(fake.calls) == 1


def test_unknown_service_name_is_silently_ignored(monkeypatch):
    fake = _FakeBoto3AppRunnerClient()
    client = _build_client(monkeypatch, fake)

    statuses = client.resume(service_names=["does-not-exist"])

    assert statuses == []
    assert fake.calls == []


def test_invalid_config_json_results_in_zero_services(monkeypatch):
    monkeypatch.setattr(apprunner_client_module.boto3, "client", lambda *a, **kw: _FakeBoto3AppRunnerClient())

    client = AppRunnerClient(services_json="not valid json")

    assert client.services == []
    assert client.describe_all() == []
