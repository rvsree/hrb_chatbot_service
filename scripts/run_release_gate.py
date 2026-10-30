#!/usr/bin/env python
"""Release gate (Phase 80) - runs every scorable golden-dataset case
through genai-rag's real pipeline.answer_query(), aggregates scores, and
calls the existing get_release_decision() to produce a PASS/REVIEW/BLOCK
verdict. Exits non-zero on BLOCK, so CI fails the job. Real LLM calls,
real cost - meant to be triggered by hand (or the eval-gate.yml workflow's
own manual trigger), not run automatically.

Phase 258 - additionally runs the subset of cases with expected_tool/
expected_agent set through single-agentic-rag/multi-agentic-rag too,
scoring routing accuracy. Informational only (never gates the PASS/
REVIEW/BLOCK decision) - only that subset pays the extra pipeline calls,
not the whole dataset. For routing-only iteration without the cost of
every other judge, see scripts/run_routing_accuracy_check.py instead.

Phase 259 - a token budget (RELEASE_GATE_TOKEN_BUDGET, default 200,000)
tracked cumulatively across the whole run. Hitting it stops the run from
starting any new cases (genai-rag or routing) and flags the result as
PARTIAL - direct response to this project's own real $70 LLM-credit
incident this session. A budget, not a precise cost calculator - token
count, not dollars, since cost-per-token varies by model/provider."""

import argparse
import asyncio
import json
import sys
import traceback

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.hrb_chatbot.ai.agents.workflow_agents import multi_agent_pipeline, orchestration_agent
from src.hrb_chatbot.ai.rag_pipeline import pipeline
from src.hrb_chatbot.ai.rag_pipeline.response_generation import response_generator
from src.hrb_chatbot.ai.rag_pipeline.evaluations.golden_dataset_harness import (
    GOLDEN_DATASET_PATH,
    calculate_retrieval_metrics,
    evaluate_completeness,
    evaluate_contextual_precision,
    evaluate_contextual_recall,
    evaluate_groundedness,
    evaluate_routing_accuracy,
    get_release_decision,
)
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.enums import LlmProvider
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.rag_query_params import RagQueryParams

logger = get_logger("run_release_gate")

METRICS = ("precision", "recall", "f1", "groundedness", "completeness", "contextual_precision", "contextual_recall")

# calculate_retrieval_metrics() defaults to k=3 (the IK FDE course's own
# demo.py value) - genai-rag actually retrieves RAG_DEFAULT_TOP_K chunks
# (5 by default). Passing the real k here (instead of score_case()'s own
# hardcoded k=3) is still correct - it reflects this project's real
# retrieval depth - but confirmed live it does NOT remove the structural
# ceiling: every golden case has exactly 1 relevant document, and
# precision@k = (relevant found)/k can never exceed 1/k when only 1
# relevant document can ever exist - 0.2 at k=5, worse than k=3's 0.33, not
# better. This is a mismatch between the metric (built for narrow
# search-result ranking, assuming several relevant results could appear)
# and this project's actual design (deliberately broad multi-chunk RAG
# context, one labeled canonical source per case) - not a quality problem,
# confirmed by recall sitting at 1.0 on nearly every case (the right
# document is always found). GATE_METRICS below is what actually feeds
# get_release_decision() - precision/f1 are still computed and printed per
# case as informational context, just never block a release.
RETRIEVAL_K = int(read_setting(None, "RAG_DEFAULT_TOP_K", 5))
GATE_METRICS = ("recall", "groundedness", "completeness")

# Phase 259 - direct response to this session's own real $70 LLM-credit
# incident. A real ceiling on how many tokens one gate run can spend before
# it stops starting new cases - a budget guard, not a precise cost
# calculator (token count != dollar cost, which varies by model/provider -
# this is a cheap, model-agnostic proxy good enough to catch a genuine
# runaway, not a billing system). Default picked generously above a normal
# full-dataset run's real usage (confirmed live: a single routing case with
# both single/multi-agentic-rag costs ~2-4k tokens; the full ~29-case
# golden set is well under this by a wide margin under normal conditions).
TOKEN_BUDGET = int(read_setting(None, "RELEASE_GATE_TOKEN_BUDGET", 200_000))


def _total_tokens(result: dict) -> int:
    token_usage = result.get("token_usage")
    return token_usage["total_tokens"] if token_usage else 0


def _load_scorable_cases() -> list[dict]:
    """Golden cases, with expected_source_document resolved from the dataset's
    own short keys ("401k.pdf") to the real uploaded filename chunks actually
    carry ("AmazingBank_Empower_401k_Savings_Plan.pdf") - confirmed live, before this
    fix, every case's precision/recall/f1 came back 0.0 because nothing was ever
    comparing against the right value, which would have made this gate always
    report BLOCK regardless of real retrieval quality. agent_call cases
    (Phase 73) are excluded - they bypass retrieval/generation entirely via
    genai-rag's own MCP routing, so scoring them against these metrics isn't meaningful."""
    with open(GOLDEN_DATASET_PATH, encoding="utf-8") as file:
        data = json.load(file)

    source_documents = data["_meta"]["source_documents"]
    cases = []
    for case in data["cases"]:
        if case.get("call_type") == "agent_call":
            continue
        resolved_case = dict(case)
        short_key = case.get("expected_source_document")
        if short_key:
            resolved_case["expected_source_document"] = source_documents.get(short_key, short_key)
        cases.append(resolved_case)
    return cases


def _load_routing_cases() -> list[dict]:
    """Phase 258 - cases with expected_tool and/or expected_agent set, for
    the routing-accuracy extension below. Unlike _load_scorable_cases(),
    deliberately INCLUDES agent_call cases - routing cases are agent_call
    by nature (genai-rag's own MCP-bypass routing_type), the exact ones
    _load_scorable_cases() excludes from genai-rag's own groundedness/
    completeness/recall scoring. The two functions serve different gates."""
    with open(GOLDEN_DATASET_PATH, encoding="utf-8") as file:
        data = json.load(file)
    return [case for case in data["cases"] if case.get("expected_tool") or case.get("expected_agent")]


async def score_routing_case(case: dict) -> dict:
    """Runs a routing case through whichever of single-agentic-rag/multi-
    agentic-rag it has an expectation for (both, if it has both). Real
    LLM calls, real cost - only paid by this specific subset of cases,
    not the whole golden dataset."""
    scores = {}
    tokens = 0
    if case.get("expected_tool"):
        result = await orchestration_agent.run_agent(case["query"], employee_id=None)
        tokens += _total_tokens(result)
        tool_names = [call["tool_name"] for call in result["tools_used"]]
        routing = evaluate_routing_accuracy(case["expected_tool"], tool_names)
        scores["single_agentic_routing"] = routing

    if case.get("expected_agent"):
        result = await multi_agent_pipeline.run_multi_agent(case["query"], employee_id=None)
        tokens += _total_tokens(result)
        tool_names = [call["tool_name"] for call in result["tools_used"]]
        routing = evaluate_routing_accuracy(case["expected_agent"], tool_names)
        scores["multi_agentic_routing"] = routing

    return {"case_id": case["id"], "category": case.get("category"), "scores": scores, "tokens": tokens}


async def ask_genai_rag(query: str) -> dict:
    """Same adapter shape test_golden_dataset_harness.py already established,
    with retrieved_ids corrected to the real filename (not document_id, a UUID
    that can never match expected_source_document regardless of retrieval quality)."""
    result = await pipeline.answer_query(RagQueryParams(query=query))
    retrieved_texts = [chunk["text"] for chunk in result["sources"]]
    retrieved_ids = [chunk["filename"] for chunk in result["sources"]]
    return {
        "answer": result["answer"],
        "retrieved_texts": retrieved_texts,
        "retrieved_ids": retrieved_ids,
        "tokens": _total_tokens(result),
    }


async def _resolve_judge_provider() -> LlmProvider | None:
    """Phase 260 - app_settings is the source of truth, read fresh at the
    top of each run (CLI script, not a live request path - "dynamic" here
    means "takes effect on the next run," not mid-run). None (OpenAI,
    today's exact behavior) if never set."""
    value = await get_db_gateway().app_settings_store().get_setting("judge_provider_default", "openai")
    return LlmProvider(value) if value != "openai" else None


async def score_case_with_real_k(case: dict, judge_provider: LlmProvider | None = None) -> dict:
    """Same shape/logic as golden_dataset_harness.py's own score_case(), just
    with calculate_retrieval_metrics() given the real retrieval depth
    (RETRIEVAL_K) instead of that function's own hardcoded k=3 default."""
    result = await ask_genai_rag(case["query"])
    answer = result["answer"]
    retrieved_texts = result["retrieved_texts"]
    retrieved_ids = result["retrieved_ids"]

    expected_source = case.get("expected_source_document")
    relevant_ids = [expected_source] if expected_source else []

    scores = {}
    if relevant_ids:
        retrieval_scores = calculate_retrieval_metrics(retrieved_ids, relevant_ids, k=RETRIEVAL_K)
        scores["precision"] = retrieval_scores["precision"]
        scores["recall"] = retrieval_scores["recall"]
        scores["f1"] = retrieval_scores["f1"]

    groundedness = evaluate_groundedness(answer, retrieved_texts, judge_provider=judge_provider)
    completeness = evaluate_completeness(case["query"], answer, case.get("expected_answer"), judge_provider=judge_provider)
    scores["groundedness"] = groundedness["score"]
    scores["completeness"] = completeness["score"]

    # Phase 256 - additive, informational-only (not in GATE_METRICS) - only
    # scorable when a case has a real expected_answer (ContextualPrecision/
    # Recall both need expected_output), same precondition evaluate_completeness's
    # own reference-answer path already uses.
    expected_answer = case.get("expected_answer")
    if expected_answer:
        contextual_precision = evaluate_contextual_precision(
            case["query"], answer, retrieved_texts, expected_answer, judge_provider=judge_provider
        )
        contextual_recall = evaluate_contextual_recall(
            case["query"], answer, retrieved_texts, expected_answer, judge_provider=judge_provider
        )
        scores["contextual_precision"] = contextual_precision["score"]
        scores["contextual_recall"] = contextual_recall["score"]

    return {"case_id": case["id"], "category": case["category"], "scores": scores, "tokens": result["tokens"]}


async def _score_genai_rag_pass(scorable_cases: list[dict], judge_provider: LlmProvider | None) -> dict:
    """Phase 273 - extracted out of main() (unchanged behavior/output there)
    so run_prompt_experiment() below can run this same real scoring loop
    twice - once against today's real prompt, once with
    response_generator.RAG_PROMPT monkeypatched to a variant - without
    duplicating it. Returns {"per_metric_scores", "failed_ids",
    "case_results", "cumulative_tokens", "budget_exceeded"}."""
    per_metric_scores: dict[str, list[float]] = {metric: [] for metric in METRICS}
    failed_ids: list[str] = []
    case_results: list[dict] = []
    cumulative_tokens = 0
    budget_exceeded = False
    print(f"Scoring {len(scorable_cases)} golden case(s) against genai-rag (retrieval k={RETRIEVAL_K})...")
    print(f"Judge provider: {judge_provider.value if judge_provider else 'openai'} (app_settings: judge_provider_default)")
    print(f"Token budget for this run: {TOKEN_BUDGET:,}\n")

    for case in scorable_cases:
        if cumulative_tokens >= TOKEN_BUDGET:
            budget_exceeded = True
            print(f"\nTOKEN BUDGET EXCEEDED ({cumulative_tokens:,}/{TOKEN_BUDGET:,}) - stopping, not starting any more cases.")
            break
        print(f"  scoring {case['id']}...", flush=True)
        try:
            result = await score_case_with_real_k(case, judge_provider=judge_provider)
        except Exception:
            print(f"  {case['id']}: FAILED", flush=True)
            traceback.print_exc()
            sys.stdout.flush()
            failed_ids.append(case["id"])
            case_results.append({"case_id": case["id"], "category": case.get("category"), "scores": {}, "status": "failed"})
            continue
        cumulative_tokens += result["tokens"]
        for metric, score in result["scores"].items():
            if metric in per_metric_scores and score is not None:
                per_metric_scores[metric].append(score)
        case_results.append(
            {"case_id": result["case_id"], "category": result["category"], "scores": result["scores"], "status": "scored"}
        )
        print(f"  {case['id']}: {result['scores']} ({cumulative_tokens:,} tokens so far)", flush=True)

    return {
        "per_metric_scores": per_metric_scores,
        "failed_ids": failed_ids,
        "case_results": case_results,
        "cumulative_tokens": cumulative_tokens,
        "budget_exceeded": budget_exceeded,
    }


def _build_variant_rag_prompt(variant_path: str) -> ChatPromptTemplate:
    """Phase 273 - same message structure RAG_PROMPT already uses (system/
    chat_history/human), just the system text swapped for the variant
    file's own content - keeps the {context}/{tabular_instruction}
    placeholders generate_answer() always fills in, since that function
    itself is completely unchanged."""
    with open(variant_path, encoding="utf-8") as file:
        variant_system_prompt = file.read()
    return ChatPromptTemplate.from_messages(
        [
            ("system", variant_system_prompt),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{question}"),
        ]
    )


def _print_experiment_comparison(baseline: dict, variant: dict) -> None:
    baseline_aggregated = {
        metric: sum(scores) / len(scores) for metric, scores in baseline["per_metric_scores"].items() if scores
    }
    variant_aggregated = {
        metric: sum(scores) / len(scores) for metric, scores in variant["per_metric_scores"].items() if scores
    }
    print("\n=== Prompt experiment: baseline vs variant ===")
    print(f"{'metric':<22}{'baseline':>10}{'variant':>10}{'delta':>10}")
    for metric in METRICS:
        if metric not in baseline_aggregated and metric not in variant_aggregated:
            continue
        base_value = baseline_aggregated.get(metric)
        variant_value = variant_aggregated.get(metric)
        base_str = f"{base_value:.3f}" if base_value is not None else "-"
        variant_str = f"{variant_value:.3f}" if variant_value is not None else "-"
        delta_str = f"{variant_value - base_value:+.3f}" if base_value is not None and variant_value is not None else "-"
        print(f"{metric:<22}{base_str:>10}{variant_str:>10}{delta_str:>10}")

    baseline_by_id = {result["case_id"]: result["scores"] for result in baseline["case_results"]}
    variant_by_id = {result["case_id"]: result["scores"] for result in variant["case_results"]}
    print("\nPer-case scores that moved:")
    for case_id in baseline_by_id:
        if baseline_by_id[case_id] != variant_by_id.get(case_id):
            print(f"  {case_id}: baseline={baseline_by_id[case_id]} variant={variant_by_id.get(case_id)}")

    total_tokens = baseline["cumulative_tokens"] + variant["cumulative_tokens"]
    print(f"\nTotal tokens used (both passes): {total_tokens:,}")


async def run_prompt_experiment(scorable_cases: list[dict], judge_provider: LlmProvider | None, variant_path: str) -> int:
    """Phase 273 - runs the real genai-rag scoring pass twice: once
    unchanged (baseline), once with response_generator.RAG_PROMPT
    monkeypatched to the variant file's text for the duration of this
    process only - pipeline.answer_query() itself is never touched, and
    nothing is ever written back to response_generator.py. Experiment
    runs are never persisted to eval_run_store (not a release decision)
    and never gate anything - stdout only."""
    print(f"PROMPT EXPERIMENT MODE: doubles real LLM cost/token usage (2 full passes, not 1) - variant file: {variant_path}\n")

    # Phase 273 - built and validated before Pass 1, not between passes: a
    # missing/unreadable variant file must fail before any real LLM call
    # (and its cost) happens, not after wasting the whole baseline pass.
    variant_prompt = _build_variant_rag_prompt(variant_path)

    original_prompt = response_generator.RAG_PROMPT
    print("--- Pass 1/2: baseline (today's real prompt) ---")
    baseline = await _score_genai_rag_pass(scorable_cases, judge_provider)

    response_generator.RAG_PROMPT = variant_prompt
    try:
        print("\n--- Pass 2/2: variant ---")
        variant = await _score_genai_rag_pass(scorable_cases, judge_provider)
    finally:
        response_generator.RAG_PROMPT = original_prompt

    _print_experiment_comparison(baseline, variant)
    return 0


async def main() -> int:
    scorable_cases = _load_scorable_cases()
    judge_provider = await _resolve_judge_provider()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt-variant",
        help="Path to a text file whose content replaces genai-rag's real system prompt for one experimental run, "
        "scored against the golden dataset twice (baseline vs variant) and printed as a comparison. "
        "Never persisted, never gates a release - see RAG-ROADMAP.md Phase 273.",
    )
    args = parser.parse_args()
    if args.prompt_variant:
        return await run_prompt_experiment(scorable_cases, judge_provider, args.prompt_variant)

    pass_result = await _score_genai_rag_pass(scorable_cases, judge_provider)
    per_metric_scores = pass_result["per_metric_scores"]
    failed_ids = pass_result["failed_ids"]
    case_results = pass_result["case_results"]
    cumulative_tokens = pass_result["cumulative_tokens"]
    budget_exceeded = pass_result["budget_exceeded"]

    # Phase 258 - routing-accuracy extension: only the subset of cases with
    # expected_tool/expected_agent set pay for the extra single-agentic-rag/
    # multi-agentic-rag calls, not every case - see script docstring/spec.
    routing_cases = _load_routing_cases()
    single_agentic_scores: list[float] = []
    multi_agentic_scores: list[float] = []
    routing_failed_ids: list[str] = []
    if routing_cases and not budget_exceeded:
        print(f"\nScoring {len(routing_cases)} routing case(s) (single/multi-agentic-rag)...\n")
        for case in routing_cases:
            if cumulative_tokens >= TOKEN_BUDGET:
                budget_exceeded = True
                print(f"\nTOKEN BUDGET EXCEEDED ({cumulative_tokens:,}/{TOKEN_BUDGET:,}) - stopping, not starting any more routing cases.")
                break
            print(f"  routing-scoring {case['id']}...", flush=True)
            try:
                routing_result = await score_routing_case(case)
            except Exception:
                print(f"  {case['id']}: FAILED", flush=True)
                traceback.print_exc()
                sys.stdout.flush()
                routing_failed_ids.append(case["id"])
                case_results.append(
                    {"case_id": case["id"], "category": case.get("category"), "scores": {}, "status": "failed"}
                )
                continue
            cumulative_tokens += routing_result["tokens"]
            single_routing = routing_result["scores"].get("single_agentic_routing")
            multi_routing = routing_result["scores"].get("multi_agentic_routing")
            if single_routing is not None:
                single_agentic_scores.append(single_routing["score"])
            if multi_routing is not None:
                multi_agentic_scores.append(multi_routing["score"])
            case_results.append(
                {
                    "case_id": routing_result["case_id"],
                    "category": routing_result["category"],
                    "scores": routing_result["scores"],
                    "status": "scored",
                }
            )
            print(f"  {case['id']}: {routing_result['scores']} ({cumulative_tokens:,} tokens so far)", flush=True)
    elif routing_cases and budget_exceeded:
        print("\nSkipping routing-accuracy scoring entirely - token budget already exceeded by the genai-rag pass above.")

    aggregated = {metric: sum(scores) / len(scores) for metric, scores in per_metric_scores.items() if scores}
    if single_agentic_scores:
        aggregated["single_agentic_routing_accuracy"] = sum(single_agentic_scores) / len(single_agentic_scores)
    if multi_agentic_scores:
        aggregated["multi_agentic_routing_accuracy"] = sum(multi_agentic_scores) / len(multi_agentic_scores)

    if routing_failed_ids:
        print(f"\nRouting case(s) that failed to score (informational only, does not gate): {', '.join(routing_failed_ids)}")

    print("\nAggregated scores (averaged across all scored cases):")
    for metric, value in aggregated.items():
        gated = " (gates the verdict)" if metric in GATE_METRICS else " (informational only - see script docstring)"
        print(f"  {metric}: {value:.3f}{gated}")

    gate_scores = {metric: value for metric, value in aggregated.items() if metric in GATE_METRICS}

    # Found live, 2026-10-05: get_release_decision({}) returns PASS on
    # empty input (nothing to check against thresholds) - with every case
    # failing to score (a real incident that day), the gate still reported
    # PASS. A gate that can't tell "verified good" apart from "verified
    # nothing" is worse than no gate at all. Any missing gate metric, or
    # any failed case, is now a hard BLOCK - never silently a PASS.
    missing_gate_metrics = [metric for metric in GATE_METRICS if metric not in gate_scores]
    if failed_ids or missing_gate_metrics:
        decision = "BLOCK"
        flags = []
        if failed_ids:
            flags.append(f"{len(failed_ids)}/{len(scorable_cases)} case(s) failed to score at all: {', '.join(failed_ids)}")
        if missing_gate_metrics:
            flags.append(f"no scores collected for: {', '.join(missing_gate_metrics)} - cannot verify release quality")
    else:
        decision, flags = get_release_decision(gate_scores)

    if budget_exceeded:
        flags.append(
            f"TOKEN BUDGET EXCEEDED mid-run ({cumulative_tokens:,}/{TOKEN_BUDGET:,}) - this run is PARTIAL, "
            "not every case was scored. Raise RELEASE_GATE_TOKEN_BUDGET or investigate why usage was abnormally high "
            "before trusting this result."
        )

    print(f"\nTotal tokens used this run: {cumulative_tokens:,} / {TOKEN_BUDGET:,} budget")
    print(f"\nRelease decision: {decision}")
    for flag in flags:
        print(f"  - {flag}")

    # Phase 182 - persist this run so the Deployment Dashboard has history,
    # not just this run's own stdout. Never allowed to affect the gate's
    # own exit code - a persistence failure (e.g. POSTGRES_DB_HOST unset
    # in this CI job's environment) degrades to a logged warning only.
    try:
        await get_db_gateway().eval_run_store().record_run(
            decision=decision,
            flags=flags,
            aggregated_scores=aggregated,
            total_cases=len(scorable_cases),
            scored_cases=len(scorable_cases) - len(failed_ids),
            failed_case_ids=failed_ids,
            retrieval_k=RETRIEVAL_K,
            case_results=case_results,
        )
    except Exception as error:
        logger.warning("Could not persist this eval run - gate's own decision is unaffected: %s", error)

    return 1 if decision == "BLOCK" else 0


if __name__ == "__main__":
    # Diagnostic hardening, 2026-10-05: a real failure on a fresh CI
    # runner produced zero output anywhere - no per-case score, no
    # traceback, even with PYTHONUNBUFFERED=1 - genuinely unclear why a
    # normal Python exception wouldn't have printed one. This guarantees
    # visibility regardless of the mechanism: explicit catch, explicit
    # flush, explicit non-zero exit, so the next failure (if any) is
    # finally diagnosable.
    try:
        exit_code = asyncio.run(main())
    except BaseException:
        print("FATAL - exception escaped main():", flush=True)
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        sys.exit(1)
    sys.exit(exit_code)
