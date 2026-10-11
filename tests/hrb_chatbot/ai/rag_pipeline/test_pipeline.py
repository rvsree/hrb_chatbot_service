"""Tests for answer_query()'s default-resolution logic (ai/rag_pipeline/
pipeline.py) - top_k/temperature/search_strategy fall back to .env
(RAG_DEFAULT_TOP_K/RAG_DEFAULT_TEMPERATURE/RAG_DEFAULT_SEARCH_STRATEGY) when
the request omits them, not a hardcoded literal (Phase 38). retrieve_chunks/
generate_answer are faked - no real network call, this only tests the
resolution branching."""

import pytest

from src.hrb_chatbot.ai.pre_processing import conversation_memory
from src.hrb_chatbot.ai.rag_core import guarded_pipeline
from src.hrb_chatbot.ai.rag_pipeline import pipeline
from src.hrb_chatbot.common.rag_query_params import RagQueryParams
from tests.conftest import FakeConversationStore, FakeDBGateway


@pytest.fixture(autouse=True)
def _fake_answer_cache(monkeypatch):
    """Phase 78: pipeline.py now calls get_db_gateway().answer_cache() on every
    answer_query() call - fake it for every test in this file, or tests would
    hit real Postgres (confirmed live: one unfaked run got served a real,
    stale cache hit from an earlier live-verification query, short-circuiting
    the very resolution logic this file exists to test)."""
    gateway = FakeDBGateway()
    monkeypatch.setattr(pipeline, "get_db_gateway", lambda: gateway)


@pytest.fixture(autouse=True)
def _fake_eval_judges(monkeypatch):
    """Phase 109: answer_query() now scores every live (non-empty-sources)
    answer via evaluate_groundedness()/evaluate_completeness(), which make
    a real OpenAI call each - fake both for every test in this file, or a
    test with non-empty fake chunks silently costs money and takes real
    network latency (confirmed: this file's run time went from ~4s to
    ~40s before this fixture was added)."""
    monkeypatch.setattr(
        pipeline,
        "evaluate_groundedness",
        lambda answer, context_texts: {"score": 0.9, "verdict": "GROUNDED", "explanation": "fake"},
    )
    monkeypatch.setattr(
        pipeline,
        "evaluate_completeness",
        lambda query, answer, reference_answer=None: {"score": 0.9, "verdict": "COMPLETE", "explanation": "fake"},
    )


@pytest.fixture(autouse=True)
def _fake_decompose(monkeypatch):
    """Phase 130: generate() now calls decompose() on every live call, a real
    OpenAI structured-output call - fake it as a no-op (always 1 sub-question,
    the original query unchanged) for every test in this file except the ones
    that explicitly test decomposition itself, which override this."""

    async def _passthrough_decompose(query):
        return [query]

    monkeypatch.setattr(pipeline, "decompose", _passthrough_decompose)


def _patch_conversation_store(monkeypatch, conversation_store=None):
    gateway = FakeDBGateway(conversation_store=conversation_store or FakeConversationStore())
    monkeypatch.setattr(conversation_memory, "get_db_gateway", lambda: gateway)
    return gateway


def _fake_retrieve_chunks_capturing(captured, chunks=None):
    async def _fake(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        captured["top_k"] = top_k
        captured["search_strategy"] = search_strategy
        return (chunks or [], None)

    return _fake


def _fake_generate_answer_capturing(captured):
    def _fake(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        captured["temperature"] = temperature
        return {"answer": "fake answer", "model_used": "gpt-4.1-mini"}

    return _fake


# Guardrails pass the query/answer through unchanged - these tests are about
# top_k/temperature resolution, not guardrail behavior (see test_pipeline_guardrails.py).
async def _fake_check_input(query):
    return query


async def _fake_check_output(query, answer):
    return answer


def _patch_guardrails(monkeypatch):
    # check_input is still called directly in pipeline.py (the MCP fast-path
    # needs it before deciding whether to short-circuit); check_output only
    # exists in the Phase 98 shared core now - genai-rag's own path never
    # calls it a second time, since pipeline.py passes pre_checked_query.
    monkeypatch.setattr(pipeline, "check_input", _fake_check_input)
    monkeypatch.setattr(guarded_pipeline, "check_output", _fake_check_output)


async def test_omitted_top_k_and_search_strategy_use_env_defaults(monkeypatch):
    captured = {}
    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve_chunks_capturing(captured))
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate_answer_capturing(captured))

    await pipeline.answer_query(RagQueryParams(query="How much leave?"))

    assert captured["top_k"] == 5  # RAG_DEFAULT_TOP_K in .env
    assert captured["search_strategy"] == "similarity"  # RAG_DEFAULT_SEARCH_STRATEGY in .env


async def test_explicit_top_k_and_search_strategy_are_not_overridden(monkeypatch):
    captured = {}
    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve_chunks_capturing(captured))
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate_answer_capturing(captured))

    await pipeline.answer_query(RagQueryParams(query="test", top_k=3, search_strategy="mmr"))

    assert captured["top_k"] == 3
    assert captured["search_strategy"] == "mmr"


async def test_omitted_temperature_uses_env_default(monkeypatch):
    captured = {}
    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve_chunks_capturing(captured))
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate_answer_capturing(captured))

    await pipeline.answer_query(RagQueryParams(query="test"))

    assert captured["temperature"] == 0.0  # RAG_DEFAULT_TEMPERATURE in .env


async def test_explicit_temperature_zero_is_not_treated_as_omitted(monkeypatch):
    """The real edge case this resolution has to get right: `params.temperature
    or default` would wrongly replace an explicit 0.0 (falsy) with the .env
    default - the code must check `is None`, not truthiness."""
    captured = {}
    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve_chunks_capturing(captured))
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate_answer_capturing(captured))

    await pipeline.answer_query(RagQueryParams(query="test", temperature=0.0))

    assert captured["temperature"] == 0.0


async def test_explicit_nonzero_temperature_passes_through(monkeypatch):
    captured = {}
    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve_chunks_capturing(captured))
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate_answer_capturing(captured))

    await pipeline.answer_query(RagQueryParams(query="test", temperature=0.7))

    assert captured["temperature"] == 0.7


async def test_result_echoes_back_the_resolved_temperature(monkeypatch):
    # Phase 127 - Explainability needs the actual value used, not just what was requested.
    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve_chunks_capturing({}))
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate_answer_capturing({}))

    result = await pipeline.answer_query(RagQueryParams(query="test", temperature=0.7))

    assert result["temperature"] == 0.7


# Phase 49: a matched query short-circuits before retrieve_chunks/generate_answer
# are ever called - the two spies below prove retrieval/generation were skipped.
async def test_mcp_routable_query_skips_retrieval_and_generation(monkeypatch):
    called = {"retrieve": False, "generate": False}

    async def _spy_retrieve_chunks(*args, **kwargs):
        called["retrieve"] = True
        return [], None

    def _spy_generate_answer(*args, **kwargs):
        called["generate"] = True
        return {"answer": "should not be used", "model_used": "gpt-4.1-mini"}

    async def _fake_try_route_to_mcp(query, employee_id):
        return {"query": query, "answer": "MCP answer", "model_used": None, "sources": [],
                "vector_db": None, "search_strategy": None, "applied_filter": None, "routed_to": "get_leave_balance",
                "mcp_arguments": {"employee_id": employee_id}, "mcp_raw_result": ["MCP answer"]}

    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _spy_retrieve_chunks)
    monkeypatch.setattr(pipeline, "generate_answer", _spy_generate_answer)
    monkeypatch.setattr(pipeline, "try_route_to_mcp", _fake_try_route_to_mcp)

    result = await pipeline.answer_query(RagQueryParams(query="What's my PTO balance?", employee_id="EMP052"))

    assert result["answer"] == "MCP answer"
    assert called["retrieve"] is False
    assert called["generate"] is False


async def test_mcp_routed_answer_builds_a_real_tools_used_entry(monkeypatch):
    # Phase 126
    async def _fake_try_route_to_mcp(query, employee_id):
        return {
            "query": query, "answer": "You have 12 days left.", "model_used": "mcp:get_leave_balance", "sources": [],
            "vector_db": None, "search_strategy": None, "applied_filter": None,
            "routed_to": "get_leave_balance", "tool_latency_ms": 42.5,
            "mcp_arguments": {"employee_id": employee_id}, "mcp_raw_result": ["You have 12 days left."],
        }

    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "try_route_to_mcp", _fake_try_route_to_mcp)

    result = await pipeline.answer_query(RagQueryParams(query="What's my PTO balance?", employee_id="EMP052"))

    assert len(result["tools_used"]) == 1
    call = result["tools_used"][0]
    assert call["tool_name"] == "get_leave_balance"
    assert call["tool_type"] == "mcp"
    assert call["latency_ms"] == 42.5
    assert call["success"] is True


# Phase 58: server-side conversation memory - disabled by default, opt-in
# via RagQueryParams.enable_conversation_memory.
async def test_conversation_memory_disabled_by_default_no_conversation_id(monkeypatch):
    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve_chunks_capturing({}))
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate_answer_capturing({}))

    result = await pipeline.answer_query(RagQueryParams(query="test"))

    assert result["conversation_id"] is None


async def test_enabling_conversation_memory_generates_and_saves_a_turn(monkeypatch):
    _patch_conversation_store(monkeypatch)
    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve_chunks_capturing({}, chunks=[{"filename": "x", "chunk_index": 0, "text": "y"}]))
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate_answer_capturing({}))

    result = await pipeline.answer_query(RagQueryParams(query="test question", enable_conversation_memory=True))

    assert result["conversation_id"] is not None
    saved = await conversation_memory.load_history(result["conversation_id"])
    assert [m.content for m in saved] == ["test question", "fake answer"]


async def test_mcp_routed_answer_saves_a_turn_like_any_other_answer(monkeypatch):
    # Phase 151: a separate top-level MCP shortcut used to bypass
    # run_guarded_pipeline() entirely (and so never called
    # conversation_memory.save_turn() for an MCP-routed answer) - removed
    # because it also silently dropped the rest of a compound query. MCP
    # routing now always goes through _answer_sub_question() -> the shared
    # core, so it saves a turn like every other answer, matching how
    # single/multi-agentic-rag already save MCP-routed answers too.
    _patch_conversation_store(monkeypatch)

    async def _fake_try_route_to_mcp(query, employee_id):
        return {"query": query, "answer": "MCP answer", "model_used": "mcp:x", "sources": [],
                "vector_db": "n/a (mcp)", "search_strategy": "n/a (mcp)", "applied_filter": None,
                "routed_to": "x", "tool_latency_ms": 50.0,
                "mcp_arguments": {"employee_id": employee_id}, "mcp_raw_result": ["MCP answer"]}

    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(pipeline, "try_route_to_mcp", _fake_try_route_to_mcp)

    result = await pipeline.answer_query(
        RagQueryParams(query="What's my PTO balance?", employee_id="EMP052", enable_conversation_memory=True)
    )

    assert result["conversation_id"] is not None
    saved = await conversation_memory.load_history(result["conversation_id"])
    assert [m.content for m in saved] == ["What's my PTO balance?", "MCP answer"]


async def test_an_existing_conversation_id_is_passed_to_generate_answer_as_chat_history(monkeypatch):
    conversation_store = FakeConversationStore()
    _patch_conversation_store(monkeypatch, conversation_store)
    await conversation_memory.save_turn("conv-1", "EMP052", "earlier question", "earlier answer")
    captured = {}
    _patch_guardrails(monkeypatch)
    monkeypatch.setattr(
        pipeline,
        "retrieve_chunks",
        _fake_retrieve_chunks_capturing(captured, chunks=[{"filename": "x", "chunk_index": 0, "text": "y"}]),
    )

    def _fake_generate_answer(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        captured["chat_history"] = chat_history
        return {"answer": "fake answer", "model_used": "gpt-4.1-mini"}

    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate_answer)

    await pipeline.answer_query(
        RagQueryParams(query="follow-up question", enable_conversation_memory=True, conversation_id="conv-1")
    )

    assert [m.content for m in captured["chat_history"]] == ["earlier question", "earlier answer"]


async def test_a_cache_hit_skips_retrieval_and_generation_entirely(monkeypatch):
    """Phase 78 - the second identical call must not touch retrieve_chunks/
    generate_answer at all, not just return the same answer by coincidence."""
    _patch_guardrails(monkeypatch)
    call_count = {"retrieve": 0, "generate": 0}

    async def _counting_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        call_count["retrieve"] += 1
        return ([{"filename": "x", "chunk_index": 0, "text": "y"}], None)

    def _counting_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        call_count["generate"] += 1
        return {"answer": "fake answer", "model_used": "gpt-4.1-mini"}

    monkeypatch.setattr(pipeline, "retrieve_chunks", _counting_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _counting_generate)

    first = await pipeline.answer_query(RagQueryParams(query="what is the parental leave policy?"))
    second = await pipeline.answer_query(RagQueryParams(query="what is the parental leave policy?"))

    assert call_count == {"retrieve": 1, "generate": 1}  # only the first call did real work
    assert first["answer"] == second["answer"] == "fake answer"


async def test_two_fresh_memory_enabled_conversations_can_share_a_cache_hit(monkeypatch):
    """Phase 101 - the FIRST message of a memory-enabled conversation has no
    prior turns yet, so it's just as cacheable as a non-memory query. Two
    independent fresh conversations asking the identical question should
    share one cache entry, each still getting its OWN conversation_id."""
    _patch_conversation_store(monkeypatch)
    _patch_guardrails(monkeypatch)
    call_count = {"generate": 0}

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "x", "chunk_index": 0, "text": "y"}], None)

    def _counting_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        call_count["generate"] += 1
        return {"answer": f"answer #{call_count['generate']}", "model_used": "gpt-4.1-mini"}

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _counting_generate)

    first = await pipeline.answer_query(RagQueryParams(query="what is my balance?", enable_conversation_memory=True))
    second = await pipeline.answer_query(RagQueryParams(query="what is my balance?", enable_conversation_memory=True))

    assert call_count["generate"] == 1  # second call was cache-served, not a real generation
    assert first["answer"] == second["answer"] == "answer #1"
    assert first["conversation_id"] != second["conversation_id"]  # never leaks one caller's id to another

    # The cache-served turn was still saved under THIS caller's own
    # conversation - a follow-up in conversation #2 still has it in history.
    saved = await conversation_memory.load_history(second["conversation_id"])
    assert [m.content for m in saved] == ["what is my balance?", "answer #1"]


async def test_a_repeated_question_mid_conversation_is_now_cache_served(monkeypatch):
    """Phase 105 - user explicitly chose speed over per-turn context-
    freshness: a repeated exact-text question later in the SAME
    conversation is now cache-served too, not just a fresh conversation's
    first message. The cached turn is still appended under this caller's
    own conversation history, not skipped."""
    _patch_conversation_store(monkeypatch)
    _patch_guardrails(monkeypatch)
    call_count = {"generate": 0}

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "x", "chunk_index": 0, "text": "y"}], None)

    def _counting_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        call_count["generate"] += 1
        return {"answer": f"answer #{call_count['generate']}", "model_used": "gpt-4.1-mini"}

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _counting_generate)

    first = await pipeline.answer_query(RagQueryParams(query="what is my balance?", enable_conversation_memory=True))
    second = await pipeline.answer_query(
        RagQueryParams(
            query="what is my balance?",
            enable_conversation_memory=True,
            conversation_id=first["conversation_id"],
        )
    )

    assert call_count["generate"] == 1  # second call was cache-served, not a real generation
    assert first["answer"] == second["answer"] == "answer #1"
    assert second["conversation_id"] == first["conversation_id"]

    saved = await conversation_memory.load_history(first["conversation_id"])
    assert [m.content for m in saved] == ["what is my balance?", "answer #1", "what is my balance?", "answer #1"]


async def test_a_different_employee_in_a_different_conversation_shares_the_cache(monkeypatch):
    """Phase 105 - the cache key never includes employee_id (see
    build_cache_key()), so two different employees asking the identical
    question in two independent conversations also share one cache
    entry - not just the same employee repeating themselves."""
    _patch_conversation_store(monkeypatch)
    _patch_guardrails(monkeypatch)
    call_count = {"generate": 0}

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "x", "chunk_index": 0, "text": "y"}], None)

    def _counting_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        call_count["generate"] += 1
        return {"answer": f"answer #{call_count['generate']}", "model_used": "gpt-4.1-mini"}

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _counting_generate)

    first = await pipeline.answer_query(
        RagQueryParams(query="what is my balance?", employee_id="EMP001", enable_conversation_memory=True)
    )
    second = await pipeline.answer_query(
        RagQueryParams(query="what is my balance?", employee_id="EMP002", enable_conversation_memory=True)
    )

    assert call_count["generate"] == 1
    assert first["answer"] == second["answer"] == "answer #1"
    assert first["conversation_id"] != second["conversation_id"]


async def test_live_generation_reports_real_explainability_fields(monkeypatch):
    """Phase 107 - a live (non-cached) call reports served_from_cache=False,
    llm_call_count=2 (Phase 130: +1 for the decompose call), real retrieval/
    generation timing, and whatever token_usage generate_answer() returned."""
    _patch_guardrails(monkeypatch)

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "x", "chunk_index": 0, "text": "y"}], None)

    def _fake_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        return {
            "answer": "fake answer",
            "model_used": "gpt-4.1-mini",
            "token_usage": {"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50},
        }

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate)

    result = await pipeline.answer_query(RagQueryParams(query="explainability check one"))

    assert result["served_from_cache"] is False
    assert result["llm_call_count"] == 2
    assert result["token_usage"] == {"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50}
    assert result["latency_ms"]["retrieval"] is not None
    assert result["latency_ms"]["generation"] is not None
    assert result["latency_ms"]["total"] is not None


async def test_cache_hit_reports_zero_llm_calls_and_null_token_usage(monkeypatch):
    """Phase 107 - a cache-served answer made zero LLM/retrieval calls this
    time, so served_from_cache=True, llm_call_count=0, token_usage=None,
    retrieval/generation timing both None - regardless of what the
    original (now-cached) generation's own token_usage was."""
    _patch_guardrails(monkeypatch)

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "x", "chunk_index": 0, "text": "y"}], None)

    def _fake_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        return {
            "answer": "fake answer",
            "model_used": "gpt-4.1-mini",
            "token_usage": {"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50},
        }

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate)

    await pipeline.answer_query(RagQueryParams(query="explainability check two"))
    second = await pipeline.answer_query(RagQueryParams(query="explainability check two"))

    assert second["served_from_cache"] is True
    assert second["llm_call_count"] == 0
    assert second["token_usage"] is None
    assert second["latency_ms"]["retrieval"] is None
    assert second["latency_ms"]["generation"] is None
    assert second["latency_ms"]["total"] is not None


async def test_live_generation_with_sources_includes_eval_scores(monkeypatch):
    """Phase 109 - a live answer grounded in retrieved chunks gets real
    (faked-in-this-test) groundedness/completeness scores."""
    _patch_guardrails(monkeypatch)

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "x", "chunk_index": 0, "text": "y"}], None)

    def _fake_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        return {"answer": "fake answer", "model_used": "gpt-4.1-mini", "token_usage": None}

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate)

    result = await pipeline.answer_query(RagQueryParams(query="eval scoring check one"))

    assert result["eval_scores"] == {
        "groundedness": 0.9,
        "groundedness_verdict": "GROUNDED",
        "completeness": 0.9,
        "completeness_verdict": "COMPLETE",
    }
    assert result["latency_ms"]["eval"] is not None


async def test_live_generation_with_no_sources_skips_eval_scoring(monkeypatch):
    """Phase 109 - nothing to check groundedness against when retrieval found nothing."""
    _patch_guardrails(monkeypatch)

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([], None)

    def _fake_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        return {"answer": "I don't know.", "model_used": "gpt-4.1-mini", "token_usage": None}

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate)

    result = await pipeline.answer_query(RagQueryParams(query="eval scoring check two"))

    assert result["eval_scores"] is None
    assert result["latency_ms"]["eval"] is None


async def test_cache_hit_reuses_eval_scores_without_rejudging(monkeypatch):
    """Phase 109 - a cache hit must not call the eval judges again: same
    answer, same (question, context) triple, so the original score still
    applies - and re-judging would defeat part of the point of caching."""
    _patch_guardrails(monkeypatch)
    judge_call_count = {"groundedness": 0, "completeness": 0}

    def _counting_groundedness(answer, context_texts):
        judge_call_count["groundedness"] += 1
        return {"score": 0.9, "verdict": "GROUNDED", "explanation": "fake"}

    def _counting_completeness(query, answer, reference_answer=None):
        judge_call_count["completeness"] += 1
        return {"score": 0.9, "verdict": "COMPLETE", "explanation": "fake"}

    monkeypatch.setattr(pipeline, "evaluate_groundedness", _counting_groundedness)
    monkeypatch.setattr(pipeline, "evaluate_completeness", _counting_completeness)

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "x", "chunk_index": 0, "text": "y"}], None)

    def _fake_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        return {"answer": "fake answer", "model_used": "gpt-4.1-mini", "token_usage": None}

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate)

    first = await pipeline.answer_query(RagQueryParams(query="eval scoring check three"))
    second = await pipeline.answer_query(RagQueryParams(query="eval scoring check three"))

    assert judge_call_count == {"groundedness": 1, "completeness": 1}  # only the first call judged
    assert second["served_from_cache"] is True
    assert second["eval_scores"] == first["eval_scores"]


# Phase 130 - query decomposition


async def test_atomic_question_behaves_exactly_like_before_decomposition(monkeypatch):
    # The _fake_decompose autouse fixture already returns [query] unchanged -
    # this just confirms that single-sub-question path costs exactly 1 retrieve + 1 generate.
    _patch_guardrails(monkeypatch)
    call_count = {"retrieve": 0, "generate": 0}

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        call_count["retrieve"] += 1
        return ([{"filename": "x", "chunk_index": 0, "text": "y"}], None)

    def _fake_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        call_count["generate"] += 1
        return {"answer": "single answer", "model_used": "gpt-4.1-mini"}

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate)

    result = await pipeline.answer_query(RagQueryParams(query="what is the dental plan?"))

    assert call_count == {"retrieve": 1, "generate": 1}
    assert result["answer"] == "single answer"
    assert result["llm_call_count"] == 2  # 1 decompose + 1 generate


async def test_compound_kb_question_merges_two_sub_answers(monkeypatch):
    _patch_guardrails(monkeypatch)

    async def _fake_decompose_compound(query):
        return ["what is the dental plan?", "what is the vision plan?"]

    monkeypatch.setattr(pipeline, "decompose", _fake_decompose_compound)

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "x", "chunk_index": 0, "text": f"chunk for {query}"}], None)

    def _fake_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        if "dental" in query:
            return {"answer": "Dental is MetLife PPO.", "model_used": "gpt-4.1-mini"}
        return {"answer": "Vision is VSP.", "model_used": "gpt-4.1-mini"}

    async def _fake_review(query, agent_results):
        assert len(agent_results) == 2
        assert agent_results[0]["result"] == "Dental is MetLife PPO."
        assert agent_results[1]["result"] == "Vision is VSP."
        return "Dental is MetLife PPO. Vision is VSP.", {"label": "reviewer", "system_prompt": "fake reviewer system prompt", "human_message": "fake reviewer human message", "chat_history": [], "response": "fake"}

    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate)
    monkeypatch.setattr(pipeline.reviewer_agent, "review", _fake_review)

    result = await pipeline.answer_query(RagQueryParams(query="what is the dental plan and the vision plan?"))

    assert result["answer"] == "Dental is MetLife PPO. Vision is VSP."
    assert len(result["sources"]) == 2
    assert result["llm_call_count"] == 4  # 1 decompose + 2 generate + 1 merge


async def test_compound_kb_and_mcp_question_gets_both_halves_right(monkeypatch):
    # The actual live failure this phase fixes: a 401k (KB) + PTO balance (MCP) compound question.
    _patch_guardrails(monkeypatch)

    async def _fake_decompose_compound(query):
        # Decomposition's own LLM paraphrase normalizes "how many days of PTO I have"
        # into wording that actually matches the real MCP keyword list - the real,
        # deliberate side benefit this phase's spec calls out, not an accident here.
        return ["Is the 401k employer match immediately vested?", "What is my PTO balance?"]

    monkeypatch.setattr(pipeline, "decompose", _fake_decompose_compound)

    async def _fake_try_route_to_mcp(sub_question, employee_id):
        # Mirrors the real keyword list's precision (mcp_tools/__init__.py) - the
        # full, undecomposed compound query must NOT match this, only the
        # decomposed sub-question should, same as production's real behavior.
        if "pto balance" in sub_question.lower():
            return {
                "answer": "You have 12 PTO days left.", "model_used": "mcp:get_leave_balance",
                "routed_to": "get_leave_balance", "tool_latency_ms": 40.0,
                "mcp_arguments": {"employee_id": employee_id}, "mcp_raw_result": ["You have 12 PTO days left."],
            }
        return None

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "401k.pdf", "chunk_index": 0, "text": "100% immediately vested."}], None)

    def _fake_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        return {"answer": "Employer match is 100% immediately vested.", "model_used": "gpt-4.1-mini"}

    async def _fake_review(query, agent_results):
        assert {r["result"] for r in agent_results} == {
            "Employer match is 100% immediately vested.",
            "You have 12 PTO days left.",
        }
        return "Employer match is 100% immediately vested. You have 12 PTO days left.", {"label": "reviewer", "system_prompt": "fake reviewer system prompt", "human_message": "fake reviewer human message", "chat_history": [], "response": "fake"}

    monkeypatch.setattr(pipeline, "try_route_to_mcp", _fake_try_route_to_mcp)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate)
    monkeypatch.setattr(pipeline.reviewer_agent, "review", _fake_review)

    result = await pipeline.answer_query(
        RagQueryParams(query="Is the 401k match vested and how many PTO days do I have?")
    )

    assert "100% immediately vested" in result["answer"]
    assert "12 PTO days" in result["answer"]
    assert len(result["tools_used"]) == 1
    assert result["tools_used"][0]["tool_name"] == "get_leave_balance"
    assert result["tools_used"][0]["tool_type"] == "mcp"


async def test_a_compound_kb_and_mcp_answer_is_never_cached(monkeypatch):
    """Phase 140 - the real bug this closes: a decomposed query's merged
    result used to be cached unconditionally even when one sub-question's
    answer came from live MCP data (e.g. a point-in-time PTO balance),
    baking a stale number into a 6h cache entry. Same compound-query setup
    as test_compound_kb_and_mcp_question_gets_both_halves_right above, but
    called twice: the second call must still hit the real fakes, not a
    cached result."""
    _patch_guardrails(monkeypatch)
    call_count = {"mcp": 0, "generate": 0}

    async def _fake_decompose_compound(query):
        return ["Is the 401k employer match immediately vested?", "What is my PTO balance?"]

    async def _fake_try_route_to_mcp(sub_question, employee_id):
        if "pto balance" in sub_question.lower():
            call_count["mcp"] += 1
            return {
                "answer": "You have 12 PTO days left.", "model_used": "mcp:get_leave_balance",
                "routed_to": "get_leave_balance", "tool_latency_ms": 40.0,
                "mcp_arguments": {"employee_id": employee_id}, "mcp_raw_result": ["You have 12 PTO days left."],
            }
        return None

    async def _fake_retrieve(query, top_k=5, vector_db=None, search_strategy=None, **kwargs):
        return ([{"filename": "401k.pdf", "chunk_index": 0, "text": "100% immediately vested."}], None)

    def _fake_generate(query, chunks, model_name=None, temperature=0.0, max_tokens=None, chat_history=None):
        call_count["generate"] += 1
        return {"answer": "Employer match is 100% immediately vested.", "model_used": "gpt-4.1-mini"}

    async def _fake_review(query, agent_results):
        return "Employer match is 100% immediately vested. You have 12 PTO days left.", {"label": "reviewer", "system_prompt": "fake reviewer system prompt", "human_message": "fake reviewer human message", "chat_history": [], "response": "fake"}

    monkeypatch.setattr(pipeline, "decompose", _fake_decompose_compound)
    monkeypatch.setattr(pipeline, "try_route_to_mcp", _fake_try_route_to_mcp)
    monkeypatch.setattr(pipeline, "retrieve_chunks", _fake_retrieve)
    monkeypatch.setattr(pipeline, "generate_answer", _fake_generate)
    monkeypatch.setattr(pipeline.reviewer_agent, "review", _fake_review)

    query_text = "Is the 401k match vested and how many PTO days do I have?"
    await pipeline.answer_query(RagQueryParams(query=query_text))
    second = await pipeline.answer_query(RagQueryParams(query=query_text))

    assert call_count == {"mcp": 2, "generate": 2}  # both calls did real work - never cache-served
    assert second["served_from_cache"] is False
