"""Tests for Phase 215's shared eval-score threshold check, used identically
by all 3 pipelines' own _score_live_answer()."""

from src.hrb_chatbot.ai.rag_core.eval_threshold import check_eval_threshold


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
