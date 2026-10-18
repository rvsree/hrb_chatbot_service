"""Phase 67 - validates the Planner/Reviewer behave correctly on the golden
dataset's 2 multi-part cases (resources/golden_dataset/golden_dataset.json,
ids multi-agent-same-domain-01/multi-agent-cross-domain-01). Real LLM calls,
real cost - excluded from the default suite, run with `pytest -m eval -v`.
Not mocked on purpose, same reasoning as test_golden_dataset_harness.py:
this is the one place Planner routing/Reviewer merge quality is checked
against real data, for real - not the quantitative scoring (that's
Phase 69's job), just "did it route and merge sensibly."""

import json

import pytest

from src.hrb_chatbot.ai.agents.workflow_agents.multi_agent_pipeline import run_multi_agent

pytestmark = pytest.mark.eval

GOLDEN_DATASET_PATH = "resources/golden_dataset/golden_dataset.json"
EVAL_EMPLOYEE_ID = "EMP052"


def _load_case(case_id: str) -> dict:
    with open(GOLDEN_DATASET_PATH, encoding="utf-8") as file:
        data = json.load(file)
    return next(case for case in data["cases"] if case["id"] == case_id)


async def test_same_domain_compound_question_covers_both_topics():
    case = _load_case("multi-agent-same-domain-01")

    result = await run_multi_agent(case["query"], employee_id=EVAL_EMPLOYEE_ID)

    agents_used = {task["agent"] for task in result["tasks"]}
    assert set(case["expected_agents"]) <= agents_used

    answer_lower = result["answer"].lower()
    assert "100%" in result["answer"] or "5%" in result["answer"]
    assert "$7,500" in result["answer"]
    assert "401k" in answer_lower or "tuition" in answer_lower or len(result["tasks"]) >= 1


async def test_cross_domain_question_routes_to_both_agents_and_covers_the_kb_half():
    case = _load_case("multi-agent-cross-domain-01")

    result = await run_multi_agent(case["query"], employee_id=EVAL_EMPLOYEE_ID)

    agents_used = {task["agent"] for task in result["tasks"]}
    assert set(case["expected_agents"]) <= agents_used
    assert "16" in result["answer"] and "week" in result["answer"].lower()
