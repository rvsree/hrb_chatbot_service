"""Tests for POST /v1/adhoc-document-chat/query (Phase 136) - the agent and
guardrails are faked (no real LLM call), matching every other route test in
this project. extract_text() runs for real against small, real-shaped bytes
- it's pure, local, no network. Phase 163: the route now also calls
get_db_gateway().chat_workflow_store() for session memory - faked via
FakeDBGateway for every test here, same reasoning as every other route
test that touches a store (confirmed real need, not precautionary: this
route would otherwise hit a real Postgres connection on every test)."""

import json

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.adhoc_chat import adhoc_document_chat
from src.hrb_chatbot.main import app
from tests.conftest import FakeDBGateway

client = TestClient(app)

EMPLOYEE_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}


def _patch_guardrails_and_agent(monkeypatch, agent_result=None):
    async def _passthrough_check_input(query):
        return query, {"status": "pass", "rail": None}

    async def _passthrough_check_output(query, answer):
        return answer, {"status": "pass", "rail": None}

    async def _fake_run_agent(question, file_texts, file_bytes, chat_history=None):
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
    monkeypatch.setattr(adhoc_document_chat, "get_db_gateway", lambda: FakeDBGateway())


def _post(
    question="What's in this file?",
    files=None,
    recipient_email=None,
    profile=None,
    session_id=None,
    send_email_on_answer=None,
    cc_email=None,
):
    data = {"user_profile": json.dumps(profile or EMPLOYEE_PROFILE), "question": question}
    if recipient_email:
        data["recipient_email"] = recipient_email
    if session_id:
        data["session_id"] = session_id
    if send_email_on_answer is not None:
        data["send_email_on_answer"] = str(send_email_on_answer).lower()
    if cc_email:
        data["cc_email"] = cc_email
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


# Phase 161 - email_evidence round-trips through the route's own response
# model, sent or failed, so a failed send is visible instead of
# indistinguishable from "no email asked for at all".


def test_email_evidence_is_surfaced_for_a_successful_send(monkeypatch):
    _patch_guardrails_and_agent(
        monkeypatch,
        agent_result={
            "answer": "Done.",
            "files_used": ["a.csv"],
            "web_searches": [],
            "email_sent_to": "someone@example.com",
            "email_evidence": {
                "recipient_email": "someone@example.com",
                "subject": "Your Accenture Offer Summary",
                "sent": True,
                "message": "Email sent to someone@example.com.",
                "attached_files": [],
                "sent_at": "2026-10-11T20:00:00+00:00",
            },
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
    evidence = response.json()["email_evidence"]
    assert evidence["sent"] is True
    assert evidence["recipient_email"] == "someone@example.com"
    assert evidence["subject"] == "Your Accenture Offer Summary"
    assert evidence["sent_at"] == "2026-10-11T20:00:00+00:00"


def test_email_evidence_is_surfaced_for_a_failed_send(monkeypatch):
    _patch_guardrails_and_agent(
        monkeypatch,
        agent_result={
            "answer": "Done.",
            "files_used": ["a.csv"],
            "web_searches": [],
            "email_sent_to": None,
            "email_evidence": {
                "recipient_email": "someone@example.com",
                "subject": "Your Accenture Offer Summary",
                "sent": False,
                "message": "SES_SENDER_EMAIL is not configured.",
                "attached_files": [],
                "sent_at": "2026-10-11T20:00:00+00:00",
            },
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
    body = response.json()
    assert body["email_sent_to"] is None
    evidence = body["email_evidence"]
    assert evidence["sent"] is False
    assert evidence["message"] == "SES_SENDER_EMAIL is not configured."


def test_email_evidence_is_none_when_no_email_was_requested(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    response = _post(question="What's in this file?", files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))])

    assert response.status_code == 200
    assert response.json()["email_evidence"] is None


# Phase 159 - the recipient-email field is sticky across turns in the UI,
# so what gets appended to the agent's question must stay purely
# informational, never a directive - a directive gets appended to every
# later, unrelated turn too, and the model mostly complies with it
# regardless of what that turn's own question actually says (confirmed
# live: an unconditional "please email the answer" caused a send on an
# unrelated follow-up question; an over-corrected conditional directive
# then caused the opposite failure, silently not sending on 2 of 3
# explicit "email it to me" requests - both confirmed by live
# reproduction, not assumed).


def test_recipient_email_is_appended_informationally_not_as_a_directive(monkeypatch):
    captured_questions = []

    async def _capturing_run_agent(question, file_texts, file_bytes, chat_history=None):
        captured_questions.append(question)
        return {
            "answer": "Done.",
            "files_used": [],
            "web_searches": [],
            "email_sent_to": None,
            "model_used": "gpt-4.1-mini-fake",
            "iterations": 1,
            "llm_call_count": 1,
            "token_usage": None,
            "latency_ms": {"total": 100.0},
        }

    _patch_guardrails_and_agent(monkeypatch)
    monkeypatch.setattr(adhoc_document_chat.adhoc_document_agent, "run_agent", _capturing_run_agent)

    _post(
        question="did you sent the email to given id",
        files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
        recipient_email="someone@example.com",
    )

    sent_question = captured_questions[0]
    assert "someone@example.com" in sent_question
    assert "please email" not in sent_question.lower()
    assert "do not send" not in sent_question.lower()


def test_no_recipient_email_leaves_the_question_unchanged(monkeypatch):
    captured_questions = []

    async def _capturing_run_agent(question, file_texts, file_bytes, chat_history=None):
        captured_questions.append(question)
        return {
            "answer": "Done.",
            "files_used": [],
            "web_searches": [],
            "email_sent_to": None,
            "model_used": "gpt-4.1-mini-fake",
            "iterations": 1,
            "llm_call_count": 1,
            "token_usage": None,
            "latency_ms": {"total": 100.0},
        }

    _patch_guardrails_and_agent(monkeypatch)
    monkeypatch.setattr(adhoc_document_chat.adhoc_document_agent, "run_agent", _capturing_run_agent)

    _post(question="What's in this file?", files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))])

    assert captured_questions[0] == "What's in this file?"


# Phase 163 - session memory: session_id is always returned, reused when
# sent back, and prior turns get loaded into chat_history for the agent.


def test_session_id_is_always_returned_even_when_not_sent(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    response = _post(files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))])

    assert response.status_code == 200
    assert response.json()["session_id"]


def test_a_sent_session_id_is_echoed_back_unchanged(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    response = _post(files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))], session_id="my-existing-session")

    assert response.json()["session_id"] == "my-existing-session"


def test_prior_turns_are_loaded_into_chat_history_when_a_session_id_is_sent(monkeypatch):
    captured_chat_history = []

    async def _capturing_run_agent(question, file_texts, file_bytes, chat_history=None):
        captured_chat_history.append(chat_history)
        return {
            "answer": "Done.",
            "files_used": [],
            "web_searches": [],
            "email_sent_to": None,
            "email_evidence": None,
            "model_used": "gpt-4.1-mini-fake",
            "iterations": 1,
            "llm_call_count": 1,
            "token_usage": None,
            "latency_ms": {"total": 100.0},
        }

    from tests.conftest import FakeChatWorkflowStore, FakeDBGateway

    store = FakeChatWorkflowStore()
    store._turns["existing-session"] = [
        {"turn_id": 1, "employee_id": "EMP052", "user_query_text": "What's the salary?", "agent_response_text": "$145,000."}
    ]

    _patch_guardrails_and_agent(monkeypatch)
    monkeypatch.setattr(adhoc_document_chat.adhoc_document_agent, "run_agent", _capturing_run_agent)
    monkeypatch.setattr(adhoc_document_chat, "get_db_gateway", lambda: FakeDBGateway(chat_workflow_store=store))

    _post(
        question="And the start date?",
        files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
        session_id="existing-session",
    )

    history = captured_chat_history[0]
    assert len(history) == 2
    assert history[0].content == "What's the salary?"
    assert history[1].content == "$145,000."


def test_no_session_id_sent_means_no_prior_history_is_loaded(monkeypatch):
    captured_chat_history = []

    async def _capturing_run_agent(question, file_texts, file_bytes, chat_history=None):
        captured_chat_history.append(chat_history)
        return {
            "answer": "Done.",
            "files_used": [],
            "web_searches": [],
            "email_sent_to": None,
            "email_evidence": None,
            "model_used": "gpt-4.1-mini-fake",
            "iterations": 1,
            "llm_call_count": 1,
            "token_usage": None,
            "latency_ms": {"total": 100.0},
        }

    _patch_guardrails_and_agent(monkeypatch)
    monkeypatch.setattr(adhoc_document_chat.adhoc_document_agent, "run_agent", _capturing_run_agent)

    _post(question="Summarize this", files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))])

    assert captured_chat_history[0] == []


# Phase 163 - the checkbox-driven email path, deliberately separate code
# from the agent's own in-text SendEmailWithAnswer decision (already
# covered by test_email_sent_to_is_surfaced_when_the_agent_actually_sent_one
# and friends, above).


def test_checkbox_email_requires_a_recipient(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    response = _post(
        files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
        send_email_on_answer=True,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_checkbox_email_rejects_an_invalid_cc_address(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    response = _post(
        files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
        recipient_email="someone@example.com",
        send_email_on_answer=True,
        cc_email="not-an-email",
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_checkbox_email_sends_via_send_email_and_surfaces_as_checkbox_auto(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)
    captured_calls = []

    def _fake_send_email(recipient_email, subject, body_text, attachments=None, html_body=None, cc_addresses=None):
        captured_calls.append({"recipient_email": recipient_email, "subject": subject, "cc_addresses": cc_addresses})
        return {"sent": True, "message": f"Email sent to {recipient_email}."}

    monkeypatch.setattr(adhoc_document_chat, "send_email", _fake_send_email)

    response = _post(
        files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
        recipient_email="someone@example.com",
        send_email_on_answer=True,
        cc_email="cc1@example.com, cc2@example.com",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email_sent_to"] == "someone@example.com"
    assert body["email_evidence"]["sent"] is True
    assert body["email_evidence"]["recipient_email"] == "someone@example.com"
    assert captured_calls[0]["cc_addresses"] == ["cc1@example.com", "cc2@example.com"]


def test_checkbox_email_failure_is_still_surfaced_as_evidence(monkeypatch):
    _patch_guardrails_and_agent(monkeypatch)

    def _failing_send_email(recipient_email, subject, body_text, attachments=None, html_body=None, cc_addresses=None):
        return {"sent": False, "message": "SES_SENDER_EMAIL is not configured."}

    monkeypatch.setattr(adhoc_document_chat, "send_email", _failing_send_email)

    response = _post(
        files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
        recipient_email="someone@example.com",
        send_email_on_answer=True,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email_sent_to"] is None
    assert body["email_evidence"]["sent"] is False
    assert body["email_evidence"]["message"] == "SES_SENDER_EMAIL is not configured."


def test_checkbox_auto_evidence_takes_priority_over_model_decision_when_both_fire(monkeypatch):
    agent_result = {
        "answer": "The summary.",
        "files_used": [],
        "web_searches": [],
        "email_sent_to": "model-chosen@example.com",
        "email_evidence": {
            "recipient_email": "model-chosen@example.com",
            "subject": "Model subject",
            "sent": True,
            "message": "Email sent to model-chosen@example.com.",
            "attached_files": [],
            "sent_at": "2026-10-12T00:00:00+00:00",
        },
        "model_used": "gpt-4.1-mini-fake",
        "iterations": 2,
        "llm_call_count": 2,
        "token_usage": None,
        "latency_ms": {"total": 100.0},
    }
    _patch_guardrails_and_agent(monkeypatch, agent_result=agent_result)

    def _fake_send_email(recipient_email, subject, body_text, attachments=None, html_body=None, cc_addresses=None):
        return {"sent": True, "message": f"Email sent to {recipient_email}."}

    monkeypatch.setattr(adhoc_document_chat, "send_email", _fake_send_email)

    response = _post(
        files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))],
        recipient_email="checkbox-chosen@example.com",
        send_email_on_answer=True,
    )

    body = response.json()
    # The checkbox-driven evidence wins in the response - the more
    # deterministic, explicitly-requested one - even though the model's own
    # decision also fired this turn.
    assert body["email_evidence"]["recipient_email"] == "checkbox-chosen@example.com"


# Phase 163 - both of these are regression tests for real bugs a live,
# 2-turn local test caught before this shipped (not theoretical): (1) a
# prior turn's own "...also send email..." phrasing, once sitting in
# chat_history, made the model re-attempt a send on a later, unrelated
# turn - even to the literal text "given id" from the original question.
# (2) a later "did you send it?" turn had no way to know an earlier
# email actually succeeded, since chat_history only ever carried the
# plain answer text - the model said "I have not sent any email yet",
# the exact bug from the user's own original production report,
# reintroduced by memory itself. The user's own explicit instruction
# ("I will run chatbot in local and test... this has never worked in
# local and AWS") is exactly why these were caught before shipping.


def test_stored_turn_text_notes_a_successful_email_for_later_turns_to_see(monkeypatch):
    from tests.conftest import FakeChatWorkflowStore, FakeDBGateway

    agent_result = {
        "answer": "Here is the summary.",
        "files_used": [],
        "web_searches": [],
        "email_sent_to": "someone@example.com",
        "email_evidence": {
            "recipient_email": "someone@example.com",
            "subject": "Your summary",
            "sent": True,
            "message": "Email sent to someone@example.com.",
            "attached_files": [],
            "sent_at": "2026-10-12T00:00:00+00:00",
        },
        "model_used": "gpt-4.1-mini-fake",
        "iterations": 2,
        "llm_call_count": 2,
        "token_usage": None,
        "latency_ms": {"total": 100.0},
    }
    _patch_guardrails_and_agent(monkeypatch, agent_result=agent_result)
    store = FakeChatWorkflowStore()
    monkeypatch.setattr(adhoc_document_chat, "get_db_gateway", lambda: FakeDBGateway(chat_workflow_store=store))

    response = _post(files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))], recipient_email="someone@example.com")

    assert response.status_code == 200
    # The user-facing answer is unchanged - the note is in what's stored for
    # chat_history reconstruction, never shown to the user directly.
    assert response.json()["answer"] == "Here is the summary."
    stored_text = list(store._turns.values())[0][0]["agent_response_text"]
    assert "successfully sent to someone@example.com" in stored_text


def test_stored_turn_text_notes_a_failed_email_for_later_turns_to_see(monkeypatch):
    from tests.conftest import FakeChatWorkflowStore, FakeDBGateway

    agent_result = {
        "answer": "Here is the summary.",
        "files_used": [],
        "web_searches": [],
        "email_sent_to": None,
        "email_evidence": {
            "recipient_email": "someone@example.com",
            "subject": "Your summary",
            "sent": False,
            "message": "SES_SENDER_EMAIL is not configured.",
            "attached_files": [],
            "sent_at": "2026-10-12T00:00:00+00:00",
        },
        "model_used": "gpt-4.1-mini-fake",
        "iterations": 2,
        "llm_call_count": 2,
        "token_usage": None,
        "latency_ms": {"total": 100.0},
    }
    _patch_guardrails_and_agent(monkeypatch, agent_result=agent_result)
    store = FakeChatWorkflowStore()
    monkeypatch.setattr(adhoc_document_chat, "get_db_gateway", lambda: FakeDBGateway(chat_workflow_store=store))

    _post(files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))], recipient_email="someone@example.com")

    stored_text = list(store._turns.values())[0][0]["agent_response_text"]
    assert "attempted this turn but failed" in stored_text
    assert "SES_SENDER_EMAIL is not configured" in stored_text


def test_stored_turn_text_has_no_email_note_when_no_email_was_attempted(monkeypatch):
    from tests.conftest import FakeChatWorkflowStore, FakeDBGateway

    _patch_guardrails_and_agent(monkeypatch)
    store = FakeChatWorkflowStore()
    monkeypatch.setattr(adhoc_document_chat, "get_db_gateway", lambda: FakeDBGateway(chat_workflow_store=store))

    _post(files=[("files", ("a.csv", b"a,b\n1,2", "text/csv"))])

    stored_text = list(store._turns.values())[0][0]["agent_response_text"]
    assert stored_text == "The answer."


def test_list_adhoc_sessions_returns_only_the_callers_own_sessions(monkeypatch):
    from tests.conftest import FakeChatWorkflowStore, FakeDBGateway

    store = FakeChatWorkflowStore()
    store._sessions["mine"] = {
        "session_id": "mine",
        "employee_id": "EMP052",
        "full_name": "Eddy Employee",
        "session_title": "My question",
        "started_at": "2026-10-10T00:00:00Z",
        "last_active": "2026-10-10T00:05:00Z",
        "turn_count_total": 2,
    }
    store._sessions["not-mine"] = {
        "session_id": "not-mine",
        "employee_id": "EMP999",
        "full_name": "Someone Else",
        "session_title": "Their question",
        "started_at": "2026-10-10T00:00:00Z",
        "last_active": "2026-10-10T00:05:00Z",
        "turn_count_total": 1,
    }
    monkeypatch.setattr(adhoc_document_chat, "get_db_gateway", lambda: FakeDBGateway(chat_workflow_store=store))

    response = client.get("/v1/adhoc-document-chat/sessions", params=EMPLOYEE_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["sessions"][0]["session_id"] == "mine"


def test_list_adhoc_sessions_requires_identity(monkeypatch):
    response = client.get("/v1/adhoc-document-chat/sessions")
    assert response.status_code == 401


def test_get_adhoc_session_returns_alternating_human_ai_turns(monkeypatch):
    from tests.conftest import FakeChatWorkflowStore, FakeDBGateway

    store = FakeChatWorkflowStore()
    store._sessions["mine"] = {
        "session_id": "mine",
        "employee_id": "EMP052",
        "full_name": "Eddy Employee",
        "session_title": "My question",
        "started_at": "2026-10-10T00:00:00Z",
        "last_active": "2026-10-10T00:05:00Z",
        "turn_count_total": 1,
    }
    store._turns["mine"] = [
        {
            "turn_id": 1,
            "employee_id": "EMP052",
            "user_query_text": "What's the salary?",
            "agent_response_text": "$145,000.",
            "created_at": "2026-10-10T00:00:00Z",
        }
    ]
    monkeypatch.setattr(adhoc_document_chat, "get_db_gateway", lambda: FakeDBGateway(chat_workflow_store=store))

    response = client.get("/v1/adhoc-document-chat/sessions/mine", params=EMPLOYEE_PROFILE)

    assert response.status_code == 200
    turns = response.json()["turns"]
    assert len(turns) == 2
    assert turns[0] == {"role": "human", "content": "What's the salary?", "created_at": "2026-10-10T00:00:00Z"}
    assert turns[1] == {"role": "ai", "content": "$145,000.", "created_at": "2026-10-10T00:00:00Z"}


def test_get_adhoc_session_strips_the_internal_system_note_from_ai_turns(monkeypatch):
    """Regression test - found live, not by this test suite first: the stored
    agent_response_text carries a trailing [System note: ...] block purely
    for a later turn's own chat_history to read, never meant for a person to
    see. The sidebar history view must strip it."""
    from tests.conftest import FakeChatWorkflowStore, FakeDBGateway

    store = FakeChatWorkflowStore()
    store._sessions["mine"] = {
        "session_id": "mine",
        "employee_id": "EMP052",
        "full_name": "Eddy Employee",
        "session_title": "My question",
        "started_at": "2026-10-10T00:00:00Z",
        "last_active": "2026-10-10T00:05:00Z",
        "turn_count_total": 1,
    }
    store._turns["mine"] = [
        {
            "turn_id": 1,
            "employee_id": "EMP052",
            "user_query_text": "Summarize and email it",
            "agent_response_text": (
                "Here is the summary.\n\n"
                "[System note: an email was successfully sent to a@example.com this turn.]"
            ),
            "created_at": "2026-10-10T00:00:00Z",
        }
    ]
    monkeypatch.setattr(adhoc_document_chat, "get_db_gateway", lambda: FakeDBGateway(chat_workflow_store=store))

    response = client.get("/v1/adhoc-document-chat/sessions/mine", params=EMPLOYEE_PROFILE)

    assert response.status_code == 200
    ai_turn = response.json()["turns"][1]
    assert ai_turn["content"] == "Here is the summary."
    assert "System note" not in ai_turn["content"]


def test_get_adhoc_session_not_owned_by_caller_returns_empty_turns(monkeypatch):
    from tests.conftest import FakeChatWorkflowStore, FakeDBGateway

    store = FakeChatWorkflowStore()
    store._sessions["not-mine"] = {
        "session_id": "not-mine",
        "employee_id": "EMP999",
        "full_name": "Someone Else",
        "session_title": "Their question",
        "started_at": "2026-10-10T00:00:00Z",
        "last_active": "2026-10-10T00:05:00Z",
        "turn_count_total": 1,
    }
    store._turns["not-mine"] = [
        {
            "turn_id": 1,
            "employee_id": "EMP999",
            "user_query_text": "Their question",
            "agent_response_text": "Their answer.",
            "created_at": "2026-10-10T00:00:00Z",
        }
    ]
    monkeypatch.setattr(adhoc_document_chat, "get_db_gateway", lambda: FakeDBGateway(chat_workflow_store=store))

    response = client.get("/v1/adhoc-document-chat/sessions/not-mine", params=EMPLOYEE_PROFILE)

    assert response.status_code == 200
    assert response.json()["turns"] == []
