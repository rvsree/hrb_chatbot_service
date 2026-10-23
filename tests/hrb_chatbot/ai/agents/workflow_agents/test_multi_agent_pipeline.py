"""Tests for the real LangGraph graph (Phase 64) - Planner -> Orchestration
dispatch (Send fan-out) -> domain agents -> Reviewer. Every agent and
guardrail call is faked; only the graph wiring itself is real."""

import pytest

from src.hrb_chatbot.ai.agents.workflow_agents import multi_agent_pipeline
from src.hrb_chatbot.ai.rag_core import eval_threshold, guarded_pipeline
from src.hrb_chatbot.ai.search_pre_processing import conversation_memory
from tests.conftest import FakeConversationStore, FakeDBGateway


@pytest.fixture(autouse=True)
def _fake_cache_and_eval_judges(monkeypatch):
    """Phase 110/115: run_multi_agent() now calls get_db_gateway().answer_cache()
    and (for non-empty agent_result_texts) the real eval-judge functions on
    every call - fake both for every test in this file, same reasoning/
    confirmed-regression as test_pipeline.py's and test_orchestration_agent.py's
    own fixtures (confirmed here too: unfaked, these tests logged real
    "Redis unreachable"/"Event loop is closed" errors on every call)."""
    gateway = FakeDBGateway()
    monkeypatch.setattr(multi_agent_pipeline, "get_db_gateway", lambda: gateway)

    async def _fake_generate_follow_ups(query, answer):
        return []

    monkeypatch.setattr(multi_agent_pipeline.reviewer_agent, "generate_follow_ups", _fake_generate_follow_ups)

    # Phase 150: review() always calls a real LLM now (even for 1 result -
    # see reviewer_agent.py), so every test needs it faked, not just the
    # ones that happen to check result["answer"]'s exact text. Default
    # behavior joins agent results, matching the old (buggy) 1-result
    # shortcut's output exactly, so tests that don't care about synthesis
    # keep working unchanged; a test that wants real merge behavior
    # overrides this locally, same as several already do.
    async def _default_review(query, agent_results, request_id=None):
        return " ".join(r["result"] for r in agent_results), {"label": "reviewer"}

    monkeypatch.setattr(multi_agent_pipeline.reviewer_agent, "review", _default_review)

    def _fake_evaluate_groundedness(answer, context_texts, judge_model=None):
        # Phase 120 regression guard - a tuple here means some domain agent's
        # "result" wasn't unpacked before joining into agent_result_texts.
        assert all(isinstance(t, str) for t in context_texts)
        return {"score": 0.9, "verdict": "GROUNDED", "explanation": "fake", "prompt": "fake", "model_used": judge_model or "fake-chat-model"}

    monkeypatch.setattr(eval_threshold, "evaluate_groundedness", _fake_evaluate_groundedness)
    monkeypatch.setattr(
        eval_threshold,
        "evaluate_completeness",
        lambda query, answer, reference_answer=None, judge_model=None: {"score": 0.9, "verdict": "COMPLETE", "explanation": "fake", "prompt": "fake", "model_used": judge_model or "fake-chat-model"},
    )
    monkeypatch.setattr(
        eval_threshold,
        "evaluate_retrieval_relevance",
        lambda query, chunk_texts, judge_model=None, wider_pool_texts=None: {
            "precision": 1.0 if chunk_texts else None,
            "relevant_chunk_indices": [1] if chunk_texts else [],
            "explanation": "fake",
            "prompt": "fake",
            "model_used": judge_model or "fake-chat-model",
            "recall_estimate": 1.0 if wider_pool_texts else None,
            "f1_estimate": 1.0 if wider_pool_texts else None,
            "pool_size": len(wider_pool_texts) if wider_pool_texts else None,
            "relevant_pool_count": 1 if wider_pool_texts else None,
        },
    )
    # Phase 220 - _score_live_answer() now fetches a wider exact-KNN pool
    # (search_knn) when sources is non-empty - fake it as "no extra
    # candidates" for every test in this file, same reasoning
    # test_pipeline.py's own fixture gives.
    monkeypatch.setattr(multi_agent_pipeline, "search_knn", lambda query, top_k, vector_db: [])


@pytest.fixture(autouse=True)
def _fake_normalize_query(monkeypatch):
    """Phase 173: run_multi_agent() now calls normalize_query() before
    check_input() on every call, a real OpenAI structured-output call - fake
    it as a no-op for every test in this file, same reasoning as
    test_pipeline.py's own fixture. Real normalization behavior is covered
    by test_query_normalize.py instead."""

    async def _passthrough_normalize(query):
        return query

    monkeypatch.setattr(multi_agent_pipeline, "normalize_query", _passthrough_normalize)


def _patch_guardrails(monkeypatch):
    """Phase 245 - check_input() is still called directly from
    multi_agent_pipeline (the pre-cache-check, unchanged by this phase);
    check_output() now runs inside run_guarded_pipeline()'s own call, so
    it's patched on guarded_pipeline, same convention test_orchestration_agent.py
    already uses for the same reason."""

    async def _passthrough_check_input(query, guardrails_model=None):
        return query, {"status": "pass", "rail": None, "model_used": guardrails_model or "gpt-4.1-nano"}

    async def _passthrough_check_output(query, answer, guardrails_model=None):
        return answer, {"status": "pass", "rail": None, "model_used": guardrails_model or "gpt-4.1-nano"}

    monkeypatch.setattr(multi_agent_pipeline, "check_input", _passthrough_check_input)
    monkeypatch.setattr(guarded_pipeline, "check_output", _passthrough_check_output)


def _patch_conversation_store(monkeypatch, conversation_store=None):
    gateway = FakeDBGateway(conversation_store=conversation_store or FakeConversationStore())
    monkeypatch.setattr(conversation_memory, "get_db_gateway", lambda: gateway)
    return gateway


async def test_single_task_query_runs_one_domain_agent_and_still_goes_through_review(monkeypatch):
    # Phase 150: a single domain agent no longer skips the Reviewer's LLM -
    # the fixture's default fake just passes the result through unchanged.
    _patch_guardrails(monkeypatch)

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [{"agent": "vector_kb_agent", "focus": query}], {"label": "planner"}

    async def _fake_vector_kb_run(focus, search_strategy=None, role=None, department=None):
        return "8 weeks paid parental leave.", []

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)

    result = await multi_agent_pipeline.run_multi_agent("what is the parental leave policy?", employee_id="EMP052")

    assert result["answer"] == "8 weeks paid parental leave."
    assert result["tasks"] == [{"agent": "vector_kb_agent", "focus": "what is the parental leave policy?"}]
    # Phase 160 - only planner/reviewer make a real LLM call among the 7 graph nodes.
    assert [turn["label"] for turn in result["llm_context"]["turns"]] == ["planner", "reviewer"]
    assert len(result["tools_used"]) == 1
    call = result["tools_used"][0]
    assert call["tool_name"] == "vector_kb_agent"
    assert call["tool_input"] == "what is the parental leave policy?"
    assert call["tool_type"] == "vector_db"  # Phase 126
    assert call["success"] is True
    assert call["latency_ms"] is not None
    assert result["iterations"] == 1
    # Phase 200 - only planner+reviewer are real LLM calls, regardless of
    # how many domain agents were dispatched.
    assert result["llm_call_count"] == 2
    assert result["conversation_id"] is None


async def test_multi_task_query_dispatches_to_both_agents_in_parallel_and_merges(monkeypatch):
    _patch_guardrails(monkeypatch)

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [
            {"agent": "vector_kb_agent", "focus": "parental leave policy"},
            {"agent": "lms_ops_agent", "focus": "my leave balance"},
        ], {"label": "planner"}

    async def _fake_vector_kb_run(focus, search_strategy=None, role=None, department=None):
        return "8 weeks paid.", []

    async def _fake_lms_ops_run(focus, employee_id):
        return "10 days available.", []

    async def _fake_review(query, agent_results, request_id=None):
        assert {r["agent"] for r in agent_results} == {"vector_kb_agent", "lms_ops_agent"}
        return "merged answer", {"label": "reviewer"}

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)
    monkeypatch.setattr(multi_agent_pipeline.lms_ops_agent, "run", _fake_lms_ops_run)
    monkeypatch.setattr(multi_agent_pipeline.reviewer_agent, "review", _fake_review)

    result = await multi_agent_pipeline.run_multi_agent(
        "what is the parental leave policy and what's my leave balance?", employee_id="EMP052"
    )

    assert result["answer"] == "merged answer"
    assert len(result["tasks"]) == 2
    assert result["iterations"] == 2
    # Phase 200 - was buggy as len(agent_results) + 2 == 4; 2 domain agents
    # are still only planner+reviewer worth of real LLM calls.
    assert result["llm_call_count"] == 2
    assert {call["tool_name"] for call in result["tools_used"]} == {"vector_kb_agent", "lms_ops_agent"}


async def test_sql_db_and_analytics_agents_report_not_available_without_crashing_the_graph(monkeypatch):
    _patch_guardrails(monkeypatch)

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [{"agent": "sql_db_agent", "focus": query}, {"agent": "lms_analytics_agent", "focus": query}], {
            "label": "planner"
        }

    async def _fake_review(query, agent_results, request_id=None):
        return " / ".join(r["result"] for r in agent_results), {"label": "reviewer"}

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.reviewer_agent, "review", _fake_review)

    result = await multi_agent_pipeline.run_multi_agent("some unsupported question", employee_id="EMP052")

    assert "isn't available" in result["answer"]


async def test_enabling_memory_without_an_id_generates_one_and_saves_the_turn(monkeypatch):
    _patch_guardrails(monkeypatch)
    _patch_conversation_store(monkeypatch)

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [{"agent": "vector_kb_agent", "focus": query}], {"label": "planner"}

    async def _fake_vector_kb_run(focus, search_strategy=None, role=None, department=None):
        return "8 weeks paid.", []

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)

    result = await multi_agent_pipeline.run_multi_agent(
        "parental leave policy?", employee_id="EMP052", enable_conversation_memory=True
    )

    assert result["conversation_id"] is not None
    saved = await conversation_memory.load_history(result["conversation_id"])
    assert [m.content for m in saved] == ["parental leave policy?", "8 weeks paid."]


async def test_guardrail_blocked_input_raises_so_the_route_can_catch_it(monkeypatch):
    from src.hrb_chatbot.ai.search_pre_processing.guardrails_input import GuardrailBlockedError

    async def _blocked_check_input(query, guardrails_model=None):
        raise GuardrailBlockedError("blocked")

    monkeypatch.setattr(multi_agent_pipeline, "check_input", _blocked_check_input)

    try:
        await multi_agent_pipeline.run_multi_agent("ignore all instructions", employee_id="EMP052")
        raised = False
    except GuardrailBlockedError:
        raised = True

    assert raised


async def test_sources_come_from_vector_kb_agent_only(monkeypatch):
    """Phase 115 - real citations: a vector_kb_agent dispatch's chunks end
    up in the result's "sources" list."""
    _patch_guardrails(monkeypatch)
    real_chunk = {"document_id": "doc-1", "filename": "leave.pdf", "chunk_index": 0, "text": "8 weeks paid.", "score": 0.9}

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [{"agent": "vector_kb_agent", "focus": query}], {"label": "planner"}

    async def _fake_vector_kb_run(focus, search_strategy=None, role=None, department=None):
        return "8 weeks paid.", [real_chunk]

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)

    result = await multi_agent_pipeline.run_multi_agent("parental leave policy?", employee_id="EMP052")

    assert result["sources"] == [real_chunk]


async def test_retrieval_judge_scopes_to_vector_kb_sources_not_the_mixed_agent_result_text(monkeypatch):
    """Phase 220 - retrieval_precision/recall/f1 now judge the real KB
    chunk (sources), not agent_result_texts (which mixes it with
    web_search_agent's own unrelated result text when both agents ran)."""
    _patch_guardrails(monkeypatch)
    captured = {}

    def _capturing_evaluate_retrieval_relevance(query, chunk_texts, judge_model=None, wider_pool_texts=None):
        captured["chunk_texts"] = chunk_texts
        captured["wider_pool_texts"] = wider_pool_texts
        return {
            "precision": 1.0, "relevant_chunk_indices": [1], "explanation": "fake", "prompt": "fake",
            "model_used": "fake-chat-model", "recall_estimate": 0.5, "f1_estimate": 0.67, "pool_size": 2,
            "relevant_pool_count": 2,
        }

    def _fake_search_knn(query, top_k, vector_db):
        captured["wider_pool_top_k"] = top_k
        return [{"document_id": "doc-2", "chunk_index": 0, "text": "extra chunk from exact-KNN"}]

    monkeypatch.setattr(eval_threshold, "evaluate_retrieval_relevance", _capturing_evaluate_retrieval_relevance)
    monkeypatch.setattr(multi_agent_pipeline, "search_knn", _fake_search_knn)

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [
            {"agent": "vector_kb_agent", "focus": "parental leave policy"},
            {"agent": "web_search_agent", "focus": "general IRS rules"},
        ], {"label": "planner"}

    async def _fake_vector_kb_run(focus, search_strategy=None, role=None, department=None):
        return "KB chunk text", [{"document_id": "doc-1", "chunk_index": 0, "text": "KB chunk text", "filename": "plan.pdf", "score": 0.9}]

    async def _fake_web_search_run(focus):
        return "unrelated web text"

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)
    monkeypatch.setattr(multi_agent_pipeline.web_search_agent, "run", _fake_web_search_run)

    result = await multi_agent_pipeline.run_multi_agent("parental leave policy and general IRS rules?", employee_id="EMP052")

    # Scoped to the real KB chunk only - web_search_agent's own text never reaches this judge call.
    assert captured["chunk_texts"] == ["KB chunk text"]
    assert captured["wider_pool_texts"] == ["KB chunk text", "extra chunk from exact-KNN"]
    assert captured["wider_pool_top_k"] == multi_agent_pipeline.VECTOR_KB_AGENT_TOP_K * multi_agent_pipeline.WIDER_POOL_MULTIPLIER
    assert result["eval_scores"]["retrieval_recall_estimate"] == 0.5
    assert result["eval_scores"]["retrieval_f1_estimate"] == 0.67
    assert result["eval_scores"]["retrieval_recall_pool_size"] == 2


async def test_a_vector_kb_only_repeat_is_cache_served(monkeypatch):
    """Phase 115 - a query whose only dispatched task was vector_kb_agent
    is exactly as cacheable as a genai-rag answer (same static index)."""
    _patch_guardrails(monkeypatch)
    call_count = {"plan": 0}

    async def _fake_plan(query, request_id=None, planner_model=None):
        call_count["plan"] += 1
        return [{"agent": "vector_kb_agent", "focus": query}], {"label": "planner"}

    async def _fake_vector_kb_run(focus, search_strategy=None, role=None, department=None):
        return "8 weeks paid.", []

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)

    first = await multi_agent_pipeline.run_multi_agent("cacheable multi-agent question", employee_id="EMP052")
    second = await multi_agent_pipeline.run_multi_agent("cacheable multi-agent question", employee_id="EMP052")

    assert call_count["plan"] == 1  # only the first call ran the planner at all
    assert second["served_from_cache"] is True
    assert second["answer"] == first["answer"]
    # Phase 160 - a cache hit never re-sends anything, so its llm_context
    # must be null, not the original call's stale turns replayed as if live.
    assert first["llm_context"] is not None
    assert second["llm_context"] is None


async def test_a_live_data_agent_dispatch_is_never_cached(monkeypatch):
    """Phase 115 - lms_ops_agent returns live, per-employee data; caching
    that answer would go stale the moment it's reused."""
    _patch_guardrails(monkeypatch)
    call_count = {"plan": 0}

    async def _fake_plan(query, request_id=None, planner_model=None):
        call_count["plan"] += 1
        return [{"agent": "lms_ops_agent", "focus": query}], {"label": "planner"}

    async def _fake_lms_ops_run(focus, employee_id):
        return "10 days available.", []

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.lms_ops_agent, "run", _fake_lms_ops_run)

    await multi_agent_pipeline.run_multi_agent("what's my pto balance", employee_id="EMP052")
    second = await multi_agent_pipeline.run_multi_agent("what's my pto balance", employee_id="EMP052")

    assert call_count["plan"] == 2  # both calls did real work - never cache-served
    assert second["served_from_cache"] is False


async def test_follow_ups_are_empty_when_no_domain_agent_ran(monkeypatch):
    _patch_guardrails(monkeypatch)

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [], {"label": "planner"}

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)

    async def _fail_if_called(query, answer):
        raise AssertionError("generate_follow_ups should not be called when no domain agent ran")

    monkeypatch.setattr(multi_agent_pipeline.reviewer_agent, "generate_follow_ups", _fail_if_called)

    result = await multi_agent_pipeline.run_multi_agent("gibberish query", employee_id="EMP052")

    assert result["follow_up_questions"] == []


async def test_follow_ups_are_generated_when_a_domain_agent_ran(monkeypatch):
    _patch_guardrails(monkeypatch)

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [{"agent": "vector_kb_agent", "focus": query}], {"label": "planner"}

    async def _fake_vector_kb_run(focus, search_strategy=None, role=None, department=None):
        return "8 weeks paid parental leave.", []

    async def _fake_generate_follow_ups(query, answer):
        return ["What is my dental plan?"]

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)
    monkeypatch.setattr(multi_agent_pipeline.reviewer_agent, "generate_follow_ups", _fake_generate_follow_ups)

    result = await multi_agent_pipeline.run_multi_agent("what is the parental leave policy?", employee_id="EMP052")

    assert result["follow_up_questions"] == ["What is my dental plan?"]


async def test_tool_call_metrics_mark_success_false_on_an_error_result(monkeypatch):
    _patch_guardrails(monkeypatch)

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [{"agent": "lms_ops_agent", "focus": query}], {"label": "planner"}

    async def _fake_lms_ops_run(focus, employee_id):
        return "Error: hrb_lms_mcp unreachable", []

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.lms_ops_agent, "run", _fake_lms_ops_run)

    result = await multi_agent_pipeline.run_multi_agent("what's my pto balance", employee_id="EMP052")

    call = result["tools_used"][0]
    assert call["success"] is False
    assert call["tool_type"] == "mcp"


async def test_real_guardrail_status_reaches_the_result_on_the_shared_core_path(monkeypatch):
    """Phase 224, updated Phase 245 - multi_agent_pipeline.py now runs
    check_output() through the shared rag_core.guarded_pipeline, same as
    genai-rag/single-agentic-rag (check_input() is still called directly
    here, for the pre-cache-check, unchanged) - confirms the real status
    still reaches result["guardrails"], not just a hardcoded "pass", now
    that it flows through the shared core instead of a direct call."""

    async def _masking_check_input(query, guardrails_model=None):
        return query.replace("123-45-6789", "<SSN>"), {"status": "modified", "rail": "pii detection"}

    async def _masking_check_output(query, answer, guardrails_model=None):
        return answer.replace("Roth", "<PERSON>"), {"status": "modified", "rail": "self check output"}

    monkeypatch.setattr(multi_agent_pipeline, "check_input", _masking_check_input)
    monkeypatch.setattr(guarded_pipeline, "check_output", _masking_check_output)

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [{"agent": "vector_kb_agent", "focus": query}], {"label": "planner"}

    async def _fake_vector_kb_run(focus, search_strategy=None, role=None, department=None):
        return "You can make Roth contributions.", []

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)

    result = await multi_agent_pipeline.run_multi_agent("My SSN is 123-45-6789", employee_id="EMP052")

    assert result["answer"] == "You can make <PERSON> contributions."
    assert result["guardrails"] == {
        "input": {"status": "modified", "rail": "pii detection"},
        "output": {"status": "modified", "rail": "self check output"},
    }


async def test_search_strategy_reaches_vector_kb_agent_end_to_end(monkeypatch):
    """Phase 228 - unlike single-agentic-rag (an agent-level per-call
    choice this just defaults), multi-agentic-rag's vector_kb_agent never
    exposed a choice at all before this - run_multi_agent()'s own param is
    the only lever, so this confirms it actually reaches the agent, not
    just that the parameter exists."""
    _patch_guardrails(monkeypatch)
    captured = {}

    async def _fake_plan(query, request_id=None, planner_model=None):
        return [{"agent": "vector_kb_agent", "focus": query}], {"label": "planner"}

    async def _fake_vector_kb_run(focus, search_strategy=None, role=None, department=None):
        captured["search_strategy"] = search_strategy
        return "8 weeks paid.", []

    monkeypatch.setattr(multi_agent_pipeline.planner_agent, "plan", _fake_plan)
    monkeypatch.setattr(multi_agent_pipeline.vector_kb_agent, "run", _fake_vector_kb_run)

    await multi_agent_pipeline.run_multi_agent(
        "parental leave policy?", employee_id="EMP052", search_strategy="mmr"
    )

    assert captured["search_strategy"] == "mmr"
