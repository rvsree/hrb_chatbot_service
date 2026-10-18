# Endpoint Request/Response Contracts

Source of truth for each endpoint's finalized request, response, and error
shape - written and confirmed here **before** any code changes, so a
contract never has to be re-derived from scattered conversation. When
implementing, match this file exactly; if a contract needs to change,
update this file first, then the code.

Status per endpoint is marked below. Only what's marked **Finalized** has
been confirmed - everything else is not yet agreed and must not be
implemented yet.

## Identity source: JSON payload on every endpoint, never headers, never query params

Confirmed 2026-09-20 (final form): every endpoint that does RBAC takes a
JSON body with a `user_profile` sub-object, including `GET`/`DELETE` -
non-standard HTTP (a body on `GET`/`DELETE`), a deliberate choice so there
is exactly one identity mechanism everywhere, not two. `X-Employee-Id`/
`X-Full-Name`/`X-Role` headers and query-param identity were both tried
and rejected during this design pass - neither is used anywhere.

- `DELETE .../{id}`, `DELETE .../documents`, `DELETE /v1/conversations/{id}`
  (all): body is `{"user_profile": {...}}` only - no other fields.
- `POST` endpoints (upload, query): `user_profile` is one sub-object
  alongside the endpoint's other fields, same as already documented below.
- `GET /health`/`GET /ping` stay exactly as they are - no identity, no
  RBAC. Confirmed: they're called by automated infrastructure (Docker
  `HEALTHCHECK`, CI smoke test), not an employee acting on data.

**Revised 2026-10-06 (Phase 96), for `GET` only:** `GET /v1/genai-rag/
ingest-document/documents`, `GET .../{id}`, and `GET .../documents/
cleanup/preview` now take identity as **query params**
(`?employee_id=...&full_name=...&role=...`), not a body - confirmed, not
guessed, that the Fetch spec forbids a body on `GET`/`HEAD` (`fetch()`
throws `TypeError: Request with GET/HEAD method cannot have body` before
any network call reaches the server), so a real browser client -
`hrb_chatbot_ui` - could never call the 2026-09-20 shape above as
written. This is **not** a reversal of the header/query-param rejection
above for `POST`/`DELETE` - those keep the body exactly as decided; this
is new information specific to `GET` that the original design pass
didn't have. `api/gateway/rbac.py`'s `identity_from_query_params()`
builds the same `UserProfile` either way, then hands it to the same
unchanged `require_role()` - 401/403 behavior is identical, only the
transport differs.

**Known, accepted tradeoff, on record per the 2026-09-20 security review:**
`role` now comes from the same payload/query-params as the action it
gates, so `require_role()` can't stop anyone who knows the field name - RBAC
here is a formality, not a real control, once this ships. Matches this
project's existing placeholder-auth stage (real OAuth was always the
eventual fix, per `CLAUDE.md`) - accepted deliberately, not overlooked.

## Shared error object

Every endpoint returns this same shape on failure (`api/dependencies.py`'s
`json_error()`):

```json
{
  "error": "Human-readable message",
  "code": "STABLE_ERROR_CODE"
}
```

`details` is added only for request-validation failures (a list of
field-level errors). Real codes in use today (`common/error_codes.py`):
`VALIDATION_ERROR`, `DOCUMENT_NOT_FOUND`, `RATE_LIMITED`,
`BACKEND_UNAVAILABLE`, `INDEXING_FAILED`, `QUERY_FAILED`,
`NOT_IMPLEMENTED`, `INTERNAL_ERROR`, `UNAUTHENTICATED`, `FORBIDDEN`,
`AMBIGUOUS_DOCUMENT_IDENTIFIER`. Per-file upload rejection reasons (still
inside a 200 batch response, not a top-level error): `INVALID_FILE_TYPE`,
`EMPTY_FILE`, `FILE_TOO_LARGE`, `UPLOAD_READ_FAILED`,
`SUPERSEDES_TARGET_NOT_FOUND`, `STORAGE_FAILURE`.

---

## POST /v1/genai-rag/ingest-document/documents (upload) — **Finalized**

`multipart/form-data`, two parts:
- `files` — one or more PDFs (binary, unchanged from today)
- `payload` — one JSON-string form field, parsed server-side, shape:

```json
{
  "user_profile": {
    "employee_id": "EMP051",
    "full_name": "Hana Support",
    "role": "hr_support"
  },
  "chunk_info": {
    "chunking_strategy": "recursive",
    "chunk_size": 1000,
    "chunk_overlap": 150
  },
  "document_metadata": {
    "supersedes_document_id": null,
    "doc_category": "benefits",
    "department": "HR",
    "doc_description": "401k",
    "owner": null,
    "purpose": null,
    "effective_date": null,
    "audience": null,
    "confidentiality_level": null,
    "author": null,
    "doc_date": null,
    "doc_version": null
  }
}
```

**Renamed 2026-09-25 (Phase 57), user-directed:** `doc_type` -> `doc_category`,
`doc_classification` -> `doc_description` - a pure field rename, same
meaning and same optional/nullable behavior as before, not a new field or
a semantic change.

**Added 2026-09-25 (Phase 59), user-directed:** `author`, `doc_date`,
`doc_version` - three new document-metadata fields, same
caller-overrides-extraction-guess/nullable pattern as every other field in
this sub-object. Document-level only, not chunk-level (unlike
`doc_category`/`department`/`doc_description`) - not exposed as a
Self-Query filterable field, since these describe provenance, not
something a caller would search/filter chunks by.

All fields in all three sub-objects are optional. `document_metadata`
fields the caller sends override the LLM extraction step's own guess for
that field; fields left null still get filled in by extraction as today.

`payload` itself: `max_length=20000` characters on the raw form field (same
"bound every string field" rule as the rest of this project's contracts -
generous for this shape, small enough to reject an obvious abuse case).
Missing `payload` is treated as `{}` (every field defaults). Malformed
JSON, or JSON that doesn't match the shape above, returns `422` /
`VALIDATION_ERROR` (shared error object above), same as any other
validation failure - not a 500.

Response — `200`:

```json
{
  "uploaded_count": 1,
  "duplicate_count": 0,
  "rejected_count": 0,
  "results": [
    {
      "filename": "401k-policy.pdf",
      "document_id": "d3f1...",
      "status": "uploaded",
      "uploaded_by": "EMP051",
      "chunk_info": {
        "chunking_strategy": "recursive",
        "chunk_size": 1000,
        "chunk_overlap": 150,
        "action": "insert",
        "chunks_indexed": 12,
        "chunks_removed": 0
      },
      "document_metadata": {
        "doc_category": "benefits",
        "department": "HR",
        "doc_description": "401k",
        "owner": null,
        "purpose": null,
        "effective_date": null,
        "audience": null,
        "confidentiality_level": null,
        "author": null,
        "doc_date": null,
        "doc_version": null
      },
      "versioning_info": {
        "document_version": 1,
        "is_current": true,
        "supersedes": null,
        "superseded_by": null
      },
      "error": null,
      "error_code": null,
      "message": null,
      "file_size_bytes": 123456
    }
  ]
}
```

`status` is `"uploaded"`, `"duplicate"`, or `"rejected"` per file - a bad
file in a batch doesn't fail the good ones (unchanged from today).

---

## POST /v1/genai-rag/ingest-document/documents/{document_id}/reindex — Finalized (Phase 125)

In-place re-index: replaces an existing document's file content under the
*same* `document_id`, then runs the same chunk/embed/write pipeline
`POST /documents` already uses. Fills a real, previously-unbuilt gap - the
`"duplicate"` status response on the upload endpoint already told callers
"use that document_id to re-index if needed" with nowhere to actually do
that. Single file only (replacing one document's content is inherently
singular, unlike the batch upload endpoint) - `multipart/form-data`:

- `file` - one PDF (binary)
- `payload` - one JSON-string form field, parsed server-side:

```json
{
  "user_profile": {
    "employee_id": "EMP051",
    "full_name": "Hana Support",
    "role": "hr_support"
  },
  "chunk_info": {
    "chunking_strategy": "recursive",
    "chunk_size": 1000,
    "chunk_overlap": 150
  }
}
```

No `document_metadata`/`supersedes_document_id` sub-object - those describe
a *new* document's provenance/relationship to another; an in-place content
replace doesn't create a new document, so neither applies. `chunk_info` is
optional, same auto-select-if-omitted behavior as `POST /documents`.

Response - `200`:

```json
{
  "document_id": "d3f1...",
  "filename": "401k-policy-v2.pdf",
  "status": "reindexed",
  "chunk_info": {
    "chunking_strategy": "recursive",
    "chunk_size": 1000,
    "chunk_overlap": 150,
    "action": "update",
    "chunks_indexed": 14,
    "chunks_removed": 2
  },
  "versioning_info": {
    "document_version": 2,
    "is_current": true,
    "supersedes": null,
    "superseded_by": null
  },
  "error": null,
  "error_code": null,
  "message": null,
  "file_size_bytes": 128400
}
```

Reuses `DocumentUploadResult` (same shape as one entry in `POST /documents`'
own `results` array) - no new response model. `status` gains two new real
values on top of the three `POST /documents` already defines:
`"reindexed"` (content changed, full re-index ran) and `"unchanged"`
(uploaded content's hash exactly matches what's already indexed - a
no-op, cheap short-circuit, no embedding cost spent). `"rejected"` still
applies (bad file type/size/empty, same validation as upload). A
`document_id` that doesn't exist returns `404` / `DOCUMENT_NOT_FOUND`
(existing error code, reused) - a real error here, not a per-file
`"rejected"` result, since there's no batch to keep going for.

---

## POST /v1/genai-rag-retrieval/query — Finalized

Same `payload`-as-JSON-string-in-multipart pattern doesn't apply here -
this endpoint has no file, so it can be a real JSON body, no wrapper trick
needed.

```json
{
  "user_profile": {
    "employee_id": "EMP051",
    "full_name": "Hana Support",
    "role": "hr_support"
  },
  "query": "How many weeks of paid parental leave does JPMorgan Chase provide?",
  "search_options": {
    "top_k": 5,
    "vector_db": "chromadb",
    "search_strategy": "similarity",
    "use_multi_query": false,
    "use_self_query": false,
    "llm_provider": "openai"
  },
  "generation_options": {
    "model_name": "gpt-4.1-mini",
    "temperature": 0.0,
    "max_tokens": 500
  },
  "enable_conversation_memory": false,
  "conversation_id": null
}
```

**Added 2026-09-25 (Phase 58), user-directed:** `enable_conversation_memory`
(bool, default `false`) and `conversation_id` (string, default `null`).
When `enable_conversation_memory` is `true`: if `conversation_id` is
omitted/null, a new one is generated server-side and returned in the
response - pass that same value back on the next call to continue the
conversation. Server-side, in-memory store (see Phase 58 entry) - lost on
restart, single-process only; a cache DB is planned later, not built now.
When `false` (the default), behavior is unchanged from before this phase -
every query is independent, `conversation_id` in the response is `null`.

Response:

```json
{
  "query": "How many weeks of paid parental leave does JPMorgan Chase provide?",
  "answer_info": {
    "answer": "...",
    "model_used": "gpt-4.1-mini"
  },
  "retrieval_info": {
    "vector_db": "chromadb",
    "search_strategy": "similarity",
    "applied_filter": null,
    "sources": [
      { "document_id": "d3f1...", "filename": "401k-policy.pdf", "chunk_index": 3, "text": "...", "score": 0.87 }
    ]
  },
  "conversation_id": null
}
```

## POST /v1/single-agentic-rag-retrieval/query — Finalized (Phase 55)

Same identity-in-payload pattern as `genai-rag`'s query endpoint. No
`search_options`/`generation_options` - the agent decides retrieval/tool
choice itself, there's nothing for the caller to override yet.

```json
{
  "user_profile": {
    "employee_id": "EMP052",
    "full_name": "Eddy Employee",
    "role": "employee"
  },
  "query": "What is my PTO balance?",
  "max_iterations": 5,
  "enable_conversation_memory": false,
  "conversation_id": null
}
```

**Added 2026-09-25 (Phase 58):** same `enable_conversation_memory`/
`conversation_id` contract as `genai-rag`'s query endpoint above - same
server-side, in-memory store, shared module. Only the final answer per
turn is saved to history here, not the intermediate tool calls within a
turn's own reasoning loop.

Response:

```json
{
  "query": "What is my PTO balance?",
  "answer": "Your current Paid Time Off (PTO) balance is 11 days available.",
  "tools_used": [
    { "tool_name": "GetLeaveBalance", "tool_input": "" }
  ],
  "iterations": 2,
  "conversation_id": null
}
```

`tools_used` is empty when the agent answers without calling anything
(e.g. a greeting). No `sources`/`retrieval_info` shape like `genai-rag`'s
response - a tool-calling agent's grounding varies per tool, not always a
vector-store chunk list, so it isn't forced into that shape here.

## POST /v1/multi-agentic-rag-retrieval/query — Finalized (Phase 61, scaffold only)

Same identity-in-payload/RBAC/rate-limiting pattern as every other query
endpoint. **The pipeline itself is stubbed** (Phase 61) - this contract is
real and finalized, but a well-formed request returns `501` today, naming
`ai/agents/workflow_agents/multi_agent_pipeline.py`. Real orchestration
logic is a follow-up phase, not built yet.

```json
{
  "user_profile": {
    "employee_id": "EMP052",
    "full_name": "Eddy Employee",
    "role": "employee"
  },
  "query": "Plan my next 2 weeks: check my PTO balance and summarize the parental leave policy",
  "enable_conversation_memory": false,
  "conversation_id": null
}
```

No `max_iterations` at the top level - each dispatched sub-agent will
have its own, once orchestration exists; not a caller-facing knob yet.

Response (once implemented):

```json
{
  "query": "Plan my next 2 weeks: check my PTO balance and summarize the parental leave policy",
  "answer": "...",
  "tasks": [
    { "agent": "domain_agent_name", "focus": "what this sub-agent was asked to do" }
  ],
  "tools_used": [
    { "tool_name": "GetLeaveBalance", "tool_input": "" }
  ],
  "iterations": 3,
  "conversation_id": null
}
```

`tasks` records which sub-agent(s) the router dispatched to and why -
`AgentTaskInfo` in `models/multi_agentic_rag.py`. `tools_used` reuses
`ToolCallInfo` from `models/agentic_rag.py` (single-agentic-rag's own
shape) - aggregated across every sub-agent's own tool calls, not
per-agent, matching `single-agentic-rag`'s existing flat shape rather
than inventing a nested one.

Note: this example predates `sources`/`explainability_info` (both real on
the response today) and, as of Phase 123, `suggested_follow_up_questions:
list[str]` - Reviewer Agent-generated, empty when no domain agent ran.
Not rewritten here (stale example, not this phase's scope) - see
`MultiAgenticRagResponse` in `models/multi_agentic_rag.py` for the real,
current shape.

## `request_id` on every query response (EX-1, Explainability overhaul) — Finalized

Implemented as proposed below, including the single-id framing - raised as
an open question, not separately re-confirmed in words before
implementation, but no objection was raised either; flagging this
explicitly rather than treating silence as confirmation. One new field on
the shared `ExplainabilityInfo` model
(`models/rag.py`) - `RagQueryResponse`, `AgenticRagResponse`, and
`MultiAgenticRagResponse` all build their `explainability_info` from this
one model already, so adding the field there puts it in all three query
responses identically, with no per-pipeline special-casing:

```json
"explainability_info": {
  "request_id": "a1b2c3d4-5e6f-7890-abcd-ef1234567890",
  "served_from_cache": false,
  "llm_call_count": 1,
  "...": "...existing fields, unchanged"
}
```

- **Type:** `str` (UUID4, generated server-side). Always present, never
  null - including on a cache hit or an MCP fast-path answer. This is
  deliberately different from `token_usage`/`llm_context`, which go to
  `null`/`0` on those same paths - `request_id` identifies the HTTP
  request/response pair itself, not the generation work done to answer it,
  so it doesn't follow that pattern.
- **One id, not two:** proposing a single `request_id`, reused as the
  correlating value in that request's own backend log lines, in the
  (new, nullable) `request_metrics.request_id` column, and as LangSmith
  run metadata - not a separate `response_id`. A synchronous HTTP call has
  exactly one request and one response; nothing a second, distinct value
  would identify that this one doesn't already cover. Flagging this
  explicitly rather than silently deciding it, since this phase's own
  framing said "request_id/response_id" - confirm before implementation.
- **Not added this phase:** a lookup endpoint (paste a `request_id`, see
  everything about that call) - that's the later Engineering Trace tab
  (EX-8), not this one.
- **Where generated, in practice:** centralized in
  `common/observability/response_metrics.py`'s `time_and_log()` - every
  one of the 3 query routes already funnels through it (Phase 184), so
  generating there once covers cache hits and live calls uniformly without
  each pipeline's own early-return cache path needing special-casing. This
  is a cleaner realization of the same intent than the Design section
  below originally named (`run_guarded_pipeline()`/`run_multi_agent()`
  each generating their own) - found during implementation, not a change
  of goal.

## `groundedness_explanation`/`completeness_explanation` on `EvalScores` (Phase 202, Explainability overhaul) — Finalized

User asked for a "Response Generation Eval Score" tab showing *how* each
score was calculated, not just the number. `evaluate_groundedness()`/
`evaluate_completeness()` (`golden_dataset_harness.py`) already return the
judge LLM's full raw output (`{"score", "verdict", "explanation"}`) - the
`explanation` field is the complete "Score: X\nReasoning: ..." text the
judge produced - but all 3 pipelines' own `eval_scores = {...}` dict
construction (`pipeline.py`, `orchestration_agent.py`,
`multi_agent_pipeline.py`) already drops it, keeping only `score`/`verdict`.
Two new optional fields on the shared `EvalScores` model (`models/rag.py`),
additive, same every-pipeline-shares-one-model pattern as
`ExplainabilityInfo.request_id`:

```json
"eval_scores": {
  "groundedness": 0.9,
  "groundedness_verdict": "GROUNDED",
  "groundedness_explanation": "Score: 9\nReasoning: The answer's figures match the retrieved context exactly.",
  "completeness": 0.9,
  "completeness_verdict": "COMPLETE",
  "completeness_explanation": "Score: 9\nReasoning: Both parts of the question are addressed."
}
```

`str | None` - null only on the pre-existing paths where `eval_scores`
itself is already null (no retrieved context to judge against). Shown
verbatim in the new tab, not re-parsed - it's already the judge's own
"Score: X / Reasoning: ..." text.

## Live `retrieval_precision` on `EvalScores` (Phase 208, Explainability overhaul) — Finalized

Resolves the open design question raised repeatedly this session (sub-
question-coverage approximation vs. per-chunk LLM judging) by building the
more rigorous option: one new LLM judge call per live response (when
`sources` is non-empty), batched into a single call across every retrieved
chunk, asking which chunks actually help answer the question.
`precision = (chunks judged relevant) / (chunks retrieved)` - real,
computed live, not an estimate.

```json
"eval_scores": {
  "...": "...existing groundedness/completeness fields, unchanged",
  "retrieval_precision": 0.6,
  "retrieval_relevant_chunk_indices": [1, 3],
  "retrieval_precision_explanation": "Relevant: 1, 3\nReasoning: Chunks 1 and 3 cover the match percentage and vesting; chunk 2 is about an unrelated tuition benefit."
}
```

- **Deliberately no live `recall`/`f1`:** recall needs the total count of
  relevant documents that exist for the question, which is unknowable for
  an arbitrary live question outside the golden dataset (only there is
  the "1 relevant document" ground truth known in advance). Returning a
  fabricated recall number would be worse than returning none - the
  golden-dataset-only recall/F1 (`scripts/run_release_gate.py`) stays the
  only source for those two.
- **Type:** `retrieval_precision: float | None`,
  `retrieval_relevant_chunk_indices: list[int]`,
  `retrieval_precision_explanation: str | None`. Null/empty on the same
  paths `groundedness`/`completeness` are already null on (no sources, a
  cache hit, an MCP fast-path answer).

## `reasoning` on `AgentTaskInfo` (Phase 209, Explainability overhaul) — Finalized

User asked (item 3 of the pasted spec) to show "which tools the LLM
selected and why" for each query. The Planner already decides *which*
domain agent handles each part of a question (`PlannerTask.agent`/
`.focus`) but was never asked to say *why* - one new field, additive:

```json
"tasks": [
  { "agent": "vector_kb_agent", "focus": "401k match percentage", "reasoning": "This is a policy/benefits document question, which vector_kb_agent handles." }
]
```

`reasoning: str` - always present once a task exists (the Planner's own
prompt now asks for it on every task, including the single-task case).
The one hardcoded fallback (`PlannerOutput` parse failure ->
`vector_kb_agent` with the raw query as focus) gets a fixed, honest
`reasoning` string noting it's a fallback, not a real Planner decision.

## GET /v1/genai-rag/ingest-document/documents, GET .../{id} — Finalized

Identity: query params (`?employee_id=...&full_name=...&role=...`), not a
body - see the Phase 96 revision note above; a real browser can't send a
body on `GET` at all. `{id}` stays in the path for the single-document
form. Response is where the same 27-flat-field problem
from `DocumentRecord` (flagged earlier this session) actually lives -
reuses the same three sub-objects as the upload response, not redefined:

```json
{
  "id": "d3f1...",
  "filename": "401k-policy.pdf",
  "file_path": "data/uploads/d3f1.../401k-policy.pdf",
  "status": "indexed",
  "error_message": null,
  "created_at": "2026-09-19T...",
  "updated_at": "2026-09-19T...",
  "last_indexed_at": "2026-09-19T...",
  "chunk_ids": ["d3f1...:0", "d3f1...:1"],
  "chunk_count": 2,
  "file_size_bytes": 123456,
  "embedding_model": "text-embedding-3-small",
  "embedding_dimension": 1536,
  "uploaded_by": "EMP051",
  "chunk_info": { "chunk_size": 1000, "chunk_overlap": 150 },
  "document_metadata": { "doc_category": "benefits", "department": "HR", "doc_description": "401k", "owner": null, "purpose": null, "effective_date": null, "audience": null, "confidentiality_level": null, "author": null, "doc_date": null, "doc_version": null },
  "versioning_info": { "document_version": 1, "is_current": true, "supersedes": null, "superseded_by": null }
}
```
`GET /documents` (list) wraps this in `{"count": N, "documents": [...]}`, unchanged.

## DELETE /v1/genai-rag/ingest-document/documents/{id}, DELETE .../documents (all) — Finalized

Body: `{"user_profile": {...}}` only, same as the GET endpoints above.
This is the endpoint the audit trail matters most for - `deleted_by` on
the response, using the caller's `employee_id`:

```json
{ "document_id": "d3f1...", "filename": "401k-policy.pdf", "chunks_removed": 12, "deleted_by": "EMP051" }
```
```json
{ "documents_deleted": 6, "chunks_removed": 54, "deleted_by": "EMP051" }
```

## GET .../documents/cleanup/preview, DELETE .../documents/cleanup — Finalized (Phase 46)

`GET .../preview`: query params, per the Phase 96 revision above.
`DELETE .../cleanup`: body, `{"user_profile": {...}}` only, unchanged.
Registered before `GET/DELETE /documents/{id}` so `cleanup` is
never read as a document id. "Test noise" = `file_size_bytes` below
`TEST_NOISE_MAX_FILE_SIZE_BYTES` (`.env`, default `1024`) - a structural
signal (every test-generated file is a short fake string), not a guess.

Preview (`GET`) - deletes nothing:
```json
{
  "count": 2,
  "threshold_bytes": 1024,
  "documents": [
    { "id": "a1b2...", "filename": "noise.pdf", "file_size_bytes": 42, "created_at": "2026-09-20T..." }
  ]
}
```

Delete (`DELETE`) - same response shape as delete-all:
```json
{ "documents_deleted": 2, "chunks_removed": 0, "deleted_by": "EMP051" }
```

## GET /health, GET /ping — Finalized: no identity, no change

No identity params, on purpose - both are called by automated
infrastructure (Docker's `HEALTHCHECK`, CI's deploy smoke test), not by an
employee acting on data. Requiring `employee_id`/`role` here would break
those automated callers, which have no employee context to send. Audit
trail is for actions on documents (upload/query/delete) - these two don't
touch documents. Response is already grouped by backend
(`checks.llm`/`checks.vector_database`/`checks.metadata_database`) -
no change needed there either, it already matches this exercise's pattern:

```json
{ "status": "healthy", "app": "HRB Chatbot", "checks": { "llm": {...}, "vector_database": {...}, "metadata_database": {...} } }
```
`/ping`: `{"status": "ok"}`, unchanged - it's deliberately minimal (no provider calls).

## GET /v1/admin/golden-dataset — Finalized (Phase 181)

Identity: query params (`?employee_id=...&full_name=...&role=...`), same
Phase 96 convention every other admin-only `GET` route already uses - this
is an application of that settled pattern to a new resource, not a new
negotiation. `Role.ADMIN` only (Engineering Admin) - Employee Admin does
not get this, same split as `/v1/admin/docs`. Read-only - no POST/PUT/
DELETE in this phase; editing stays in the source JSON files, mirrored in
by `scripts/sync_golden_dataset.py`, not edited through the API.

```json
{
  "count": 25,
  "cases": [
    {
      "id": 1,
      "case_key": "401k-01",
      "dataset": "genai_rag",
      "category": "happy",
      "query": "What percentage does JPMorgan Chase match on my 401(k) contributions?",
      "raw_case": {
        "id": "401k-01",
        "category": "happy",
        "query": "What percentage does JPMorgan Chase match on my 401(k) contributions?",
        "expected_source_document": "401k.pdf",
        "expected_answer": "JPMorgan Chase matches 100% of employee contributions (dollar-for-dollar) up to 5% of Eligible Compensation, available after one year of service.",
        "expected_keywords": ["100%", "dollar-for-dollar", "5%", "one year of service"],
        "call_type": "llm_call"
      },
      "updated_at": "2026-10-15T00:00:00Z"
    }
  ]
}
```
`raw_case` is the original JSON case object verbatim (jsonb column) - every
field from `golden_dataset.json`/`nfr_golden_dataset.json` renders without
the API needing to know each dataset's exact field set up front. `dataset`
is `"genai_rag"` or `"nfr"`, matching which source file the case came from.

## GET /v1/admin/eval-runs, GET /v1/admin/eval-runs/{id} — Finalized (Phase 182)

Identity: query params, same Phase 96 convention. `Role.ADMIN` only. List
returns summaries (no per-case detail); `{id}` adds the full per-case
breakdown.

```json
{
  "count": 3,
  "runs": [
    {
      "id": 1,
      "run_at": "2026-10-15T12:00:00Z",
      "decision": "PASS",
      "flags": [],
      "aggregated_scores": { "recall": 0.96, "groundedness": 0.91, "completeness": 0.88 },
      "total_cases": 23,
      "scored_cases": 23,
      "failed_case_ids": [],
      "retrieval_k": 5
    }
  ]
}
```
`GET /eval-runs/{id}` returns one run object (same shape) plus `"cases":
[{"case_id": "401k-01", "category": "happy", "scores": {"recall": 1.0,
"groundedness": 0.9, "completeness": 0.85}, "status": "scored"}, ...]`.
404 (`ADMIN_EVAL_RUN_NOT_FOUND`) for an unknown id.

## GET /v1/admin/ci-status — Finalized (Phase 183)

Identity: query params, same Phase 96 convention. `Role.ADMIN` only. Live
read of this repo's own GitHub Actions `ci.yml`/`deploy.yml` runs (5
latest each) via `github_actions_client.py`. Never 500s on a GitHub-side
failure (unset `GITHUB_TOKEN`, rate limit, network) - each workflow's own
`error` field carries that instead of a crashed request.

```json
{
  "ci": {
    "runs": [
      {
        "id": 123456,
        "status": "completed",
        "conclusion": "success",
        "head_sha": "d870681",
        "head_commit_message": "Add golden dataset Postgres mirror",
        "html_url": "https://github.com/rvsree/hrb_chatbot_v2/actions/runs/123456",
        "created_at": "2026-10-15T03:58:22Z"
      }
    ],
    "error": null
  },
  "deploy": {
    "runs": [],
    "error": null
  }
}
```
`error` is a string (e.g. `"GITHUB_TOKEN not configured"`) when the
GitHub-side call failed - `runs` is then always `[]`, never a partial list.

## GET /v1/admin/request-metrics — Finalized (Phase 184)

Identity: query params, same Phase 96 convention, plus `window` (hours,
default 24). `Role.ADMIN` only. Aggregated from `request_metrics`, which
`common/observability/response_metrics.py`'s `time_and_log()` writes once
per real response from genai-rag/single-agentic-rag/multi-agentic-rag's
own route handlers (fire-and-forget - a logging failure never affects the
real response). No `cost_usd` field - no verified per-model price table
exists in this project, so cost is never estimated/guessed.

```json
{
  "window_hours": 24,
  "rows": [
    {
      "pipeline": "genai-rag",
      "status": "success",
      "request_count": 42,
      "avg_latency_ms": 850.3,
      "p50_latency_ms": 700.0,
      "p95_latency_ms": 1800.0,
      "total_tokens": 12000
    }
  ]
}
```
`total_tokens` is `null` for `multi-agentic-rag` rows - no per-domain-
agent token usage exists yet (`BACKLOG.md`'s own documented gap), not
fabricated to look complete.

## POST /v1/faq/submit, GET /v1/admin/faq-submissions, POST .../restructure, POST .../review, GET /v1/faq/published — Finalized (Phase 186)

`POST /v1/faq/submit` - body identity (every other `EMPLOYEE`-reachable
route's convention), `{"user_profile": {...}, "query": "..."}`. Any role.
Response: the created row.
```json
{
  "id": 1,
  "employee_id": "EMP052",
  "query": "Does the tuition reimbursement cover certifications, not just degrees?",
  "external_llm_answer": "Based on the knowledge base, ...",
  "internal_review_status": "pending",
  "answer_restructuring_status": "not_started",
  "final_answer": null,
  "published": false,
  "reviewed_by": null,
  "created_at": "2026-10-15T...",
  "updated_at": "2026-10-15T..."
}
```
`GET /v1/admin/faq-submissions` - query-param identity (Phase 96),
`Role.HR_SUPPORT`/`ADMIN`. Returns `{"count": N, "submissions": [...same
shape as above...]}`.

`POST /v1/admin/faq-submissions/{id}/restructure` - body identity,
`{"user_profile": {...}}`, same 2 roles. Returns the updated row with
`final_answer` set to Claude's suggested rewrite and
`answer_restructuring_status: "claude_restructured"` - a draft, not
published.

`POST /v1/admin/faq-submissions/{id}/review` - body identity,
`{"user_profile": {...}, "internal_review_status": "approved", "final_answer": "...", "published": true}`.
Returns the updated row, `reviewed_by` set to the caller's `employee_id`.

`GET /v1/faq/published` - query-param identity, any role. Returns
`{"count": N, "faqs": [{"id": 1, "query": "...", "final_answer": "..."}]}`
- only the 2 public-facing fields, none of the review-workflow internals.

## GET/POST/PUT/DELETE /v1/admin/interview-qa — Finalized (Phase 187)

Identity: query params on `GET`, body on `POST`/`PUT`/`DELETE` (Phase 96/45
conventions, same split every other admin resource uses). `Role.ADMIN`
only. Real CRUD, not read-only - this is genuinely editable content.

```json
{
  "id": 1,
  "topic": "Tool integration: search, browser, retrieval; failures & circuit breakers",
  "topic_order": 2,
  "card_order": 2,
  "question": "What is a circuit breaker for tool calls, and why not just retry on failure?",
  "hint": "N consecutive failures → trip → skip real calls for a cooldown → fail open if the check itself fails",
  "concept": "...",
  "situation": "...",
  "task": "...",
  "action": "...",
  "result": "...",
  "project_link": "...",
  "leadership_angle": "...",
  "trade_offs": ["...", "..."],
  "keywords": [{"term": "Circuit breaker", "definition": "..."}],
  "tech_stack": ["Python", "FastAPI", "psycopg"],
  "feature_references": [{"label": "_check_circuit_breaker()", "file_path": "src/hrb_chatbot/ai/rag_pipeline/tools/mcp_tools/__init__.py"}],
  "created_at": "2026-10-15T...",
  "updated_at": "2026-10-15T..."
}
```
`GET /v1/admin/interview-qa` (list, optional `?topic=...` filter) wraps
this in `{"count": N, "cards": [...]}`. `POST` body omits `id`/
`created_at`/`updated_at`. `PUT`/`DELETE` take `{id}` in the path, `PUT`
body is the same shape as `POST`. 404 (new code `ADMIN_INTERVIEW_QA_NOT_FOUND`)
for an unknown id on `PUT`/`DELETE`/`GET .../{id}`.

## POST /v1/genai-rag/ingest-document/documents/presigned-upload — Finalized (Phase 89)

**Additive, confirmed with the user 2026-10-06 - does not replace, and
nothing changes about, the existing `POST .../documents` above.** Single
file only, no batch variant this phase.

Request, JSON (not multipart - no file bytes exist yet):
```json
{
  "user_profile": { "employee_id": "EMP051", "full_name": "Hana Support", "role": "hr_support" },
  "filename": "401k-policy.pdf",
  "content_type": "application/pdf",
  "chunk_info": { "chunking_strategy": null, "chunk_size": null, "chunk_overlap": null },
  "document_metadata": {
    "supersedes_document_id": null, "doc_category": "benefits", "department": "HR",
    "doc_description": "401k", "owner": null, "purpose": null, "effective_date": null,
    "audience": null, "confidentiality_level": null, "author": null, "doc_date": null, "doc_version": null
  }
}
```
`chunk_info`/`document_metadata` are the exact same sub-objects the
synchronous endpoint above already accepts - identical fields, identical
optional/nullable behavior. Validated the same way the synchronous
endpoint validates a file: content-type/extension check
(`error_codes.INVALID_FILE_TYPE`), `supersedes_document_id` must
reference a real document if given (`error_codes.
SUPERSEDES_TARGET_NOT_FOUND`). Role gate and rate limit unchanged from
every other mutating route (`hr_support` only).

Response — `200`:
```json
{ "document_id": "d3f1...", "upload_url": "https://hrb-chatbot-kb-uploads.s3.amazonaws.com/...", "expires_in_seconds": 300, "status": "pending_upload" }
```
A **new, separate response shape** - not `DocumentUploadResponse` above -
since nothing has been chunked/embedded/indexed yet when this responds.
The client `PUT`s the file body directly to `upload_url` (plain HTTP, no
AWS SDK, no credentials needed client-side - see `docs/dev-reference/
deployment-guide/05-rag-ingestion-batch.html`'s "Presigned URLs" section),
then polls the existing `GET /v1/genai-rag/ingest-document/documents/{id}`
above for the real indexing result once Phase 88's S3 → SQS → Lambda
pipeline picks it up - same response shape that endpoint already returns
today, no change there either.
