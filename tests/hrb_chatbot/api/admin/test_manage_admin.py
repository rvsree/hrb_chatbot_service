"""Tests for GET/DELETE /v1/admin/* (Phase 168) - MCP calls and store calls
are faked, no real network/database call, matching every other route test
in this project."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.ai.pre_processing import conversation_memory as conversation_memory_module
from src.hrb_chatbot.api.admin import manage_admin
from src.hrb_chatbot.main import app
from tests.conftest import (
    FakeConversationStore,
    FakeDBGateway,
    FakeDocMetadataStore,
    FakeEvalRunStore,
    FakeFaqSubmissionStore,
    FakeFeedbackStore,
    FakeInterviewQaStore,
    FakePipelineRunStore,
)

client = TestClient(app)

ADMIN_PROFILE = {"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin"}
EMPLOYEE_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}
HR_PROFILE = {"employee_id": "EMP021", "full_name": "Daniel Rodriguez", "role": "hr_support"}


def test_non_admin_cannot_list_conversations(monkeypatch):
    response = client.get("/v1/admin/conversations", params=HR_PROFILE)
    assert response.status_code == 403


def test_non_admin_cannot_delete_a_conversation(monkeypatch):
    response = client.request(
        "DELETE", "/v1/admin/conversations/conv-1", json={"user_profile": EMPLOYEE_PROFILE}
    )
    assert response.status_code == 403


def test_admin_lists_every_employees_conversations(monkeypatch):
    store = FakeConversationStore()

    async def _seed():
        await store.save_turn("conv-1", "EMP052", "human", "What's my PTO balance?")
        await store.save_turn("conv-1", "EMP052", "ai", "You have 10 days.")
        await store.save_turn("conv-2", "EMP021", "human", "What's the dental plan?")
        await store.save_turn("conv-2", "EMP021", "ai", "We offer two plans.")

    import asyncio

    asyncio.run(_seed())
    monkeypatch.setattr(conversation_memory_module, "get_db_gateway", lambda: FakeDBGateway(conversation_store=store))

    response = client.get("/v1/admin/conversations", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    employee_ids = {c["employee_id"] for c in body["conversations"]}
    assert employee_ids == {"EMP052", "EMP021"}


def test_non_admin_cannot_get_a_conversation_transcript(monkeypatch):
    response = client.get("/v1/admin/conversations/conv-1", params=HR_PROFILE)
    assert response.status_code == 403


def test_admin_gets_the_full_transcript_for_any_employees_conversation(monkeypatch):
    store = FakeConversationStore()

    async def _seed():
        await store.save_turn("conv-1", "EMP052", "human", "What's my PTO balance?")
        await store.save_turn("conv-1", "EMP052", "ai", "You have 10 days.")

    import asyncio

    asyncio.run(_seed())
    monkeypatch.setattr(conversation_memory_module, "get_db_gateway", lambda: FakeDBGateway(conversation_store=store))

    response = client.get("/v1/admin/conversations/conv-1", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert len(body["turns"]) == 2
    assert body["turns"][0]["content"] == "What's my PTO balance?"
    assert body["turns"][1]["content"] == "You have 10 days."


def test_admin_deletes_any_employees_conversation(monkeypatch):
    store = FakeConversationStore()

    async def _seed():
        await store.save_turn("conv-1", "EMP052", "human", "hi")
        await store.save_turn("conv-1", "EMP052", "ai", "hello")

    import asyncio

    asyncio.run(_seed())
    monkeypatch.setattr(conversation_memory_module, "get_db_gateway", lambda: FakeDBGateway(conversation_store=store))

    response = client.request(
        "DELETE", "/v1/admin/conversations/conv-1", json={"user_profile": ADMIN_PROFILE}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["turns_deleted"] == 2
    assert store._turns.get("conv-1") is None


def test_non_admin_cannot_list_all_feedback(monkeypatch):
    response = client.get("/v1/admin/feedback", params=HR_PROFILE)
    assert response.status_code == 403


def test_admin_lists_all_feedback(monkeypatch):
    store = FakeFeedbackStore()

    async def _seed():
        await store.save_feedback("EMP052", None, "msg-1", "helpful", [], None, "q", "a")

    import asyncio

    asyncio.run(_seed())
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(feedback_store=store))

    response = client.get("/v1/admin/feedback", params=ADMIN_PROFILE)

    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_admin_deletes_a_feedback_entry(monkeypatch):
    store = FakeFeedbackStore()

    async def _seed():
        await store.save_feedback("EMP052", None, "msg-1", "helpful", [], None, "q", "a")

    import asyncio

    asyncio.run(_seed())
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(feedback_store=store))

    response = client.request("DELETE", "/v1/admin/feedback/1", json={"user_profile": ADMIN_PROFILE})

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert store._entries == []


def test_non_admin_cannot_list_all_leave_requests(monkeypatch):
    response = client.get("/v1/admin/leave-requests", params=HR_PROFILE)
    assert response.status_code == 403


def test_admin_lists_all_leave_requests_regardless_of_status(monkeypatch):
    async def _fake_call_mcp_tool_json(tool_name, arguments):
        assert tool_name == "list_hitl_requests"
        assert arguments == {"status": "all", "request_type": "UNPAID_LEAVE_REQUEST"}
        return {
            "total": 2,
            "requests": [
                {
                    "hitlRequestId": 1,
                    "requestType": "UNPAID_LEAVE_REQUEST",
                    "employeeId": "EMP052",
                    "query": "q1",
                    "context": {},
                    "status": "COMPLETED",
                    "assignedTo": "Daniel",
                    "createdAt": "2026-10-01T00:00:00",
                },
                {
                    "hitlRequestId": 2,
                    "requestType": "UNPAID_LEAVE_REQUEST",
                    "employeeId": "EMP001",
                    "query": "q2",
                    "context": {},
                    "status": "PENDING",
                    "assignedTo": None,
                    "createdAt": "2026-10-02T00:00:00",
                },
            ],
        }

    monkeypatch.setattr(manage_admin, "_call_mcp_tool_json", _fake_call_mcp_tool_json)

    response = client.get("/v1/admin/leave-requests", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    statuses = {r["status"] for r in body["requests"]}
    assert statuses == {"COMPLETED", "PENDING"}


def test_non_admin_cannot_delete_a_leave_request(monkeypatch):
    response = client.request(
        "DELETE", "/v1/admin/leave-requests/1", json={"user_profile": HR_PROFILE}
    )
    assert response.status_code == 403


def test_admin_deletes_a_leave_request_and_cleans_up_s3(monkeypatch):
    captured_s3_deletes = []

    async def _fake_admin_delete(hitl_request_context_id):
        assert hitl_request_context_id == 7
        return {
            "hitlRequestId": 7,
            "deletedHitlRequest": True,
            "deletedSpecialistLeaveReviews": 1,
            "deletedLeaveRequest": True,
            "deletedDocumentS3Keys": ["abc/doc.pdf"],
        }

    def _fake_delete_s3(s3_key):
        captured_s3_deletes.append(s3_key)

    monkeypatch.setattr(manage_admin, "admin_delete_hitl_request", _fake_admin_delete)
    monkeypatch.setattr(manage_admin, "delete_leave_document_object", _fake_delete_s3)

    response = client.request(
        "DELETE", "/v1/admin/leave-requests/7", json={"user_profile": ADMIN_PROFILE}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["deleted_leave_request"] is True
    assert body["deleted_document_count"] == 1
    assert captured_s3_deletes == ["abc/doc.pdf"]


def test_admin_delete_leave_request_still_succeeds_if_s3_cleanup_fails(monkeypatch):
    """Best-effort - the database-side delete already succeeded by the
    time S3 cleanup runs, so an S3 failure must not turn that into an error."""

    async def _fake_admin_delete(hitl_request_context_id):
        return {
            "hitlRequestId": hitl_request_context_id,
            "deletedHitlRequest": True,
            "deletedSpecialistLeaveReviews": 0,
            "deletedLeaveRequest": False,
            "deletedDocumentS3Keys": ["abc/doc.pdf"],
        }

    def _failing_delete_s3(s3_key):
        raise RuntimeError("S3 unavailable")

    monkeypatch.setattr(manage_admin, "admin_delete_hitl_request", _fake_admin_delete)
    monkeypatch.setattr(manage_admin, "delete_leave_document_object", _failing_delete_s3)

    response = client.request(
        "DELETE", "/v1/admin/leave-requests/9", json={"user_profile": ADMIN_PROFILE}
    )

    assert response.status_code == 200


def test_admin_delete_leave_request_failure_returns_a_clear_500(monkeypatch):
    async def _failing_admin_delete(hitl_request_context_id):
        raise RuntimeError("not found")

    monkeypatch.setattr(manage_admin, "admin_delete_hitl_request", _failing_admin_delete)

    response = client.request(
        "DELETE", "/v1/admin/leave-requests/404", json={"user_profile": ADMIN_PROFILE}
    )

    assert response.status_code == 500
    assert response.json()["code"] == "ADMIN_OPERATION_FAILED"


# Phase 170 (round 1) - the admin-only docs viewer.

_SAMPLE_DOC = {
    "id": 1,
    "feature_name": "request-unpaid-leave",
    "doc_title": "Leave Approval A2A",
    "doc_type": "design",
    "doc_version": 1,
    "s3_bucket": "hrb-chatbot-leave-docs-dev",
    "s3_key": "admin-docs/request-unpaid-leave.html",
    "source_local_path": "docs/dev-reference/leave-approval-a2a-design.html",
    "content_hash": "abc123",
    "created_at": "2026-10-12T00:00:00",
    "updated_at": "2026-10-12T00:00:00",
    "last_synced_at": "2026-10-12T00:00:00",
}


def test_non_admin_cannot_list_docs(monkeypatch):
    response = client.get("/v1/admin/docs", params=HR_PROFILE)
    assert response.status_code == 403


def test_admin_lists_synced_docs(monkeypatch):
    store = FakeDocMetadataStore(docs=[_SAMPLE_DOC])
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(doc_metadata_store=store))

    response = client.get("/v1/admin/docs", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["docs"][0]["feature_name"] == "request-unpaid-leave"


def test_non_admin_cannot_get_doc_content(monkeypatch):
    response = client.get("/v1/admin/docs/1/content", params=HR_PROFILE)
    assert response.status_code == 403


def test_get_doc_content_returns_a_presigned_url(monkeypatch):
    store = FakeDocMetadataStore(docs=[_SAMPLE_DOC])
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(doc_metadata_store=store))

    def _fake_generate(s3_key):
        assert s3_key == "admin-docs/request-unpaid-leave.html"
        return {"download_url": "https://example.com/presigned", "expires_in_seconds": 300}

    monkeypatch.setattr(manage_admin, "generate_admin_doc_download_url", _fake_generate)

    response = client.get("/v1/admin/docs/1/content", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["download_url"] == "https://example.com/presigned"


def test_get_doc_content_404_for_an_unknown_doc_id(monkeypatch):
    store = FakeDocMetadataStore(docs=[])
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(doc_metadata_store=store))

    response = client.get("/v1/admin/docs/999/content", params=ADMIN_PROFILE)

    assert response.status_code == 404
    assert response.json()["code"] == "ADMIN_DOC_NOT_FOUND"


def test_employee_cannot_list_faq_submissions(monkeypatch):
    response = client.get("/v1/admin/faq-submissions", params=EMPLOYEE_PROFILE)
    assert response.status_code == 403


def test_hr_support_lists_faq_submissions(monkeypatch):
    import asyncio

    store = FakeFaqSubmissionStore()

    async def _seed():
        await store.create_submission("EMP052", "Does tuition cover certifications?", "Yes, based on the KB.")

    asyncio.run(_seed())
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(faq_submission_store=store))

    response = client.get("/v1/admin/faq-submissions", params=HR_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["submissions"][0]["query"] == "Does tuition cover certifications?"


def test_restructure_calls_claude_and_stores_the_draft(monkeypatch):
    import asyncio

    store = FakeFaqSubmissionStore()

    async def _seed():
        return await store.create_submission("EMP052", "What's the 401k match?", "Raw first-pass answer.")

    submission = asyncio.run(_seed())
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(faq_submission_store=store))

    class _FakeAnthropicClient:
        def ask(self, question, context=None, system_prompt=None, temperature=0.0, max_tokens=None):
            return "Clean, restructured answer."

    class _FakeClientGateway:
        def anthropic_chat(self):
            return _FakeAnthropicClient()

    monkeypatch.setattr(manage_admin, "get_client_gateway", lambda: _FakeClientGateway())

    response = client.post(
        f"/v1/admin/faq-submissions/{submission['id']}/restructure", json={"user_profile": ADMIN_PROFILE}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["final_answer"] == "Clean, restructured answer."
    assert body["answer_restructuring_status"] == "claude_restructured"


def test_restructure_404_for_an_unknown_submission(monkeypatch):
    store = FakeFaqSubmissionStore()
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(faq_submission_store=store))

    response = client.post("/v1/admin/faq-submissions/999/restructure", json={"user_profile": ADMIN_PROFILE})

    assert response.status_code == 404
    assert response.json()["code"] == "ADMIN_FAQ_SUBMISSION_NOT_FOUND"


def test_review_publishes_and_records_the_reviewer(monkeypatch):
    import asyncio

    store = FakeFaqSubmissionStore()

    async def _seed():
        return await store.create_submission("EMP052", "What's the dental plan?", "Raw answer.")

    submission = asyncio.run(_seed())
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(faq_submission_store=store))

    response = client.post(
        f"/v1/admin/faq-submissions/{submission['id']}/review",
        json={
            "user_profile": ADMIN_PROFILE,
            "internal_review_status": "approved",
            "final_answer": "We offer two dental plans.",
            "published": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["published"] is True
    assert body["reviewed_by"] == "ADM001"
    assert body["answer_restructuring_status"] == "human_edited"


EMPLOYEE_ADMIN_PROFILE = {"employee_id": "ADM002", "full_name": "Erin Admin", "role": "employee_admin"}

_INTERVIEW_QA_FIELDS = {
    "topic": "Smoke Test",
    "topic_order": 1,
    "card_order": 1,
    "question": "Does CRUD work end to end?",
    "hint": "yes",
    "concept": None,
    "situation": None,
    "task": None,
    "action": None,
    "result": None,
    "project_link": None,
    "leadership_angle": None,
    "trade_offs": ["one"],
    "keywords": [{"term": "CRUD", "definition": "Create/Read/Update/Delete"}],
    "tech_stack": ["FastAPI"],
    "feature_references": [{"label": "store", "file_path": "src/hrb_chatbot/common/clients/db_client/interview_qa_store.py"}],
}


def test_employee_admin_cannot_list_interview_qa_cards(monkeypatch):
    """Interview Q&A is Engineering-Admin-only, unlike feedback/leave-
    requests - employee_admin gets 403 just like a plain employee does."""
    response = client.get("/v1/admin/interview-qa", params=EMPLOYEE_ADMIN_PROFILE)
    assert response.status_code == 403


def test_admin_lists_interview_qa_cards_filtered_by_topic(monkeypatch):
    import asyncio

    store = FakeInterviewQaStore()

    async def _seed():
        await store.create_card({**_INTERVIEW_QA_FIELDS, "topic": "Topic A"})
        await store.create_card({**_INTERVIEW_QA_FIELDS, "topic": "Topic B"})

    asyncio.run(_seed())
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(interview_qa_store=store))

    response = client.get("/v1/admin/interview-qa", params=ADMIN_PROFILE)
    assert response.status_code == 200
    assert response.json()["count"] == 2

    filtered = client.get("/v1/admin/interview-qa", params={**ADMIN_PROFILE, "topic": "Topic A"})
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["count"] == 1
    assert body["cards"][0]["topic"] == "Topic A"


def test_get_interview_qa_card_404_for_unknown_id(monkeypatch):
    store = FakeInterviewQaStore()
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(interview_qa_store=store))

    response = client.get("/v1/admin/interview-qa/999", params=ADMIN_PROFILE)

    assert response.status_code == 404
    assert response.json()["code"] == "ADMIN_INTERVIEW_QA_NOT_FOUND"


def test_create_update_and_delete_interview_qa_card(monkeypatch):
    store = FakeInterviewQaStore()
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(interview_qa_store=store))

    create_response = client.post(
        "/v1/admin/interview-qa", json={"user_profile": ADMIN_PROFILE, "fields": _INTERVIEW_QA_FIELDS}
    )
    assert create_response.status_code == 200
    card = create_response.json()
    assert card["question"] == "Does CRUD work end to end?"
    assert card["keywords"] == [{"term": "CRUD", "definition": "Create/Read/Update/Delete"}]

    updated_fields = {**_INTERVIEW_QA_FIELDS, "question": "Does CRUD work end to end - updated?"}
    update_response = client.put(
        f"/v1/admin/interview-qa/{card['id']}", json={"user_profile": ADMIN_PROFILE, "fields": updated_fields}
    )
    assert update_response.status_code == 200
    assert update_response.json()["question"] == "Does CRUD work end to end - updated?"

    delete_response = client.request(
        "DELETE", f"/v1/admin/interview-qa/{card['id']}", json={"user_profile": ADMIN_PROFILE}
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {"id": card["id"], "deleted": True}

    get_after_delete = client.get(f"/v1/admin/interview-qa/{card['id']}", params=ADMIN_PROFILE)
    assert get_after_delete.status_code == 404


def test_update_interview_qa_card_404_for_unknown_id(monkeypatch):
    store = FakeInterviewQaStore()
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(interview_qa_store=store))

    response = client.put(
        "/v1/admin/interview-qa/999", json={"user_profile": ADMIN_PROFILE, "fields": _INTERVIEW_QA_FIELDS}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ADMIN_INTERVIEW_QA_NOT_FOUND"


class _FakeGitHubActionsClient:
    """Phase 188 - controlled fixture data standing in for real GitHub
    Actions API responses, same never-raises shape as the real client."""

    def __init__(self, latest_sha="abc1234", runs=None, jobs_by_run_id=None, error=None):
        self.latest_sha = latest_sha
        self.runs = runs if runs is not None else []
        self.jobs_by_run_id = jobs_by_run_id or {}
        self.error = error

    def get_latest_run_sha(self):
        if self.error:
            return {"sha": None, "error": self.error}
        return {"sha": self.latest_sha, "error": None}

    def get_runs_for_sha(self, sha):
        if self.error:
            return {"runs": [], "error": self.error}
        return {"runs": self.runs, "error": None}

    def get_run_jobs(self, run_id):
        return {"jobs": self.jobs_by_run_id.get(run_id, []), "error": None}


def _fake_client_gateway_with_github(fake_github):
    class _FakeClientGateway:
        def github_actions(self):
            return fake_github

    return _FakeClientGateway()


def test_employee_admin_cannot_view_pipeline_status(monkeypatch):
    response = client.get("/v1/admin/ci-status/pipeline", params=EMPLOYEE_ADMIN_PROFILE)
    assert response.status_code == 403


def test_pipeline_status_defaults_to_the_latest_sha_and_stitches_workflows(monkeypatch):
    fake_github = _FakeGitHubActionsClient(
        latest_sha="d40e8b1c1e276d4180df42356069ef730e93b603",
        runs=[
            {
                "id": 1,
                "run_number": 240,
                "workflow_file": "ci.yml",
                "status": "completed",
                "conclusion": "success",
                "head_commit_message": "Suppress bandit finding",
                "head_branch": "develop",
                "event": "push",
                "actor_login": "rvsree",
                "html_url": "https://github.com/rvsree/hrb_chatbot_v2/actions/runs/1",
                "created_at": "2026-10-16T02:52:00Z",
            },
            {
                "id": 2,
                "run_number": 58,
                "workflow_file": "deploy.yml",
                "status": "completed",
                "conclusion": "success",
                "head_commit_message": "Suppress bandit finding",
                "head_branch": "master",
                "event": "push",
                "actor_login": "rvsree",
                "html_url": "https://github.com/rvsree/hrb_chatbot_v2/actions/runs/2",
                "created_at": "2026-10-16T02:53:20Z",
            },
        ],
        jobs_by_run_id={
            1: [{"name": "Test suite", "status": "completed", "conclusion": "success", "html_url": "https://github.com/.../jobs/1", "steps": []}],
            2: [{"name": "Build, push, and deploy", "status": "completed", "conclusion": "success", "html_url": "https://github.com/.../jobs/2", "steps": []}],
        },
    )
    monkeypatch.setattr(manage_admin, "get_client_gateway", lambda: _fake_client_gateway_with_github(fake_github))

    eval_store = FakeEvalRunStore(
        runs=[
            {
                "id": 1,
                "run_at": "2026-10-15T22:10:00Z",
                "decision": "PASS",
                "flags": [],
                "aggregated_scores": {"recall": 0.91},
                "total_cases": 26,
                "scored_cases": 26,
                "failed_case_ids": [],
                "retrieval_k": 5,
            }
        ]
    )
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(eval_run_store=eval_store))

    response = client.get("/v1/admin/ci-status/pipeline", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["head_sha"] == "d40e8b1c1e276d4180df42356069ef730e93b603"
    assert body["error"] is None
    assert [run["workflow_file"] for run in body["runs"]] == ["ci.yml", "deploy.yml"]
    assert body["runs"][1]["run_number"] == 58
    assert body["eval_gate"]["decision"] == "PASS"


def test_pipeline_status_shows_no_eval_gate_when_none_precedes_it(monkeypatch):
    fake_github = _FakeGitHubActionsClient(
        latest_sha="abc1234",
        runs=[
            {
                "id": 1,
                "run_number": 10,
                "workflow_file": "deploy.yml",
                "status": "in_progress",
                "conclusion": None,
                "head_commit_message": "",
                "head_branch": "master",
                "event": "push",
                "actor_login": "rvsree",
                "html_url": "https://github.com/.../runs/1",
                "created_at": "2026-10-16T02:53:20Z",
            }
        ],
        jobs_by_run_id={1: []},
    )
    monkeypatch.setattr(manage_admin, "get_client_gateway", lambda: _fake_client_gateway_with_github(fake_github))
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(eval_run_store=FakeEvalRunStore(runs=[])))

    response = client.get("/v1/admin/ci-status/pipeline", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["eval_gate"] is None
    assert body["runs"][0]["status"] == "in_progress"


def test_pipeline_status_surfaces_a_github_error_as_data(monkeypatch):
    fake_github = _FakeGitHubActionsClient(error="GITHUB_TOKEN not configured")
    monkeypatch.setattr(manage_admin, "get_client_gateway", lambda: _fake_client_gateway_with_github(fake_github))

    response = client.get("/v1/admin/ci-status/pipeline", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["error"] == "GITHUB_TOKEN not configured"
    assert body["runs"] == []


def test_pipeline_status_accepts_an_explicit_sha(monkeypatch):
    fake_github = _FakeGitHubActionsClient(runs=[], jobs_by_run_id={})
    monkeypatch.setattr(manage_admin, "get_client_gateway", lambda: _fake_client_gateway_with_github(fake_github))

    response = client.get("/v1/admin/ci-status/pipeline", params={**ADMIN_PROFILE, "sha": "deadbeef"})

    assert response.status_code == 200
    assert response.json()["head_sha"] == "deadbeef"


def test_pipeline_status_persists_a_snapshot_on_read(monkeypatch):
    fake_github = _FakeGitHubActionsClient(
        runs=[
            {
                "id": 1,
                "run_number": 5,
                "workflow_file": "ci.yml",
                "status": "completed",
                "conclusion": "success",
                "head_commit_message": "A real commit",
                "head_branch": "master",
                "event": "push",
                "actor_login": "rvsree",
                "html_url": "https://github.com/.../runs/1",
                "created_at": "2026-10-16T00:00:00Z",
            }
        ],
        jobs_by_run_id={1: []},
    )
    monkeypatch.setattr(manage_admin, "get_client_gateway", lambda: _fake_client_gateway_with_github(fake_github))
    pipeline_store = FakePipelineRunStore()
    monkeypatch.setattr(
        manage_admin, "get_db_gateway", lambda: FakeDBGateway(eval_run_store=FakeEvalRunStore(runs=[]), pipeline_run_store=pipeline_store)
    )

    response = client.get("/v1/admin/ci-status/pipeline", params={**ADMIN_PROFILE, "sha": "cafef00d"})
    assert response.status_code == 200

    history = client.get("/v1/admin/ci-status/pipeline/history", params=ADMIN_PROFILE)
    assert history.status_code == 200
    body = history.json()
    assert body["count"] == 1
    assert body["snapshots"][0]["head_sha"] == "cafef00d"
    assert body["snapshots"][0]["head_commit_message"] == "A real commit"


def test_employee_admin_cannot_view_pipeline_history(monkeypatch):
    response = client.get("/v1/admin/ci-status/pipeline/history", params=EMPLOYEE_ADMIN_PROFILE)
    assert response.status_code == 403


def test_get_pipeline_snapshot_returns_the_stored_detail(monkeypatch):
    pipeline_store = FakePipelineRunStore()

    async def _seed():
        return await pipeline_store.upsert_snapshot(
            head_sha="cafef00d",
            head_commit_message="A real commit",
            head_branch="master",
            event="push",
            actor_login="rvsree",
            runs=[
                {
                    "workflow_file": "deploy.yml",
                    "id": 1,
                    "run_number": 9,
                    "status": "completed",
                    "conclusion": "success",
                    "html_url": "https://github.com/.../runs/1",
                    "created_at": "2026-10-16T00:00:00Z",
                    "jobs": [],
                }
            ],
            eval_gate=None,
        )

    import asyncio

    snapshot = asyncio.run(_seed())
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(pipeline_run_store=pipeline_store))

    response = client.get(f"/v1/admin/ci-status/pipeline/history/{snapshot['id']}", params=ADMIN_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["head_sha"] == "cafef00d"
    assert body["runs"][0]["workflow_file"] == "deploy.yml"


def test_get_pipeline_snapshot_404_for_unknown_id(monkeypatch):
    monkeypatch.setattr(manage_admin, "get_db_gateway", lambda: FakeDBGateway(pipeline_run_store=FakePipelineRunStore()))

    response = client.get("/v1/admin/ci-status/pipeline/history/999", params=ADMIN_PROFILE)

    assert response.status_code == 404
    assert response.json()["code"] == "ADMIN_PIPELINE_SNAPSHOT_NOT_FOUND"
