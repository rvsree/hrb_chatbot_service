"""Planner Agent tests - the LLM itself is faked (no real API call), matching
test_orchestration_agent.py's own pattern, but for a structured-output call
(.with_structured_output(..., include_raw=True).ainvoke()) instead of a
tool-calling loop. include_raw=True (Phase 66) is what exposes token usage -
the fake mirrors that same {"raw", "parsed"} dict shape."""

from src.hrb_chatbot.ai.agents.workflow_agents import planner_agent
from src.hrb_chatbot.ai.agents.workflow_agents.planner_agent import PlannerOutput, PlannerTask


class FakeRawResponse:
    usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    content = ""


class FakeStructuredLlm:
    def __init__(self, parsed):
        self._parsed = parsed

    async def ainvoke(self, messages):
        return {"raw": FakeRawResponse(), "parsed": self._parsed, "parsing_error": None}


class FakeLlm:
    def __init__(self, parsed):
        self._parsed = parsed

    def with_structured_output(self, schema, include_raw=False):
        return FakeStructuredLlm(self._parsed)


def _patch_llm(monkeypatch, parsed):
    monkeypatch.setattr(planner_agent, "_build_llm", lambda: FakeLlm(parsed))


async def test_single_task_routes_to_one_agent(monkeypatch):
    _patch_llm(
        monkeypatch,
        PlannerOutput(tasks=[PlannerTask(agent="vector_kb_agent", focus="parental leave policy")]),
    )

    tasks, turn = await planner_agent.plan("what is the parental leave policy?")

    assert tasks == [{"agent": "vector_kb_agent", "focus": "parental leave policy"}]
    assert turn["label"] == "planner"


async def test_multi_part_question_routes_to_multiple_agents(monkeypatch):
    _patch_llm(
        monkeypatch,
        PlannerOutput(
            tasks=[
                PlannerTask(agent="vector_kb_agent", focus="parental leave policy"),
                PlannerTask(agent="lms_ops_agent", focus="my leave balance"),
            ]
        ),
    )

    tasks, turn = await planner_agent.plan("what is the parental leave policy and what's my leave balance?")

    assert tasks == [
        {"agent": "vector_kb_agent", "focus": "parental leave policy"},
        {"agent": "lms_ops_agent", "focus": "my leave balance"},
    ]


async def test_empty_tasks_falls_back_to_vector_kb_agent(monkeypatch):
    _patch_llm(monkeypatch, PlannerOutput(tasks=[]))

    tasks, turn = await planner_agent.plan("hello")

    assert tasks == [{"agent": "vector_kb_agent", "focus": "hello"}]


async def test_parsing_failure_falls_back_to_vector_kb_agent_instead_of_crashing(monkeypatch):
    _patch_llm(monkeypatch, None)

    tasks, turn = await planner_agent.plan("hello")

    assert tasks == [{"agent": "vector_kb_agent", "focus": "hello"}]
