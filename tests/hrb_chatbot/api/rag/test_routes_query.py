"""Tests for POST /v1/genai-rag-retrieval/query (api/rag/retrieve_document.py). The real
pipeline exists now (ai/rag_pipeline/), so well-formed-request tests
monkeypatch pipeline.answer_query() to a canned response - this file
tests the ROUTE's contract (status codes, response shape), not retrieval/
generation correctness itself (see
tests/hrb_chatbot/ai/rag_pipeline/query_retrieval/test_retriever.py and
.../response_generation/test_generator.py for that). No test here may hit
a real network call or cost money.

Phase 45: identity travels in the request body's user_profile sub-object,
not shared client headers - see docs/agent-reference/endpoint-request-response-contracts.md."""

from fastapi.testclient import TestClient

from src.hrb_chatbot.api.rag import retrieve_document
from src.hrb_chatbot.main import app

client = TestClient(app)

EMPLOYEE_USER_PROFILE = {"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "employee"}


def _body(query: str = "test", user_profile=None, search_options=None, generation_options=None) -> dict:
    body = {"user_profile": EMPLOYEE_USER_PROFILE if user_profile is None else user_profile, "query": query}
    if search_options is not None:
        body["search_options"] = search_options
    if generation_options is not None:
        body["generation_options"] = generation_options
    return body


async def _fake_answer_query(params):
    return {
        "query": params.query,
        "answer": "This is a fake grounded answer.",
        "model_used": params.model_name or "gpt-4.1-mini",
        "sources": [
            {
                "document_id": "doc-1",
                "filename": "JPMC Healthcare Benefits.pdf",
                "chunk_index": 0,
                "text": "Some grounded chunk text.",
                "score": 0.95,
            }
        ],
        "vector_db": params.vector_db or "chromadb",
        "search_strategy": params.search_strategy or "similarity",
        "applied_filter": {"doc_description": {"$eq": "401k"}} if params.use_self_query else None,
        "served_from_cache": False,
        "llm_call_count": 1,
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        "latency_ms": {"total": 500.0, "retrieval": 150.0, "generation": 350.0},
        "temperature": params.temperature if params.temperature is not None else 0.0,
    }


def test_well_formed_query_returns_a_grounded_answer(monkeypatch):
    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_answer_query)

    response = client.post(
        "/v1/genai-rag-retrieval/query", json=_body(query="How many weeks of parental leave do I get?")
    )

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "How many weeks of parental leave do I get?"
    assert body["answer_info"]["answer"] == "This is a fake grounded answer."
    assert body["answer_info"]["model_used"] == "gpt-4.1-mini"
    assert body["retrieval_info"]["sources"][0]["filename"] == "JPMC Healthcare Benefits.pdf"


def test_mcp_routed_answer_reports_routed_to_in_explainability(monkeypatch):
    async def _fake_mcp_answer_query(params):
        return {
            "query": params.query,
            "answer": "You have 12 days of PTO remaining.",
            "model_used": "mcp:get_leave_balance",
            "sources": [],
            "vector_db": "n/a (mcp)",
            "search_strategy": "n/a (mcp)",
            "applied_filter": None,
            "served_from_cache": False,
            "llm_call_count": 0,
            "token_usage": None,
            "latency_ms": {"total": 80.0, "retrieval": None, "generation": None},
            "routed_to": "get_leave_balance",
        }

    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_mcp_answer_query)

    response = client.post("/v1/genai-rag-retrieval/query", json=_body(query="What's my PTO balance?"))

    assert response.status_code == 200
    assert response.json()["explainability_info"]["routed_to"] == "get_leave_balance"


def test_non_mcp_answer_has_null_routed_to(monkeypatch):
    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_answer_query)

    response = client.post("/v1/genai-rag-retrieval/query", json=_body(query="How many weeks of PTO do I get?"))

    assert response.json()["explainability_info"]["routed_to"] is None


def test_temperature_actually_used_reaches_explainability(monkeypatch):
    # Phase 127
    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_answer_query)

    response = client.post(
        "/v1/genai-rag-retrieval/query",
        json=_body(query="test", generation_options={"temperature": 0.6}),
    )

    assert response.json()["explainability_info"]["temperature"] == 0.6


def test_empty_query_string_is_rejected_before_reaching_the_pipeline():
    response = client.post("/v1/genai-rag-retrieval/query", json=_body(query=""))

    assert response.status_code == 422


def test_missing_query_field_is_rejected():
    response = client.post(
        "/v1/genai-rag-retrieval/query", json={"user_profile": EMPLOYEE_USER_PROFILE}
    )

    assert response.status_code == 422


def test_top_k_above_the_maximum_is_rejected():
    response = client.post("/v1/genai-rag-retrieval/query", json=_body(search_options={"top_k": 100}))

    assert response.status_code == 422


def test_optional_generation_fields_are_accepted_and_passed_through(monkeypatch):
    """Confirms model_name/temperature/max_tokens are real, accepted request
    fields that reach the pipeline, not just documented intent."""
    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_answer_query)

    response = client.post(
        "/v1/genai-rag-retrieval/query",
        json=_body(generation_options={"model_name": "gpt-4.1-mini", "temperature": 0.5, "max_tokens": 200}),
    )

    assert response.status_code == 200
    assert response.json()["answer_info"]["model_used"] == "gpt-4.1-mini"


def test_temperature_out_of_range_is_rejected():
    response = client.post("/v1/genai-rag-retrieval/query", json=_body(generation_options={"temperature": 5.0}))

    assert response.status_code == 422


def test_search_strategy_field_is_accepted_and_passed_through(monkeypatch):
    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_answer_query)

    response = client.post(
        "/v1/genai-rag-retrieval/query", json=_body(search_options={"search_strategy": "mmr"})
    )

    assert response.status_code == 200
    assert response.json()["retrieval_info"]["search_strategy"] == "mmr"


def test_dedicated_mmr_endpoint_no_longer_exists():
    # Phase 21 removed it - MMR is selected via search_strategy in the body
    # of POST /query instead (see test_search_strategy_field_is_accepted_and_passed_through).
    response = client.post("/v1/genai-rag-retrieval/query/mmr", json=_body())

    assert response.status_code == 404


def test_unknown_search_strategy_is_a_422_naming_the_valid_options():
    response = client.post(
        "/v1/genai-rag-retrieval/query", json=_body(search_options={"search_strategy": "made-up"})
    )

    assert response.status_code == 422


def test_use_multi_query_and_use_self_query_are_accepted_and_passed_through(monkeypatch):
    captured = {}

    async def _capturing_fake(params):
        captured["params"] = params
        return await _fake_answer_query(params)

    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _capturing_fake)

    response = client.post(
        "/v1/genai-rag-retrieval/query",
        json=_body(
            query="what's my 401k vesting schedule",
            search_options={"use_multi_query": True, "use_self_query": True, "llm_provider": "anthropic"},
        ),
    )

    assert response.status_code == 200
    assert captured["params"].use_multi_query is True
    assert captured["params"].use_self_query is True
    assert captured["params"].llm_provider == "anthropic"
    assert response.json()["retrieval_info"]["applied_filter"] == {"doc_description": {"$eq": "401k"}}


def test_use_multi_query_and_use_self_query_default_to_false(monkeypatch):
    captured = {}

    async def _capturing_fake(params):
        captured["params"] = params
        return await _fake_answer_query(params)

    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _capturing_fake)

    response = client.post("/v1/genai-rag-retrieval/query", json=_body())

    assert response.status_code == 200
    assert captured["params"].use_multi_query is False
    assert captured["params"].use_self_query is False
    assert captured["params"].llm_provider is None
    assert response.json()["retrieval_info"]["applied_filter"] is None


def test_unknown_llm_provider_is_a_422_naming_the_valid_options():
    response = client.post(
        "/v1/genai-rag-retrieval/query", json=_body(search_options={"llm_provider": "made-up"})
    )

    assert response.status_code == 422


def test_retrieval_without_any_identity_is_a_401():
    response = client.post("/v1/genai-rag-retrieval/query", json={"query": "test"})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_retrieval_accepts_all_three_roles(monkeypatch):
    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_answer_query)

    for role in ("employee", "manager", "hr_support"):
        response = client.post(
            "/v1/genai-rag-retrieval/query",
            json=_body(user_profile={"employee_id": "MGR006", "full_name": "Someone", "role": role}),
        )
        assert response.status_code == 200, role


def test_unknown_role_in_the_payload_is_a_401_not_a_422():
    # An unknown role is an identity problem, not a generic payload
    # validation problem - must match the query-param path's own 401,
    # not fall through to Pydantic's automatic 422 for a bad enum value.
    response = client.post(
        "/v1/genai-rag-retrieval/query",
        json=_body(user_profile={"employee_id": "EMP052", "full_name": "Eddy Employee", "role": "made-up-role"}),
    )

    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "UNAUTHENTICATED"
    assert "made-up-role" in body["error"]


def test_unexpected_pipeline_failure_returns_a_clean_500(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("vector store unreachable")

    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _raise)

    response = client.post("/v1/genai-rag-retrieval/query", json=_body())

    assert response.status_code == 500
    assert "error" in response.json()


def test_mcp_routed_answer_reports_tools_used(monkeypatch):
    async def _fake_mcp_answer_query(params):
        return {
            "query": params.query,
            "answer": "You have 12 days of PTO remaining.",
            "model_used": "mcp:get_leave_balance",
            "sources": [],
            "vector_db": "n/a (mcp)",
            "search_strategy": "n/a (mcp)",
            "applied_filter": None,
            "served_from_cache": False,
            "llm_call_count": 0,
            "token_usage": None,
            "latency_ms": {"total": 80.0, "retrieval": None, "generation": None},
            "routed_to": "get_leave_balance",
            "tools_used": [
                {
                    "tool_name": "get_leave_balance",
                    "tool_input": "What's my PTO balance?",
                    "tool_type": "mcp",
                    "latency_ms": 65.0,
                    "success": True,
                }
            ],
        }

    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_mcp_answer_query)

    response = client.post("/v1/genai-rag-retrieval/query", json=_body(query="What's my PTO balance?"))

    assert response.status_code == 200
    tools_used = response.json()["tools_used"]
    assert len(tools_used) == 1
    assert tools_used[0]["tool_type"] == "mcp"
    assert tools_used[0]["latency_ms"] == 65.0


def test_non_mcp_answer_has_empty_tools_used(monkeypatch):
    monkeypatch.setattr(retrieve_document.pipeline, "answer_query", _fake_answer_query)

    response = client.post("/v1/genai-rag-retrieval/query", json=_body(query="How many weeks of PTO do I get?"))

    assert response.json()["tools_used"] == []
