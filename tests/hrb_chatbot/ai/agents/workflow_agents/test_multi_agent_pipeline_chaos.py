"""Chaos/failure-injection testing (Phase 74) - the real backend-down cases
were already seen by accident during Phase 64/67/70's own live testing
(hrb_lms_mcp genuinely unreachable) but never exercised by a deliberate,
repeatable test. This deliberately forces one domain agent to fail and
confirms the other agents' real results still reach the Reviewer, and the
final answer stays coherent - not that the whole graph fails closed."""

import pytest

from src.hrb_chatbot.ai.agents.workflow_agents import multi_agent_pipeline
from tests.conftest import FakeDBGateway


@pytest.fixture(autouse=True)
def _fake_cache_and_eval_judges(monkeypatch):
    """Phase 110/115: run_multi_agent() now calls get_db_gateway().answer_cache()
    and the real eval-judge functions on every call - fake both, same
    reasoning as test_multi_agent_pipeline.py's own fixture (this file has
    its own fixtures, not shared with that one)."""
    gateway = FakeDBGateway()
    monkeypatch.setattr(multi_agent_pipeline, "get_db_gateway", lambda: gateway)

    async def _fake_generate_follow_ups(query, answer):
        return []

    monkeypatch.setattr(multi_agent_pipeline.reviewer_agent, "generate_follow_ups", _fake_generate_follow_ups)
    monkeypatch.setattr(
        multi_agent_pipeline,
        "evaluate_groundedness",
        lambda answer, context_texts: {"score": 0.9, "verdict": "GROUNDED", "explanation": "fake"},
    )
    monkeypatch.setattr(
        multi_agent_pipeline,
        "evaluate_completeness",
        lambda query, answer, reference_answer=None: {"score": 0.9, "verdict": "COMPLETE", "explanation": "fake"},
    )


def _patch_guardrails(monkeypatch):
    async def _passthrough_check_input(query):
        return query

    async def _passthrough_check_output(query, answer):
        return answer

    monkeypatch.setattr(multi_agent_pipeline, "check_input", _passthrough_check_input)
    monkeypatch.setattr(multi_agent_pipeline, "check_output", _passthrough_check_output)


async def test_one_domain_agent_failing_does_not_crash_the_graph_or_drop_the_others(monkeypatch):
    _patch_guardrails(monkeypatch)

    async def _fake_plan(query):
        return [
            {"agent": "vector_kb_agent", "focus": "parental leave policy"},
            {"agent": "lms_ops_agent", "focus": "my leave balance"},
        ], {"label": "planner"}

    async def _fake_vector_kb_run(focus):
        return "8 weeks paid.", []

    async def _failing_lms_ops_run(focus, employee_id):
        # A real MCP failure returns an error string, never a raised exception.
        return "Error: leave balance lookup failed (connection refused).", []

    captured_agent_results = {}

    async def _capturing_review(query, agent_results):
        captured_agent_results["value"] = agent_results
        return "Parental leave is 8 weeks paid. Your leave balance lookup failed.", {"label": "reviewer"}

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)
    monkeypatch.setattr(multi_agent_pipeline.lms_ops_agent, "run", _failing_lms_ops_run)
    monkeypatch.setattr(multi_agent_pipeline.reviewer_agent, "review", _capturing_review)

    result = await multi_agent_pipeline.run_multi_agent(
        "what is the parental leave policy and what's my leave balance?", employee_id="EMP052"
    )

    assert result["answer"] == "Parental leave is 8 weeks paid. Your leave balance lookup failed."
    agents_seen = {r["agent"] for r in captured_agent_results["value"]}
    assert agents_seen == {"vector_kb_agent", "lms_ops_agent"}
    vector_kb_result = next(r for r in captured_agent_results["value"] if r["agent"] == "vector_kb_agent")
    assert vector_kb_result["result"] == "8 weeks paid."


async def test_a_domain_agent_node_raising_outright_propagates_rather_than_silently_dropping(monkeypatch):
    """If a domain agent's own run() breaks its never-raise contract, the graph
    should surface that loudly (a real bug to fix), not silently swallow it
    and return a half-wrong answer as if nothing happened."""
    _patch_guardrails(monkeypatch)

    async def _fake_plan(query):
        return [{"agent": "vector_kb_agent", "focus": "parental leave policy"}], {"label": "planner"}

    async def _raising_vector_kb_run(focus):
        raise RuntimeError("unexpected failure inside the tool wrapper")

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _raising_vector_kb_run)

    raised = False
    try:
        await multi_agent_pipeline.run_multi_agent("what is the parental leave policy?", employee_id="EMP052")
    except RuntimeError:
        raised = True

    assert raised
