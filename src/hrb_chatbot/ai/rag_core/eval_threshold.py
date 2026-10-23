"""Phase 215 - shared "is this live answer's eval score below a caller-given
threshold" check, used identically by all 3 pipelines' own _score_live_answer().
Phase 246 - also the shared home for the per-judge on/off switches and the
shared eval_scores dict construction, same reasoning: all 3 pipelines'
_score_live_answer() implementations were near-identical, now genuinely share
this code instead of each re-implementing it."""

import asyncio

from src.hrb_chatbot.ai.rag_pipeline.evaluations.golden_dataset_harness import (
    evaluate_answer_relevancy,
    evaluate_completeness,
    evaluate_groundedness,
    evaluate_retrieval_relevance,
)
from src.hrb_chatbot.common.config.settings import read_setting

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


def _is_enabled(env_var_name: str, default: str = "true") -> bool:
    return read_setting(None, env_var_name, default).strip().lower() == "true"


def groundedness_enabled() -> bool:
    return _is_enabled("EVAL_GROUNDEDNESS_ENABLED")


def completeness_enabled() -> bool:
    return _is_enabled("EVAL_COMPLETENESS_ENABLED")


def retrieval_relevance_enabled() -> bool:
    """Also gates whether the expensive wider-pool fetch (a real exact-KNN
    call) runs at all - see each pipeline's own _score_live_answer()."""
    return _is_enabled("EVAL_RETRIEVAL_RELEVANCE_ENABLED")


def answer_relevancy_enabled() -> bool:
    """Phase 250 - unlike the 3 toggles above (which defaulted true because
    they were already running before the toggle existed), this one defaults
    false: AnswerRelevancy is a brand-new metric that has never run before,
    so opt-out-by-default would be a silent live-cost increase nobody asked
    for - opt-in instead."""
    return _is_enabled("EVAL_ANSWER_RELEVANCY_ENABLED", default="false")


async def run_enabled_eval_judges(
    query: str,
    answer: str,
    groundedness_context: list[str],
    retrieval_context: list[str],
    judge_model: str | None,
    wider_pool_texts: list[str] | None,
) -> tuple[dict | None, dict | None, dict | None, dict | None]:
    """Phase 246 - runs only the judges enabled via EVAL_*_ENABLED (default
    true each - unchanged behavior unless explicitly disabled), in parallel
    via asyncio.gather() same as before. Returns (groundedness, completeness,
    retrieval, answer_relevancy), None for any disabled judge.
    groundedness_context is what groundedness/completeness are judged
    against (may differ from retrieval_context - Phase 220's own real
    finding: retrieval-relevance scopes to real KB chunks only,
    groundedness/completeness to the full answer context, which can also
    include MCP/web-search text).

    Phase 250: answer_relevancy defaults OFF (answer_relevancy_enabled()),
    unlike the other 3 - see that function's own docstring for why."""
    names: list[str] = []
    tasks = []
    if groundedness_enabled():
        names.append("groundedness")
        tasks.append(asyncio.to_thread(evaluate_groundedness, answer, groundedness_context, judge_model))
    if completeness_enabled():
        names.append("completeness")
        tasks.append(asyncio.to_thread(evaluate_completeness, query, answer, None, judge_model))
    if retrieval_relevance_enabled():
        names.append("retrieval")
        tasks.append(
            asyncio.to_thread(evaluate_retrieval_relevance, query, retrieval_context, judge_model, wider_pool_texts)
        )
    if answer_relevancy_enabled():
        names.append("answer_relevancy")
        tasks.append(asyncio.to_thread(evaluate_answer_relevancy, query, answer, judge_model))

    results = await asyncio.gather(*tasks) if tasks else []
    by_name = dict(zip(names, results))
    return by_name.get("groundedness"), by_name.get("completeness"), by_name.get("retrieval"), by_name.get("answer_relevancy")


def build_eval_scores(
    groundedness: dict | None,
    completeness: dict | None,
    retrieval: dict | None,
    eval_score_threshold: float | None,
    answer_relevancy: dict | None = None,
) -> dict:
    """Phase 246 - the eval_scores dict all 3 pipelines used to build inline,
    identically, now shared. None-safe per judge, so a disabled judge's
    fields come back null rather than crashing - same "null means this
    didn't run" convention decompose_model_used/planner_model_used already
    use. judge_model_used falls back across whichever judge actually ran.

    Phase 250: answer_relevancy, same None-safe convention, defaults to
    None/not-run since answer_relevancy_enabled() defaults false."""
    eval_scores = {
        "groundedness": groundedness["score"] if groundedness else None,
        "groundedness_verdict": groundedness["verdict"] if groundedness else None,
        "groundedness_explanation": groundedness["explanation"] if groundedness else None,
        "groundedness_prompt": groundedness["prompt"] if groundedness else None,
        "completeness": completeness["score"] if completeness else None,
        "completeness_verdict": completeness["verdict"] if completeness else None,
        "completeness_explanation": completeness["explanation"] if completeness else None,
        "completeness_prompt": completeness["prompt"] if completeness else None,
        "retrieval_precision": retrieval["precision"] if retrieval else None,
        "retrieval_relevant_chunk_indices": retrieval["relevant_chunk_indices"] if retrieval else None,
        "retrieval_precision_explanation": retrieval["explanation"] if retrieval else None,
        "retrieval_precision_prompt": retrieval["prompt"] if retrieval else None,
        "retrieval_recall_estimate": retrieval["recall_estimate"] if retrieval else None,
        "retrieval_f1_estimate": retrieval["f1_estimate"] if retrieval else None,
        "retrieval_recall_pool_size": retrieval["pool_size"] if retrieval else None,
        "retrieval_recall_relevant_count": retrieval["relevant_pool_count"] if retrieval else None,
        "answer_relevancy": answer_relevancy["score"] if answer_relevancy else None,
        "answer_relevancy_verdict": answer_relevancy["verdict"] if answer_relevancy else None,
        "answer_relevancy_explanation": answer_relevancy["explanation"] if answer_relevancy else None,
        "answer_relevancy_prompt": answer_relevancy["prompt"] if answer_relevancy else None,
        "judge_model_used": (groundedness or completeness or retrieval or answer_relevancy or {}).get("model_used"),
    }
    eval_scores["below_threshold"], eval_scores["below_threshold_metrics"] = check_eval_threshold(
        eval_scores, eval_score_threshold
    )
    return eval_scores
