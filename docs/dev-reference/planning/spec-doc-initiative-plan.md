# Spec / Architecture / Design Doc Initiative — Plan

Status: planning only, nothing written yet except this plan. Pilot feature not yet started - waiting on confirmation below.

## Why this exists

The existing `docs/dev-reference/*.html` docs (the ones now wired to the admin "Docs" links) are status
dashboards - colored boxes showing built/not-built as of a snapshot date, hand-updated, not living
documents. Real review found they don't cover personas, API contracts, DB schema by table, tradeoffs, or
NFRs in any structured way. This plan defines a better document shape and how to roll it out carefully -
pilot first, not all features at once.

## What actually exists in the `snip-url` reference project - checked directly, not assumed

`C:\workspace\2026-v1\interview_coding_assignment\schwab\snip-url\docs\`:

| File | Content |
|---|---|
| `project_brief.md` | Problem, stakeholders, constraints, approach, architecture overview |
| `decisions.md` | `ID \| Decision \| Source` table, then per-decision **Context / Decision / Alternative / Why / Trade-off** |
| `architecture.md` + `.html` + `diagrams/` | Workflow, application, and target-design diagrams |
| `data-model.html` | Conceptual + physical data model |
| `design.md` | API contracts, data model (tables), key flows, **NFRs (section 6)**, known limitations |
| `scenarios.md` | Scenario walkthroughs with results |
| `review-checklist.md` | Progress + golden test IDs + deviation log |
| `metrics.md` | Generated reliability metrics |
| `SCHWAB_SPEC_MAPPER.md` | Requirement -> evidence -> status mapping |
| Root `README.md` | 5-minute reviewer path, quick start, endpoints, doc index |

One correction to the premise I was given: **NFR is not its own separate file** - it's `design.md` section
6, a table of `NFR | Built (prototype) | Target design (not built)`, backed by real back-of-envelope sizing
math in section 2. That's the pattern to copy for HRB, not a 4th standalone NFR file per feature.

**Also found, not duplicated**: this project already has a system-wide scaling/NFR doc -
`docs/dev-reference/design/scaling-latency-design.html` ("How this project's own request chain spends its
time today... written for the 'scale beyond Docker/Kubernetes' interview question"). A per-feature Design
doc's own NFR section should stay narrow (that feature's own latency/scale/failure questions) and link out
to this existing doc for the system-wide "1000s of concurrent users" picture, not repeat it.

## Proposed document categories for HRB features

Four kinds, one file (or file pair) each, per feature:

### 1. Spec (new - doesn't exist for any HRB feature today)
Request/intent, scope and explicit non-scope, personas/roles involved, acceptance criteria, open questions
and how each was actually resolved (mirrors this session's own back-and-forth, formalized).
Maps to `snip-url`'s `project_brief.md` + the request/spec half of its per-feature `specs/<feature>/` folder.

### 2. Architecture (exists today in spirit, keep the diagram-first style)
Sequence/component/data-flow diagrams - "where does a request physically travel." This is what
`rag-architecture-layers.html` / `multi-agent-graph.html` already do well; keep that style, don't redesign it.
Maps to `snip-url`'s `architecture.md/.html` + `diagrams/`.

### 3. Design (new content needed - this is the real gap)
API/contract details (request/response shapes, every error code), DB schema by table (columns, FKs,
indexes, SQL vs NoSQL choice and why), key flows step-by-step, a narrow NFR section (Built vs Target table,
per `snip-url` design.md §6's exact format), known limitations.
Maps to `snip-url`'s `design.md` + `data-model.html`.

### 4. Decisions (new - the tradeoffs table that's missing everywhere today)
Exact `snip-url` `decisions.md` format: summary table, then per-decision Context/Decision/Alternative/
Why/Trade-off. This project already *has* the raw material for this (every "I chose X over Y because Z"
moment in `RAG-ROADMAP.md`'s own phase write-ups) - it just needs pulling into this shape.

## Icons

Book icon (already shipped) = Architecture/status doc, the existing `.html` dashboards.
**Suggested second icon**: a small clipboard-with-lines glyph, representing the combined Spec + Design +
Decisions set for that feature (one icon for all three, not three separate icons - avoids icon clutter next
to every label). Confirm before I build it.

## Pilot feature - proposing a genuinely small one, not Request Unpaid Leave

Per your correction: start easy, confirm the template is right, then decide whether to extend.

**Proposed pilot: Admin Secret Code (Phase 169 + 171).** Reasoning: single concern (login + reset), small
file set (one store, one route file, a handful of model fields), fully built/tested/live-verified already
this session with nothing in flux, no cross-repo complexity (unlike Request Unpaid Leave's 3-repo span).

Alternatives if you'd rather a different one: Phase 173 (query normalization - also small, single concern)
or Phase 170/175 (the admin docs viewer itself - small, and reviewing it would be a bit recursive/fun).

## Process

1. Write Spec + Design + Decisions for the pilot feature only (Architecture doc for it already exists in
   spirit if needed, or gets added if genuinely missing).
2. You review each against the real code directly - confirm accuracy, confirm the template actually
   surfaces what you'd want to walk through in an interview.
3. Only after that: decide whether/how to extend to more features, and in what order.
4. **Keeping docs living, from day one**: going forward, a phase's own spec block in `RAG-ROADMAP.md`
   (already required by this project's `spec_gate.py` hook) also names which Spec/Design/Decisions doc it
   touches, so updating the doc becomes part of finishing the phase, not a separate retrofit pass that goes
   stale again the way the `.html` dashboards did.

## Explicitly not doing yet

- Not writing these docs for every feature - pilot only, per your direction.
- Not changing the existing `.html` architecture dashboards' content/style in this phase.
- Not duplicating `scaling-latency-design.html` - per-feature NFR sections stay narrow and link out to it.
