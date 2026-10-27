"""Tests for POST/GET /v1/feedback (Phase 104) - FeedbackStore is faked via
FakeDBGateway, no real Postgres, matching this project's zero-network-call
test guarantee."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.feedback import manage_feedback
from src.hrb_chatbot.main import app
from tests.conftest import FakeDBGateway, FakeFeedbackStore

client = TestClient(app)

EMPLOYEE_USER_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}
OTHER_EMPLOYEE_USER_PROFILE = {"employee_id": "EMP099", "full_name": "Olivia Other", "role": "employee"}
HR_USER_PROFILE = {"employee_id": "EMP001", "full_name": "Hannah HR", "role": "hr_support"}


def _create_body(user_profile=None, **overrides) -> dict:
    body = {
        "user_profile": EMPLOYEE_USER_PROFILE if user_profile is None else user_profile,
        "conversation_id": "conv-1",
        "message_id": "msg-1",
        "vote": "helpful",
        "reason_tags": ["accurate"],
        "notes": None,
        "question": "What dental plans are offered?",
        "answer": "Amazing Bank offers two dental plan options.",
    }
    body.update(overrides)
    return body


def test_create_feedback_returns_a_new_id(monkeypatch):
    gateway = FakeDBGateway(feedback_store=FakeFeedbackStore())
    monkeypatch.setattr(manage_feedback, "get_db_gateway", lambda: gateway)

    response = client.post("/v1/feedback", json=_create_body())

    assert response.status_code == 200
    assert response.json() == {"id": 1}


def test_create_feedback_missing_user_profile_is_401(monkeypatch):
    gateway = FakeDBGateway(feedback_store=FakeFeedbackStore())
    monkeypatch.setattr(manage_feedback, "get_db_gateway", lambda: gateway)

    body = _create_body()
    body["user_profile"] = None

    response = client.post("/v1/feedback", json=body)

    assert response.status_code == 401


def test_list_feedback_scopes_an_employee_to_their_own(monkeypatch):
    feedback_store = FakeFeedbackStore()
    gateway = FakeDBGateway(feedback_store=feedback_store)
    monkeypatch.setattr(manage_feedback, "get_db_gateway", lambda: gateway)

    client.post("/v1/feedback", json=_create_body(user_profile=EMPLOYEE_USER_PROFILE))
    client.post("/v1/feedback", json=_create_body(user_profile=OTHER_EMPLOYEE_USER_PROFILE))

    response = client.get("/v1/feedback", params=EMPLOYEE_USER_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["feedback"][0]["employee_id"] == "EMP052"


def test_list_feedback_hr_support_sees_everyone(monkeypatch):
    feedback_store = FakeFeedbackStore()
    gateway = FakeDBGateway(feedback_store=feedback_store)
    monkeypatch.setattr(manage_feedback, "get_db_gateway", lambda: gateway)

    client.post("/v1/feedback", json=_create_body(user_profile=EMPLOYEE_USER_PROFILE))
    client.post("/v1/feedback", json=_create_body(user_profile=OTHER_EMPLOYEE_USER_PROFILE))

    response = client.get("/v1/feedback", params=HR_USER_PROFILE)

    assert response.status_code == 200
    assert response.json()["count"] == 2


def test_list_feedback_missing_identity_is_401(monkeypatch):
    gateway = FakeDBGateway(feedback_store=FakeFeedbackStore())
    monkeypatch.setattr(manage_feedback, "get_db_gateway", lambda: gateway)

    response = client.get("/v1/feedback")

    assert response.status_code == 401
