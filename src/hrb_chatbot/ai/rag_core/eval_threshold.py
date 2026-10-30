"""Phase 215 - shared "is this live answer's eval score below a caller-given
threshold" check, used identically by all 3 pipelines' own _score_live_answer().
Phase 246 - also the shared home for the per-judge on/off switches and the
shared eval_scores dict construction, same reasoning: all 3 pipelines'
_score_live_answer() implementations were near-identical, now genuinely share
this code instead of each re-implementing it."""

import asyncio

from langsmith import Client
from langsmith.run_helpers import get_current_run_tree

from src.hrb_chatbot.ai.rag_pipeline.evaluations.golden_dataset_harness import (
    evaluate_answer_relevancy,
    evaluate_completeness,
    evaluate_groundedness,
    evaluate_retrieval_relevance,
)
from src.hrb_chatbot.ai.search_pre_processing.intent_classify import classify_query_intent
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_core.eval_threshold")

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


async def maybe_capture_live_query(
    query: str, answer: str, eval_scores: dict | None, pipeline: str, request_id: str | None, employee_id: str | None,
) -> None:
    """Phase 257 - called once by each of the 3 pipelines, right after they
    build eval_scores (same shared-helper pattern as build_eval_scores
    itself). Fire-and-forget: never raises, a capture failure must never
    affect the real response being scored. Gates on groundedness alone
    (always-on by default, simplest) crossing the LTM threshold -
    app_settings key ltm_score_threshold, default 0.6 if never set.
    No-op if groundedness wasn't computed (EVAL_GROUNDEDNESS_ENABLED=false)."""
    if eval_scores is None:
        return
    groundedness = eval_scores.get("groundedness")
    if groundedness is None:
        return
    # Phase 277 - intent classification, purely for observability: tags
    # this trace and fills the live_queries table's own long-dormant
    # category column. Never raised past this function - a classification
    # failure must not block the capture it rides alongside.
    category = None
    try:
        category = classify_query_intent(query)
        run = get_current_run_tree()
        if run is not None:
            run.add_tags([f"intent:{category}"])
    except Exception as error:
        logger.warning("Could not classify query intent for pipeline=%s request_id=%s: %s", pipeline, request_id, error)
    try:
        gateway = get_db_gateway()
        threshold = await gateway.app_settings_store().get_setting("ltm_score_threshold", 0.6)
        await gateway.live_query_store().capture(
            query_text=query,
            answer_text=answer,
            pipeline=pipeline,
            request_id=request_id,
            employee_id=employee_id,
            eval_score=groundedness,
            is_ltm=groundedness >= threshold,
            category=category,
        )
    except Exception as error:
        logger.warning("Could not capture live query for pipeline=%s request_id=%s: %s", pipeline, request_id, error)


async def meets_cache_quality_threshold(eval_scores: dict | None) -> bool:
    """2026-10-30, user-directed - an answer below the live-query LTM
    threshold (same app_settings key ltm_score_threshold, default 0.6, as
    maybe_capture_live_query() above) must not be cached: caching is what
    makes a bad answer fast to repeat, which is worse than not caching it.
    Returns True (don't block caching) when no groundedness score is
    available at all - the eval-judge feature being off shouldn't silently
    disable a different feature (caching)."""
    if eval_scores is None:
        return True
    groundedness = eval_scores.get("groundedness")
    if groundedness is None:
        return True
    threshold = await get_db_gateway().app_settings_store().get_setting("ltm_score_threshold", 0.6)
    return groundedness >= threshold


_LANGSMITH_CLIENT: Client | None = None


def _get_langsmith_client() -> Client:
    global _LANGSMITH_CLIENT
    if _LANGSMITH_CLIENT is None:
        _LANGSMITH_CLIENT = Client()
    return _LANGSMITH_CLIENT


# Phase 271 - which eval_scores keys are real feedback-worthy metrics, not
# their own verdict/explanation/prompt sidecar fields (those stay visible
# in the trace's own output/metadata, not duplicated as feedback scores).
_FEEDBACK_METRICS = ("groundedness", "completeness", "retrieval_precision", "answer_relevancy")


async def record_eval_feedback(eval_scores: dict | None) -> None:
    """Phase 271 - posts each non-null metric in _FEEDBACK_METRICS to
    LangSmith as feedback on the current trace, so traces become
    filterable/sortable by eval score directly in LangSmith's own Tracing
    view, not just visible per-trace in its metadata panel. Called from
    each pipeline's own top-level function (answer_query()/run_agent()/
    run_multi_agent()), all 3 now @traceable - get_current_run_tree()
    needs their span still open to resolve correctly at this point (after
    the inner chain.invoke()/graph.ainvoke()/tool-calling loop has already
    returned).

    No-ops cleanly when tracing is off (get_current_run_tree() returns
    None then) or eval_scores is None/empty. Fire-and-forget, same
    discipline as maybe_capture_live_query() right above - a feedback-post
    failure must never affect the real response being scored."""
    if not eval_scores:
        return
    run = get_current_run_tree()
    if run is None:
        return
    client = _get_langsmith_client()
    for metric in _FEEDBACK_METRICS:
        value = eval_scores.get(metric)
        if value is None:
            continue
        try:
            await asyncio.to_thread(client.create_feedback, run_id=run.id, key=metric, score=value)
        except Exception as error:
            logger.warning("Could not post LangSmith feedback for key=%s run_id=%s: %s", metric, run.id, error)


async def tag_golden_match(query: str) -> None:
    """Phase 274 - if this live query's text exactly matches (case/
    whitespace-insensitive) a Golden Dataset case, tags the current
    LangSmith trace `golden_match:<case_key>` and attaches the golden
    case's own expected_answer as trace metadata - so opening that trace
    in LangSmith shows the submitted query, the real actual answer
    (already the trace's own output), and the golden expected answer
    (metadata) together, with no app-side wire-shape/UI change needed.

    No-ops cleanly when tracing is off (get_current_run_tree() returns
    None) or there's no match. Fire-and-forget, same discipline as
    maybe_capture_live_query()/record_eval_feedback() above - a lookup or
    tag/metadata-post failure must never affect the real response."""
    run = get_current_run_tree()
    if run is None:
        return
    try:
        golden_case = await get_db_gateway().golden_dataset_store().find_by_query(query)
        if golden_case is None:
            return
        expected_answer = golden_case["raw_case"].get("expected_answer")
        run.add_tags([f"golden_match:{golden_case['case_key']}"])
        run.add_metadata(
            {
                "golden_case_key": golden_case["case_key"],
                "golden_expected_answer": expected_answer,
            }
        )
    except Exception as error:
        logger.warning("Could not tag golden-dataset match for query=%r: %s", query, error)
