"""Tests for GET/POST /v1/admin/aws-demo/* (Phase 261) - AppRunnerClient is
faked, no real boto3/AWS call, matching every other route test in this
project."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.admin import manage_admin
from src.hrb_chatbot.main import app

client = TestClient(app)

ADMIN_PROFILE = {"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin"}
EMPLOYEE_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}

_ONE_SERVICE = {
    "service_name": "hrb-chatbot",
    "display_name": "Chatbot Backend",
    "status": "RUNNING",
    "url": "https://hrb-chatbot.rvsree.dev",
    "error": None,
}


class _FakeAppRunnerClient:
    def __init__(self, *args, **kwargs):
        pass

    def describe_all(self):
        return [_ONE_SERVICE]

    def resume(self, service_names=None):
        return [{**_ONE_SERVICE, "status": "OPERATION_IN_PROGRESS", "url": None}]

    def pause(self, service_names=None):
        return [{**_ONE_SERVICE, "status": "OPERATION_IN_PROGRESS", "url": None}]


class _FailingAppRunnerClient:
    def __init__(self, *args, **kwargs):
        pass

    def describe_all(self):
        return [{**_ONE_SERVICE, "status": "ERROR", "url": None, "error": "boto3 ClientError: AccessDenied"}]

    def resume(self, service_names=None):
        return self.describe_all()

    def pause(self, service_names=None):
        return self.describe_all()


def test_non_admin_cannot_view_aws_demo_status():
    response = client.get("/v1/admin/aws-demo/status", params=EMPLOYEE_PROFILE)
    assert response.status_code == 403


def test_non_admin_cannot_resume_aws_demo_services():
    response = client.post("/v1/admin/aws-demo/resume", json={"user_profile": EMPLOYEE_PROFILE})
    assert response.status_code == 403


def test_get_aws_demo_status_returns_live_service_list(monkeypatch):
    monkeypatch.setattr(manage_admin, "AppRunnerClient", _FakeAppRunnerClient)

    response = client.get("/v1/admin/aws-demo/status", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["services"][0]["service_name"] == "hrb-chatbot"
    assert body["services"][0]["status"] == "RUNNING"


def test_resume_aws_demo_services_returns_in_progress_state(monkeypatch):
    monkeypatch.setattr(manage_admin, "AppRunnerClient", _FakeAppRunnerClient)

    response = client.post("/v1/admin/aws-demo/resume", json={"user_profile": ADMIN_PROFILE})

    assert response.status_code == 200
    body = response.json()
    assert body["services"][0]["status"] == "OPERATION_IN_PROGRESS"
    assert body["services"][0]["url"] is None


def test_pause_aws_demo_services_returns_in_progress_state(monkeypatch):
    monkeypatch.setattr(manage_admin, "AppRunnerClient", _FakeAppRunnerClient)

    response = client.post("/v1/admin/aws-demo/pause", json={"user_profile": ADMIN_PROFILE})

    assert response.status_code == 200
    assert response.json()["services"][0]["status"] == "OPERATION_IN_PROGRESS"


def test_aws_demo_status_surfaces_a_per_service_error_without_a_500(monkeypatch):
    monkeypatch.setattr(manage_admin, "AppRunnerClient", _FailingAppRunnerClient)

    response = client.get("/v1/admin/aws-demo/status", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["services"][0]["status"] == "ERROR"
    assert "AccessDenied" in body["services"][0]["error"]


def test_resume_aws_demo_services_with_specific_service_names(monkeypatch):
    captured = {}

    class _CapturingClient(_FakeAppRunnerClient):
        def resume(self, service_names=None):
            captured["service_names"] = service_names
            return [_ONE_SERVICE]

    monkeypatch.setattr(manage_admin, "AppRunnerClient", _CapturingClient)

    response = client.post(
        "/v1/admin/aws-demo/resume",
        json={"user_profile": ADMIN_PROFILE, "service_names": ["hrb-chatbot"]},
    )

    assert response.status_code == 200
    assert captured["service_names"] == ["hrb-chatbot"]
