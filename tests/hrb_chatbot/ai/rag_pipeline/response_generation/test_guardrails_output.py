"""Tests for check_output() (guardrails_output/__init__.py) - Gate 6.
get_rails() is faked, so no real LLM call and no API key needed.

Phase 229 - check_output() now calls generate_async() directly (not NeMo's
own check_async() convenience wrapper - see guardrails_input.py's
check_input() docstring for why), so these fakes stand in for
generate_async()'s real response shape (.response / .log.activated_rails),
not check_async()'s simpler one."""

from src.hrb_chatbot.ai.rag_pipeline.response_generation import guardrails_output
from src.hrb_chatbot.ai.rag_pipeline.response_generation.guardrails_output import SAFE_FALLBACK_ANSWER, check_output


class FakeActivatedRail:
    def __init__(self, name, decisions=None, stop=False):
        self.name = name
        self.decisions = decisions or []
        self.stop = stop


class FakeLog:
    def __init__(self, activated_rails):
        self.activated_rails = activated_rails


class FakeGenerateResponse:
    def __init__(self, content, activated_rails=None):
        self.response = [{"role": "assistant", "content": content}]
        self.log = FakeLog(activated_rails or [])


class FakeRails:
    """Stands in for nemoguardrails.LLMRails - no real LLM call."""

    def __init__(self, response: FakeGenerateResponse):
        self._response = response

    async def generate_async(self, messages, options=None):
        return self._response


async def test_a_normal_answer_passes_through_unchanged(monkeypatch):
    answer = "You get 16 weeks of parental leave."
    activated = [
        FakeActivatedRail("self check output", decisions=["execute self_check_output"]),
        FakeActivatedRail("mask sensitive data on output", decisions=["execute mask_sensitive_data"]),
    ]
    monkeypatch.setattr(guardrails_output, "get_rails", lambda: FakeRails(FakeGenerateResponse(answer, activated)))

    result, status = await check_output("How much leave?", answer)

    assert result == answer
    assert status["status"] == "pass"
    assert status["rail"] is None
    assert status["activated_rails"] == [
        {"name": "self check output", "decisions": ["execute self_check_output"], "stop": False},
        {"name": "mask sensitive data on output", "decisions": ["execute mask_sensitive_data"], "stop": False},
    ]


async def test_a_blocked_answer_returns_the_safe_fallback(monkeypatch):
    activated = [
        FakeActivatedRail(
            "self check output",
            decisions=["execute self_check_output", "refuse to respond", "stop"],
            stop=True,
        )
    ]
    response = FakeGenerateResponse("I'm sorry, I can't respond to that.", activated)
    monkeypatch.setattr(guardrails_output, "get_rails", lambda: FakeRails(response))

    result, status = await check_output("test", "some unsafe answer")

    assert result == SAFE_FALLBACK_ANSWER
    assert status["status"] == "blocked"
    assert status["rail"] == "self check output"
    assert status["activated_rails"][0]["stop"] is True


async def test_a_modified_answer_returns_the_masked_text(monkeypatch):
    activated = [
        FakeActivatedRail("self check output", decisions=["execute self_check_output"]),
        FakeActivatedRail("mask sensitive data on output", decisions=["execute mask_sensitive_data"]),
    ]
    monkeypatch.setattr(
        guardrails_output, "get_rails", lambda: FakeRails(FakeGenerateResponse("Contact <MASKED>", activated))
    )

    result, status = await check_output("test", "Contact john@example.com")

    assert result == "Contact <MASKED>"
    # Confirmed against NeMo's own check_async() logic: a MODIFIED result
    # is never attributed to one specific rail name - rail stays null,
    # activated_rails carries the real per-rail detail instead.
    assert status["status"] == "modified"
    assert status["rail"] is None
    assert status["activated_rails"] == [
        {"name": "self check output", "decisions": ["execute self_check_output"], "stop": False},
        {"name": "mask sensitive data on output", "decisions": ["execute mask_sensitive_data"], "stop": False},
    ]


async def test_a_known_safe_term_is_protected_before_the_guardrail_check(monkeypatch):
    """Phase 113 - "Roth" must reach the guardrail wrapped, not bare, so
    Presidio's NER can't tag it as PERSON (confirmed live: it scores
    0.85, the same as a genuine name)."""
    captured = {}

    class SpyRails:
        async def generate_async(self, messages, options=None):
            captured["messages"] = messages
            return FakeGenerateResponse(messages[-1]["content"])

    monkeypatch.setattr(guardrails_output, "get_rails", lambda: SpyRails())

    answer = "You can make Roth contributions."
    await check_output("test", answer)

    sent_content = captured["messages"][-1]["content"]
    assert sent_content != answer
    assert "⁦Roth⁩" in sent_content
