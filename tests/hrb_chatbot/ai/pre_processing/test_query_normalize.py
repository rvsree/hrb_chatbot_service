"""Phase 173 - normalize_query() tests, same structured-output fake
pattern as test_query_decompose.py (the LLM itself is faked, no real API call)."""

from src.hrb_chatbot.ai.pre_processing import query_normalize
from src.hrb_chatbot.ai.pre_processing.query_normalize import NormalizedQuery


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
    monkeypatch.setattr(query_normalize, "_build_llm", lambda: FakeLlm(parsed, raise_error))


async def test_a_typo_is_corrected(monkeypatch):
    _patch_llm(monkeypatch, NormalizedQuery(normalized_query="What is my leave balance?"))

    result = await query_normalize.normalize_query("wat is my leav balance")

    assert result == "What is my leave balance?"


async def test_an_already_clean_query_is_returned_unchanged(monkeypatch):
    _patch_llm(monkeypatch, NormalizedQuery(normalized_query="What is my leave balance?"))

    result = await query_normalize.normalize_query("What is my leave balance?")

    assert result == "What is my leave balance?"


async def test_blank_query_is_returned_unchanged_without_calling_the_llm(monkeypatch):
    def _fail_if_called():
        raise AssertionError("_build_llm() should not be called for a blank query")

    monkeypatch.setattr(query_normalize, "_build_llm", _fail_if_called)

    result = await query_normalize.normalize_query("   ")

    assert result == "   "


async def test_empty_normalized_result_falls_back_to_the_original_query(monkeypatch):
    _patch_llm(monkeypatch, NormalizedQuery(normalized_query="  "))

    result = await query_normalize.normalize_query("wat is my leav balance")

    assert result == "wat is my leav balance"


async def test_parsing_failure_falls_back_to_the_original_query(monkeypatch):
    _patch_llm(monkeypatch, None)

    result = await query_normalize.normalize_query("wat is my leav balance")

    assert result == "wat is my leav balance"


async def test_llm_call_failure_falls_back_to_the_original_query_not_a_crash(monkeypatch):
    _patch_llm(monkeypatch, raise_error=RuntimeError("OpenAI is down"))

    result = await query_normalize.normalize_query("wat is my leav balance")

    assert result == "wat is my leav balance"
