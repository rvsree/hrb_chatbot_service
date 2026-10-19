"""Scores Gate 1 (input guardrail) behavior - separate from golden_dataset_harness.py, which scores answer quality."""

import json

from src.hrb_chatbot.ai.pre_processing.guardrails_input import GuardrailBlockedError, check_input

NFR_GOLDEN_DATASET_PATH = "resources/golden_dataset/nfr_golden_dataset.json"


def load_nfr_cases() -> list[dict]:
    with open(NFR_GOLDEN_DATASET_PATH, encoding="utf-8") as file:
        data = json.load(file)
    return data["cases"]


async def score_nfr_case(case: dict) -> dict:
    """'blocked' if check_input() raises, 'masked' if NeMo reports MODIFIED,
    else 'pass'. Phase 224 - reads the real status field now instead of
    inferring "masked" by string-comparing the checked query against the
    original (strictly more accurate - a status change with no visible
    text difference would have been missed before)."""
    try:
        _, status = await check_input(case["query"])
        actual_outcome = "masked" if status["status"] == "modified" else "pass"
    except GuardrailBlockedError:
        actual_outcome = "blocked"

    return {
        "case_id": case["id"],
        "category": case["category"],
        "expected_outcome": case["expected_outcome"],
        "actual_outcome": actual_outcome,
        "passed": actual_outcome == case["expected_outcome"],
    }
