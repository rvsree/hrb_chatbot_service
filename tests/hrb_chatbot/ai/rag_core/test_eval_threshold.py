"""Tests for Phase 215's shared eval-score threshold check, used identically
by all 3 pipelines' own _score_live_answer(). Phase 246 - also tests the
shared per-judge enable switches and eval_scores dict construction added
alongside it."""

from src.hrb_chatbot.ai.rag_core import eval_threshold
from src.hrb_chatbot.ai.rag_core.eval_threshold import build_eval_scores, check_eval_threshold, run_enabled_eval_judges
from tests.conftest import FakeAppSettingsStore, FakeDBGateway


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
