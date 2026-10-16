"""Tests for POST/GET /v1/unpaid-leave/* (Phase 162) - the agent and MCP
calls are faked, no real LLM/network call, matching every other route test
in this project."""

import json

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.leave import unpaid_leave
from src.hrb_chatbot.main import app

client = TestClient(app)

EMPLOYEE_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}
HR_PROFILE = {"employee_id": "HR001", "full_name": "Holly HR", "role": "hr_support"}
ADMIN_PROFILE = {"employee_id": "ADM001", "full_name": "Sree Rad", "role": "admin"}


def _fake_submit_result(employee_id="EMP052", is_repeat=False):
    return {
        "requestId": 1,
        "employeeId": employee_id,
        "leaveType": "UNPAID",
        "startDate": "2026-12-01",
        "endDate": "2026-12-03",
        "days": 3.0,
        "status": "PENDING_HITL",
        "approverId": "MGR001",
        "isRepeatWithin12Months": is_repeat,
        "hitlRequestId": 7,
        "hitlStatus": "PENDING",
        "createdAt": "2026-10-11T00:00:00",
    }


def test_submit_unpaid_leave_returns_the_agent_result(monkeypatch):
    async def _fake_run(**kwargs):
        return _fake_submit_result(employee_id=kwargs["employee_id"])

    monkeypatch.setattr(unpaid_leave, "run_unpaid_leave_request", _fake_run)

    response = client.post(
        "/v1/unpaid-leave/request",
        json={
            "user_profile": EMPLOYEE_PROFILE,
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "purpose": "Family caregiving",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == 1
    assert body["hitl_request_context_id"] == 7
    assert body["is_repeat_within_12_months"] is False


def test_submit_unpaid_leave_passes_through_the_repeat_flag(monkeypatch):
    async def _fake_run(**kwargs):
        return _fake_submit_result(is_repeat=True)

    monkeypatch.setattr(unpaid_leave, "run_unpaid_leave_request", _fake_run)

    response = client.post(
        "/v1/unpaid-leave/request",
        json={
            "user_profile": EMPLOYEE_PROFILE,
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "purpose": "Family caregiving",
        },
    )

    assert response.status_code == 200
    assert response.json()["is_repeat_within_12_months"] is True


def test_submit_unpaid_leave_failure_returns_a_clear_500(monkeypatch):
    async def _failing_run(**kwargs):
        raise RuntimeError("hrb_lms_mcp unreachable")

    monkeypatch.setattr(unpaid_leave, "run_unpaid_leave_request", _failing_run)

    response = client.post(
        "/v1/unpaid-leave/request",
        json={
            "user_profile": EMPLOYEE_PROFILE,
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "purpose": "Family caregiving",
        },
    )

    assert response.status_code == 500
    assert response.json()["code"] == "LEAVE_REQUEST_FAILED"


def test_hr_support_role_required_to_list_pending_requests(monkeypatch):
    response = client.get("/v1/unpaid-leave/pending", params={"user_profile": json.dumps(EMPLOYEE_PROFILE)})

    assert response.status_code == 403


def test_list_pending_requests_returns_the_mcp_result(monkeypatch):
    async def _fake_call_mcp_tool_json(tool_name, arguments):
        assert tool_name == "list_hitl_requests"
        assert arguments == {"status": "PENDING", "request_type": "UNPAID_LEAVE_REQUEST"}
        return {
            "total": 1,
            "requests": [
                {
                    "hitlRequestId": 7,
                    "requestType": "UNPAID_LEAVE_REQUEST",
                    "employeeId": "EMP052",
                    "query": "Employee Eddy requests 3 days of unpaid leave.",
                    "context": {"is_repeat_within_12_months": False},
                    "status": "PENDING",
                    "assignedTo": "hr-team@company.com",
                    "createdAt": "2026-10-11T00:00:00",
                }
            ],
        }

    monkeypatch.setattr(unpaid_leave, "_call_mcp_tool_json", _fake_call_mcp_tool_json)

    response = client.get("/v1/unpaid-leave/pending", params={"user_profile": json.dumps(HR_PROFILE)})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["requests"][0]["hitl_request_context_id"] == 7


def test_employee_role_cannot_list_all_leave_requests(monkeypatch):
    response = client.get("/v1/unpaid-leave/all", params=EMPLOYEE_PROFILE)
    assert response.status_code == 403


def test_list_all_leave_requests_returns_every_status_not_just_pending(monkeypatch):
    async def _fake_list_all(status=None):
        assert status == "all"
        return {
            "total": 2,
            "requests": [
                {
                    "hitlRequestId": 7,
                    "requestId": 1,
                    "employeeId": "EMP052",
                    "employeeName": "Eddy Employee",
                    "leaveType": "UNPAID",
                    "startDate": "2026-10-01",
                    "endDate": "2026-10-03",
                    "days": 3.0,
                    "purpose": "Family caregiving",
                    "status": "COMPLETED",
                    "decision": "APPROVED",
                    "hrComments": "Looks good.",
                    "hrSpecialistName": "Daniel Rodriguez",
                    "createdAt": "2026-10-01T00:00:00",
                    "respondedAt": "2026-10-02T00:00:00",
                },
                {
                    "hitlRequestId": 8,
                    "requestId": 2,
                    "employeeId": "EMP001",
                    "employeeName": "John Doe",
                    "leaveType": "STD",
                    "startDate": "2026-11-01",
                    "endDate": "2026-11-05",
                    "days": 5.0,
                    "purpose": "Recovery",
                    "status": "PENDING",
                    "decision": None,
                    "hrComments": None,
                    "hrSpecialistName": None,
                    "createdAt": "2026-11-01T00:00:00",
                    "respondedAt": None,
                },
            ],
        }

    monkeypatch.setattr(unpaid_leave, "list_all_leave_requests", _fake_list_all)

    response = client.get("/v1/unpaid-leave/all", params=HR_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    statuses = {r["status"] for r in body["requests"]}
    assert statuses == {"COMPLETED", "PENDING"}
    assert body["requests"][0]["employee_name"] == "Eddy Employee"


def test_admin_role_can_also_list_all_leave_requests(monkeypatch):
    """Round 3 - the admin dashboard's own Leave Requests tab reuses this
    exact route, same richer shape as the HR grid."""

    async def _fake_list_all(status=None):
        return {"total": 0, "requests": []}

    monkeypatch.setattr(unpaid_leave, "list_all_leave_requests", _fake_list_all)

    response = client.get("/v1/unpaid-leave/all", params=ADMIN_PROFILE)

    assert response.status_code == 200


def test_list_all_leave_requests_failure_returns_a_clear_500(monkeypatch):
    async def _failing_list_all(status=None):
        raise RuntimeError("hrb_lms_mcp unreachable")

    monkeypatch.setattr(unpaid_leave, "list_all_leave_requests", _failing_list_all)

    response = client.get("/v1/unpaid-leave/all", params=HR_PROFILE)

    assert response.status_code == 500
    assert response.json()["code"] == "LEAVE_REQUEST_FAILED"


def test_employee_role_cannot_resolve_hitl_requests(monkeypatch):
    response = client.post(
        "/v1/unpaid-leave/resolve",
        json={
            "user_profile": EMPLOYEE_PROFILE,
            "hitl_request_context_id": 7,
            "decision": "APPROVED",
            "response_text": "ok",
        },
    )

    assert response.status_code == 403


def test_resolve_calls_the_mcp_wrapper_and_returns_the_decision(monkeypatch):
    captured_calls = []

    async def _fake_resolve(**kwargs):
        captured_calls.append(kwargs)
        return {
            "hitlRequestId": kwargs["hitl_request_context_id"],
            "status": "COMPLETED",
            "decision": kwargs["decision"],
            "response": kwargs["response_text"],
            "assignedTo": kwargs["resolved_by"],
            "relatedLeaveRequestUpdated": True,
        }

    monkeypatch.setattr(unpaid_leave, "resume_unpaid_leave_decision", _fake_resolve)

    response = client.post(
        "/v1/unpaid-leave/resolve",
        json={
            "user_profile": HR_PROFILE,
            "hitl_request_context_id": 7,
            "decision": "APPROVED",
            "response_text": "Documentation verified.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "APPROVED"
    assert body["related_leave_request_updated"] is True
    assert captured_calls[0]["resolved_by"] == "Holly HR"


def test_resolve_failure_returns_a_clear_500(monkeypatch):
    async def _failing_resolve(**kwargs):
        raise RuntimeError("already resolved")

    monkeypatch.setattr(unpaid_leave, "resume_unpaid_leave_decision", _failing_resolve)

    response = client.post(
        "/v1/unpaid-leave/resolve",
        json={"user_profile": HR_PROFILE, "hitl_request_context_id": 7, "decision": "APPROVED", "response_text": "ok"},
    )

    assert response.status_code == 500
    assert response.json()["code"] == "HITL_RESOLUTION_FAILED"


def _patch_register_leave_document(monkeypatch, captured_calls=None):
    async def _fake_register(employee_id, s3_key, original_filename, content_type):
        if captured_calls is not None:
            captured_calls.append(
                {"employee_id": employee_id, "s3_key": s3_key, "original_filename": original_filename, "content_type": content_type}
            )
        return {"documentId": 1, "s3Key": s3_key, "originalFilename": original_filename, "uploadedAt": "2026-10-12T00:00:00"}

    monkeypatch.setattr(unpaid_leave, "register_leave_document", _fake_register)


def test_hr_support_cannot_get_an_upload_url(monkeypatch):
    """Phase 165 (round 2) - confirmed live as a real gap: an hr_support
    persona could submit a leave request through this same flow before
    this fix. HR reviews requests, they don't file their own through here."""
    response = client.post(
        "/v1/unpaid-leave/upload-url",
        json={"user_profile": HR_PROFILE, "filename": "doctor-note.pdf", "content_type": "application/pdf"},
    )
    assert response.status_code == 403


def test_hr_support_cannot_submit_an_unpaid_leave_request(monkeypatch):
    response = client.post(
        "/v1/unpaid-leave/request",
        json={
            "user_profile": HR_PROFILE,
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "purpose": "Family caregiving",
        },
    )
    assert response.status_code == 403


def test_hr_support_cannot_list_my_requests(monkeypatch):
    response = client.get("/v1/unpaid-leave/my-requests", params=HR_PROFILE)
    assert response.status_code == 403


def test_get_upload_url_returns_a_presigned_url(monkeypatch):
    def _fake_generate(token, filename, content_type):
        return {"upload_url": f"https://s3.example.com/{token}/{filename}", "key": f"{token}/{filename}", "expires_in_seconds": 300}

    monkeypatch.setattr(unpaid_leave, "generate_leave_document_upload_url", _fake_generate)
    captured_calls = []
    _patch_register_leave_document(monkeypatch, captured_calls)

    response = client.post(
        "/v1/unpaid-leave/upload-url",
        json={"user_profile": EMPLOYEE_PROFILE, "filename": "doctor-note.pdf", "content_type": "application/pdf"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["key"].endswith("doctor-note.pdf")
    assert body["expires_in_seconds"] == 300
    # Phase 165 - the manifest row must be registered at upload time, not
    # only once (or if) a later submit succeeds.
    assert captured_calls[0]["employee_id"] == "EMP052"
    assert captured_calls[0]["s3_key"] == body["key"]


def test_get_upload_url_still_succeeds_if_manifest_registration_fails(monkeypatch):
    """Phase 165 - best-effort: the presigned URL is already generated by
    this point, so a manifest-registration failure must not turn a working
    upload into an error response."""

    def _fake_generate(token, filename, content_type):
        return {"upload_url": f"https://s3.example.com/{token}/{filename}", "key": f"{token}/{filename}", "expires_in_seconds": 300}

    async def _failing_register(employee_id, s3_key, original_filename, content_type):
        raise RuntimeError("hrb_lms_mcp unreachable")

    monkeypatch.setattr(unpaid_leave, "generate_leave_document_upload_url", _fake_generate)
    monkeypatch.setattr(unpaid_leave, "register_leave_document", _failing_register)

    response = client.post(
        "/v1/unpaid-leave/upload-url",
        json={"user_profile": EMPLOYEE_PROFILE, "filename": "doctor-note.pdf", "content_type": "application/pdf"},
    )

    assert response.status_code == 200


def test_submit_unpaid_leave_defaults_leave_type_to_unpaid(monkeypatch):
    captured_calls = []

    async def _fake_run(**kwargs):
        captured_calls.append(kwargs)
        return _fake_submit_result()

    monkeypatch.setattr(unpaid_leave, "run_unpaid_leave_request", _fake_run)

    response = client.post(
        "/v1/unpaid-leave/request",
        json={
            "user_profile": EMPLOYEE_PROFILE,
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "purpose": "Family caregiving",
        },
    )

    assert response.status_code == 200
    assert response.json()["leave_type"] == "UNPAID"
    assert captured_calls[0]["leave_type_code"] == "UNPAID"


def test_submit_unpaid_leave_threads_through_a_different_leave_type(monkeypatch):
    captured_calls = []

    async def _fake_run(**kwargs):
        captured_calls.append(kwargs)
        result = _fake_submit_result()
        result["leaveType"] = "STD"
        return result

    monkeypatch.setattr(unpaid_leave, "run_unpaid_leave_request", _fake_run)

    response = client.post(
        "/v1/unpaid-leave/request",
        json={
            "user_profile": EMPLOYEE_PROFILE,
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "purpose": "Recovering from surgery",
            "leave_type_code": "STD",
        },
    )

    assert response.status_code == 200
    assert response.json()["leave_type"] == "STD"
    assert captured_calls[0]["leave_type_code"] == "STD"


def test_submit_unpaid_leave_rejects_an_unknown_leave_type(monkeypatch):
    response = client.post(
        "/v1/unpaid-leave/request",
        json={
            "user_profile": EMPLOYEE_PROFILE,
            "start_date": "2026-12-01",
            "end_date": "2026-12-03",
            "purpose": "Family caregiving",
            "leave_type_code": "SABBATICAL",
        },
    )

    assert response.status_code == 422


def test_resolve_passes_through_the_resolving_specialists_employee_id(monkeypatch):
    """Phase 172 - the route now calls resume_unpaid_leave_decision(), which
    resumes the agent's paused graph (decision-email sending moved into
    finalize_node - covered in test_unpaid_leave_agent.py now, not here)."""
    captured_calls = []

    async def _fake_resume(**kwargs):
        captured_calls.append(kwargs)
        return {
            "hitlRequestId": kwargs["hitl_request_context_id"],
            "status": "COMPLETED",
            "decision": kwargs["decision"],
            "response": kwargs["response_text"],
            "assignedTo": kwargs["resolved_by"],
            "relatedLeaveRequestUpdated": True,
        }

    monkeypatch.setattr(unpaid_leave, "resume_unpaid_leave_decision", _fake_resume)

    response = client.post(
        "/v1/unpaid-leave/resolve",
        json={"user_profile": HR_PROFILE, "hitl_request_context_id": 7, "decision": "APPROVED", "response_text": "ok"},
    )

    assert response.status_code == 200
    assert captured_calls[0]["resolved_by_employee_id"] == "HR001"


def test_my_requests_requires_identity(monkeypatch):
    response = client.get("/v1/unpaid-leave/my-requests")
    assert response.status_code == 401


def test_my_requests_returns_the_callers_own_requests(monkeypatch):
    async def _fake_list_my(employee_id):
        assert employee_id == "EMP052"
        return {
            "employeeId": employee_id,
            "total": 1,
            "limit": 20,
            "offset": 0,
            "requests": [
                {
                    "requestId": 1,
                    "leaveType": "STD",
                    "startDate": "2026-12-01",
                    "endDate": "2026-12-03",
                    "days": 3.0,
                    "purpose": "Recovering from surgery",
                    "status": "COMPLETED",
                    "decision": "APPROVED",
                    "hrComments": "Looks good.",
                    "hrSpecialistName": "Daniel Rodriguez",
                    "hrSpecialistEmployeeId": "EMP021",
                    "createdAt": "2026-10-11T00:00:00",
                    "respondedAt": "2026-10-11T01:00:00",
                }
            ],
        }

    monkeypatch.setattr(unpaid_leave, "list_my_leave_requests", _fake_list_my)

    response = client.get("/v1/unpaid-leave/my-requests", params=EMPLOYEE_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["requests"][0]["leave_type"] == "STD"
    assert body["requests"][0]["hr_specialist_name"] == "Daniel Rodriguez"


def test_document_download_requires_identity(monkeypatch):
    response = client.get("/v1/unpaid-leave/documents/1")
    assert response.status_code == 401


def test_document_download_allowed_for_the_owning_employee(monkeypatch):
    async def _fake_list_docs(leave_request_id):
        return {
            "leaveRequestId": leave_request_id,
            "ownerEmployeeId": "EMP052",
            "documents": [
                {"documentId": 1, "s3Key": "std/EMP052/1/note.pdf", "originalFilename": "note.pdf", "contentType": "application/pdf", "uploadedAt": "2026-10-11T00:00:00"}
            ],
        }

    def _fake_download(s3_key):
        return {"download_url": f"https://s3.example.com/{s3_key}?sig=abc", "expires_in_seconds": 300}

    monkeypatch.setattr(unpaid_leave, "list_leave_documents", _fake_list_docs)
    monkeypatch.setattr(unpaid_leave, "generate_leave_document_download_url", _fake_download)

    response = client.get("/v1/unpaid-leave/documents/1", params=EMPLOYEE_PROFILE)

    assert response.status_code == 200
    body = response.json()
    assert body["original_filename"] == "note.pdf"
    assert "note.pdf" in body["download_url"]


def test_document_download_allowed_for_hr_support_even_if_not_the_owner(monkeypatch):
    async def _fake_list_docs(leave_request_id):
        return {
            "leaveRequestId": leave_request_id,
            "ownerEmployeeId": "EMP052",
            "documents": [
                {"documentId": 1, "s3Key": "std/EMP052/1/note.pdf", "originalFilename": "note.pdf", "contentType": "application/pdf", "uploadedAt": "2026-10-11T00:00:00"}
            ],
        }

    def _fake_download(s3_key):
        return {"download_url": f"https://s3.example.com/{s3_key}?sig=abc", "expires_in_seconds": 300}

    monkeypatch.setattr(unpaid_leave, "list_leave_documents", _fake_list_docs)
    monkeypatch.setattr(unpaid_leave, "generate_leave_document_download_url", _fake_download)

    response = client.get("/v1/unpaid-leave/documents/1", params=HR_PROFILE)

    assert response.status_code == 200


def test_document_download_forbidden_for_an_unrelated_employee(monkeypatch):
    async def _fake_list_docs(leave_request_id):
        return {
            "leaveRequestId": leave_request_id,
            "ownerEmployeeId": "EMP052",
            "documents": [
                {"documentId": 1, "s3Key": "std/EMP052/1/note.pdf", "originalFilename": "note.pdf", "contentType": "application/pdf", "uploadedAt": "2026-10-11T00:00:00"}
            ],
        }

    monkeypatch.setattr(unpaid_leave, "list_leave_documents", _fake_list_docs)

    other_employee = {"employee_id": "EMP999", "full_name": "Someone Else", "role": "employee"}
    response = client.get("/v1/unpaid-leave/documents/1", params=other_employee)

    assert response.status_code == 403


def test_document_download_404_when_no_document_exists(monkeypatch):
    async def _fake_list_docs(leave_request_id):
        return {"leaveRequestId": leave_request_id, "ownerEmployeeId": "EMP052", "documents": []}

    monkeypatch.setattr(unpaid_leave, "list_leave_documents", _fake_list_docs)

    response = client.get("/v1/unpaid-leave/documents/1", params=EMPLOYEE_PROFILE)

    assert response.status_code == 404
    assert response.json()["code"] == "LEAVE_DOCUMENT_NOT_FOUND"
