"""Tests for POST /v1/faq/submit, GET /v1/faq/published (Phase 186) -
run_agent() and the DB store are faked, no real LLM/network/database call."""

import asyncio

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.faq import faq_submission
from src.hrb_chatbot.main import app
from tests.conftest import FakeDBGateway, FakeFaqSubmissionStore

client = TestClient(app)

EMPLOYEE_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}


def test_submit_returns_the_first_pass_answer(monkeypatch):
    async def _fake_run_agent(query, employee_id, enable_conversation_memory=False):
        return {"answer": "Based on the knowledge base, yes it covers certifications."}

    monkeypatch.setattr(faq_submission, "run_agent", _fake_run_agent)
    store = FakeFaqSubmissionStore()
    monkeypatch.setattr(faq_submission, "get_db_gateway", lambda: FakeDBGateway(faq_submission_store=store))

    response = client.post(
        "/v1/faq/submit",
        json={"user_profile": EMPLOYEE_PROFILE, "query": "Does tuition reimbursement cover certifications?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["external_llm_answer"] == "Based on the knowledge base, yes it covers certifications."
    assert body["internal_review_status"] == "pending"
    assert body["published"] is False


def test_submit_still_saves_the_question_when_the_first_pass_answer_fails(monkeypatch):
    async def _failing_run_agent(query, employee_id, enable_conversation_memory=False):
        raise ConnectionError("LLM unreachable")

    monkeypatch.setattr(faq_submission, "run_agent", _failing_run_agent)
    store = FakeFaqSubmissionStore()
    monkeypatch.setattr(faq_submission, "get_db_gateway", lambda: FakeDBGateway(faq_submission_store=store))

    response = client.post("/v1/faq/submit", json={"user_profile": EMPLOYEE_PROFILE, "query": "What's the 401k match?"})

    assert response.status_code == 200
    body = response.json()
    assert body["external_llm_answer"] is None
    assert body["query"] == "What's the 401k match?"


def test_published_list_only_shows_published_faqs(monkeypatch):
    store = FakeFaqSubmissionStore()

    async def _seed():
        await store.create_submission("EMP052", "Q1", "A1")
        row2 = await store.create_submission("EMP052", "Q2", "A2")
        await store.review_submission(row2["id"], "approved", "Published answer", True, "ADM001", "finalized")

    asyncio.run(_seed())
    monkeypatch.setattr(faq_submission, "get_db_gateway", lambda: FakeDBGateway(faq_submission_store=store))

    response = client.get("/v1/faq/published", params=EMPLOYEE_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["faqs"][0]["query"] == "Q2"
    assert body["faqs"][0]["final_answer"] == "Published answer"
