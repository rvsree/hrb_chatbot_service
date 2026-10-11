"""Phase 130 - decompose() tests, same structured-output fake pattern as
test_planner_agent.py (the LLM itself is faked, no real API call)."""

from src.hrb_chatbot.ai.pre_processing import query_decompose
from src.hrb_chatbot.ai.pre_processing.query_decompose import DecomposedQuery


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
    monkeypatch.setattr(query_decompose, "_build_llm", lambda: FakeLlm(parsed, raise_error))


async def test_atomic_question_returns_one_sub_question(monkeypatch):
    _patch_llm(monkeypatch, DecomposedQuery(sub_questions=["what is the dental plan?"]))

    sub_questions = await query_decompose.decompose("what is the dental plan?")

    assert sub_questions == ["what is the dental plan?"]


async def test_compound_question_returns_multiple_sub_questions(monkeypatch):
    _patch_llm(
        monkeypatch,
        DecomposedQuery(
            sub_questions=["Is the 401k employer match immediately vested?", "How many PTO days do I have?"]
        ),
    )

    sub_questions = await query_decompose.decompose(
        "Whether 401(k) employer contributions immediately vested, how many days of PTO I have"
    )

    assert sub_questions == ["Is the 401k employer match immediately vested?", "How many PTO days do I have?"]


async def test_empty_sub_questions_falls_back_to_the_original_query(monkeypatch):
    _patch_llm(monkeypatch, DecomposedQuery(sub_questions=[]))

    sub_questions = await query_decompose.decompose("hello")

    assert sub_questions == ["hello"]


async def test_parsing_failure_falls_back_to_the_original_query(monkeypatch):
    _patch_llm(monkeypatch, None)

    sub_questions = await query_decompose.decompose("hello")

    assert sub_questions == ["hello"]


async def test_llm_call_failure_falls_back_to_the_original_query_not_a_crash(monkeypatch):
    _patch_llm(monkeypatch, raise_error=RuntimeError("OpenAI is down"))

    sub_questions = await query_decompose.decompose("hello")

    assert sub_questions == ["hello"]


async def test_blank_sub_questions_are_filtered_out(monkeypatch):
    _patch_llm(monkeypatch, DecomposedQuery(sub_questions=["real question", "  ", ""]))

    sub_questions = await query_decompose.decompose("real question")

    assert sub_questions == ["real question"]
