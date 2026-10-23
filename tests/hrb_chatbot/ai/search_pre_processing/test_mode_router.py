"""Phase 240 - classify_query_complexity() tests, same structured-output
fake pattern as test_query_decompose.py (the LLM itself is faked, no real
API call)."""

from src.hrb_chatbot.ai.search_pre_processing import mode_router
from src.hrb_chatbot.ai.search_pre_processing.mode_router import ModeClassification


class FakeRawResponse:
    usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


class FakeStructuredLlm:
    def __init__(self, parsed, raise_error=None):
        self._parsed = parsed
        self._raise_error = raise_error

    async def ainvoke(self, messages):
        if self._raise_error:
            raise self._raise_error
        return {"raw": FakeRawResponse(), "parsed": self._parsed, "parsing_error": None}


class FakeLlm:
    def __init__(self, parsed, raise_error=None):
        self._parsed = parsed
        self._raise_error = raise_error

    def with_structured_output(self, schema, include_raw=False):
        return FakeStructuredLlm(self._parsed, self._raise_error)


def _patch_llm(monkeypatch, parsed=None, raise_error=None):
    monkeypatch.setattr(mode_router, "_build_llm", lambda router_model=None: FakeLlm(parsed, raise_error))


async def test_single_domain_question_classifies_as_single(monkeypatch):
    _patch_llm(monkeypatch, ModeClassification(mode="single"))

    mode = await mode_router.classify_query_complexity("What's the dental plan?")

    assert mode == "single"


async def test_multi_domain_question_classifies_as_multi(monkeypatch):
    _patch_llm(monkeypatch, ModeClassification(mode="multi"))

    mode = await mode_router.classify_query_complexity(
        "What's the parental leave policy and how many PTO days do I have left?"
    )

    assert mode == "multi"


async def test_parsing_failure_falls_back_to_single(monkeypatch):
    _patch_llm(monkeypatch, None)

    mode = await mode_router.classify_query_complexity("hello")

    assert mode == "single"


async def test_llm_call_failure_falls_back_to_single_not_a_crash(monkeypatch):
    _patch_llm(monkeypatch, raise_error=RuntimeError("OpenAI is down"))

    mode = await mode_router.classify_query_complexity("hello")

    assert mode == "single"
