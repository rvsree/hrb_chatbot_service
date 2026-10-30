"""Scores retrieval + generation against the golden dataset - ported directly from the
IK FDE cohort's modules/5_evaluation/demo.py (Phase 62). Phase 249 moved groundedness/
completeness onto DeepEval (see deepeval_judge_model.py) - a deliberate, user-approved
deviation from that courseware's own hand-rolled-prompt pattern, see
docs/dev-reference/deepeval-standardization-design.html. Retrieval scoring
(calculate_retrieval_metrics/evaluate_retrieval_relevance) stays hand-rolled, untouched."""

import json

from deepeval.metrics import AnswerRelevancyMetric, ContextualPrecisionMetric, ContextualRecallMetric, FaithfulnessMetric, GEval
from deepeval.test_case import LLMTestCase, SingleTurnParams
from langsmith import traceable

from src.hrb_chatbot.ai.rag_core.deepeval_judge_model import GatewayDeepEvalModel
from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway
from src.hrb_chatbot.common.enums import LlmProvider


def _resolve_judge_model_name(judge_model: str | None, judge_provider: LlmProvider | None) -> str:
    """Phase 256 - same resolution pattern the OpenAI path already used,
    mirrored for Anthropic: an explicit judge_model always wins; otherwise
    fall back to whichever provider's own configured default model."""
    if judge_model:
        return judge_model
    if judge_provider == LlmProvider.ANTHROPIC:
        return get_client_gateway().anthropic_chat().model
    return get_client_gateway().openai_chat().model

GOLDEN_DATASET_PATH = "resources/golden_dataset/golden_dataset.json"


def load_golden_cases() -> list[dict]:
    with open(GOLDEN_DATASET_PATH, encoding="utf-8") as file:
        data = json.load(file)
    return data["cases"]


def calculate_retrieval_metrics(retrieved_ids: list[str], relevant_ids: list[str], k: int = 3) -> dict:
    """Precision/Recall/F1@k - course's own exact-match method, not an LLM judgment.

    Precision@k = (relevant docs in top-k) / k
    Recall@k = (relevant docs in top-k) / (total relevant docs)
    F1@k = harmonic mean of Precision and Recall
    """
    retrieved_set = set(retrieved_ids[:k])
    relevant_set = set(relevant_ids)

    tp = len(retrieved_set & relevant_set)

    precision = tp / k if k > 0 else 0.0
    recall = tp / len(relevant_set) if len(relevant_set) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": tp,
        "retrieved_count": k,
        "relevant_count": len(relevant_set),
    }


def evaluate_groundedness(
    answer: str, context_texts: list[str], judge_model: str | None = None, judge_provider: LlmProvider | None = None
) -> dict:
    """Groundedness (Faithfulness): is the answer supported by the retrieved context?
    Phase 249: DeepEval's FaithfulnessMetric under the hood - judge sees ONLY retrieved
    evidence, same faithfulness test as before, now DeepEval-powered.

    Phase 215: judge_model, when given, overrides which model does the
    judging - the real model used (override or the client's own default)
    is always returned as model_used, so a caller can verify an override
    actually took effect rather than just trusting it did.

    Phase 256: judge_provider, when given, routes the judge call through
    Anthropic instead of OpenAI - default stays OpenAI (None), unchanged."""
    resolved_model = _resolve_judge_model_name(judge_model, judge_provider)
    test_case = LLMTestCase(input="", actual_output=answer, retrieval_context=context_texts)
    metric = FaithfulnessMetric(model=GatewayDeepEvalModel(judge_model, judge_provider), threshold=0.0, include_reason=True)

    try:
        metric.measure(test_case)
        score = metric.score
        verdict = "GROUNDED" if score >= 0.7 else "PARTIAL" if score >= 0.4 else "HALLUCINATED"
        return {
            "score": score,
            "verdict": verdict,
            "explanation": metric.reason,
            "prompt": metric.verbose_logs,
            "model_used": resolved_model,
        }
    except Exception as error:
        return {"score": 0.5, "verdict": "ERROR", "explanation": str(error), "prompt": None, "model_used": resolved_model}


def evaluate_completeness(
    question: str,
    answer: str,
    reference_answer: str | None = None,
    judge_model: str | None = None,
    judge_provider: LlmProvider | None = None,
) -> dict:
    """Response Completeness: does the answer fully address the question?
    Phase 249: DeepEval's GEval (custom criteria - DeepEval has no built-in
    "Completeness" metric) under the hood - same question relative to a
    reference answer when one exists.

    Phase 215: judge_model, when given, overrides which model does the judging.
    Phase 256: judge_provider, when given, routes through Anthropic instead
    of OpenAI - default stays OpenAI (None), unchanged."""
    resolved_model = _resolve_judge_model_name(judge_model, judge_provider)
    question_text = f"{question}\n\nReference answer: {reference_answer}" if reference_answer else question
    test_case = LLMTestCase(input=question_text, actual_output=answer)
    metric = GEval(
        name="Completeness",
        criteria="Does the answer fully address every part of the question, without leaving anything unanswered?",
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=GatewayDeepEvalModel(judge_model, judge_provider),
        threshold=0.0,
    )

    try:
        metric.measure(test_case)
        score = metric.score
        verdict = "COMPLETE" if score >= 0.7 else "PARTIAL" if score >= 0.4 else "INCOMPLETE"
        return {
            "score": score,
            "verdict": verdict,
            "explanation": metric.reason,
            "prompt": metric.verbose_logs,
            "model_used": resolved_model,
        }
    except Exception as error:
        return {"score": 0.5, "verdict": "ERROR", "explanation": str(error), "prompt": None, "model_used": resolved_model}


def evaluate_answer_relevancy(
    question: str, answer: str, judge_model: str | None = None, judge_provider: LlmProvider | None = None
) -> dict:
    """Answer Relevancy: does the answer actually address what was asked -
    a new metric, Phase 250, doesn't exist in the hand-rolled version.
    DeepEval's AnswerRelevancyMetric - different from completeness (which
    checks full coverage of every part of the question); this checks the
    answer isn't off-topic/padded with irrelevant content.

    Phase 256: judge_provider, when given, routes through Anthropic instead
    of OpenAI - default stays OpenAI (None), unchanged."""
    resolved_model = _resolve_judge_model_name(judge_model, judge_provider)
    test_case = LLMTestCase(input=question, actual_output=answer)
    metric = AnswerRelevancyMetric(model=GatewayDeepEvalModel(judge_model, judge_provider), threshold=0.0, include_reason=True)

    try:
        metric.measure(test_case)
        score = metric.score
        verdict = "RELEVANT" if score >= 0.7 else "PARTIAL" if score >= 0.4 else "IRRELEVANT"
        return {
            "score": score,
            "verdict": verdict,
            "explanation": metric.reason,
            "prompt": metric.verbose_logs,
            "model_used": resolved_model,
        }
    except Exception as error:
        return {"score": 0.5, "verdict": "ERROR", "explanation": str(error), "prompt": None, "model_used": resolved_model}


def evaluate_contextual_precision(
    query: str,
    answer: str,
    chunk_texts: list[str],
    expected_answer: str,
    judge_model: str | None = None,
    judge_provider: LlmProvider | None = None,
) -> dict:
    """Golden-dataset-only (needs expected_output) - are the relevant chunks
    ranked above irrelevant ones? Phase 250, additive: a new, separate
    number from calculate_retrieval_metrics()'s own exact-ID-match
    precision, which stays the one RELEASE_GATE_THRESHOLDS/the CI eval-gate
    actually key off - this is not a replacement for that.

    Phase 256: judge_provider, when given, routes through Anthropic instead
    of OpenAI - default stays OpenAI (None), unchanged."""
    resolved_model = _resolve_judge_model_name(judge_model, judge_provider)
    test_case = LLMTestCase(input=query, actual_output=answer, expected_output=expected_answer, retrieval_context=chunk_texts)
    metric = ContextualPrecisionMetric(model=GatewayDeepEvalModel(judge_model, judge_provider), threshold=0.0, include_reason=True)

    try:
        metric.measure(test_case)
        return {"score": metric.score, "explanation": metric.reason, "prompt": metric.verbose_logs, "model_used": resolved_model}
    except Exception as error:
        return {"score": 0.5, "explanation": str(error), "prompt": None, "model_used": resolved_model}


def evaluate_contextual_recall(
    query: str,
    answer: str,
    chunk_texts: list[str],
    expected_answer: str,
    judge_model: str | None = None,
    judge_provider: LlmProvider | None = None,
) -> dict:
    """Golden-dataset-only (needs expected_output) - does retrieval contain
    everything needed to produce the expected answer? Phase 250, additive -
    same non-replacement relationship to calculate_retrieval_metrics()'s
    own exact-ID-match recall as evaluate_contextual_precision()'s above.

    Phase 256: judge_provider, when given, routes through Anthropic instead
    of OpenAI - default stays OpenAI (None), unchanged."""
    resolved_model = _resolve_judge_model_name(judge_model, judge_provider)
    test_case = LLMTestCase(input=query, actual_output=answer, expected_output=expected_answer, retrieval_context=chunk_texts)
    metric = ContextualRecallMetric(model=GatewayDeepEvalModel(judge_model, judge_provider), threshold=0.0, include_reason=True)

    try:
        metric.measure(test_case)
        return {"score": metric.score, "explanation": metric.reason, "prompt": metric.verbose_logs, "model_used": resolved_model}
    except Exception as error:
        return {"score": 0.5, "explanation": str(error), "prompt": None, "model_used": resolved_model}


@traceable(name="evaluate_retrieval_relevance")
def evaluate_retrieval_relevance(
    query: str,
    chunk_texts: list[str],
    judge_model: str | None = None,
    wider_pool_texts: list[str] | None = None,
) -> dict:
    """Phase 270 - @traceable: the only remaining hand-rolled (non-DeepEval)
    judge metric, calls raw .ask() below - without this it was invisible in
    LangSmith on every live query that runs retrieval-relevance scoring.

    Live (per-query) retrieval precision - the piece calculate_retrieval_metrics()
    can't do for a live question, which has no pre-known "correct" document to
    exact-match against. One LLM call judges every retrieved chunk at once (not one
    call per chunk - real cost, kept to a single call), asked which chunks actually
    help answer the question. precision = (chunks judged relevant) / (chunks retrieved).

    Still can't return a TRUE live recall/F1 - that needs the total count of
    relevant documents that exist, which stays unknowable for an arbitrary live
    question outside the golden dataset; that limitation hasn't changed and this
    function still refuses to fabricate a number claiming to be it.

    Phase 219 - wider_pool_texts (optional) is a real, different, explicitly-
    bounded metric instead: pass chunk_texts' own values as wider_pool_texts'
    first len(chunk_texts) entries, followed by extra candidates (pipeline.py's
    _fetch_wider_pool_texts fetches these via exact-KNN, a different search
    path than whatever strategy actually produced chunk_texts, so the pool
    isn't just re-confirming the same approximation). Judging that whole pool
    in this SAME single LLM call (not a second one) gives "recall_estimate" =
    (relevant chunks within chunk_texts) / (relevant chunks found anywhere in
    the pool) - real and computable, but bounded by pool size, never claimed
    as true recall. None when wider_pool_texts isn't given, or when nothing
    in the pool was judged relevant (undefined, not fabricated as 0 or 1)."""
    client = get_client_gateway().openai_chat()
    resolved_model = judge_model or client.model
    judge_texts = wider_pool_texts if wider_pool_texts else chunk_texts
    if not judge_texts:
        return {
            "precision": None,
            "relevant_chunk_indices": [],
            "explanation": None,
            "prompt": None,
            "model_used": resolved_model,
            "recall_estimate": None,
            "f1_estimate": None,
            "pool_size": None,
            "relevant_pool_count": None,
        }

    numbered_chunks = "\n\n".join(f"[{index + 1}] {text}" for index, text in enumerate(judge_texts))
    prompt = f"""Below are chunks retrieved for a question. Identify which chunks are actually
relevant to answering it - a chunk is relevant if it contains information that helps
answer the question, even partially. A chunk about an unrelated topic is not relevant.

QUESTION:
{query}

CHUNKS:
{numbered_chunks}

Provide:
1. Relevant chunk numbers, comma-separated (or "none" if none are relevant)
2. Reasoning (one sentence)

Format:
Relevant: 1, 3
Reasoning: <explanation>"""

    try:
        output = client.ask(prompt, temperature=0.0, model_name_override=judge_model)
        relevant_line = next((line for line in output.split("\n") if line.startswith("Relevant:")), "Relevant: none")
        numbers_text = relevant_line.split(":", 1)[1].strip()
        raw_indices = (
            [] if numbers_text.lower() == "none" else [int(n.strip()) for n in numbers_text.split(",") if n.strip().isdigit()]
        )
        # The judge is a free-text LLM response, not a constrained one - it can
        # hallucinate a duplicate or out-of-range chunk number (confirmed live:
        # "Relevant: 1, 3, 2, 5" against only 2 real chunks produced precision
        # 2.0, mathematically impossible). Clamp to the real (judged) range and
        # dedupe before computing precision/recall.
        relevant_indices = sorted({index for index in raw_indices if 1 <= index <= len(judge_texts)})
        original_count = len(chunk_texts)
        # chunk_texts occupies positions 1..original_count of judge_texts by
        # construction (see docstring) - this is what keeps precision scoped
        # to the originally-retrieved set even when a wider pool was judged.
        relevant_in_original = [index for index in relevant_indices if index <= original_count]
        precision = len(relevant_in_original) / original_count if original_count else None

        recall_estimate = None
        f1_estimate = None
        pool_size = None
        relevant_pool_count = None
        if wider_pool_texts:
            pool_size = len(wider_pool_texts)
            if relevant_indices:
                # Phase 225 - the real denominator of recall_estimate,
                # previously computed here but never returned, so the
                # Explainability panel could show the final ratio but not
                # the arithmetic behind it.
                relevant_pool_count = len(relevant_indices)
                recall_estimate = len(relevant_in_original) / relevant_pool_count
                if precision is not None and (precision + recall_estimate) > 0:
                    f1_estimate = 2 * precision * recall_estimate / (precision + recall_estimate)

        return {
            "precision": precision,
            "relevant_chunk_indices": relevant_in_original,
            "explanation": output,
            "prompt": prompt,
            "model_used": resolved_model,
            "recall_estimate": recall_estimate,
            "f1_estimate": f1_estimate,
            "pool_size": pool_size,
            "relevant_pool_count": relevant_pool_count,
        }
    except Exception as error:
        return {
            "precision": None,
            "relevant_chunk_indices": [],
            "explanation": str(error),
            "prompt": prompt,
            "model_used": resolved_model,
            "recall_estimate": None,
            "f1_estimate": None,
            "pool_size": len(wider_pool_texts) if wider_pool_texts else None,
            "relevant_pool_count": None,
        }


async def score_case(case: dict, ask) -> dict:
    """Runs one case through `ask`, which must return {"answer": str, "retrieved_texts": list[str],
    "retrieved_ids": list[str]}. Retrieval metrics are skipped when the case has no known relevant
    document (unhappy_out_of_scope cases carry expected_source_document=None)."""
    result = await ask(case["query"])
    answer = result["answer"]
    retrieved_texts = result["retrieved_texts"]
    retrieved_ids = result["retrieved_ids"]

    expected_source = case.get("expected_source_document")
    relevant_ids = [expected_source] if expected_source else []
    expected_answer = case.get("expected_answer")

    scores = {}
    if relevant_ids:
        retrieval_scores = calculate_retrieval_metrics(retrieved_ids, relevant_ids)
        scores["precision"] = retrieval_scores["precision"]
        scores["recall"] = retrieval_scores["recall"]
        scores["f1"] = retrieval_scores["f1"]

    groundedness = evaluate_groundedness(answer, retrieved_texts)
    completeness = evaluate_completeness(case["query"], answer, expected_answer)
    answer_relevancy = evaluate_answer_relevancy(case["query"], answer)
    scores["groundedness"] = groundedness["score"]
    scores["completeness"] = completeness["score"]
    scores["answer_relevancy"] = answer_relevancy["score"]

    # Phase 250 - additive, golden-only (needs expected_output): a separate,
    # DeepEval-judged number alongside the exact-ID-match precision/recall/f1
    # above, never replacing them - see this function's own module docstring.
    if expected_answer:
        contextual_precision = evaluate_contextual_precision(case["query"], answer, retrieved_texts, expected_answer)
        contextual_recall = evaluate_contextual_recall(case["query"], answer, retrieved_texts, expected_answer)
        scores["contextual_precision"] = contextual_precision["score"]
        scores["contextual_recall"] = contextual_recall["score"]

    return {"case_id": case["id"], "category": case["category"], "scores": scores}


# Course's own named thresholds.
RELEASE_GATE_THRESHOLDS = {
    "precision": {"pass": 0.80, "review": 0.70},
    "recall": {"pass": 0.70, "review": 0.60},
    "f1": {"pass": 0.75, "review": 0.65},
    "groundedness": {"pass": 0.85, "review": 0.75},
    "completeness": {"pass": 0.75, "review": 0.65},
}


def get_release_decision(scores: dict) -> tuple[str, list[str]]:
    """Returns (decision, flags) - below 'review' blocks, below 'pass' asks for review.
    f1 is computed here when precision/recall are present but f1 itself is not - matches
    the course's own release-gate script, which always derives f1 rather than trusting a passed-in value."""
    scored = dict(scores)
    if "precision" in scored and "recall" in scored and "f1" not in scored:
        precision = scored["precision"]
        recall = scored["recall"]
        scored["f1"] = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    red_flags, yellow_flags = [], []
    for metric_name, thresholds in RELEASE_GATE_THRESHOLDS.items():
        if metric_name not in scored:
            continue
        value = scored[metric_name]
        if value < thresholds["review"]:
            red_flags.append(f"{metric_name} = {value:.2f} (min {thresholds['review']})")
        elif value < thresholds["pass"]:
            yellow_flags.append(f"{metric_name} = {value:.2f} (target {thresholds['pass']})")

    if red_flags:
        return "BLOCK", red_flags
    if yellow_flags:
        return "REVIEW", yellow_flags
    return "PASS", []


def diagnose_failure_patterns(scores: dict) -> list[str]:
    """Course's own four named failure patterns - root-cause hints, not just pass/fail flags."""
    precision = scores.get("precision")
    recall = scores.get("recall")
    f1 = scores.get("f1")
    groundedness = scores.get("groundedness")
    completeness = scores.get("completeness")

    patterns = []

    if precision is not None and recall is not None:
        if precision >= 0.75 and recall < 0.60:
            patterns.append(
                "PATTERN A - High Precision, Low Recall: retrieval is too conservative - "
                "correct docs found but many missed. Fix: increase k, use smaller chunks, "
                "expand query with synonyms."
            )
        if precision < 0.60 and recall >= 0.75:
            patterns.append(
                "PATTERN B - Low Precision, High Recall: too many irrelevant docs entering "
                "the result set. Fix: use MMR, add metadata filters, improve embeddings."
            )

    if f1 is not None and f1 >= 0.75 and ((groundedness is not None and groundedness < 0.70) or (completeness is not None and completeness < 0.65)):
        patterns.append(
            "PATTERN C - Strong Retrieval, Weak Generation: right documents retrieved but "
            "the LLM is not using them well. Fix: strengthen prompt, add few-shot examples, "
            "use a stronger LLM."
        )

    if groundedness is not None and groundedness < 0.70:
        patterns.append(
            "PATTERN D - Low Groundedness (Hallucination Risk): LLM is generating claims not "
            "supported by retrieved context. Fix: stricter grounding prompt, temperature=0, "
            "require source citations."
        )

    return patterns


def evaluate_routing_accuracy(expected: str | None, actual_tool_names: list[str]) -> dict | None:
    """Phase 258 - did the agent call the tool/dispatch to the agent the
    case expected? Deterministic fact, not a quality judgment - no LLM
    judge call here, unlike every other evaluate_*() in this file. Works
    for both single-agentic-rag's expected_tool (compared against
    tools_used[].tool_name) and multi-agentic-rag's expected_agent
    (multi-agentic-rag already copies each dispatched agent's name into
    that same tools_used[].tool_name key, confirmed by reading
    multi_agent_pipeline.py directly - one function serves both).
    Returns None (not scored) when the case has no expectation set, so an
    un-annotated case never drags down the aggregate."""
    if expected is None:
        return None
    return {"score": 1.0 if expected in actual_tool_names else 0.0, "expected": expected, "actual": actual_tool_names}
