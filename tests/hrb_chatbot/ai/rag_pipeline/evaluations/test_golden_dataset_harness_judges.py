"""Phase 249/250: unit tests for evaluate_groundedness()/evaluate_completeness()/
evaluate_answer_relevancy()/evaluate_contextual_precision()/
evaluate_contextual_recall()'s own logic (verdict derivation, field mapping,
exception handling) - fakes DeepEval's metric classes themselves, not their
internal multi-step LLM orchestration (that's DeepEval's own tested
responsibility, not re-tested here). No real network call. The existing
test_golden_dataset_harness.py stays real-API/pytest.mark.eval-only,
unmodified - this is the fast, default-suite coverage for these functions."""

from src.hrb_chatbot.ai.rag_pipeline.evaluations import golden_dataset_harness
from src.hrb_chatbot.ai.rag_pipeline.evaluations.golden_dataset_harness import (
    evaluate_answer_relevancy,
    evaluate_completeness,
    evaluate_contextual_precision,
    evaluate_contextual_recall,
    evaluate_groundedness,
    evaluate_routing_accuracy,
    score_case,
)


def _patch_all_judges(monkeypatch):
    monkeypatch.setattr(golden_dataset_harness, "evaluate_groundedness", lambda *a, **k: {"score": 0.9})
    monkeypatch.setattr(golden_dataset_harness, "evaluate_completeness", lambda *a, **k: {"score": 0.8})
    monkeypatch.setattr(golden_dataset_harness, "evaluate_answer_relevancy", lambda *a, **k: {"score": 0.7})
    monkeypatch.setattr(golden_dataset_harness, "evaluate_contextual_precision", lambda *a, **k: {"score": 0.6})
    monkeypatch.setattr(golden_dataset_harness, "evaluate_contextual_recall", lambda *a, **k: {"score": 0.5})


async def _fake_ask(query):
    return {"answer": "fake answer", "retrieved_texts": ["fake chunk"], "retrieved_ids": ["doc-1"]}


async def test_score_case_always_includes_answer_relevancy(monkeypatch):
    _patch_all_judges(monkeypatch)

    result = await score_case({"id": "c1", "category": "happy", "query": "q"}, _fake_ask)

    assert result["scores"]["groundedness"] == 0.9
    assert result["scores"]["completeness"] == 0.8
    assert result["scores"]["answer_relevancy"] == 0.7


async def test_score_case_adds_contextual_precision_recall_only_when_expected_answer_exists(monkeypatch):
    _patch_all_judges(monkeypatch)

    result = await score_case(
        {"id": "c1", "category": "happy", "query": "q", "expected_answer": "the real answer"}, _fake_ask
    )

    assert result["scores"]["contextual_precision"] == 0.6
    assert result["scores"]["contextual_recall"] == 0.5


async def test_score_case_skips_contextual_precision_recall_when_no_expected_answer(monkeypatch):
    _patch_all_judges(monkeypatch)

    result = await score_case({"id": "c1", "category": "unhappy_out_of_scope", "query": "q"}, _fake_ask)

    assert "contextual_precision" not in result["scores"]
    assert "contextual_recall" not in result["scores"]


class _FakeFaithfulnessMetric:
    def __init__(self, model=None, threshold=0.0, include_reason=True):
        self.model = model
        self.score = _FakeFaithfulnessMetric.next_score
        self.reason = "fake faithfulness reason"
        self.verbose_logs = "fake verbose logs"

    def measure(self, test_case):
        self.test_case = test_case


class _RaisingFaithfulnessMetric:
    def __init__(self, model=None, threshold=0.0, include_reason=True):
        pass

    def measure(self, test_case):
        raise RuntimeError("judge model unreachable")


class _FakeGEval:
    def __init__(self, name=None, criteria=None, evaluation_params=None, model=None, threshold=0.0):
        self.name = name
        self.score = _FakeGEval.next_score
        self.reason = "fake completeness reason"
        self.verbose_logs = "fake geval verbose logs"

    def measure(self, test_case):
        self.test_case = test_case


def test_evaluate_groundedness_maps_a_high_score_to_grounded(monkeypatch):
    _FakeFaithfulnessMetric.next_score = 0.9
    monkeypatch.setattr(golden_dataset_harness, "FaithfulnessMetric", _FakeFaithfulnessMetric)

    result = evaluate_groundedness("an answer", ["some context"])

    assert result["score"] == 0.9
    assert result["verdict"] == "GROUNDED"
    assert result["explanation"] == "fake faithfulness reason"
    assert result["prompt"] == "fake verbose logs"


def test_evaluate_groundedness_maps_a_mid_score_to_partial(monkeypatch):
    _FakeFaithfulnessMetric.next_score = 0.5
    monkeypatch.setattr(golden_dataset_harness, "FaithfulnessMetric", _FakeFaithfulnessMetric)

    result = evaluate_groundedness("an answer", ["some context"])

    assert result["verdict"] == "PARTIAL"


def test_evaluate_groundedness_maps_a_low_score_to_hallucinated(monkeypatch):
    _FakeFaithfulnessMetric.next_score = 0.1
    monkeypatch.setattr(golden_dataset_harness, "FaithfulnessMetric", _FakeFaithfulnessMetric)

    result = evaluate_groundedness("an answer", ["some context"])

    assert result["verdict"] == "HALLUCINATED"


def test_evaluate_groundedness_on_judge_failure_returns_error_shape_not_raise(monkeypatch):
    monkeypatch.setattr(golden_dataset_harness, "FaithfulnessMetric", _RaisingFaithfulnessMetric)

    result = evaluate_groundedness("an answer", ["some context"])

    assert result["score"] == 0.5
    assert result["verdict"] == "ERROR"
    assert "judge model unreachable" in result["explanation"]


def test_evaluate_groundedness_judge_model_override_reports_as_model_used(monkeypatch):
    _FakeFaithfulnessMetric.next_score = 0.9
    monkeypatch.setattr(golden_dataset_harness, "FaithfulnessMetric", _FakeFaithfulnessMetric)

    result = evaluate_groundedness("an answer", ["some context"], judge_model="gpt-4.1-nano")

    assert result["model_used"] == "gpt-4.1-nano"


def test_evaluate_completeness_maps_a_high_score_to_complete(monkeypatch):
    _FakeGEval.next_score = 0.9
    monkeypatch.setattr(golden_dataset_harness, "GEval", _FakeGEval)

    result = evaluate_completeness("what is the pto policy?", "15 days a year")

    assert result["score"] == 0.9
    assert result["verdict"] == "COMPLETE"
    assert result["explanation"] == "fake completeness reason"
    assert result["prompt"] == "fake geval verbose logs"


def test_evaluate_completeness_maps_a_low_score_to_incomplete(monkeypatch):
    _FakeGEval.next_score = 0.2
    monkeypatch.setattr(golden_dataset_harness, "GEval", _FakeGEval)

    result = evaluate_completeness("what is the pto policy?", "I don't know")

    assert result["verdict"] == "INCOMPLETE"


def test_evaluate_completeness_with_a_reference_answer_folds_it_into_the_test_case_input(monkeypatch):
    _FakeGEval.next_score = 0.9
    captured = {}

    class _CapturingGEval(_FakeGEval):
        def measure(self, test_case):
            captured["input"] = test_case.input

    monkeypatch.setattr(golden_dataset_harness, "GEval", _CapturingGEval)

    evaluate_completeness("what is the pto policy?", "15 days a year", reference_answer="15 days per year, accrued monthly")

    assert "what is the pto policy?" in captured["input"]
    assert "15 days per year, accrued monthly" in captured["input"]


def test_evaluate_completeness_on_judge_failure_returns_error_shape_not_raise(monkeypatch):
    class _RaisingGEval:
        def __init__(self, **kwargs):
            pass

        def measure(self, test_case):
            raise RuntimeError("judge model unreachable")

    monkeypatch.setattr(golden_dataset_harness, "GEval", _RaisingGEval)

    result = evaluate_completeness("what is the pto policy?", "15 days a year")

    assert result["score"] == 0.5
    assert result["verdict"] == "ERROR"


class _FakeAnswerRelevancyMetric:
    def __init__(self, model=None, threshold=0.0, include_reason=True):
        self.score = _FakeAnswerRelevancyMetric.next_score
        self.reason = "fake answer relevancy reason"
        self.verbose_logs = "fake answer relevancy verbose logs"

    def measure(self, test_case):
        self.test_case = test_case


class _FakeContextualPrecisionMetric:
    def __init__(self, model=None, threshold=0.0, include_reason=True):
        self.score = _FakeContextualPrecisionMetric.next_score
        self.reason = "fake contextual precision reason"
        self.verbose_logs = "fake contextual precision verbose logs"

    def measure(self, test_case):
        self.test_case = test_case


class _FakeContextualRecallMetric:
    def __init__(self, model=None, threshold=0.0, include_reason=True):
        self.score = _FakeContextualRecallMetric.next_score
        self.reason = "fake contextual recall reason"
        self.verbose_logs = "fake contextual recall verbose logs"

    def measure(self, test_case):
        self.test_case = test_case


def test_evaluate_answer_relevancy_maps_a_high_score_to_relevant(monkeypatch):
    _FakeAnswerRelevancyMetric.next_score = 0.9
    monkeypatch.setattr(golden_dataset_harness, "AnswerRelevancyMetric", _FakeAnswerRelevancyMetric)

    result = evaluate_answer_relevancy("what is the pto policy?", "15 days a year")

    assert result["score"] == 0.9
    assert result["verdict"] == "RELEVANT"
    assert result["explanation"] == "fake answer relevancy reason"


def test_evaluate_answer_relevancy_maps_a_low_score_to_irrelevant(monkeypatch):
    _FakeAnswerRelevancyMetric.next_score = 0.1
    monkeypatch.setattr(golden_dataset_harness, "AnswerRelevancyMetric", _FakeAnswerRelevancyMetric)

    result = evaluate_answer_relevancy("what is the pto policy?", "the weather is nice today")

    assert result["verdict"] == "IRRELEVANT"


def test_evaluate_answer_relevancy_on_judge_failure_returns_error_shape_not_raise(monkeypatch):
    class _RaisingAnswerRelevancyMetric:
        def __init__(self, **kwargs):
            pass

        def measure(self, test_case):
            raise RuntimeError("judge model unreachable")

    monkeypatch.setattr(golden_dataset_harness, "AnswerRelevancyMetric", _RaisingAnswerRelevancyMetric)

    result = evaluate_answer_relevancy("what is the pto policy?", "15 days a year")

    assert result["score"] == 0.5
    assert result["verdict"] == "ERROR"


def test_evaluate_contextual_precision_returns_the_metrics_own_score(monkeypatch):
    _FakeContextualPrecisionMetric.next_score = 0.75
    monkeypatch.setattr(golden_dataset_harness, "ContextualPrecisionMetric", _FakeContextualPrecisionMetric)

    result = evaluate_contextual_precision(
        "what is the pto policy?", "15 days a year", ["15 days of pto per year"], "15 days of pto per year"
    )

    assert result["score"] == 0.75
    assert result["explanation"] == "fake contextual precision reason"
    assert "score" in result and "verdict" not in result  # no verdict bucket for this one, unlike the others


def test_evaluate_contextual_precision_on_judge_failure_returns_error_shape_not_raise(monkeypatch):
    class _RaisingContextualPrecisionMetric:
        def __init__(self, **kwargs):
            pass

        def measure(self, test_case):
            raise RuntimeError("judge model unreachable")

    monkeypatch.setattr(golden_dataset_harness, "ContextualPrecisionMetric", _RaisingContextualPrecisionMetric)

    result = evaluate_contextual_precision("q", "a", ["c"], "e")

    assert result["score"] == 0.5
    assert "judge model unreachable" in result["explanation"]


def test_evaluate_contextual_recall_returns_the_metrics_own_score(monkeypatch):
    _FakeContextualRecallMetric.next_score = 0.6
    monkeypatch.setattr(golden_dataset_harness, "ContextualRecallMetric", _FakeContextualRecallMetric)

    result = evaluate_contextual_recall(
        "what is the pto policy?", "15 days a year", ["15 days of pto per year"], "15 days of pto per year"
    )

    assert result["score"] == 0.6
    assert result["explanation"] == "fake contextual recall reason"


def test_evaluate_contextual_recall_on_judge_failure_returns_error_shape_not_raise(monkeypatch):
    class _RaisingContextualRecallMetric:
        def __init__(self, **kwargs):
            pass

        def measure(self, test_case):
            raise RuntimeError("judge model unreachable")

    monkeypatch.setattr(golden_dataset_harness, "ContextualRecallMetric", _RaisingContextualRecallMetric)

    result = evaluate_contextual_recall("q", "a", ["c"], "e")

    assert result["score"] == 0.5
    assert "judge model unreachable" in result["explanation"]


class TestEvaluateRoutingAccuracy:
    """Phase 258 - deterministic, no LLM call, no judge model to fake."""

    def test_no_expectation_returns_none(self):
        assert evaluate_routing_accuracy(None, ["SearchKnowledgeBase"]) is None

    def test_expected_tool_was_called_scores_one(self):
        result = evaluate_routing_accuracy("GetLeaveBalance", ["GetLeaveBalance"])

        assert result["score"] == 1.0
        assert result["expected"] == "GetLeaveBalance"
        assert result["actual"] == ["GetLeaveBalance"]

    def test_expected_tool_among_several_actual_still_scores_one(self):
        result = evaluate_routing_accuracy("GetLeaveBalance", ["SearchKnowledgeBase", "GetLeaveBalance"])

        assert result["score"] == 1.0

    def test_expected_tool_not_called_scores_zero(self):
        result = evaluate_routing_accuracy("GetLeaveHistory", ["SearchKnowledgeBase"])

        assert result["score"] == 0.0

    def test_no_tools_called_at_all_scores_zero(self):
        result = evaluate_routing_accuracy("GetLeaveBalance", [])

        assert result["score"] == 0.0

    def test_works_identically_for_an_agent_name_not_just_a_tool_name(self):
        """Confirms the same function serves multi-agentic-rag's expected_agent
        too - no separate implementation needed."""
        result = evaluate_routing_accuracy("lms_ops_agent", ["lms_ops_agent"])

        assert result["score"] == 1.0
