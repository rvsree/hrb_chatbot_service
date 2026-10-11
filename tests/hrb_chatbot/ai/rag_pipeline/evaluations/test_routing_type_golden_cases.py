"""Phase 73 - confirms genai-rag's pipeline takes the deterministic MCP
bypass (try_route_to_mcp(), Phase 49) for golden cases marked
call_type="agent_call", and that no "llm_call" case accidentally matches
the bypass keywords. The real "CI-wired eval gate" for routing correctness
named earlier - default suite, not @pytest.mark.eval. Phase 151 removed
the top-level MCP shortcut that used to let a pure agent_call query skip
decompose() entirely - every query goes through decompose() first now, so
it's faked here too (as a passthrough, matching its own real behavior for
an already-atomic question) to keep this a genuinely zero-real-call test,
not because the keyword-matching logic itself needs faking - that part
still runs unfaked, same as always."""

import json

from src.hrb_chatbot.ai.rag_pipeline import pipeline
from src.hrb_chatbot.ai.rag_pipeline.tools import mcp_tools
from src.hrb_chatbot.common.rag_query_params import RagQueryParams

GOLDEN_DATASET_PATH = "resources/golden_dataset/golden_dataset.json"
EVAL_EMPLOYEE_ID = "EMP052"


def _load_cases_by_call_type(call_type: str) -> list[dict]:
    with open(GOLDEN_DATASET_PATH, encoding="utf-8") as file:
        data = json.load(file)
    return [case for case in data["cases"] if case.get("call_type") == call_type]


async def test_agent_call_cases_bypass_the_llm_entirely(monkeypatch):
    # check_input() itself calls NeMo's "self check input" rail, a real LLM call -
    # faked here so this stays a genuinely zero-cost default-suite test, same
    # project rule every other default-suite test already follows.
    async def _passthrough_check_input(query):
        return query

    async def _fake_get_leave_balance(employee_id):
        return {"tool": "get_leave_balance", "content": ["PTO: 10 days, Sick: 5 days"]}

    async def _fake_get_leave_history(employee_id):
        return {"tool": "get_leave_history", "content": ["No recent leave requests."]}

    # Phase 151 - decompose() now always runs (see module docstring); faked
    # as a passthrough, same as its own real behavior for an atomic query.
    async def _passthrough_decompose(query):
        return [query]

    monkeypatch.setattr(pipeline, "check_input", _passthrough_check_input)
    monkeypatch.setattr(pipeline, "decompose", _passthrough_decompose)
    monkeypatch.setattr(mcp_tools, "get_leave_balance", _fake_get_leave_balance)
    monkeypatch.setattr(mcp_tools, "get_leave_history", _fake_get_leave_history)

    cases = _load_cases_by_call_type("agent_call")
    assert cases, "expected at least one agent_call golden case"

    for case in cases:
        result = await pipeline.answer_query(RagQueryParams(query=case["query"], employee_id=EVAL_EMPLOYEE_ID))
        assert result["model_used"].startswith("mcp:"), f"{case['id']} did not take the deterministic bypass"


async def test_llm_call_cases_do_not_accidentally_match_mcp_keywords():
    cases = _load_cases_by_call_type("llm_call")
    assert cases, "expected at least one llm_call golden case"

    for case in cases:
        assert not mcp_tools.is_leave_balance_query(case["query"]), f"{case['id']} unexpectedly matches balance keywords"
        assert not mcp_tools.is_leave_history_query(case["query"]), f"{case['id']} unexpectedly matches history keywords"
