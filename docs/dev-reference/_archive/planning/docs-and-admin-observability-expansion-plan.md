# Docs System + Admin Observability Expansion — Plan

Status: planning only, nothing in this document is built. Supersedes/extends
`spec-doc-initiative-plan.md` (the pilot that produced Admin Secret Code's
4 docs) with everything asked for in this round. Every fact below was
checked directly against real code/config before being written in here -
not assumed.

## How to read this

Four separate asks came in together. They're related but not the same size
or the same kind of work, so this plan keeps them as separate sections with
their own proposed phase numbers, rather than one giant phase:

1. **Pick a real feature for the next pilot**, not another small one like
   Admin Secret Code.
2. **A system-level vs. feature-level doc inventory**, plus a DB schema
   that can actually hold version *history* (not just a version number
   that gets overwritten) and knows which category/scope each doc belongs to.
3. **An admin-facing CI/CD + eval-score view**, backed by a real
   `golden_dataset` DB table (versioned, categorized) that both the admin
   UI *and* the CI pipeline read from - one source of truth, not two.
4. **Two new doc categories** - `interview-faq-system` and
   `interview-faq-feature` - with real architecture diagrams for A2A, HITL,
   and the S3-async RAG ingestion batch path.

## Resolving your point about admin-only login credentials

You asked for these documents to be linked to credentials that only work
for the admin user. That's already true for the real delivery path - worth
being precise about the difference between two things that look similar:

- **The real path** (what ships): `DocLink` in `hrb_chatbot_ui` renders
  nothing unless `identity.role === "admin"`; it calls
  `GET /v1/admin/docs`, which backend-enforces `require_role(..., Role.ADMIN)`
  before returning anything; the actual file comes back as a short-lived
  (300s) presigned S3 URL, not public content. An unauthenticated or
  non-admin request gets a 401/403, full stop.
- **The claude.ai artifact links** I shared last turn (Spec/Architecture/
  Design/Decisions, and the scaling doc) are a **separate, temporary review
  convenience** for this conversation only - private-by-default links so
  you could react without opening the file locally. They were never part
  of the shipped product and don't go through `require_role()` at all.
  They'll keep existing as artifacts on claude.ai unless you ask me to
  delete them, but the *actual* admin gating lives entirely in the app,
  already working today.

So: no new work is needed to satisfy "admin-only" - it's already enforced.
What *is* worth deciding is in the open-decisions section at the end:
whether the claude.ai preview links should be treated as throwaway (deleted
once you've reviewed them) or kept around as a standing convenience.

## 1. Picking a real feature for the next pilot

Admin Secret Code proved the mechanism (multi-doc-per-feature, the popover,
the migration) but isn't representative - it's a small CRUD-shaped feature,
not something with real architectural interest. Ranked by how much genuine
diagram/interview material each one has, and how directly it maps onto the
`interview-faq-feature` ask:

| Rank | Feature | Why it's a strong pilot |
|---|---|---|
| 1 | **RAG ingestion - S3 async batch** (`ai/doc_processing/pipeline.py`, `S3-ASYNC-UPLOAD-DESIGN.md`) | Real multi-stage pipeline (extract → chunk → embed → index), a genuine design doc already exists to draw from, and it's explicitly one of the 3 diagrams you named for the interview-faq category - building it once here covers two asks at once. |
| 2 | **Request Unpaid Leave (A2A + HITL)** (`unpaid_leave_agent.py`, `leave-approval-a2a-design.html`) | The richest flow in the whole project - LangGraph checkpointing, a real pause-and-resume HITL step, cross-service A2A to `hrb_lms_mcp`. Also one of your 3 named interview diagrams. Bigger than #1, so second rather than first. |
| 3 | **Multi-Agentic RAG** (`multi_agent_pipeline.py`) | A real LangGraph multi-agent graph already has its own diagram (`multi-agent-graph.html`) to build on; good interview material (orchestrator → parallel workers → synthesizer). |
| 4 | **Guardrails** (`guarded_pipeline.py`) | Cross-cutting (all 3 chat pipelines funnel through it as of Phase 98) - a good "architecture decision" story (why a shared core, what shipped without it first) but thinner on its own as a single feature page. |

**Recommendation: build #1 (RAG ingestion) next**, since it directly produces
one of the three interview-faq diagrams you asked for in the same pass,
and it's self-contained enough to finish without touching HITL/A2A's
larger surface area. #2 would be the natural follow-up once #1 is confirmed.

## 2. System-level vs. feature-level doc inventory

**System-level** = applies to the whole project, not one feature.
**Feature-level** = scoped to one discrete capability.

| Scope | Key | Status | Candidate doc types |
|---|---|---|---|
| System | `architecture-overview` | not started | architecture, interview-faq-system |
| System | `deployment-pipeline` | not started (this round's ask #4 below) | architecture, design, decisions |
| System | `scaling-nfr` | **live** (`scaling-latency-design.html`, just expanded) | architecture (already is one) |
| System | `security-rbac` | partially covered (mentioned in scaling doc panel 7) | design, decisions |
| System | `mcp-integration` | doc exists (`mcp-integration-overview.html`), not yet in `doc_metadata` | architecture |
| Feature | `admin-secret-code` | **live** - all 4 types (the pilot) | spec, architecture, design, decisions |
| Feature | `rag-ingestion` | not started - **recommended next pilot** | spec, architecture, design, decisions, interview-faq-feature |
| Feature | `request-unpaid-leave` | 1 doc only (`design`, from before this initiative) | spec, decisions, interview-faq-feature (architecture/design already partly covered) |
| Feature | `genai-rag-chat` | 1 doc only (`architecture`) | spec, design, decisions |
| Feature | `single-agentic-rag` | 1 doc only (`architecture`) | spec, design, decisions |
| Feature | `multi-agentic-rag` | 1 doc only (`architecture`) | spec, design, decisions, interview-faq-feature |
| Feature | `retrieval-strategies` | 1 doc only (`architecture`, shared across 4 options) | design |
| Feature | `genai-chat-workflow` | 1 doc only (`architecture`) | spec, design, decisions |
| Feature | `document-management` (upload/manage) | none yet | spec, design |
| Feature | `golden-dataset-evals` | none yet (this round's ask #3) | spec, design, decisions |

This is a **lot** of rows if all attempted at once - exactly the thing you
corrected me on last round ("let's not do this work for all features"). The
inventory above is for visibility, not a build-everything commitment - see
the phased order in section 6.

## 3. DB schema redesign — real version history, organized by category

### What's wrong with today's `doc_metadata` table

It has `doc_version` (an int) but **updates the row in place** when content
changes - the old `s3_key`/`content_hash` is overwritten. There is no way
to see "what did the Design doc look like 3 versions ago" from the
database; the only history is whatever the git log of the source `.html`
file happens to preserve. That's exactly the gap you flagged: "if any
underlying documents are updated... the DB table should be able to insert
the data" - insert, not overwrite.

It also has no notion of **scope** (system vs. feature) - `feature_name`
is required and there's no row that cleanly represents "this doc isn't
about one feature, it's about the whole project."

### Proposed redesign: two tables, catalog + versions

```
doc_catalog                          doc_versions
------------------------------       ------------------------------
id (PK)                              id (PK)
scope          'system' | 'feature'  catalog_id (FK -> doc_catalog.id)
feature_name   NULL when scope=      version_number  (1, 2, 3, ...)
               'system'              s3_bucket
doc_type       'spec'|'architecture' s3_key
               |'design'|'decisions' source_local_path
               |'interview-faq-      content_hash
                system'|             created_at
                'interview-faq-
                feature'
doc_title      (current title)      -- one row per version, append-only,
current_version_id (FK -> versions)  -- never updated after insert
created_at
updated_at
```

- **`doc_catalog`** is the stable identity of a document (what `DocLink`
  looks up by `feature_name` + `doc_type`, or by `scope='system'` +
  `doc_type` for system-level docs) - unique on `(scope, feature_name,
  doc_type)`.
- **`doc_versions`** is append-only history - `sync_admin_docs.py`'s
  content-hash check still decides whether a *new row* is worth inserting
  (unchanged content = no-op, exactly like today), but when content *has*
  changed, it INSERTs a new `doc_versions` row instead of overwriting the
  existing one, then updates `doc_catalog.current_version_id` to point at
  it. Old versions stay queryable (`SELECT * FROM doc_versions WHERE
  catalog_id = ? ORDER BY version_number DESC`) - a real "show me the
  previous version" admin feature becomes possible later, not just a
  version *number* with no content behind it.
- `GET /v1/admin/docs` would join `doc_catalog` + its `current_version_id`
  row for the listing (same shape the frontend already consumes - `id`
  becomes `doc_catalog.id`, everything else comes from the joined current
  version). A new `GET /v1/admin/docs/{id}/versions` could list history
  later, once there's a UI that wants it - not built in this pass unless
  you want it now (see open decisions).

**Migration path**: same idempotent `CREATE TABLE IF NOT EXISTS` +
`ALTER`/`CREATE INDEX IF NOT EXISTS` convention already used for the
`(feature_name, doc_type)` unique-index change two rounds ago. The
existing 10 rows migrate by becoming 10 `doc_catalog` rows each pointing
at one `doc_versions` row (`version_number = 1`), copying their current
`s3_key`/`content_hash`/etc. across - a one-time backfill script, not a
destructive change.

## 4. New doc categories: interview-faq-system and interview-faq-feature

Two new `doc_type` values, not two new tables - they fit directly into the
redesigned schema above (`doc_catalog.doc_type`).

- **`interview-faq-system`**: one per project, cross-cutting techniques
  explained the way you'd actually explain them in an interview - a real
  diagram plus a short Q&A underneath it. Your 3 named examples map here
  directly:
  - **A2A** (agent-to-agent): the real OAuth2 client-credentials call from
    `hrb_chatbot_service` to `hrb_lms_mcp` (Phase 53) - diagram the token
    exchange + the actual MCP tool call, not a generic A2A explainer.
  - **HITL** (human-in-the-loop): the LangGraph checkpoint/pause/resume
    used by the unpaid-leave approval flow - diagram the graph pausing at
    the HITL node, an hr_support decision resuming it.
  - **RAG ingestion batch via S3 async**: the S3 → SQS → Lambda path
    (`S3-ASYNC-UPLOAD-DESIGN.md`) - diagram the decoupled write path, tied
    to why it's decoupled from the query path (already explained in
    `scaling-latency-design.html` panel 4, cross-link rather than repeat).
- **`interview-faq-feature`**: same idea, scoped to one feature's own
  specific techniques - e.g. the Admin Secret Code pilot could get one
  covering "why salted-hash over bcrypt" as a condensed interview-ready
  version of its own `decisions.html`.

**Content bar, since these are explicitly your interview/demo material**:
each one needs (a) one real diagram, not a stock description, (b) 3-5
likely interview questions with real, specific answers (not "it depends"),
(c) explicit links to the fuller Architecture/Design/Decisions docs for
follow-up depth. This is genuinely more writing effort per doc than the
other 4 categories - budget for that rather than treating it as a quick add.

## 5. Deployment-to-AWS diagrams

A new **system-level** `deployment-pipeline` doc (architecture-style,
diagram-first, matching the existing dashboard convention), built from
real, already-checked facts rather than generic CI/CD advice:

- The real pipeline: `git push` → `ci.yml` (tests/lint/bandit/pip-audit on
  every push) → merge to `master` → `deploy.yml` (build → push to ECR →
  trigger App Runner deployment → poll for `RUNNING` → smoke test).
- `eval-gate.yml` as its own separate, manually-triggered lane (real LLM
  cost, `workflow_dispatch` only, never auto-fires) - this is also exactly
  the data source for the admin CI/CD view in section 6, so this doc and
  that admin view should be built together, not separately.
- `deploy-lambda.yml` as a third, narrower lane (the ingestion Lambda
  worker, separate deploy target from the main API).
- Real resource identifiers already documented in
  `AWS-DEVOPS-RUNBOOK.md` (App Runner service ARN, ECR repo, IAM roles) -
  this doc visualizes what that runbook already describes in prose, it
  doesn't re-derive new facts.

## 6. Admin CI/CD + eval-score view

This is the largest single ask here - worth breaking into its own pieces,
because one real gap changes the plan: **today, nothing about a release-gate
run is persisted anywhere.** `scripts/run_release_gate.py` prints to CI logs
and exits with a pass/fail code - there is no table, no file, nothing an
admin UI could query after the fact. That has to be built, not just surfaced.

### 6.1 `golden_dataset` table - versioned, categorized

Grounded in the real 26-case shape already in
`resources/golden_dataset/golden_dataset.json`:

```
golden_dataset_items                 (versioned, same catalog/version
--------------------------------      split as doc_catalog/doc_versions,
id (PK)                               for the same reason: "insert, don't
case_key        '401k-01'             overwrite" applies here too)
category        'happy' | 'edge' | ...
feature_name    which pipeline this exercises (genai-rag, single-agentic-
                rag, request-unpaid-leave, ...) - not in the JSON today,
                a genuinely new field your "organized by category... which
                features" ask requires
query
expected_source_document
expected_answer
expected_keywords      (JSON array)
call_type       'llm_call' | ...
version_number
is_latest       boolean - avoids a join/subquery for "give me the current
                set," which is the UI grid's own most common query
created_at
```

- **The admin grid** loads `WHERE is_latest = true`, grouped/filterable by
  `category` and `feature_name` - directly answers "load the golden
  dataset based on latest version of the info."
- **A new sync script** (`scripts/sync_golden_dataset.py`, same shape as
  `sync_admin_docs.py`) reads the JSON file and upserts into this table -
  keeps the JSON file as the authored source (easy to hand-edit/review in
  a PR) while the DB becomes the served copy, same pattern already working
  for the docs viewer.
- **`golden_dataset_harness.py`** changes from reading the JSON file
  directly to reading `golden_dataset_items WHERE is_latest = true` -
  this is the "use the same table when running CI/CD" ask. The JSON file
  stays as the human-edited source of truth that gets synced in, not
  replaced - editing golden cases should still be a reviewable text diff
  in a PR, not a direct DB edit.

### 6.2 Release observability - expanded per direct request to "think like
real-world applications"

The original proposal only covered golden-dataset scores. The real ask is
broader: deployment metadata, test/security gate results, and - the
genuinely new, valuable piece - **error rates per subsystem, captured so
they can drive fine-tuning decisions**, not just displayed. Four tables,
not one, each answering a different question a real engineering org tracks
separately:

```
deployment_events                    ci_gate_results
--------------------------------     --------------------------------
id (PK)                              id (PK)
git_sha                              git_sha
branch                               workflow_name  'ci'|'deploy'|
environment    'local'|'dev'|'prod'                 'eval-gate'|'deploy-lambda'
triggered_by                         test_pass_count
image_tag      (ECR digest)          test_fail_count
deploy_status  'success'|'rollback'  test_total
  |'failed'                          coverage_percent
feature_flags_snapshot (JSONB -      bandit_high_count
  which optional features were on    bandit_medium_count
  at deploy time: LANGSMITH_ENABLED, bandit_low_count
  GENAI_CHAT_WORKFLOW, etc. - so a   pip_audit_vuln_count
  later regression can be traced to  lint_status
  a config change, not just code)    overall_status  'pass'|'block'
rollback_of_id (FK, nullable)        started_at / finished_at
started_at / finished_at

eval_runs / eval_run_results         runtime_events  <- the new piece
(as originally proposed - golden-    --------------------------------
dataset scores, held pending         id (PK)
DeepEval, see 6.3)                   subsystem  'rag_ingestion'|
                                        'rag_retrieval'|'hitl'|'a2a'|
                                        'memory'|'state_management'|
                                        'guardrails'|'mcp_tools'|...
                                      service, operation  (same names
                                        log_backend_call() already uses)
                                      status  'success'|'error'
                                      error_type, error_message (nullable)
                                      duration_ms
                                      correlation_id  (conversation_id or
                                        request id, nullable - lets one
                                        failure be traced across subsystems)
                                      created_at
```

**A real finding that changes how `runtime_events` has to be built, not
just a design choice:** `log_backend_call()` (used by every outbound call
in this project - S3, vector DB, LLM providers, MCP tool calls) already
passes structured fields (`service`, `operation`, `duration_ms`, `status`)
through `extra={...}` on every log call. But `logger.py`'s current
`Formatter` uses a **plain-text** format string that doesn't reference
`extra` at all - those fields are attached to the Python `LogRecord`
object in memory and then **silently discarded**. They never reach
stdout, a file, CloudWatch, or anywhere queryable. So "capture error rates
from the log" as literally stated would mean regex-parsing prose lines
like `"[s3] put_object succeeded in 697.9ms - {...}"` after the fact -
fragile, and exactly the kind of log-scraping real observability tooling
(Sentry, Datadog, CloudWatch Insights with structured logs) moved away
from years ago in favor of emitting structured events directly.

**Recommendation: write to `runtime_events` directly at the source, not
via log parsing.** Concretely: `log_backend_call()` gains an optional
`subsystem` keyword (every call site already names its `service`, adding
one more string costs nothing) and, on `status == "error"`, inserts a row
into `runtime_events` in addition to its existing log line - the logging
and the structured capture happen in the same place, from the same data,
instead of two different mechanisms that can drift apart. A new, lighter
`log_business_event()` helper covers non-backend-call moments worth
tracking the same way (a guardrail blocking a query, a HITL pause/resume,
a LangGraph checkpoint write) - these aren't "calls to an external
service" so `log_backend_call()`'s own shape doesn't fit, but they're
exactly the kind of event you'd want in the same table to compute a real
HITL/A2A/memory error rate. **Sampling successes, not just logging
errors**, is worth deciding deliberately too - an error *count* without a
success *denominator* can't produce a real error *rate*; even a 1-in-N
sampled success row per subsystem would be enough to compute one without
writing a row on every single successful call.

`scripts/run_release_gate.py` gains a real write step at the end (insert
one `eval_runs` row + N `eval_run_results` rows, as originally proposed)
instead of only printing and exiting. `ci.yml`/`deploy.yml` each gain a
small step writing their own `ci_gate_results`/`deployment_events` row.
The admin UI's "CI/CD view" then has real data across all four tables:
deploy history, test/security gate trend, golden-dataset score trend, and
- the part aimed directly at fine-tuning - **error rate by subsystem over
time**, filterable to "did the error rate for `rag_ingestion` spike right
after deploy X," answerable by joining `runtime_events` against
`deployment_events` on time range.

### 6.3 Important sequencing note on "DeepEval scores"

You asked for a view showing "how much deepeval scores against golden
dataset." Worth being direct about where this actually stands: **DeepEval
itself is still Phase 174 - spec'd and researched, explicitly not built
yet**, per your own instruction to hold it. The hand-written scoring
(Groundedness/Completeness/Precision/Recall/F1) that
`golden_dataset_harness.py` already runs today is **not** DeepEval - it's
the original Phase 8 approach.

Two honest options, not silently picked for you:

- **(a)** Build the admin view against today's hand-written scores first
  (real now, ships sooner), and swap the score columns to DeepEval's once
  Phase 174 actually lands - the `eval_run_results` schema above already
  has named score columns that map 1:1 either way, so this is a clean
  swap, not a rebuild.
- **(b)** Hold the admin CI/CD view until Phase 174 ships DeepEval first,
  so the view only ever shows "real" DeepEval numbers and never shows a
  number you'll later want to explain was from a different scoring method.

**Decided: (b) - hold, narrowed to scoring specifically.** Only the
golden-dataset scoring piece - `eval_runs`/`eval_run_results`,
`run_release_gate.py`'s score-writing step, and the admin UI's score panel
- waits for Phase 174. Every score shown there will be a real DeepEval
number, never a hand-written-harness one that later needs re-labeling.
**This does not block**: section 6.1's `golden_dataset_items` table/grid
(pure data versioning, no scoring), or the broader release-observability
tables added in 6.2 above (`deployment_events`, `ci_gate_results`,
`runtime_events`) - none of those are golden-dataset scores, so none of
them have a DeepEval dependency. See the phase order below for exactly
which pieces ship when.

## 7. Proposed phased build order — confirmed

Reordered per your call (RAG ingestion pilot before the schema redesign)
and with section 6.2 held per the DeepEval decision above:

| Phase (proposed) | What |
|---|---|
| 180 | **RAG Ingestion pilot** - Spec/Architecture/Design/Decisions, 4 docs, same bar as Admin Secret Code, built on today's schema |
| 181 | `doc_catalog`/`doc_versions` schema redesign + migration of all 14 existing rows (the original 10 + RAG Ingestion's 4) |
| 182 | `golden_dataset_items` table + sync script + admin grid (section 6.1) - proceeds now, not gated on DeepEval |
| 183 | `deployment-pipeline` system-level doc (section 5) |
| 184 | `interview-faq-system`: A2A + HITL + RAG-ingestion-batch diagrams (depends on 180 for the RAG ingestion material already being written) |
| 185 | **Release observability infrastructure** (section 6.2, the non-scoring half): `deployment_events`, `ci_gate_results`, `runtime_events` tables; `log_backend_call()` gains a `subsystem` tag + error-row write; `ci.yml`/`deploy.yml` each gain a result-persisting step. Proceeds independently - none of this is golden-dataset scoring, so it isn't gated on DeepEval. |
| held, pending Phase 174 | `eval_runs`/`eval_run_results` tables specifically (golden-dataset scores) + `run_release_gate.py`'s own persistence step + the admin UI panel that shows scores - starts only once DeepEval ships, per the decision above. The deploy/test/security/error-rate panels from Phase 185 can ship in the admin UI before this does. |
| later, unscheduled | Request Unpaid Leave (A2A/HITL) full 4-doc pilot; Multi-Agentic RAG pilot; `interview-faq-feature` entries per feature |

## 8. Ideas beyond what was literally asked

- **`is_latest` as a real column, not a derived query** (section 6.1) -
  makes the admin grid's most common query a plain `WHERE`, not a subquery
  against `MAX(version_number)` - cheap to add now, annoying to retrofit later.
- **Tie `eval_runs.golden_dataset_version` to a real FK**, not just a
  number - so "this run graded against version 3, which has since become
  version 5" is answerable directly, not just inferable.
- **Keep the JSON file as the authored source for golden-dataset cases**,
  DB as the served copy (mirrors the docs-viewer pattern exactly) - edits
  stay reviewable in a PR diff, never a direct prod DB edit for content
  that should be reviewed like code.
- **Don't build `GET /v1/admin/docs/{id}/versions` (history browsing) yet**
  - the schema supports it from day one, but a UI for "diff this version
    against that one" is real scope on its own; flagged as a natural
    follow-up once the base grid/view exists, not bundled in now.
- **Cross-link relentlessly instead of repeating content** - the
  `deployment-pipeline` doc should link to `AWS-DEVOPS-RUNBOOK.md` and
  `scaling-latency-design.html` rather than re-explaining App Runner's
  autoscaling a third time; `interview-faq-system`'s RAG-ingestion entry
  should link to the Phase 181 pilot's own Architecture doc rather than
  duplicating its diagram.

## Decisions log

All 4 open questions from the first draft of this plan are now resolved:

1. **Phase order**: RAG Ingestion pilot (180) before the schema redesign
   (181) - see section 7.
2. **DeepEval sequencing**: hold section 6.2 (admin CI/CD + score view)
   until Phase 174 ships DeepEval; section 6.1 (golden-dataset table +
   grid) proceeds independently now.
3. **claude.ai preview artifacts**: kept as a standing convenience
   alongside the real in-app admin docs viewer.
4. **`eval_run_results.raw_response`**: stored in full, for real
   per-case debugging once section 6.2 eventually starts.

Nothing left to confirm before Phase 180 (RAG Ingestion pilot) starts.
