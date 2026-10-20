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

## `eval_options` request field + `judge_model_used`/`below_threshold` on `EvalScores` (Phase 215, Explainability overhaul) — Finalized

New shared `EvalOptions` sub-object, added to all 3 query requests:

```json
{
  "eval_options": {
    "judge_model": "gpt-4.1-mini",
    "eval_score_threshold": 0.6
  }
}
```

Both fields optional, `eval_options` itself optional - omitting it entirely
is identical to today's behavior (no override, no threshold check).
`judge_model` is free text (same convention as `GenerationOptions.model_name` -
a model name is open-ended, never an enum). `eval_score_threshold` is
0.0-1.0.

Response - `EvalScores` gains:

```json
"eval_scores": {
  "...": "...existing fields unchanged",
  "judge_model_used": "gpt-4.1-mini",
  "below_threshold": true,
  "below_threshold_metrics": ["completeness"]
}
```

`judge_model_used` always present once any judge call ran (the override if
given, else the real default model) - verifiable, not just trusted.
`below_threshold`/`below_threshold_metrics` only meaningful when
`eval_score_threshold` was given; `below_threshold` is `false` and
`below_threshold_metrics` is `[]` when no threshold was set, same as
"nothing to flag." Checked against whichever of
groundedness/completeness/retrieval_precision are actually present for
that call - a null field (e.g. no live retrieval_precision for an
MCP-routed answer) is never counted as a breach.

## `search_strategy` on `ToolCallInfo` (Phase 216, Explainability overhaul) — Finalized

New optional field, same additive pattern as `iteration` (Phase 206) and
`latency_ms` (Phase 205) before it:

```json
{
  "tool_name": "search_knowledge_base",
  "tool_input": "401k employer match",
  "tool_type": "vector_db",
  "search_strategy": "mmr",
  "latency_ms": 420.1,
  "success": true,
  "iteration": 1
}
```

Only ever set for `search_knowledge_base` calls (single-agentic-rag's own
ReAct tool, also multi-agentic-rag's KB Vector Agent domain agent, which
wraps the same tool with no `search_strategy` arg of its own - so it's
always `"similarity"` there, never agent-chosen). `null` for every other
tool. Real gap this closes: `search_knowledge_base` already accepted a
`search_strategy` arg the agent could set per call (`similarity`/`mmr`),
but `orchestration_agent.py`'s own tool-call logging only ever captured
`tool_args.get("input", "")` into `tool_input` - the agent's own strategy
choice was silently dropped before this, never returned anywhere.

## `knn` added to `SearchOptions.search_strategy` (Phase 218, Explainability overhaul) — Finalized

A 5th valid value alongside `similarity`/`mmr`/`keyword`/`hybrid` - no
shape change, same `search_options.search_strategy` string field genai-rag
already has:

```json
{ "search_options": { "search_strategy": "knn" } }
```

**Real, not decorative - re-investigated after user push-back.** The
earlier finding ("KNN/ANN/HNSW isn't a real per-query choice in this
stack") was correct for the *native* vector-store query path - Chroma and
Pinecone both always use HNSW internally for `similarity_search`/`mmr`,
with no "pick a different index algorithm" knob exposed by either's API.
What changed: re-reading `pinecone_client.py::get_all_chunks()` (used by
`search_keyword`/`search_hybrid` already) found it already does a full
`list()` + `fetch()` walk of the whole index and each fetched vector
already carries its own embedding (`vector.values`) - just discarded
before this phase. So a real, **exact**, brute-force KNN - compute cosine
similarity against every current chunk's own stored embedding in Python,
no index/approximation involved - is genuinely buildable against both
backends' existing `get_all_chunks()` method, not a new per-backend
capability each one would need to add.

`similarity` (the existing default) is relabeled in UI copy only - no
wire-shape change - as "Semantic Search - ANN (Approximate Nearest
Neighbor) via HNSW", since that's literally what it already runs.
`"ann"` and `"hnsw"` are NOT added as separate `search_strategy` values:
in this stack they're the same code path as `"similarity"` already is, so
offering them as distinct selectable options would silently run identical
code under 3 different names - exactly the "decorative control" the
earlier finding was right to reject. Naming both concepts in the existing
option's label/tooltip instead of inventing fake duplicate entries.

**Compatibility - both backends support `knn`, cost profile differs:**
ChromaDB's `get_all_chunks()` is a single local SQLite-backed bulk read
(fast). Pinecone's is a paginated network round-trip (100 ids/`fetch()`
call) - functionally supported, same cost profile `keyword`/`hybrid`
already accept on Pinecone today, but noticeably slower than Chroma on a
large collection. Surfaced in the Settings UI's own "?" tooltip and the
Explainability Retrieval Strategy tab, not hidden.

## `retrieval_recall_estimate`/`retrieval_f1_estimate`/`retrieval_recall_pool_size` on `EvalScores` (Phase 219, Explainability overhaul) — Finalized

3 new optional fields alongside `retrieval_precision`:

```json
{
  "retrieval_precision": 1.0,
  "retrieval_recall_estimate": 0.667,
  "retrieval_f1_estimate": 0.8,
  "retrieval_recall_pool_size": 4
}
```

**Not true recall - an explicitly bounded estimate, confirmed with the user
(2026-10-18) as the honest alternative to fabricating one.** True recall
needs the total count of relevant documents that exist for an arbitrary
live question, which stays unknowable outside the golden dataset - that
limitation is real and Phase 208's own code already refused to fabricate a
number for it. What changed: `evaluate_retrieval_relevance()` now
optionally judges a *wider candidate pool* (the originally-retrieved
chunks + extra exact-KNN candidates, Phase 218's own new capability,
capped at 20 total) in the same single LLM call, and reports
`retrieval_recall_estimate` = (chunks relevant within what was actually
retrieved) / (chunks relevant anywhere in that wider pool).
`retrieval_f1_estimate` is their harmonic mean. `retrieval_recall_pool_size`
is how large that pool was, so the estimate's own bound is visible, not
hidden. All 3 are `null` when nothing in the pool was judged relevant
(undefined, never fabricated as `0` or `1`) - same "null over a fabricated
number" rule `retrieval_precision` already followed.

**Phase 220 update - extended to `AgenticRagResponse`/`MultiAgenticRagResponse`
(single/multi-agentic-rag), with one real behavior change surfaced live:**
these 2 pipelines' own `_score_live_answer()` used to judge `retrieval_precision`
against `context_texts`/`agent_result_texts` - the RAW tool-output text,
which mixes real KB-chunk content with web-search/MCP text under headers
like "Web Source 1" (confirmed live: a judged-relevant list literally
contained both real chunk numbers and "Web Source 1-5" entries, which is
a category error for a metric meant to measure chunking/indexing/retrieval
quality - web results have nothing to do with either). Both now scope
`retrieval_precision`/`retrieval_recall_estimate`/`retrieval_f1_estimate`/
`retrieval_recall_pool_size` to `sources` (the structured, real KB-chunk
list Phase 115/120 already built for citations) instead - `null` whenever
`sources` is empty even if `context_texts`/`agent_result_texts` isn't (an
MCP-only or web-only answer). `groundedness`/`completeness` are unaffected,
still judged against the full mixed text, since "is the answer grounded in
everything the agent used" correctly includes web/MCP content.

**Cost:** adds one real exact-KNN retrieval call before the judge call on
every live answer with retrieved context (previously just the judge calls)
- confirmed acceptable by the user over having no live recall/F1 at all.
Not included in `EVAL_THRESHOLD_METRICS` (`ai/rag_core/eval_threshold.py`)
- `eval_score_threshold` still only flags on
groundedness/completeness/retrieval_precision, deliberately, since flagging
on an estimate could read as a harder signal than it actually is.

## `matched_by` on `RetrievedChunk` (Phase 221, Explainability overhaul) — Finalized

New optional field, hybrid search only:

```json
{ "document_id": "doc-1", "filename": "401k.pdf", "chunk_index": 0, "text": "...", "score": 0.0321, "matched_by": ["dense", "sparse"] }
```

`null` for every `search_strategy` except `hybrid`. For hybrid, one or both
of `"sparse"` (BM25 keyword) / `"dense"` (vector similarity) - whichever
list(s) actually surfaced that chunk before Reciprocal Rank Fusion merged
them.

**Why this instead of a "dense/sparse weight" - user asked for weights,
investigation found there isn't one to show.** This project's hybrid
search (`bm25_search.py::_reciprocal_rank_fusion`) is pure RRF:
`score = sum(1 / (RRF_K + rank))` across whichever lists a chunk appears
in, `RRF_K = 60`. There is no alpha/weight term anywhere in it (confirmed
by reading the function, not assumed) - both lists contribute identically
by rank position, by design; RRF's whole point is being scale-free (BM25's
unbounded score and cosine similarity's 0-1 range never need normalizing
against each other) rather than a tunable blend. So "show the dense/sparse
weight" has no real number behind it to show. `matched_by` is the real,
per-query substitute: which list(s) actually contributed to each result,
surfaced instead of a weight that doesn't exist.

## `below_threshold`/`below_threshold_metrics` now recomputed on a cache hit (Phase 223) — Finalized

Behavior fix, no shape change. A cache hit (same query + same retrieval/
generation config, so same cache key - `search_strategy`/`top_k`/
`temperature`/etc. are all already part of it) now recomputes
`below_threshold`/`below_threshold_metrics` against **this call's own**
`eval_options.eval_score_threshold`, instead of serving whatever was
frozen in the cache from whenever that exact (query, config) was first
asked. The underlying scores themselves (`groundedness`/`completeness`/
`retrieval_precision`/etc.) are still reused, not re-judged - only the
threshold comparison is live. `judge_model` stays an exception: a cache
hit still reports the ORIGINAL call's `judge_model_used`, since re-judging
with a different model would require a real LLM call, defeating part of
the point of caching.

## `guardrails` on `ExplainabilityInfo` (Phase 224, Explainability overhaul) — Finalized

New field on the already-shared `ExplainabilityInfo` (so all 3 main query
responses - genai-rag/single-agentic-rag/multi-agentic-rag - get it
identically):

```json
{
  "guardrails": {
    "input": { "status": "pass", "rail": null },
    "output": { "status": "modified", "rail": "pii detection" }
  }
}
```

`status` is `"pass"`, `"modified"` (NeMo Guardrails masked something, e.g.
PII), or `"blocked"` (output only - input blocks still raise a 422 before
any response is built, unchanged). `rail` names which NeMo rail fired,
`null` on a clean pass.

**Real gap this closes, found by investigation (not assumed real).**
Before this phase, `check_input()`/`check_output()` returned only the
resulting text - a MODIFIED or BLOCKED check was indistinguishable from an
untouched PASS to every caller. For `check_output()` specifically this was
worse than just "not observable": a BLOCKED output silently swaps the real
answer for `SAFE_FALLBACK_ANSWER` inside an ordinary 200 response - the
caller had **zero signal** that anything had happened to the answer they
got back. `check_input()`/`check_output()` both now return
`(content: str, status: dict)` instead of a bare string; every call site
across the codebase was updated to match (see RAG-ROADMAP.md Phase 224).

## `activated_rails` on `GuardrailCheckStatus` (Phase 229) — Finalized

New field, additive to the already-shared `GuardrailCheckStatus` (Phase
224) - both `input` and `output` checks on `ExplainabilityInfo.guardrails`
get it:

```json
{
  "guardrails": {
    "input": {
      "status": "pass",
      "rail": null,
      "activated_rails": [
        { "name": "self check input", "decisions": ["execute self_check_input"], "stop": false },
        { "name": "mask sensitive data on input", "decisions": ["execute mask_sensitive_data"], "stop": false }
      ]
    },
    "output": { "status": "pass", "rail": null, "activated_rails": [ /* same shape */ ] }
  }
}
```

**Real gap this closes, found by live verification against the actual
NeMo Guardrails library (not assumed).** `check_input()`/`check_output()`
called `LLMRails.check_async()`, which (confirmed by reading NeMo's own
source, `llmrails.py`) already internally requests NeMo's full per-rail
activation log on every call (`options["log"] = {"activated_rails": True}`)
- then throws that log away, returning only the single aggregate
status/rail. A live-verified call against this project's own config
confirmed the real, previously-discarded data: for an ordinary benign
question, BOTH configured input flows (`self check input` AND
`mask sensitive data on input`) show up individually, each with NeMo's own
real decision trace (e.g. `["execute self_check_input"]`), even though
neither one changed anything - exactly the "which validations are actually
running, not just the one that happened to matter" visibility this closes.
For a blocked query, only `self check input` appears (`stop: true`,
decisions ending in `"refuse to respond"`/`"stop"`) - `mask sensitive data`
never gets a turn, confirming this project's own documented BACKLOG.md note
live rather than just citing it.

**Implementation change:** `check_input()`/`check_output()` no longer call
`check_async()` - they call `LLMRails.generate_async()` directly (the same
call `check_async()` made internally) with
`options={"rails": [...], "log": {"activated_rails": True}}`, and
replicate `check_async()`'s own status-determination logic locally
(compare original vs. final content; a blocked rail is any activated rail
with `stop: true`) - verified against NeMo's own source as simple,
self-contained logic, not a fragile dependency on NeMo's private/
underscore-prefixed helper functions. Behavior for pass/modified/blocked
is unchanged; `activated_rails` is the only new data.

## `enable_corrective_retry` on `SearchOptions` + `retrieval_retry_attempted` on `EvalScores` (Phase 226) — Finalized

New request field, genai-rag only (`POST /v1/genai-rag-retrieval/query`'s
`search_options`) - not on the shared `EvalOptions` model, deliberately: it
only does anything in `pipeline.py` today, so putting it on the model
`AgenticRagRequest`/`MultiAgenticRagRequest` also use would make it a
decorative control there with no real effect, the exact pattern this
project avoids elsewhere (see `ChatPage.tsx`'s own Retrieval Strategy
dropdown, genai-rag-only for the identical reason).

```json
{ "search_options": { "enable_corrective_retry": true } }
```

Requires `eval_options.eval_score_threshold` to also be set - with no
threshold there's no "low" to detect, so the flag is a no-op without one
(not an error - same quiet-no-op precedent as `eval_score_threshold` itself
being optional).

Response: new `EvalScores.retrieval_retry_attempted: bool`, always `false`
when the feature wasn't enabled, `below_threshold` was never true, or
`eval_score_threshold` wasn't set.

**Real-world pattern, not invented here:** this is retrieval-stage
"Corrective RAG" - checking retrieval quality BEFORE generating an answer,
not after. Deliberately NOT implemented as "generate, score the answer,
regenerate if low" - that shape has a real correctness trap this project's
own `ai/rag_core/guarded_pipeline.py` already has baked into it: the shared
core saves the generated answer to conversation memory as part of
`generate()`'s own return, before `pipeline.py` ever scores it - a second,
different answer produced by a post-hoc regenerate would silently diverge
from what's already saved as this turn's answer. Checking retrieval
(`evaluate_retrieval_relevance()` on the chunks alone, before any answer
exists) and retrying RETRIEVAL - never generation - sidesteps that trap
entirely: by the time an answer is generated and saved, retrieval has
already had its one chance to improve.

## `search_strategy` on `AgenticRagRequest`/`MultiAgenticRagRequest` (Phase 228) — Finalized

New top-level request field (not nested in a `search_options` sub-object -
neither request has one, and this is the only search-related field either
needs), on both `POST /v1/single-agentic-rag-retrieval/query` and
`POST /v1/multi-agentic-rag-retrieval/query`:

```json
{ "search_strategy": "mmr" }
```

**Type is `Literal["similarity", "mmr"]`, NOT the full `SearchStrategy`
enum genai-rag's own `search_options.search_strategy` uses** - deliberately
narrower. The underlying tool both pipelines call
(`ai/rag_pipeline/tools/agentic_tools.py::search_knowledge_base()`) only
ever understands `"similarity"`/`"mmr"` - anything else silently falls back
to `"similarity"` inside that function. Accepting `"keyword"`/`"hybrid"`/
`"knn"` here and quietly no-op'ing them would be exactly the "decorative
control with no real effect" bug this project has been fixing all session
(Phase 218's KNN investigation, the Retrieval Strategy dropdown's own
genai-rag-only scoping) - so an unsupported value is a clean 422 at the API
boundary (Pydantic's own `Literal` validation) instead of a silent no-op.

**Single-agentic-rag specific behavior:** this is a *default*, not a
forced override - the ReAct agent already independently chooses
`search_strategy` per `SearchKnowledgeBase` tool call today (Phase 216).
When the agent's own tool call doesn't specify one, this request-level
value is used instead of the previous hardcoded `"similarity"` fallback;
when the agent DOES specify its own choice, that still wins - the agent's
live, per-call reasoning isn't overridden by a standing default.

**Multi-agentic-rag specific behavior:** `vector_kb_agent` never exposed a
strategy choice at all before this (always hardcoded `"similarity"`
indirectly via `search_knowledge_base()`'s own default) - this field is the
only way to influence it, full stop, no per-call agent choice involved.

Both pipelines' own cache keys now include `search_strategy` (same
"anything that can change the answer belongs in the key" rule genai-rag's
cache key already follows) - a cached answer generated under one default
is never served to a caller who explicitly requested a different one.

## `department` on `UserProfile` (Phase 231, Document ACL) — Finalized

New field on the `user_profile` sub-object every endpoint already takes
(see the Identity source section above) - sent the same way as `role`:

```json
{ "user_profile": { "employee_id": "EMP051", "full_name": "...", "role": "employee", "department": "Finance" } }
```

`str | None`, self-asserted exactly like `role` - same already-accepted
tradeoff noted above ("RBAC here is a formality, not a real control").
This isn't a new, worse trust problem: it extends the same identity model
to one more field, not a new one. Null (the default - every existing
caller that doesn't send it) means "no declared department," which the
Document ACL department gate (below) treats as not matching any
department-restricted document - the safe-by-default side, not the open
side. Used only by Gate 2 (document ACL) at retrieval time; never
validated against a real department directory (none exists in this
project) - same caveat as `role`.

## `restricted_roles` on `DocumentMetadataInput`/`DocumentMetadataResult` (Phase 231, Document ACL) — Finalized

New field, upload (`POST /v1/genai-rag/ingest-document/documents`) and
response only - alongside `department`/`doc_category`/etc. in the
`document_metadata` object:

```json
{ "document_metadata": { "restricted_roles": ["manager", "hr_support"] } }
```

`list[str] | None`. **Caller-supplied only, never LLM-extracted** - unlike
`doc_category`/`doc_description`/`department`, which the extraction step
guesses when the caller doesn't supply them, an access-control gate can't
be a guess. A document with no `restricted_roles` (the default - every
document uploaded before this phase) is visible to every retrieval-
eligible role, unchanged from today. Values are expected to be real
`Role` enum values (`employee`/`manager`/`hr_support`/`admin`/
`employee_admin`) but this field stays plain `list[str]`, not
`list[Role]` - a typo'd role here should fail safe (deny everyone that
spelling doesn't match, including real ones) rather than reject the
whole upload with a 422, since this is advisory access-control data, not
a request parameter the API boundary needs to validate strictly.

## `acl_denied_count` on `RetrievalInfo` (Phase 232, Document ACL visibility) — Finalized

New field on `POST /v1/genai-rag-retrieval/query`'s `retrieval_info` object only
(genai-rag, matching where `applied_filter` itself already lives - Phase 231's
Document ACL also gates single-agentic-rag/multi-agentic-rag, but neither
exposes a `retrieval_info`-shaped object at all today, so there's nowhere to
put this for them without inventing new response structure - out of scope here):

```json
{ "retrieval_info": { "acl_denied_count": 0 } }
```

`int`, default `0`. How many documents Document ACL (Phase 231) excluded
from this answer's retrieval candidate pool - `0` for the common case
(no restricted documents, or the caller's role bypasses the gate
entirely). Deliberately a count, not the denied document_ids themselves -
listing which documents a caller was denied would itself leak which
restricted documents exist, defeating the gate's own purpose. Deliberately
kept separate from `applied_filter` (not merged into it) - same reasoning
Phase 231 already gave for keeping the ACL filter out of that field:
`applied_filter` represents Self-Query's own parsed filter, and mixing in
a security control would misrepresent what it shows.

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

## GET /v1/admin/ci-status — Finalized (Phase 183, redesigned Phase 235)

Identity: query params, same Phase 96 convention. `Role.ADMIN` only. Live
read of one `application`'s GitHub Actions runs via
`github_actions_client.py`. Never 500s on a GitHub-side failure (unset
`GITHUB_TOKEN`, rate limit, network) - each workflow's own `error` field
carries that instead of a crashed request.

**Phase 235 redesign, breaking change** - the original `{ci, deploy}` fixed
pair only ever fit `backend`'s own 2 workflow files. Phase 233 gave the
*pipeline* endpoint (`/ci-status/pipeline`) an `application` selector but
never touched this one (`/ci-status`, the older "Full run history" grid
below it) - it still only ever showed `hrb_chatbot_v2`'s own `ci.yml`/
`deploy.yml`, regardless of which application the Application dropdown had
selected. This redesign gives it the same `application` param, plus new
`page`/pagination (user-reported: the grid would otherwise grow
unboundedly tall as more runs accumulate), plus a human-readable
`display_name` per workflow (user-reported: raw file names like
`deploy-lambda.yml` aren't meaningful to a non-technical reader - the real
file name moves to a "?" popover instead, not removed). No caller outside
this project's own 2 repos existed for the old shape (confirmed - no
test, no other consumer), so this is a clean replacement, not a
versioned/dual-shape endpoint.

```
GET /v1/admin/ci-status?application=backend&page=1&employee_id=...&full_name=...&role=admin
```

`application: Application = "backend"` - same enum/semantics as Phase
233's `/ci-status/pipeline?application=...` (see that section below).
`page: int = 1` (1-indexed) - each workflow file's own run list is paged
independently, 5 runs per page (reduced from an initial 10 - 2026-10-19,
user-requested), newest-first (GitHub's own API default
order, unchanged).

```json
{
  "application": "backend",
  "page": 1,
  "workflows": [
    {
      "workflow_file": "ci.yml",
      "display_name": "Continuous Integration Checks",
      "runs": [
        {
          "id": 123456,
          "run_number": 240,
          "status": "completed",
          "conclusion": "success",
          "head_sha": "d870681",
          "head_commit_message": "Add golden dataset Postgres mirror",
          "html_url": "https://github.com/rvsree/hrb_chatbot_v2/actions/runs/123456",
          "created_at": "2026-10-15T03:58:22Z"
        }
      ],
      "total_count": 47,
      "has_more": true,
      "error": null
    },
    {
      "workflow_file": "deploy.yml",
      "display_name": "Production Deploy",
      "runs": [],
      "total_count": 12,
      "has_more": true,
      "error": null
    }
  ],
  "error": null
}
```
A workflow's own `error` is a string (e.g. `"GITHUB_TOKEN not configured"`)
when that one GitHub-side call failed - its `runs` is then always `[]`,
never a partial list; `total_count`/`has_more` are `0`/`false` in that
case. The top-level `error` is reused for the same honest-degradation
pattern Phase 233 established for `frontend` on the pipeline endpoint
(`hrb_chatbot_ui` has no GitHub Actions workflow at all) - `workflows` is
then always `[]`. An unrecognized `application` value is a clean 422
(Pydantic enum validation), same as every other `Application` param.

## `application` on `GET /v1/admin/ci-status/pipeline` (Phase 233) — Finalized

New optional query param, `application: Application = "backend"` (default
preserves today's exact behavior - every existing caller that doesn't
pass it keeps working unchanged):

```
GET /v1/admin/ci-status/pipeline?application=ingestion_lambda&employee_id=...&full_name=...&role=admin
```

`Application` (new `StrEnum`, `common/enums.py`): `backend` (this
project's own `ci.yml`/`deploy.yml`, `rvsree/hrb_chatbot_v2`),
`ingestion_lambda` (`deploy-lambda.yml`, same repo as `backend` but a
different deployable, filtered out of `backend`'s own view and vice
versa - they used to be shown mixed together, confirmed confusing in
practice), `lms_mcp` (`deploy.yml`, `rvsree/hrb_lms_mcp` - a genuinely
separate repo; the existing `GITHUB_TOKEN` already has real read access
to it, live-verified before this was written), `frontend`
(`hrb_chatbot_ui` - **no GitHub Actions workflow exists for it at all**,
confirmed deliberately deferred per its own README, not a gap in this
feature).

For `frontend` specifically, the response reuses the *existing*
`PipelineStatusResponse.error` field rather than inventing a new "no
CI/CD" response shape - same honest-degradation pattern this field
already serves for a missing `GITHUB_TOKEN`:

```json
{
  "head_sha": "", "head_commit_message": "", "head_branch": "",
  "event": "", "actor_login": "", "runs": [], "eval_gate": null,
  "error": "hrb_chatbot_ui has no automated CI/CD yet - deployed manually (npm run build + aws s3 sync + CloudFront invalidation). See hrb_chatbot_ui/README.md."
}
```

An unrecognized `application` value is a clean 422 (Pydantic's own enum
validation at the API boundary), same reasoning every other `StrEnum`
request param in this project already follows - never a silent fallback
to `backend`.

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
