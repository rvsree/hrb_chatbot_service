"""Scores retrieval + generation against the golden dataset - ported directly from the
IK FDE cohort's modules/5_evaluation/demo.py (Phase 62), not DeepEval's built-in metrics.
Takes any pipeline as a plain function, not hardcoded."""

import json

from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway

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


def _parse_judge_score(output: str) -> float:
    """Course's own parse logic: read the "Score: X" line, normalize 0-10 to 0-1, default 0.5 on failure."""
    try:
        score_line = [line for line in output.split("\n") if line.startswith("Score:")][0]
        return float(score_line.split(":")[1].strip()) / 10.0
    except Exception:
        return 0.5


def evaluate_groundedness(answer: str, context_texts: list[str]) -> dict:
    """Groundedness (Faithfulness): is the answer supported by the retrieved context?
    LLM-as-judge, course's own prompt - judge sees ONLY retrieved evidence, to test faithfulness."""
    context = "\n\n".join(context_texts)

    prompt = f"""Evaluate if the ANSWER is fully supported by the CONTEXT. Check for hallucinations or unsupported claims.

CONTEXT:
{context}

ANSWER:
{answer}

Rate the groundedness from 0 to 10:

Provide:
1. Score (0-10)
2. Reasoning (one sentence)

Format:
Score: X
Reasoning: <explanation>"""

    try:
        output = get_client_gateway().openai_chat().ask(prompt, temperature=0.0)
        score = _parse_judge_score(output)
        verdict = "GROUNDED" if score >= 0.7 else "PARTIAL" if score >= 0.4 else "HALLUCINATED"
        return {"score": score, "verdict": verdict, "explanation": output, "prompt": prompt}
    except Exception as error:
        return {"score": 0.5, "verdict": "ERROR", "explanation": str(error), "prompt": prompt}


def evaluate_completeness(question: str, answer: str, reference_answer: str | None = None) -> dict:
    """Response Completeness: does the answer fully address the question?
    LLM-as-judge, course's own prompt - relative to reference coverage when one exists."""
    if reference_answer:
        prompt = f"""Evaluate if the ANSWER fully addresses the QUESTION compared to the REFERENCE ANSWER.

QUESTION:
{question}

REFERENCE ANSWER:
{reference_answer}

GENERATED ANSWER:
{answer}

Rate the completeness from 0 to 10:

Provide:
1. Score (0-10)
2. Reasoning (one sentence)

Format:
Score: X
Reasoning: <explanation>"""
    else:
        prompt = f"""Evaluate if the ANSWER fully addresses the QUESTION.

QUESTION:
{question}

ANSWER:
{answer}

Rate the completeness from 0 to 10:

Provide:
1. Score (0-10)
2. Reasoning (one sentence)

Format:
Score: X
Reasoning: <explanation>"""

    try:
        output = get_client_gateway().openai_chat().ask(prompt, temperature=0.0)
        score = _parse_judge_score(output)
        verdict = "COMPLETE" if score >= 0.7 else "PARTIAL" if score >= 0.4 else "INCOMPLETE"
        return {"score": score, "verdict": verdict, "explanation": output, "prompt": prompt}
    except Exception as error:
        return {"score": 0.5, "verdict": "ERROR", "explanation": str(error), "prompt": prompt}


def evaluate_retrieval_relevance(query: str, chunk_texts: list[str]) -> dict:
    """Live (per-query) retrieval precision - the piece calculate_retrieval_metrics()
    can't do for a live question, which has no pre-known "correct" document to
    exact-match against. One LLM call judges every retrieved chunk at once (not one
    call per chunk - real cost, kept to a single call), asked which chunks actually
    help answer the question. precision = (chunks judged relevant) / (chunks retrieved).

    Deliberately does NOT return a live recall or F1 - recall needs the total count
    of relevant documents that exist, which is unknowable for an arbitrary live
    question outside the golden dataset. Returning a fabricated recall number here
    would be worse than not showing one."""
    if not chunk_texts:
        return {"precision": None, "relevant_chunk_indices": [], "explanation": None, "prompt": None}

    numbered_chunks = "\n\n".join(f"[{index + 1}] {text}" for index, text in enumerate(chunk_texts))
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
        output = get_client_gateway().openai_chat().ask(prompt, temperature=0.0)
        relevant_line = next((line for line in output.split("\n") if line.startswith("Relevant:")), "Relevant: none")
        numbers_text = relevant_line.split(":", 1)[1].strip()
        raw_indices = (
            [] if numbers_text.lower() == "none" else [int(n.strip()) for n in numbers_text.split(",") if n.strip().isdigit()]
        )
        # The judge is a free-text LLM response, not a constrained one - it can
        # hallucinate a duplicate or out-of-range chunk number (confirmed live:
        # "Relevant: 1, 3, 2, 5" against only 2 real chunks produced precision
        # 2.0, mathematically impossible). Clamp to the real chunk range and
        # dedupe before computing precision.
        relevant_indices = sorted({index for index in raw_indices if 1 <= index <= len(chunk_texts)})
        precision = len(relevant_indices) / len(chunk_texts)
        return {"precision": precision, "relevant_chunk_indices": relevant_indices, "explanation": output, "prompt": prompt}
    except Exception as error:
        return {"precision": None, "relevant_chunk_indices": [], "explanation": str(error), "prompt": prompt}


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

    scores = {}
    if relevant_ids:
        retrieval_scores = calculate_retrieval_metrics(retrieved_ids, relevant_ids)
        scores["precision"] = retrieval_scores["precision"]
        scores["recall"] = retrieval_scores["recall"]
        scores["f1"] = retrieval_scores["f1"]

    groundedness = evaluate_groundedness(answer, retrieved_texts)
    completeness = evaluate_completeness(case["query"], answer, case.get("expected_answer"))
    scores["groundedness"] = groundedness["score"]
    scores["completeness"] = completeness["score"]

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
