"""Tests for Phase 215's shared eval-score threshold check, used identically
by all 3 pipelines' own _score_live_answer(). Phase 246 - also tests the
shared per-judge enable switches and eval_scores dict construction added
alongside it."""

from src.hrb_chatbot.ai.rag_core import eval_threshold
from src.hrb_chatbot.ai.rag_core.eval_threshold import build_eval_scores, check_eval_threshold, run_enabled_eval_judges
from tests.conftest import FakeAppSettingsStore, FakeDBGateway, FakeGoldenDatasetStore


def test_no_threshold_given_means_no_check():
    eval_scores = {"groundedness": 0.1, "completeness": 0.1, "retrieval_precision": 0.1}

    below, metrics = check_eval_threshold(eval_scores, None)

    assert below is False
    assert metrics == []


def test_all_scores_above_threshold_is_not_flagged():
    eval_scores = {"groundedness": 0.9, "completeness": 0.9, "retrieval_precision": 0.9}

    below, metrics = check_eval_threshold(eval_scores, 0.6)

    assert below is False
    assert metrics == []


def test_one_score_below_threshold_is_flagged_by_name():
    eval_scores = {"groundedness": 0.9, "completeness": 0.3, "retrieval_precision": 0.9}

    below, metrics = check_eval_threshold(eval_scores, 0.6)

    assert below is True
    assert metrics == ["completeness"]


def test_multiple_scores_below_threshold_are_all_named():
    eval_scores = {"groundedness": 0.2, "completeness": 0.3, "retrieval_precision": 0.9}

    below, metrics = check_eval_threshold(eval_scores, 0.6)

    assert below is True
    assert metrics == ["groundedness", "completeness"]


def test_a_missing_or_null_metric_is_never_counted_as_a_breach():
    """retrieval_precision is null on an MCP-routed answer - a null value must
    never be treated as "0.0 and therefore below threshold"."""
    eval_scores = {"groundedness": 0.9, "completeness": 0.9, "retrieval_precision": None}

    below, metrics = check_eval_threshold(eval_scores, 0.6)

    assert below is False
    assert metrics == []


FAKE_GROUNDEDNESS = {"score": 0.9, "verdict": "GROUNDED", "explanation": "g", "prompt": "gp", "model_used": "fake-model"}
FAKE_COMPLETENESS = {"score": 0.8, "verdict": "COMPLETE", "explanation": "c", "prompt": "cp", "model_used": "fake-model"}
FAKE_RETRIEVAL = {
    "precision": 0.7, "relevant_chunk_indices": [0], "explanation": "r", "prompt": "rp", "model_used": "fake-model",
    "recall_estimate": 0.6, "f1_estimate": 0.65, "pool_size": 4, "relevant_pool_count": 3,
}
FAKE_ANSWER_RELEVANCY = {"score": 0.85, "verdict": "RELEVANT", "explanation": "ar", "prompt": "arp", "model_used": "fake-model"}


def _patch_all_enabled(monkeypatch, groundedness=True, completeness=True, retrieval=True, answer_relevancy=False):
    monkeypatch.setenv("EVAL_GROUNDEDNESS_ENABLED", "true" if groundedness else "false")
    monkeypatch.setenv("EVAL_COMPLETENESS_ENABLED", "true" if completeness else "false")
    monkeypatch.setenv("EVAL_RETRIEVAL_RELEVANCE_ENABLED", "true" if retrieval else "false")
    monkeypatch.setenv("EVAL_ANSWER_RELEVANCY_ENABLED", "true" if answer_relevancy else "false")


class TestPerJudgeToggles:
    def test_all_enabled_by_default_with_no_env_var_set(self, monkeypatch):
        monkeypatch.delenv("EVAL_GROUNDEDNESS_ENABLED", raising=False)
        monkeypatch.delenv("EVAL_COMPLETENESS_ENABLED", raising=False)
        monkeypatch.delenv("EVAL_RETRIEVAL_RELEVANCE_ENABLED", raising=False)
        monkeypatch.delenv("EVAL_ANSWER_RELEVANCY_ENABLED", raising=False)

        assert eval_threshold.groundedness_enabled() is True
        assert eval_threshold.completeness_enabled() is True
        assert eval_threshold.retrieval_relevance_enabled() is True
        # Phase 250 - the one exception: defaults False, not True, since it's
        # a brand-new metric, not one that was already running.
        assert eval_threshold.answer_relevancy_enabled() is False

    async def test_all_three_run_when_all_enabled(self, monkeypatch):
        _patch_all_enabled(monkeypatch)
        monkeypatch.setattr(eval_threshold, "evaluate_groundedness", lambda *a, **k: FAKE_GROUNDEDNESS)
        monkeypatch.setattr(eval_threshold, "evaluate_completeness", lambda *a, **k: FAKE_COMPLETENESS)
        monkeypatch.setattr(eval_threshold, "evaluate_retrieval_relevance", lambda *a, **k: FAKE_RETRIEVAL)

        groundedness, completeness, retrieval, answer_relevancy = await run_enabled_eval_judges(
            "q", "a", ["ctx"], ["ctx"], None, None
        )

        assert groundedness == FAKE_GROUNDEDNESS
        assert completeness == FAKE_COMPLETENESS
        assert retrieval == FAKE_RETRIEVAL
        assert answer_relevancy is None  # defaults off, not patched/enabled in this test

    async def test_disabled_groundedness_is_skipped_not_called(self, monkeypatch):
        _patch_all_enabled(monkeypatch, groundedness=False)

        def _should_not_be_called(*args, **kwargs):
            raise AssertionError("evaluate_groundedness must not be called when disabled")

        monkeypatch.setattr(eval_threshold, "evaluate_groundedness", _should_not_be_called)
        monkeypatch.setattr(eval_threshold, "evaluate_completeness", lambda *a, **k: FAKE_COMPLETENESS)
        monkeypatch.setattr(eval_threshold, "evaluate_retrieval_relevance", lambda *a, **k: FAKE_RETRIEVAL)

        groundedness, completeness, retrieval, answer_relevancy = await run_enabled_eval_judges(
            "q", "a", ["ctx"], ["ctx"], None, None
        )

        assert groundedness is None
        assert completeness == FAKE_COMPLETENESS
        assert retrieval == FAKE_RETRIEVAL

    async def test_all_three_disabled_calls_nothing(self, monkeypatch):
        _patch_all_enabled(monkeypatch, groundedness=False, completeness=False, retrieval=False)

        def _should_not_be_called(*args, **kwargs):
            raise AssertionError("no judge should be called when all 3 are disabled")

        monkeypatch.setattr(eval_threshold, "evaluate_groundedness", _should_not_be_called)
        monkeypatch.setattr(eval_threshold, "evaluate_completeness", _should_not_be_called)
        monkeypatch.setattr(eval_threshold, "evaluate_retrieval_relevance", _should_not_be_called)

        groundedness, completeness, retrieval, answer_relevancy = await run_enabled_eval_judges(
            "q", "a", ["ctx"], ["ctx"], None, None
        )

        assert (groundedness, completeness, retrieval, answer_relevancy) == (None, None, None, None)

    async def test_answer_relevancy_runs_when_explicitly_enabled(self, monkeypatch):
        _patch_all_enabled(monkeypatch, groundedness=False, completeness=False, retrieval=False, answer_relevancy=True)
        monkeypatch.setattr(eval_threshold, "evaluate_answer_relevancy", lambda *a, **k: FAKE_ANSWER_RELEVANCY)

        groundedness, completeness, retrieval, answer_relevancy = await run_enabled_eval_judges(
            "q", "a", ["ctx"], ["ctx"], None, None
        )

        assert answer_relevancy == FAKE_ANSWER_RELEVANCY

    async def test_answer_relevancy_is_skipped_by_default(self, monkeypatch):
        _patch_all_enabled(monkeypatch, groundedness=False, completeness=False, retrieval=False)

        def _should_not_be_called(*args, **kwargs):
            raise AssertionError("evaluate_answer_relevancy must not be called when not explicitly enabled")

        monkeypatch.setattr(eval_threshold, "evaluate_answer_relevancy", _should_not_be_called)

        groundedness, completeness, retrieval, answer_relevancy = await run_enabled_eval_judges(
            "q", "a", ["ctx"], ["ctx"], None, None
        )

        assert answer_relevancy is None


class TestBuildEvalScores:
    def test_all_three_present_builds_full_dict(self):
        eval_scores = build_eval_scores(FAKE_GROUNDEDNESS, FAKE_COMPLETENESS, FAKE_RETRIEVAL, None)

        assert eval_scores["groundedness"] == 0.9
        assert eval_scores["completeness"] == 0.8
        assert eval_scores["retrieval_precision"] == 0.7
        assert eval_scores["retrieval_recall_estimate"] == 0.6
        assert eval_scores["judge_model_used"] == "fake-model"

    def test_disabled_judge_fields_come_back_null_not_a_crash(self):
        eval_scores = build_eval_scores(None, FAKE_COMPLETENESS, None, None)

        assert eval_scores["groundedness"] is None
        assert eval_scores["groundedness_verdict"] is None
        assert eval_scores["completeness"] == 0.8
        assert eval_scores["retrieval_precision"] is None
        assert eval_scores["retrieval_recall_estimate"] is None
        # judge_model_used falls back to whichever judge actually ran.
        assert eval_scores["judge_model_used"] == "fake-model"

    def test_all_disabled_returns_an_all_null_dict_not_none(self):
        eval_scores = build_eval_scores(None, None, None, None)

        assert eval_scores["groundedness"] is None
        assert eval_scores["completeness"] is None
        assert eval_scores["retrieval_precision"] is None
        assert eval_scores["judge_model_used"] is None
        assert eval_scores["below_threshold"] is False
        assert eval_scores["below_threshold_metrics"] == []

    def test_below_threshold_still_computed_from_the_built_dict(self):
        # FAKE_RETRIEVAL's precision (0.7) is the only one of the 3 scores
        # (groundedness 0.9, completeness 0.8, retrieval_precision 0.7) below 0.75.
        eval_scores = build_eval_scores(FAKE_GROUNDEDNESS, FAKE_COMPLETENESS, FAKE_RETRIEVAL, 0.75)

        assert eval_scores["below_threshold"] is True
        assert "retrieval_precision" in eval_scores["below_threshold_metrics"]

    def test_answer_relevancy_omitted_defaults_to_null_not_a_crash(self):
        """build_eval_scores()'s 5th param is optional - every pre-Phase-250
        call site that doesn't pass it must keep working unchanged."""
        eval_scores = build_eval_scores(FAKE_GROUNDEDNESS, FAKE_COMPLETENESS, FAKE_RETRIEVAL, None)

        assert eval_scores["answer_relevancy"] is None
        assert eval_scores["answer_relevancy_verdict"] is None

    def test_answer_relevancy_present_populates_its_own_fields(self):
        eval_scores = build_eval_scores(
            FAKE_GROUNDEDNESS, FAKE_COMPLETENESS, FAKE_RETRIEVAL, None, FAKE_ANSWER_RELEVANCY
        )

        assert eval_scores["answer_relevancy"] == 0.85
        assert eval_scores["answer_relevancy_verdict"] == "RELEVANT"
        assert eval_scores["answer_relevancy_explanation"] == "ar"
        assert eval_scores["answer_relevancy_prompt"] == "arp"

    def test_judge_model_used_falls_back_to_answer_relevancy_when_its_the_only_judge_that_ran(self):
        eval_scores = build_eval_scores(None, None, None, None, FAKE_ANSWER_RELEVANCY)

        assert eval_scores["judge_model_used"] == "fake-model"


class TestMaybeCaptureLiveQuery:
    """Phase 257 - the live-query LTM capture gate."""

    async def test_none_eval_scores_is_a_no_op(self, monkeypatch):
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        await eval_threshold.maybe_capture_live_query("q", "a", None, "genai-rag", "req-1", "EMP001")

        assert await fake_gateway.live_query_store().list_queries() == []

    async def test_missing_groundedness_key_is_a_no_op(self, monkeypatch):
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        await eval_threshold.maybe_capture_live_query("q", "a", {"completeness": 0.9}, "genai-rag", "req-1", "EMP001")

        assert await fake_gateway.live_query_store().list_queries() == []

    async def test_score_at_or_above_default_threshold_is_captured_as_ltm(self, monkeypatch):
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        await eval_threshold.maybe_capture_live_query(
            "What is my deductible?", "It's $500.", {"groundedness": 0.6}, "genai-rag", "req-1", "EMP001"
        )

        rows = await fake_gateway.live_query_store().list_queries()
        assert len(rows) == 1
        assert rows[0]["is_ltm"] is True
        assert rows[0]["eval_score"] == 0.6
        assert rows[0]["pipeline"] == "genai-rag"
        assert rows[0]["request_id"] == "req-1"
        assert rows[0]["employee_id"] == "EMP001"

    async def test_score_below_default_threshold_is_captured_but_not_ltm(self, monkeypatch):
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        await eval_threshold.maybe_capture_live_query(
            "q", "a", {"groundedness": 0.3}, "single-agentic-rag", "req-2", "EMP002"
        )

        rows = await fake_gateway.live_query_store().list_queries()
        assert len(rows) == 1
        assert rows[0]["is_ltm"] is False

    async def test_custom_threshold_from_app_settings_is_honored(self, monkeypatch):
        fake_gateway = FakeDBGateway(app_settings_store=FakeAppSettingsStore({"ltm_score_threshold": 0.9}))
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        await eval_threshold.maybe_capture_live_query("q", "a", {"groundedness": 0.7}, "genai-rag", "req-3", None)

        rows = await fake_gateway.live_query_store().list_queries()
        assert rows[0]["is_ltm"] is False

    async def test_capture_failure_is_swallowed_never_raises(self, monkeypatch):
        class _BoomStore:
            async def capture(self, *args, **kwargs):
                raise RuntimeError("db is down")

        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(fake_gateway, "live_query_store", lambda: _BoomStore())
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        # Must not raise.
        await eval_threshold.maybe_capture_live_query("q", "a", {"groundedness": 0.9}, "genai-rag", "req-4", None)

    async def test_captured_row_carries_the_classified_intent(self, monkeypatch):
        """Phase 277 - the long-dormant category column now gets a real
        value, from ai/search_pre_processing/intent_classify.py."""
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        await eval_threshold.maybe_capture_live_query(
            "What's my PTO balance?", "You have 10 days.", {"groundedness": 0.9}, "genai-rag", "req-5", "EMP001"
        )

        rows = await fake_gateway.live_query_store().list_queries()
        assert rows[0]["category"] == "leave_balance"

    async def test_classification_failure_does_not_block_the_capture(self, monkeypatch):
        """A broken classifier must not take down the real capture it
        rides alongside - same fire-and-forget discipline as everything
        else in this function."""
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)
        monkeypatch.setattr(
            eval_threshold, "classify_query_intent", lambda query: (_ for _ in ()).throw(RuntimeError("boom"))
        )

        await eval_threshold.maybe_capture_live_query(
            "q", "a", {"groundedness": 0.9}, "genai-rag", "req-6", "EMP001"
        )

        rows = await fake_gateway.live_query_store().list_queries()
        assert len(rows) == 1
        assert rows[0]["category"] is None


class TestMeetsCacheQualityThreshold:
    """2026-10-30 - the answer-cache quality gate, same ltm_score_threshold
    app_setting as TestMaybeCaptureLiveQuery above."""

    async def test_none_eval_scores_does_not_block_caching(self, monkeypatch):
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        assert await eval_threshold.meets_cache_quality_threshold(None) is True

    async def test_missing_groundedness_key_does_not_block_caching(self, monkeypatch):
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        assert await eval_threshold.meets_cache_quality_threshold({"completeness": 0.9}) is True

    async def test_score_at_or_above_default_threshold_is_cache_worthy(self, monkeypatch):
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        assert await eval_threshold.meets_cache_quality_threshold({"groundedness": 0.6}) is True

    async def test_score_below_default_threshold_is_not_cache_worthy(self, monkeypatch):
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        assert await eval_threshold.meets_cache_quality_threshold({"groundedness": 0.3}) is False

    async def test_custom_threshold_from_app_settings_is_honored(self, monkeypatch):
        fake_gateway = FakeDBGateway(app_settings_store=FakeAppSettingsStore({"ltm_score_threshold": 0.9}))
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        assert await eval_threshold.meets_cache_quality_threshold({"groundedness": 0.7}) is False


class _FakeRunTree:
    """Minimal stand-in for langsmith.run_trees.RunTree - just the surface
    record_eval_feedback()/tag_golden_match() actually touch."""

    def __init__(self, run_id="run-1"):
        self.id = run_id
        self.tags: list[str] = []
        self.metadata: dict = {}

    def add_tags(self, tags):
        self.tags.extend(tags)

    def add_metadata(self, metadata):
        self.metadata.update(metadata)


class TestRecordEvalFeedback:
    """Phase 271 - posts eval scores back to LangSmith as feedback on the current trace."""

    async def test_no_eval_scores_is_a_no_op(self, monkeypatch):
        calls = []
        monkeypatch.setattr(eval_threshold, "get_current_run_tree", lambda: _FakeRunTree())
        monkeypatch.setattr(eval_threshold, "_get_langsmith_client", lambda: type("C", (), {"create_feedback": lambda *a, **k: calls.append((a, k))})())

        await eval_threshold.record_eval_feedback(None)
        await eval_threshold.record_eval_feedback({})

        assert calls == []

    async def test_no_current_run_is_a_no_op(self, monkeypatch):
        calls = []
        monkeypatch.setattr(eval_threshold, "get_current_run_tree", lambda: None)
        monkeypatch.setattr(eval_threshold, "_get_langsmith_client", lambda: type("C", (), {"create_feedback": lambda *a, **k: calls.append((a, k))})())

        await eval_threshold.record_eval_feedback({"groundedness": 0.9})

        assert calls == []

    async def test_posts_one_feedback_call_per_non_null_metric(self, monkeypatch):
        calls = []

        class _FakeClient:
            def create_feedback(self, run_id, key, score):
                calls.append((run_id, key, score))

        run = _FakeRunTree(run_id="run-42")
        monkeypatch.setattr(eval_threshold, "get_current_run_tree", lambda: run)
        monkeypatch.setattr(eval_threshold, "_get_langsmith_client", lambda: _FakeClient())

        await eval_threshold.record_eval_feedback(
            {"groundedness": 0.9, "completeness": 0.8, "retrieval_precision": None, "answer_relevancy": 0.7}
        )

        assert sorted(calls) == sorted(
            [("run-42", "groundedness", 0.9), ("run-42", "completeness", 0.8), ("run-42", "answer_relevancy", 0.7)]
        )

    async def test_a_feedback_post_failure_is_swallowed_never_raises(self, monkeypatch):
        class _BoomClient:
            def create_feedback(self, *args, **kwargs):
                raise RuntimeError("langsmith is down")

        monkeypatch.setattr(eval_threshold, "get_current_run_tree", lambda: _FakeRunTree())
        monkeypatch.setattr(eval_threshold, "_get_langsmith_client", lambda: _BoomClient())

        # Must not raise.
        await eval_threshold.record_eval_feedback({"groundedness": 0.9})


class TestTagGoldenMatch:
    """Phase 274 - tags + annotates the current trace when a live query
    exactly matches a Golden Dataset case."""

    async def test_no_current_run_is_a_no_op(self, monkeypatch):
        fake_gateway = FakeDBGateway(golden_dataset_store=FakeGoldenDatasetStore())
        monkeypatch.setattr(eval_threshold, "get_current_run_tree", lambda: None)
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        # Must not raise, and must never even look up the golden store.
        await eval_threshold.tag_golden_match("What is my deductible?")

    async def test_no_match_tags_nothing(self, monkeypatch):
        run = _FakeRunTree()
        fake_gateway = FakeDBGateway(golden_dataset_store=FakeGoldenDatasetStore())
        monkeypatch.setattr(eval_threshold, "get_current_run_tree", lambda: run)
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        await eval_threshold.tag_golden_match("a totally unrelated question")

        assert run.tags == []
        assert run.metadata == {}

    async def test_exact_match_tags_and_annotates_the_run(self, monkeypatch):
        run = _FakeRunTree()
        fake_gateway = FakeDBGateway(
            golden_dataset_store=FakeGoldenDatasetStore(
                [
                    {
                        "id": 1, "case_key": "deductible-01", "dataset": "golden_v1", "category": "rag",
                        "query": "  What is my deductible?  ", "raw_case": {"expected_answer": "It's $500."},
                        "created_at": "2026-10-26T00:00:00Z", "updated_at": "2026-10-26T00:00:00Z",
                        "source": "curated", "source_live_query_id": None, "promoted_by": None, "promoted_at": None,
                    }
                ]
            )
        )
        monkeypatch.setattr(eval_threshold, "get_current_run_tree", lambda: run)
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        # Case/whitespace-insensitive - real submitted text differs trivially.
        await eval_threshold.tag_golden_match("what is my deductible?")

        assert run.tags == ["golden_match:deductible-01"]
        assert run.metadata == {"golden_case_key": "deductible-01", "golden_expected_answer": "It's $500."}

    async def test_a_lookup_failure_is_swallowed_never_raises(self, monkeypatch):
        class _BoomStore:
            async def find_by_query(self, *args, **kwargs):
                raise RuntimeError("db is down")

        run = _FakeRunTree()
        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(fake_gateway, "golden_dataset_store", lambda: _BoomStore())
        monkeypatch.setattr(eval_threshold, "get_current_run_tree", lambda: run)
        monkeypatch.setattr(eval_threshold, "get_db_gateway", lambda: fake_gateway)

        # Must not raise.
        await eval_threshold.tag_golden_match("What is my deductible?")
