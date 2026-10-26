#!/usr/bin/env python
"""Phase 258 - standalone routing-accuracy harness. Reuses
run_release_gate.py's own _load_routing_cases()/score_routing_case() -
same source of truth, no second implementation - but runs only the
routing subset, no genai-rag groundedness/completeness/retrieval judges.
Cheap and fast, for iterating on single-agentic-rag/multi-agentic-rag
routing without paying for the full release gate's other judges every
time. Informational only - never exits non-zero, no PASS/REVIEW/BLOCK
decision, not meant to gate CI."""

import asyncio
import sys
import traceback

from scripts.run_release_gate import _load_routing_cases, score_routing_case


async def main() -> int:
    routing_cases = _load_routing_cases()
    if not routing_cases:
        print("No golden-dataset cases have expected_tool/expected_agent set - nothing to check.")
        return 0

    single_agentic_scores: list[float] = []
    multi_agentic_scores: list[float] = []
    failed_ids: list[str] = []
    cumulative_tokens = 0

    print(f"Checking routing accuracy for {len(routing_cases)} case(s)...\n")
    for case in routing_cases:
        print(f"  {case['id']}...", flush=True)
        try:
            result = await score_routing_case(case)
        except Exception:
            print(f"  {case['id']}: FAILED", flush=True)
            traceback.print_exc()
            sys.stdout.flush()
            failed_ids.append(case["id"])
            continue

        cumulative_tokens += result["tokens"]
        single_routing = result["scores"].get("single_agentic_routing")
        multi_routing = result["scores"].get("multi_agentic_routing")
        if single_routing is not None:
            single_agentic_scores.append(single_routing["score"])
        if multi_routing is not None:
            multi_agentic_scores.append(multi_routing["score"])
        print(f"  {case['id']}: {result['scores']} ({cumulative_tokens:,} tokens so far)", flush=True)

    print(f"\nTotal tokens used: {cumulative_tokens:,}")
    print("\nResults:")
    if single_agentic_scores:
        rate = sum(single_agentic_scores) / len(single_agentic_scores)
        print(f"  single-agentic-rag routing accuracy: {rate:.0%} ({len(single_agentic_scores)} case(s))")
    if multi_agentic_scores:
        rate = sum(multi_agentic_scores) / len(multi_agentic_scores)
        print(f"  multi-agentic-rag routing accuracy: {rate:.0%} ({len(multi_agentic_scores)} case(s))")
    if failed_ids:
        print(f"  failed to score: {', '.join(failed_ids)}")

    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
    except BaseException:
        print("FATAL - exception escaped main():", flush=True)
        traceback.print_exc()
        sys.stdout.flush()
        sys.exit(1)
    sys.exit(exit_code)
