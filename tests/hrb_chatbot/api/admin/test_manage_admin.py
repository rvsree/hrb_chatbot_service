"""Tests for GET/DELETE /v1/admin/* (Phase 168) - MCP calls and store calls
are faked, no real network/database call, matching every other route test
in this project."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.ai.pre_processing import conversation_memory as conversation_memory_module
from src.hrb_chatbot.api.admin import manage_admin
from src.hrb_chatbot.main import app
from tests.conftest import FakeConversationStore, FakeDBGateway, FakeDocMetadataStore, FakeFeedbackStore

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
    async def _fake_call_mcp_tool(tool_name, arguments):
        assert tool_name == "list_hitl_requests"
        assert arguments == {"status": "all", "request_type": "UNPAID_LEAVE_REQUEST"}
        return {
            "tool": tool_name,
            "content": [
                '{"total": 2, "requests": ['
                '{"hitlRequestId": 1, "requestType": "UNPAID_LEAVE_REQUEST", "employeeId": "EMP052", '
                '"query": "q1", "context": {}, "status": "COMPLETED", "assignedTo": "Daniel", "createdAt": "2026-10-01T00:00:00"}, '
                '{"hitlRequestId": 2, "requestType": "UNPAID_LEAVE_REQUEST", "employeeId": "EMP001", '
                '"query": "q2", "context": {}, "status": "PENDING", "assignedTo": null, "createdAt": "2026-10-02T00:00:00"}'
                ']}'
            ],
        }

    monkeypatch.setattr(manage_admin, "_call_mcp_tool", _fake_call_mcp_tool)

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
