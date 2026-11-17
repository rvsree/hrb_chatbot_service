# Skills assessment — Sree

**First written 2026-11-03**, during the ClaimsGraph project setup, at
Sree's own request — he asked Claude to assess strengths and gaps
honestly, based on ~3-4 months of actually working together on
`hrb_chatbot_service` (v2), so the assessment doesn't get lost in chat and
can inform how future projects (ClaimsGraph and whatever comes after) are
structured. **This is a living document, not a one-time verdict** — update
it as new evidence shows up, don't just append.

---

## Strengths

| Strength | Evidence |
|---|---|
| **Sharp product/scope instinct** | Caught Claude over-engineering, scope-creeping, or being dismissive multiple times in a single session — the CRM-to-insurance-claims pivot, "don't perform your analysis just to kill the idea," and the "you're behaving like an order taker" correction were all correct, fast calls. |
| **Verifies before trusting** | Pushed back when an early KG analysis read as critique instead of the concise basics-and-leverage summary he'd asked for; the `ai/pre_processing/` correction only happened because standing feedback had already trained Claude to check real code instead of trusting `CLAUDE.md`'s own generic claim — Sree's insistence on verification, not Claude's initiative, is what surfaces these. |
| **Knows his own learning conditions** | "No mock features without a meaningful use case" and "I can't spec until I'm convinced" are mature, self-aware constraints — most people in a bootcamp skip straight to code without checking whether they understand what they're building. |
| **Names his own gaps directly, unprompted** | Explicitly said he's never learned to review implementation logic across layers despite 3-4 months on v2, rather than assuming the process was working because the outputs looked fine. That kind of self-audit is rare and is the whole reason ClaimsGraph is structured differently. |

## Growth areas

| Area | Evidence | Why it matters |
|---|---|---|
| **Has directed outcomes, not reviewed implementations** | Every v2 phase followed: describe intent → Claude writes the spec → Claude implements → Claude reports done. Never once asked "walk me through why `services/documents_service.py` exists but `services/rag_service.py` doesn't" mid-task — that distinction was only ever read after the fact, in the architecture notes. | This is the actual skill SDD is supposed to teach, and it hadn't been exercised yet. ClaimsGraph's review-checkpoint rule exists specifically to force this. |
| **Zero hands-on exposure to graph data modeling / Cypher** | Starting line, confirmed directly, not an assumption. | Not a deficiency — just means ClaimsGraph's early phases should isolate this as the one new unfamiliar surface, not bundle it with new stack choices too. |
| **Has approved specs as a reader, never authored one** | Driven the SDD *process* (reading specs, saying go/no-go) across every v2 phase, but never personally written a `**Spec:**` block or sat with a diff and narrated what it does without Claude summarizing first. | This is why ClaimsGraph's Phase 0 has Sree hand-write the `.claude/` SDD machinery itself, with Claude reviewing — reversing who authors and who reviews, on purpose. |

## How this should be used going forward

- **ClaimsGraph** is already structured around the two growth areas above (hand-written SDD machinery, mandatory review checkpoints per phase) — see `C:\workspace\2026-v1\interview-kickstart\claims_graph\CLAUDE.md`.
- **Future projects** (401k A2A, analytics/ETL, or whatever else gets scoped) should check against this file before repeating v2's pattern by default — the goal is for the growth-area list to actually shrink over time, not stay the same across every new project.
- Revisit this file after each ClaimsGraph phase closes, and update it with real evidence either way — confirming a strength held up, or a growth area actually moved.
