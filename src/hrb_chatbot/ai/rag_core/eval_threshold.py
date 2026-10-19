"""Phase 215 - shared "is this live answer's eval score below a caller-given
threshold" check, used identically by all 3 pipelines' own _score_live_answer()."""

EVAL_THRESHOLD_METRICS = ("groundedness", "completeness", "retrieval_precision")


def check_eval_threshold(eval_scores: dict, threshold: float | None) -> tuple[bool, list[str]]:
    """Compares whichever of groundedness/completeness/retrieval_precision are
    actually present in eval_scores against threshold. No threshold given means
    no check - (False, []) - same as nothing to flag, not a silent pass."""
    if threshold is None:
        return False, []

    breached = [
        metric
        for metric in EVAL_THRESHOLD_METRICS
        if eval_scores.get(metric) is not None and eval_scores[metric] < threshold
    ]
    return bool(breached), breached
