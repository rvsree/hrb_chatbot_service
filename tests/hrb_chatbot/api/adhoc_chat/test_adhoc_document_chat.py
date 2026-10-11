"""Tests for POST /v1/adhoc-document-chat/query (Phase 136) - the agent and
guardrails are faked (no real LLM call), matching every other route test in
this project. extract_text() runs for real against small, real-shaped bytes
- it's pure, local, no network."""

import json

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.adhoc_chat import adhoc_document_chat
from src.hrb_chatbot.main import app

client = TestClient(app)

EMPLOYEE_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}


def _patch_guardrails_and_agent(monkeypatch, agent_result=None):
    async def _passthrough_check_input(query):
        return query

    async def _passthrough_check_output(query, answer):
        return answer

    async def _fake_run_agent(question, file_texts, file_bytes):
        return agent_result or {
            "answer": "The answer.",
            "files_used": list(file_texts.keys()),
            "web_searches": [],
            "email_sent_to": None,
            "model_used": "gpt-4.1-mini-fake",
            "iterations": 1,
            "llm_call_count": 1,
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "latency_ms": {"total": 100.0},
        }

    monkeypatch.setattr(adhoc_document_chat, "check_input", _passthrough_check_input)
    monkeypatch.setattr(adhoc_document_chat, "check_output", _passthrough_check_output)
    monkeypatch.setattr(adhoc_document_chat.adhoc_document_agent, "run_agent", _fake_run_agent)


def _post(question="What's in this file?", files=None, recipient_email=None, profile=None):
    data = {"user_profile": json.dumps(profile or EMPLOYEE_PROFILE), "question": question}
    if recipient_email:
        data["recipient_email"] = recipient_email
    return client.post("/v1/adhoc-document-chat/query", data=data, files=files or [])


def test_a_real_csv_file_gets_a_real_answer(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    response = _post(files=[("files", ("team.csv", b"name,role\nAlice,Manager\n", "text/csv"))])

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "The answer."
    assert body["files_used"] == ["team.csv"]


def test_an_unsupported_file_extension_is_rejected_with_422(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    response = _post(files=[("files", ("malware.exe", b"junk", "application/octet-stream"))])

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_FILE_TYPE"


def test_more_than_three_files_is_rejected_with_422(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)
    many_files = [("files", (f"f{i}.csv", b"a,b\n1,2", "text/csv")) for i in range(4)]

    response = _post(files=many_files)

    assert response.status_code == 422
    assert "At most 3 files" in response.json()["error"]


def test_zero_files_is_rejected_with_422(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    response = _post(files=[])

    assert response.status_code == 422


def test_a_file_over_the_size_limit_is_rejected_with_422(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)
    monkeypatch.setattr(adhoc_document_chat, "MAX_FILE_SIZE_BYTES", 10)

    response = _post(files=[("files", ("big.csv", b"a,b\n1,2\n3,4\n", "text/csv"))])

    assert response.status_code == 422
    assert response.json()["code"] == "FILE_TOO_LARGE"


def test_malformed_user_profile_json_is_a_422_not_a_500(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    response = client.post(
        "/v1/adhoc-document-chat/query",
        data={"user_profile": "not valid json", "question": "test"},
        files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_all_three_roles_are_allowed(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)
    for role, name, emp_id in [("employee", "Eddy Employee", "EMP052"), ("manager", "Mia Manager", "EMP053"), ("hr_support", "Hana Support", "EMP051")]:
        response = _post(
            files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
            profile={"employee_id": emp_id, "full_name": name, "role": role},
        )
        assert response.status_code == 200, f"role {role} was rejected"


def test_a_file_whose_content_trips_the_input_guardrail_is_rejected_with_422(monkeypatch):
    from src.hrb_chatbot.ai.pre_processing.guardrails_input import GuardrailBlockedError

    async def _blocking_check_input(query):
        if "DANGEROUS" in query:
            raise GuardrailBlockedError("jailbreak attempt detected")
        return query

    _patch_guardrails_and_agent(monkeypatch)
    monkeypatch.setattr(adhoc_document_chat, "check_input", _blocking_check_input)

    response = _post(files=[("files", ("bad.csv", b"DANGEROUS,content\n1,2", "text/csv"))])

    assert response.status_code == 422
    assert response.json()["code"] == "INPUT_GUARDRAIL_BLOCKED"
    assert "bad.csv" in response.json()["error"]


def test_email_sent_to_is_surfaced_when_the_agent_actually_sent_one(monkeypatch):
    _patch_guardrails_and_agent(
        monkeypatch,
        agent_result={
            "answer": "Done.",
            "files_used": ["a.csv"],
            "web_searches": [],
            "email_sent_to": "someone@example.com",
            "model_used": "gpt-4.1-mini-fake",
            "iterations": 2,
            "llm_call_count": 2,
            "token_usage": None,
            "latency_ms": {"total": 100.0},
        },
    )

    response = _post(
        question="Email me the answer",
        files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
        recipient_email="someone@example.com",
    )

    assert response.status_code == 200
    assert response.json()["email_sent_to"] == "someone@example.com"
