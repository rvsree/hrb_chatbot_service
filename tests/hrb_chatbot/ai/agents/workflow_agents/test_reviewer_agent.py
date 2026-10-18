"""Reviewer Agent tests - 0 results short-circuits; 1+ always goes through the LLM
(Phase 150 - a single domain agent's raw result, e.g. vector_kb_agent's
"Found relevant knowledge base content:..." dump, is meta/intermediate text,
never a presentable answer on its own, so 1 result can't skip synthesis
the way 0 results can)."""

from src.hrb_chatbot.ai.agents.workflow_agents import reviewer_agent


class FakeResponse:
    def __init__(self, content):
        self.content = content
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class FakeLlm:
    def __init__(self, response):
        self._response = response

    async def ainvoke(self, messages, config=None):
        return self._response


def _patch_llm(monkeypatch, content):
    monkeypatch.setattr(reviewer_agent, "_build_llm", lambda: FakeLlm(FakeResponse(content)))


async def test_zero_results_gives_a_clear_fallback():
    answer, turn = await reviewer_agent.review("what is the policy?", [])

    assert "wasn't able to find" in answer
    assert turn is None


async def test_one_result_still_goes_through_the_llm(monkeypatch):
    # Phase 150: a single vector_kb_agent result is raw "Found relevant
    # knowledge base content:..." framing text, not a final answer - must
    # be synthesized, not returned verbatim.
    _patch_llm(monkeypatch, "Parental leave is 8 weeks paid.")

    answer, turn = await reviewer_agent.review(
        "what is the parental leave policy?",
        [
            {
                "agent": "vector_kb_agent",
                "focus": "parental leave policy",
                "result": "Found relevant knowledge base content:\n\n--- Source 1 (policy.pdf) ---\n8 weeks paid.",
            }
        ],
    )

    assert answer == "Parental leave is 8 weeks paid."
    assert turn["label"] == "reviewer"


async def test_two_or_more_results_are_merged_by_the_llm(monkeypatch):
    _patch_llm(monkeypatch, "Parental leave is 8 weeks paid. Your current balance is 10 days.")

    answer, turn = await reviewer_agent.review(
        "what is the parental leave policy and what's my leave balance?",
        [
            {"agent": "vector_kb_agent", "focus": "parental leave policy", "result": "8 weeks paid."},
            {"agent": "lms_ops_agent", "focus": "my leave balance", "result": "10 days available."},
        ],
    )

    assert answer == "Parental leave is 8 weeks paid. Your current balance is 10 days."
    assert turn["label"] == "reviewer"


class _CapturingLlm:
    def __init__(self, response, captured_calls):
        self._response = response
        self._captured_calls = captured_calls

    async def ainvoke(self, messages, config=None):
        self._captured_calls.append(messages)
        return self._response


async def test_tabular_instruction_added_when_query_says_summarize(monkeypatch):
    captured_calls = []
    monkeypatch.setattr(
        reviewer_agent, "_build_llm", lambda: _CapturingLlm(FakeResponse("| a | b |"), captured_calls)
    )

    await reviewer_agent.review(
        "summarize my benefits",
        [
            {"agent": "vector_kb_agent", "focus": "benefits", "result": "8 weeks paid."},
            {"agent": "lms_ops_agent", "focus": "balance", "result": "10 days available."},
        ],
    )

    system_message = captured_calls[0][0]
    assert "markdown table" in system_message.content


async def test_tabular_instruction_absent_for_a_plain_query(monkeypatch):
    captured_calls = []
    monkeypatch.setattr(
        reviewer_agent, "_build_llm", lambda: _CapturingLlm(FakeResponse("8 weeks paid, 10 days available."), captured_calls)
    )

    await reviewer_agent.review(
        "what is the leave policy and my balance?",
        [
            {"agent": "vector_kb_agent", "focus": "benefits", "result": "8 weeks paid."},
            {"agent": "lms_ops_agent", "focus": "balance", "result": "10 days available."},
        ],
    )

    system_message = captured_calls[0][0]
    assert "markdown table" not in system_message.content


async def test_generate_follow_ups_parses_one_question_per_line(monkeypatch):
    _patch_llm(monkeypatch, "What is my dental plan?\nHow do I enroll in a 401(k)?\n")

    follow_ups = await reviewer_agent.generate_follow_ups("What is my PTO balance?", "You have 10 days left.")

    assert follow_ups == ["What is my dental plan?", "How do I enroll in a 401(k)?"]


async def test_generate_follow_ups_returns_empty_list_on_llm_failure(monkeypatch):
    class _FailingLlm:
        async def ainvoke(self, messages, config=None):
            raise RuntimeError("LLM is down")

    monkeypatch.setattr(reviewer_agent, "_build_llm", lambda: _FailingLlm())

    follow_ups = await reviewer_agent.generate_follow_ups("What is my PTO balance?", "You have 10 days left.")

    assert follow_ups == []
