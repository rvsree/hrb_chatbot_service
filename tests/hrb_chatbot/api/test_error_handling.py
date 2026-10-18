"""Tests for main.py's global exception handler and request-validation
bounds. Core claim: when something unexpected breaks, the client gets a
generic, safe message - never raw exception text, which could leak
internal details (file paths, connection strings, etc.).

Phase 45: identity travels as a JSON body on every request, including
GET (non-standard HTTP, deliberate), not shared client headers or query params.

Phase 96: GET /documents is the one exception - a real browser can't send
a body on GET at all (Fetch spec), so that route reads identity from
query params instead. See tests/hrb_chatbot/api/rag/test_routes_documents.py."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.rag import retrieve_document
from src.hrb_chatbot.main import app
from src.hrb_chatbot.services import documents_service

client = TestClient(app)

HR_SUPPORT_IDENTITY_QUERY_PARAMS = {"employee_id": "EMP051", "full_name": "Hana Support", "role": "hr_support"}
EMPLOYEE_USER_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}

SECRET_LOOKING_MESSAGE = "connection failed: password=supersecret123 at internal-db-host:5432"


def test_an_unexpected_exception_never_leaks_its_raw_message_to_the_client(monkeypatch):
    async def raise_with_sensitive_details():
        raise RuntimeError(SECRET_LOOKING_MESSAGE)

    monkeypatch.setattr(documents_service, "list_documents", raise_with_sensitive_details)

    # raise_server_exceptions=False: otherwise TestClient re-raises the
    # exception instead of returning the handler's real HTTP response.
    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/v1/genai-rag/ingest-document/documents", params=HR_SUPPORT_IDENTITY_QUERY_PARAMS)

    assert response.status_code == 500
    body_text = response.text
    assert SECRET_LOOKING_MESSAGE not in body_text
    assert "password" not in body_text
    assert "internal-db-host" not in body_text


def test_the_generic_error_response_still_has_the_project_s_standard_shape(monkeypatch):
    async def raise_unexpectedly():
        raise RuntimeError(SECRET_LOOKING_MESSAGE)

    monkeypatch.setattr(documents_service, "list_documents", raise_unexpectedly)

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.get("/v1/genai-rag/ingest-document/documents", params=HR_SUPPORT_IDENTITY_QUERY_PARAMS)

    # Still {"error": ...} (json_error()'s shape), not FastAPI's default
    # {"detail": ...} - the handler normalizes every error response.
    body = response.json()
    assert "error" in body
    assert body["code"] == "INTERNAL_ERROR"


def test_a_multipart_body_on_a_json_endpoint_is_a_clean_422_not_a_crash():
    """Phase 24 regression: a multipart/form-data body sent where JSON is
    expected still parses as *valid JSON-request syntax* to Starlette, so it
    reaches Pydantic, whose RequestValidationError.errors() then carries the
    raw (non-UTF-8) request bytes in its "input" field.
    jsonable_encoder()'s default bytes handling used to crash on that
    *inside the exception handler itself*, with nothing left to catch it -
    originally reproduced via a PDF file posted to a JSON-only endpoint
    (Phase 26 removed that specific endpoint; POST /query is JSON-only too,
    same class of bug either way)."""
    non_utf8_multipart_body = b"--boundary\r\nContent-Disposition: form-data; name=\"files\"\r\n\r\n\xd3\xeb\xe9\xe1 raw bytes\r\n--boundary--"

    with TestClient(app, raise_server_exceptions=False) as test_client:
        response = test_client.post(
            "/v1/genai-rag-retrieval/query",
            content=non_utf8_multipart_body,
            headers={"Content-Type": "multipart/form-data; boundary=boundary"},
        )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"


def test_query_longer_than_the_max_length_is_rejected():
    too_long_query = "a" * 2001

    response = client.post(
        "/v1/genai-rag-retrieval/query",
        json={"user_profile": EMPLOYEE_USER_PROFILE, "query": too_long_query},
    )

    assert response.status_code == 422
    # Pydantic's own validation errors used to bypass json_error() entirely
    # and return FastAPI's default {"detail": [...]} shape - the
    # RequestValidationError handler in main.py now normalizes this too.
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "error" in body
    assert "details" in body  # the raw Pydantic error list, for debugging


def test_query_at_exactly_the_max_length_is_accepted_by_validation(monkeypatch):
    async def _fake_answer_query(params, request_id=None):
        return {
            "query": params.query,
            "answer": "fake answer",
            "model_used": "gpt-4.1-mini",
            "sources": [],
            "vector_db": "chromadb",
            "search_strategy": "similarity",
            "applied_filter": None,
            "served_from_cache": False,
            "llm_call_count": 1,
            "token_usage": None,
            "latency_ms": {"total": 1.0, "retrieval": None, "generation": None},
        }

    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_answer_query)
    exactly_max_length_query = "a" * 2000

    response = client.post(
        "/v1/genai-rag-retrieval/query",
        json={"user_profile": EMPLOYEE_USER_PROFILE, "query": exactly_max_length_query},
    )

    # 200, not 422 - confirms validation accepted it and the request reached
    # the route handler (the pipeline itself is faked, not under test here).
    assert response.status_code == 200
