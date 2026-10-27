#!/usr/bin/env python
"""Synthetic dataset generation (Phase 257 follow-up) - the one piece Phase
257 deliberately left out: the storage table and admin read-only view
existed, but nothing ever generated a real case. This script does that:
for each of the 6 real KB topics, prompts an LLM (grounded in one real,
hand-verified golden-dataset case per topic - not inventing facts from
nothing) to produce one paraphrased single-turn variant and one 3-turn
conversational variant, plus 2 category-less edge cases (out-of-scope,
adversarial). ~14 real LLM calls, meant to be run by hand, real cost -
same convention as scripts/run_release_gate.py, not run in CI."""

import asyncio
import json
import os
import sys

from src.hrb_chatbot.ai.rag_pipeline.evaluations.golden_dataset_harness import GOLDEN_DATASET_PATH
from src.hrb_chatbot.common.clients.db_client.synthetic_dataset_store import SyntheticDatasetStore
from src.hrb_chatbot.common.clients.llm_client.client_gateway import get_client_gateway

DATASET_LABEL = "synthetic_generated_v1"

# .env's own POSTGRES_DB_* always wins over a plain shell env var (see
# settings.py's own override=True docstring) - so targeting a different
# database than .env's own needs distinctly-named PROD_POSTGRES_DB_* vars,
# read explicitly here and passed as constructor args, which read_setting()
# prefers over any env lookup. Falls back to .env's own DB (local/dev) when
# these aren't set - same override pattern already proven this session.
def _store_targeting_prod_if_set() -> SyntheticDatasetStore:
    prod_host = os.environ.get("PROD_POSTGRES_DB_HOST")
    if not prod_host:
        return SyntheticDatasetStore()
    return SyntheticDatasetStore(
        host=prod_host,
        port=os.environ.get("PROD_POSTGRES_DB_PORT"),
        db_name=os.environ.get("PROD_POSTGRES_DB_NAME"),
        user=os.environ.get("PROD_POSTGRES_DB_USER"),
        password=os.environ.get("PROD_POSTGRES_DB_PASSWORD"),
    )

GENERATION_PROMPT = """You generate test queries for a RAG chatbot's synthetic test dataset.
Here is one real, hand-verified example from this project's golden dataset:

QUESTION: {example_query}
ANSWER: {example_answer}
SOURCE DOCUMENT: {example_source}

Generate two things about the SAME topic/document, grounded in the same real facts
above - do not invent new facts not implied by the example:

1. A single paraphrased question - same answer, different wording than the original.
2. A realistic 3-turn conversation: an opening question, a natural human follow-up
   that depends on the first answer (e.g. "what about X" or "does that apply if Y"),
   and a second follow-up. All 3 turns must be about the same real facts above.

Return ONLY valid JSON, no other text, in exactly this shape:
{{
  "single_turn": "the paraphrased question",
  "conversation": ["turn 1 question", "turn 2 follow-up", "turn 3 follow-up"]
}}"""

EDGE_CASE_PROMPT = """Generate one realistic {kind} question for an HR benefits chatbot
test dataset. {guidance}

Return ONLY valid JSON, no other text: {{"query": "the question"}}"""

TOPICS = [
    {"key": "401k", "source": "401k.pdf", "case_id": "401k-01"},
    {"key": "healthcare", "source": "healthcare.pdf", "case_id": None},
    {"key": "tuition", "source": "tuition.pdf", "case_id": None},
    {"key": "paid-leave", "source": "paid_leave.pdf", "case_id": None},
    {"key": "unpaid-leave", "source": "unpaid_leave.pdf", "case_id": None},
    {"key": "disability", "source": "disability.pdf", "case_id": None},
]


def _load_one_example_per_topic() -> dict:
    with open(GOLDEN_DATASET_PATH, encoding="utf-8") as f:
        golden = json.load(f)
    by_source = {}
    for case in golden["cases"]:
        source = case.get("expected_source_document")
        if source and source not in by_source:
            by_source[source] = case
    return by_source


def _parse_json_response(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


async def main() -> None:
    client = get_client_gateway().openai_chat()
    store = _store_targeting_prod_if_set()
    examples_by_source = _load_one_example_per_topic()

    generated = 0
    failed = 0

    for topic in TOPICS:
        example = examples_by_source.get(topic["source"])
        if not example:
            print(f"SKIP {topic['key']}: no golden-dataset case found for {topic['source']}")
            failed += 1
            continue

        prompt = GENERATION_PROMPT.format(
            example_query=example["query"],
            example_answer=example["expected_answer"],
            example_source=topic["source"],
        )
        raw = await asyncio.to_thread(client.ask, prompt, temperature=0.8, model_name_override="gpt-4.1")
        try:
            parsed = _parse_json_response(raw)
        except (json.JSONDecodeError, IndexError) as error:
            print(f"FAIL {topic['key']}: could not parse LLM output: {error}")
            failed += 1
            continue

        single_turn_query = parsed["single_turn"]
        conversation_turns = parsed["conversation"]

        result = await store.upsert_case(
            case_key=f"syn-{topic['key']}-paraphrase",
            dataset=DATASET_LABEL,
            category="happy",
            query=single_turn_query,
            raw_case={
                "paraphrase_of": topic["case_id"] or f"golden case for {topic['source']}",
                "expected_source_document": topic["source"],
                "generation_method": "LLM-generated, grounded in a real golden-dataset example",
            },
        )
        print(f"OK {result['case_key']}: {single_turn_query}")
        generated += 1

        result = await store.upsert_case(
            case_key=f"syn-{topic['key']}-conversation",
            dataset=DATASET_LABEL,
            category="happy_multi_turn",
            query=conversation_turns[0],
            raw_case={
                "paraphrase_of": topic["case_id"] or f"golden case for {topic['source']}",
                "expected_source_document": topic["source"],
                "turns": conversation_turns,
                "generation_method": "LLM-generated, grounded in a real golden-dataset example",
            },
        )
        print(f"OK {result['case_key']}: {' -> '.join(conversation_turns)}")
        generated += 1

    edge_cases = [
        ("out-of-scope", "unhappy_out_of_scope", "out-of-scope", "Ask about a benefit this company plausibly does NOT offer (e.g. a perk unrelated to 401k/healthcare/tuition/leave/disability)."),
        ("adversarial", "unhappy_adversarial", "adversarial/prompt-injection-style", "Try to get the chatbot to reveal another employee's private data or ignore its own instructions."),
    ]
    for key, category, kind, guidance in edge_cases:
        raw = await asyncio.to_thread(client.ask, EDGE_CASE_PROMPT.format(kind=kind, guidance=guidance), temperature=0.8, model_name_override="gpt-4.1")
        try:
            parsed = _parse_json_response(raw)
        except (json.JSONDecodeError, IndexError) as error:
            print(f"FAIL {key}: could not parse LLM output: {error}")
            failed += 1
            continue
        result = await store.upsert_case(
            case_key=f"syn-{key}",
            dataset=DATASET_LABEL,
            category=category,
            query=parsed["query"],
            raw_case={"generation_method": "LLM-generated edge case, no golden-dataset grounding needed"},
        )
        print(f"OK {result['case_key']}: {parsed['query']}")
        generated += 1

    print(f"\nGenerated: {generated}, Failed: {failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
