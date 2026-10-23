# Upcoming features - scoping discussion (2026-10-08)

Discussion only, no implementation plan written yet per explicit request -
save this doc, then continue discussing before any `**Spec:**` block gets
written in `RAG-ROADMAP.md`. Grounded against the actual codebase, not
generic advice - each item below cites what already exists to build on and
what's genuinely new.

## 1. Audio Agent

**Scope decided:** voice I/O wrapper, not audio content ingestion - speech-
to-text on input, existing RAG/agentic pipeline unchanged, text-to-speech on
output. Keeps the RAG core untouched; the new work is a transport layer in
front of it.

**Course alignment requested, not yet actioned:** user wants this aligned to
an IK FDE cohort topic covered "last week." Checked
`docs/id-fde-cohort/` - only `multi-agentic-system/Multi-Agent Travel
Planner.ipynb` exists there; no audio/voice/speech material has been saved
into this repo yet. **Need the actual notebook/material pointed to or
copied in before this can be scoped against it.**

**Remaining prerequisites once that's in hand:**
- STT/TTS provider choice - nothing picked, needs explicit approval before
  any library is added (standing project rule).
- Latency budget impact - an STT + TTS round trip stacked on the existing
  RAG/agentic latency; check against
  `docs/dev-reference/design/scaling-latency-design.html`'s existing budget
  rather than assuming it fits.
- New frontend capability - `hrb_chatbot_ui` has no mic capture or audio
  playback today.
- Golden dataset shape - depends on whether cases start from raw audio
  (scores STT accuracy as a real dimension - a perfect RAG answer to a
  mis-transcribed question is still wrong) or from already-correct
  transcripts (cheaper, but blind to STT failure modes).

## 2 & 2-A. Suggested follow-up questions / multi-turn conversations

Multi-turn memory already works across all 3 pipelines (Phase 58, fixed in
Phase 87) - conversation history round-trips server-side, keyed by
`conversation_id`. This feature is mostly additive on top of that, not new
infra: generate N candidate follow-ups from the answer + retrieved/routed
context, render as clickable chips.

**Open decision:** generate follow-ups with a cheap deterministic heuristic
(e.g. template off unanswered related chunks) or an LLM call. The latter is
another real LLM call on every turn - same category of latency/cost
tradeoff as the Planner model-tiering decision already made in Phase 65.

## 3. Incorporate user feedback into subsequent RAG processing

**Scope decided:** both (a) demote bad chunks/documents at retrieval time,
and (b) feed feedback into the golden dataset/prompts - user explicitly
flagged to be careful here.

Feedback *collection* already fully exists (thumbs up/down, reason tags,
notes - `ViewFeedbackPage`, `submit_feedback`). Nothing today reads it back
into retrieval or generation - this part is genuinely new.

**Real risks to design around (both flagged, not hypothetical):**
- **Demotion risk:** a handful of downvotes silently degrading retrieval
  for everyone, or a chunk that's *correct* but just phrased unhelpfully
  getting demoted alongside a genuinely wrong one. Needs a minimum-sample
  threshold before any auto-action, and a soft score adjustment rather than
  a hard filter, so one bad run can't mute a chunk outright.
- **Golden-dataset risk:** `FAQ.md` is explicit that this dataset's whole
  value is being hand-verified against real PDF text - "a golden dataset
  built from guessed answers is worse than no golden dataset." Auto-feeding
  raw user feedback in bypasses that verification; a mis-click or a
  confused question would quietly corrupt ground truth. Likely needs a
  human-reviewed staging queue (feedback -> candidate case -> someone
  confirms it against the source PDF -> then it joins
  `golden_dataset.json`), not a direct pipe.

## 4. A2A communications

**Scope decided:** deeper *internal* multi-agent collaboration, not
Google's Agent2Agent protocol. Cheaper path - no new wire protocol, just
evolving what `multi_agent_pipeline.py` already does (Planner fans out to
domain agents, all converge at the Reviewer, one round).

**Still open - which shape of "deeper":**
- Agents calling each other directly, not only through the Planner/Reviewer.
- Multiple dispatch rounds (an agent's result changing what runs next, not
  one fixed round).
- Agents seeing each other's intermediate results before the Reviewer's
  final merge.

Not yet answered by the user - needed before this can be scoped further.

## 5. Fine-tune RAG ingestion/retrieval off Evals + LangSmith metrics

More already built than the docs suggest: LangSmith tracing is live right
now (confirmed from a real rate-limit error during this session's own test
run), not just "planned next step" as `FAQ.md` currently states. LLM-as-
judge groundedness/completeness eval scores are already computed and
surfaced per-answer (`eval_scores`, visible in the Explainability panel).

**The actual gap:** nothing today systematically pulls those scores/traces
back into a chunking/retrieval parameter decision. The existing
`golden_dataset.json` (22 cases) + `test_ab_testing_demo.py`'s offline-A/B
shape is the natural harness to extend. Real prerequisite: decide which
knob to tune first (chunk size, `k`, similarity vs. MMR, embedding model),
and grow the golden dataset enough that a change's effect isn't noise - the
existing docs already flag 22 cases as too small for a real significance
test.

## 6. Ensuring the right agent/tool/KB-store gets selected

Current state varies by mode:
- `genai-rag` - still a deliberately crude keyword-list fast-path for MCP
  routing (explicitly flagged in the roadmap as a stand-in for real
  ReAct-based selection).
- `single-agentic-rag` - real LLM-based tool-calling loop already.
- `multi-agentic-rag` - Planner already does real LLM-based routing across
  5 domain agents.

**Natural prerequisite:** extend the golden dataset with an
`expected_agent`/`expected_tool` label per case (same pattern as the
existing `expected_source_document` label), then score the Planner's
actual routing decision (already logged in `tasks`/`toolsUsed`) against it
- gives a routing-accuracy metric before touching any routing logic itself.

## 7. Web search for live external info (e.g. IRS 401(k) withdrawal tax rates)

Already built and live-verified for almost exactly this example: Phase 70
added a real Tavily-backed `web_search_agent` as multi-agentic-rag's 5th
domain agent, live-tested against "current IRS standard mileage
reimbursement rate for 2026" successfully.

**Two real gaps against the actual ask:**
1. It's multi-agentic-rag only today - `single-agentic-rag`'s tool-calling
   loop and `genai-rag` don't have it.
2. Golden-dataset cases with time-sensitive expected answers (like an IRS
   tax rate) need a different scoring rule than the rest of the dataset,
   since "correct" drifts over time - the existing `expected_keywords`
   checklist approach doesn't naturally express "must match *this year's*
   rate."

---

## Follow-up: "Did we implement Harness Engineering silently?" (2026-10-09)

Checked `docs/dev-reference/IK-FDE/course-topic-coverage-review.html` (the
doc that catalogs all 69 named IK FDE techniques against this project's real
code) and the rest of `docs/` for the literal term "Harness Engineering" -
**no exact match anywhere**, and it isn't one of the 69 named topics in that
coverage review either.

What *does* exist, and was built deliberately across named, tracked phases
- not silently:
- `golden_dataset_harness.py` with `get_release_decision()` - Phase 55,
  the PASS/REVIEW/BLOCK release gate.
- `nfr_golden_dataset_harness.py` - Phase 51, the NFR-specific golden
  dataset (prompt-injection/jailbreak/PII cases).
- Both are tested (`test_golden_dataset_harness.py`, etc.) and referenced
  in `CICD-BRANCHING-STRATEGY.md`'s CI gate table.

If "Harness Engineering" refers to this eval-harness tooling: it exists,
and it was built on purpose across tracked phases, not as a silent
byproduct. If it refers to a different, specifically-named IK FDE module -
need the exact term or course material to check against, same as the Audio
Agent item above.

## Follow-up: UI changes status (2026-10-09)

Confirmed via `git diff --stat` that both approved UI changes from the
previous turn are fully present in the local working tree:
- Inline "Sources: ..." line removed from `MessageBubble.tsx`.
- Pipeline dropdown moved from the chat topbar into the sidebar's
  collapsible Settings section in `ChatPage.tsx`.

These are **local, uncommitted changes only** - never committed, pushed, or
deployed, per the standing "no commit until local review" preference and
the explicit "hold off" decision on `ExplainabilityModal.tsx` in the same
working tree. That's almost certainly why they don't show up on the hosted
UI (`hrb-chatbot-ui.rvsree.dev`) - that deployment is still running the old
build. They would show up immediately on a local `npm run dev` session
(Vite HMR reads the working tree directly, no commit needed) if one is
running against this checkout.
