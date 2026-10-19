# Backlog

Things identified while building the RAG boilerplate (2026-09-07) that are
real gaps but explicitly **not blocking** current work. Move an item out of
this file into `docs/agent-reference/RAG-ROADMAP.md`'s phase list when it's actually picked
up, rather than marking it done in place here.

## Index by category (2026-10-15)

This file itself stays chronological, append-only, resolved items struck
through in place - that's deliberate (it's the real record of when
something was found, not a tidied-up taxonomy). This index is purely
additive navigation on top of that, grouped by theme so a topic can be
found without reading linearly. A `~~ ~~` prefix below means already
resolved; `❖` marks something still genuinely open.

**AWS / Deployment / CI-CD**
- [AWS deployment (Phase 10, in progress)](#aws-deployment-phase-10-in-progress) ❖
- [CI/CD & branch strategy](#cicd--branch-strategy-2026-09-08---see-docsagent-referencecicd-branching-strategymd) ❖
- [Phase 88 follow-ups: Lambda reserved concurrency skipped; AWS CLI default region is wrong](#phase-88-follow-ups-lambda-reserved-concurrency-skipped-aws-cli-default-region-is-wrong-2026-10-06) ❖
- [Phase 88 follow-ups round 2: no input validation; cold-start init-timeout](#phase-88-follow-ups-round-2-no-input-validation-on-the-async-path-cold-start-init-timeout-is-recurring-not-a-fluke-2026-10-06) ❖
- [CI (not Deploy) has been failing since at least Phase 86](#ci-not-deploy-has-been-failing-since-at-least-phase-86-undetected-until-2026-10-06) ❖
- [~~No CI/CD automation deploys the Lambda~~](#no-cicd-automation-deploys-the-lambda---resolved-2026-10-06-githubworkflowsdeploy-lambdayml)
- [`GET /health` with no query params silently checks the wrong backends](#get-health-with-no-query-params-silently-checks-the-wrong-backends-on-aws-found-phase-92-2026-10-06-pre-existing) ❖
- [Re-verified against live AWS/CI, 2026-10-07](#re-verified-against-live-awsci-2026-10-07---all-still-open-none-regressed) ❖
- [~~`HRB_LMS_MCP_URL` never configured on AWS~~](#hrb_lms_mcp_url-never-configured-on-aws---resolved-2026-10-07-phase-118)

**Access control / Security**
- [Access control](#access-control-phase-23-2026-09-15-identity-mechanism-replaced-phase-45-2026-09-20) ❖
- [API hardening](#api-hardening-same-shape-as-the-sibling-projects-nfr-backlog) ❖
- [Orphan config - flagged, not removed](#orphan-config---flagged-not-removed-touches-env-your-call) ❖

**MCP integration**
- [MCP integration & cross-project schema standardization](#mcp-integration--cross-project-schema-standardization-2026-09-22) ❖
- [MCP gaps found by reviewing a cohort-mate's M1 MCP submission](#mcp-gaps-found-by-reviewing-a-cohort-mates-m1-mcp-submission-2026-10-15) - 2 of 3 resolved 2026-10-15, 1 deliberately deferred

**Retrieval / Indexing / Data**
- [Data handling](#data-handling) ❖
- [Retrieval quality](#retrieval-quality-phase-20-found-2026-09-14-during-live-verification) ❖
- [Pinecone relevance threshold is a data-backed stop-gap](#pinecone-relevance-threshold-is-a-data-backed-stop-gap-not-a-final-calibration-phase-83-follow-up-2026-10-05) ❖
- [~~Chunk metadata's `filename` field reads `"unknown"` in Pinecone~~](#chunk-metadatas-filename-field-reads-unknown-in-pinecone---resolved-incidentally-phase-87-2026-10-06)
- [`chunking_strategy` is never persisted, only `chunk_size`/`chunk_overlap`](#chunking_strategy-is-never-persisted-only-chunk_sizechunk_overlap) ❖
- [Indexing failures are silent to the API caller](#indexing-failures-are-silent-to-the-api-caller-confirmed-phase-83-2026-10-05) ❖

**Multi-agentic-rag**
- [Multi-agentic-rag follow-ups](#multi-agentic-rag-follow-ups-confirmed-gaps-after-phase-64-2026-10-04) ❖
- [multi-agentic-rag has no per-domain-agent token usage, and no caching](#multi-agentic-rag-has-no-per-domain-agent-token-usage-and-no-caching) ❖ - referenced directly by Phase 184's Live Metrics fine-tune popover

**Caching / Performance**
- [Caching follow-ups](#caching-follow-ups-confirmed-gaps-after-phase-7778-2026-10-05) ❖

**Observability / Evaluation**
- [Observability](#observability) ❖
- [Guardrails / Evaluation / Observability follow-up](#guardrails--evaluation--observability-follow-up-phases-7-8-2026-09-22) ❖
- [Observability gap: genai-rag's own generation calls are invisible](#observability-gap-genai-rags-own-generation-calls-are-invisible-confirmed-phase-79-2026-10-05) ❖
- [Release gate follow-up](#release-gate-follow-up-confirmed-scope-after-phase-80-2026-10-05) ❖
- [Output guardrail false positive: "Roth" masked as a name](#output-guardrail-false-positive-roth-masked-as-a-name-found-2026-10-06) ❖ - referenced directly by Phase 184's Live Metrics fine-tune popover
- [Token cost (in dollars), not just token counts, in Explainability](#token-cost-in-dollars-not-just-token-counts-in-explainability) ❖ - same, re: cost_usd's deliberate gap

**LLM providers**
- [LLM providers](#llm-providers) ❖

**Schema / Conversation / Process**
- [Schema/data work completed](#schemadata-work-completed-2026-09-22-phases-50-51--oauth2-redesign) ❖
- [Conversation memory](#conversation-memory-phase-58-2026-09-25) ❖
- [Process](#process) ❖

**Cleanup / dead code**
- [Dead code](#dead-code-phase-22-found-2026-09-15-during-comment-cleanup) ❖
- [Cleanup done 2026-09-21](#cleanup-done-2026-09-21) ❖
- [Cleanup done 2026-09-07](#cleanup-done-2026-09-07) ❖
- [Codebase cleanup findings](#codebase-cleanup-findings-phase-93-2026-10-06) ❖
- [UI backend-gap findings](#ui-backend-gap-findings-phase-95-2026-10-06) ❖

**Candidate future work (proposed, not decided)**
- [unpaid-leave benefits-lapse notification](#candidate-future-use-case-unpaid-leave-benefits-lapse-notification-proposed-2026-10-02-not-decided)
- [Analytics domain agent needs historical data](#candidate-future-requirement-analytics-domain-agent-needs-historical-data-proposed-2026-10-03-sequencing-confirmed-2026-10-05)

## Observability

- ~~**No logging around individual backend calls.**~~ Fixed 2026-09-08.
  Confirmed by direct audit that no client logged anything around its
  actual network call - only around a missing API key at construction time,
  or a whole pipeline step finishing. Added
  `common/logging/call_logger.py`'s `log_backend_call()` (a context
  manager - service, operation, duration_ms, status on every line) and
  wired it into all four LLM clients' `ask`/`ask_with_tools`/
  `get_embeddings`, both vector store clients' `upsert`/`query`/`delete`,
  and both metadata store clients' five methods. Verified live, not just
  by reading the code - a real index call now shows
  `[openai] embeddings.create succeeded in 2184.2ms - {'model': ...,
  'text_count': 45}` in the log, where before there was nothing at all
  between "starting to index" and "finished indexing." Deliberately not a
  LangSmith integration - structured consistently enough that swapping one
  in later means changing this one function's body, not every call site.
- **No correlation/request id across log lines.** A single `POST
  /rag/documents/{id}/index` call now produces several log lines (create,
  get, embeddings.create, upsert, set_chunk_ids, update_status - see
  above) but nothing ties them together as "one request" if two requests
  happen to interleave in the logs. Worth adding once this app sees real
  concurrent traffic; not worth it yet at single-user local/demo scale.
- **No retrieval-vs-generation latency breakdown yet** - can't exist until
  Phase 6 (real retrieval + generation) is built. The logging added above
  already reports per-call duration for every LLM and vector-store call
  individually (visible in the logs today), which is what a future
  retrieval-vs-generation metric would be built from - see
  `docs/agent-reference/TESTING-GUIDE.md` for the A/B-comparison pattern that's the
  natural next step once there's a real answer-quality metric to compare.

## LLM providers

- ~~**Anthropic was unhealthy.**~~ Fixed 2026-09-07. Two independent bugs:
  `anthropic==0.40.0` (this project's original, unverified pin) has no
  `.models` attribute at all, confirmed by inspection - the deep health
  check always failed regardless of key validity. Bumped to `1.2.0`,
  matching the sibling project's working install. Separately, `.env`'s
  `ANTHROPIC_BASE_URL` carried an erroneous `/v1` suffix (Anthropic's own
  docstring says host-only, opposite of OpenAI) - corrected. Retested live:
  `healthy`, 11 models visible, `chat_model_available: true`.
- ~~**Bedrock as an LLM provider.**~~ Done 2026-09-07 (Phase 9). `BedrockChatClient`
  implementing `BaseLLMClient` via the `Converse` API, wired into `/health`
  alongside OpenAI/Anthropic/OpenRouter. Confirmed with the user: Bedrock
  *as one more provider option*, not adopting Bedrock AgentCore Runtime as
  the hosting platform. One thing surfaced worth remembering: the deep
  health check passed using an ambient personal AWS credential already on
  this machine (`~/.aws/credentials`, identity `BedrockAgentCore`,
  account `418884736369`), not anything this project configured - see
  Phase 9 in `docs/agent-reference/RAG-ROADMAP.md` for the full account/permissions finding.
  `ask_with_tools()`'s tool-format conversion is still untested against a
  real tool call.
- **Tavily health check.** `common/clients/web_client/tavily_client.py`
  exists and is wired into `client_gateway.py`, but nothing calls its
  `health_check()` from `/health` - unlike the three LLM providers, it isn't
  an LLM so it doesn't belong under `check_llm()`. Needs its own
  `check_web_search()` (or similar) folded into `check_all_backend_services()`.

## AWS deployment (Phase 10, in progress)

- **Metadata store had no config switch - fixed.** `documents_service.py`,
  `vector_indexer.py`, and `routes_documents.py` all called
  `db_gateway.sqlite()` directly, hardcoded, unlike the vector store's
  `RAG_VECTOR_DB`. Surfaced by deploying to App Runner (no persistent
  local disk) rather than by reading the code. Added
  `db_gateway.metadata_store()` reading a new `RAG_METADATA_STORE` setting
  (`sqlite` default - local dev unchanged; `postgres` for anywhere without
  persistent disk) and switched all three call sites. Done 2026-09-07.
- **Deployed service is temporarily running `RAG_METADATA_STORE=sqlite`
  anyway** - the ephemeral option - because Neon (the chosen hosted
  Postgres) doesn't exist yet, and App Runner refuses to start a service
  whose `RuntimeEnvironmentSecrets` reference a not-yet-existing secret
  ARN. `RAG_VECTOR_DB=pinecone` is already live and persistent. Finish this
  once Neon exists: 5 more Secrets Manager entries
  (`hrb-chatbot/POSTGRES_DB_HOST/PORT/NAME/USER/PASSWORD`), then
  `apprunner.update_service` flipping the env var and adding those secrets
  - config-only, no rebuild. See Phase 10 in `docs/agent-reference/RAG-ROADMAP.md` for the
  exact resource ARNs.
- **AWS CLI upgrade stalled, not resolved.** `winget upgrade --id
  Amazon.AWSCLI` (2.0.30 → 2.36.40) got stuck at "Starting package
  install..." with no further progress - almost certainly a UAC elevation
  prompt this non-interactive shell can't answer. Doesn't block anything -
  deployment was scripted via `boto3` instead - but the CLI itself is still
  the old version. Needs a human to run the MSI installer directly and
  click through the UAC prompt.
- **Blocked on the user:** a free Neon Postgres project/database (neon.tech)
  - external signup, not something Claude Code can do on the user's behalf.

## CI/CD & branch strategy (2026-09-08) - see `docs/agent-reference/CICD-BRANCHING-STRATEGY.md`

- **pip-audit triage.** Wired into `ci.yml` as `continue-on-error: true` -
  report-only, not blocking. A real run turned up dozens of pre-existing
  CVEs across `langchain*`/`chromadb`/`starlette`/`pillow`, pinned for
  compatibility long before this scan existed. Needs someone to go
  through the list, upgrade what's safely upgradable (`chromadb` needs
  care - see the Python-3.13 fragility note in `README.md`'s
  Prerequisites), and explicitly accept-with-comment whatever can't move
  yet, before flipping this gate to blocking. See
  `docs/agent-reference/CICD-BRANCHING-STRATEGY.md`'s security-gate section for the exact
  steps.
- **No staging deployment target.** `develop` runs the full test gate but
  deploys nowhere - only `master` triggers `deploy.yml`, against the one
  existing App Runner service. Adding a second, always-on App Runner
  service for `develop` would give a real pre-prod environment, at the
  cost of a second continuous AWS bill. Deliberately not stood up without
  asking - see `docs/agent-reference/CICD-BRANCHING-STRATEGY.md`'s "Deployment targets"
  section for the two options laid out.
- **Docker images are tagged `:latest` only.** No way to redeploy a known-
  good previous image if a new one passes App Runner's own health check
  but is still broken in some way that check can't see - `:latest` is
  overwritten every deploy. Recommended fix: tag every build with
  `:${{ github.sha }}` too. Not implemented yet, deliberately - `deploy.yml`'s
  build command has caused three real, hard-to-diagnose failures before
  (see `AWS-DEVOPS-RUNBOOK.md`), so this needs its own isolated test
  before going anywhere near that line again.
- ~~**GitHub default branch not set to `master`.**~~ Resolved - confirmed
  live via `gh repo view` (2026-10-06) that the default branch is
  `master`. **Still open**: no branch protection rules exist (nothing
  requires CI to pass, or a review, before a merge into
  `develop`/`master`).
- **`eval-gate.yml`'s results vanish when it actually runs via GitHub
  Actions.** Found 2026-10-16 while answering a user question about CI/CD
  status persistence (unrelated to the question - flagged here, not
  fixed). The workflow spins up its own disposable `postgres:16` service
  container inside the runner (`POSTGRES_DB_HOST: localhost`, meaning
  *inside that ephemeral VM*, not this project's real Neon database).
  `scripts/run_release_gate.py`'s `record_run()` call (Phase 182) writes
  there successfully, but the row is destroyed the instant the job ends -
  it never reaches Neon or any developer's local Postgres. The 40
  `eval_runs` rows that exist in both local dev and production today got
  there because someone ran the script by hand with `.env` pointed at
  each target, never through this workflow. If `eval-gate.yml` is ever
  triggered for real via `workflow_dispatch` - its entire purpose - its
  result currently disappears. Fix would be pointing this workflow's own
  `POSTGRES_DB_*` at Neon via GitHub Actions secrets (same pattern
  `deploy.yml` already uses for its AWS secrets), traded off against the
  ingested-KB-and-cache state in that job needing a real schema to write
  into that isn't shared with production's own live data - not a trivial
  swap, needs its own decision before changing.

## API hardening (same shape as the sibling project's NFR backlog)

- ~~**Upload constraints.**~~ Done in Phase 2 - PDF-only and 20MB-max
  validation in `services/documents_service.py`, verified with a real
  rejected file. Still no per-batch count limit (nothing stops a 500-file
  batch) - worth deciding if it ever matters at this project's scale.
- **Retry / circuit breaker.** No resilience exists for the OpenAI/Anthropic/
  OpenRouter calls or the ChromaDB calls. Same gap as the sibling project;
  same recommendation - a bounded, transient-failures-only retry at the
  client layer, a circuit breaker as a separate later decision. **Not the
  same thing as rate limiting below** - retry/circuit-breaker is about
  *this app* handling a flaky backend gracefully; rate limiting is about
  protecting this app *from* too many callers.
- ~~**Rate limiting.**~~ Done 2026-09-08 -
  `common/rate_limiting/rate_limiter.py`, a fixed-window in-memory limiter
  applied via `Depends(enforce_rate_limit)` to every endpoint that writes
  state or spends money (upload, index, query). Finally gives
  `APP_RATE_LIMITING`/`APP_RATE_LIMIT_REQUESTS`/`APP_RATE_LIMIT_DURATION`
  a real job - they'd been sitting in `.env` unread since the first
  commit (see the "Orphan config" section below, now out of date on this
  point). Single-process, in-memory only - resets on redeploy, and would
  need a real shared store (Redis) the moment this app scales to more
  than one instance - documented in the module's own docstring, not a
  surprise to discover later.
- **Auth** - still nothing. Genuinely deferred, not overlooked: this is a
  single-user personal project today, and every other item on this list
  (rate limiting, idempotency, versioning) was worth doing without waiting
  for auth to exist first. Worth a real decision before this project ever
  has more than one real user.
- ~~**Versioning.**~~ Done 2026-09-08 - every business endpoint now lives
  under `/v1` (`main.py`'s `include_router(..., prefix="/v1")`).
  `GET /health` deliberately stays unversioned - a liveness/readiness
  probe needs one stable path regardless of API version, matching how
  AWS/Kubernetes health checks are conventionally exempted from an app's
  own versioning scheme.
- **Idempotency.** Done 2026-09-08, **removed 2026-09-13** - the
  `Idempotency-Key` header cache and the separate content-hash
  duplicate-upload check were both deliberately dropped (user decision,
  during the LangChain/LlamaIndex pipeline rewrite on
  `feature-langchain-rag-pipeline`) to simplify the request path while
  that rewrite is in progress. Back on the backlog as a real gap, not
  struck through - a real shared store (Redis) is the planned
  re-implementation once the pipeline rewrite is stable, see
  `docs/agent-reference/RAG-ROADMAP.md`'s phase entry.
- ~~**No app-level exception handler / possible info leak in error
  responses.**~~ Fixed 2026-09-08. An audit found two real `json_error(...)`
  calls that interpolated a caught exception's raw `str(error)` directly
  into the client-facing message
  (`routes_documents.py`'s index endpoint, `retrieve_document.py`'s query
  endpoint) - a genuine info-leak risk (a stack-trace fragment, an
  internal path, anything a library's own exception `__str__` happens to
  include). Both now log the full detail server-side and return a
  generic, safe message. `main.py` also gained a global
  `@app.exception_handler(Exception)` as a last-resort safety net for
  anything no individual route handler catches - confirmed by audit that
  none existed before this.
- ~~**No pre-flight backend-readiness check before spending money.**~~
  Fixed 2026-09-08 for the one endpoint that has a real backend
  dependency today - `index_document()` now checks (shallow, free -
  `deep=False`) that the LLM provider and vector store are at least
  configured *before* attempting the real chunk/embed/index call,
  returning a clean 503 instead of letting a config problem surface as a
  raw exception deep in the pipeline. **Deliberately not applied to the
  query endpoint yet** - it's still a pure stub with no real backend call
  to check readiness for, and gating it behind a real API key would break
  in CI, which runs with no secrets at all (see
  `docs/agent-reference/AWS-DEVOPS-RUNBOOK.md`). Add the same check there once Phase 6
  makes a real call.
- **Typed request/response/error contracts on every endpoint**, not just the
  ones built carefully - see `docs/agent-reference/CODING-STANDARDS.md` for the standard
  this is meant to hold to going forward. String fields on request models
  now also carry both a `min_length` and a `max_length` where the
  distinction matters (`RagQueryRequest.query`, `IndexRequest.vector_db`/
  `embedding_model`) - a structural, size-based guardrail, not the
  content-based (prompt-injection, PII) guardrails that remain Phase 7's
  hand-written work.

## Access control (Phase 23, 2026-09-15; identity mechanism replaced Phase 45, 2026-09-20)

- **Real OAuth still not built.** `api/gateway/rbac.py`'s `require_role()`
  reads a caller-supplied `user_profile` sub-object straight from the JSON
  request body (every endpoint, including `GET`/`DELETE`) as-is - a
  deliberate placeholder, trivially spoofable, not a security control
  (self-asserted in the same request it gates - see
  `docs/agent-reference/endpoint-request-response-contracts.md`).
  `common/clients/auth_client/oauth_client.py` is an empty placeholder for
  the real integration.
- ~~**Uploader identity isn't persisted.**~~ **Done, Phase 45:**
  `DocumentRecord`/`DocumentUploadResult` now carry `uploaded_by`
  (`documents_service.create_document()` threads the caller's
  `employee_id` through to a new DB column); `DocumentDeleteResponse`/
  `DocumentDeleteAllResponse` carry `deleted_by` the same way.
- **Rate limiting is still IP-keyed**, not by the identity the gateway now
  resolves - `common/rate_limiting/rate_limiter.py` predates Phase 23.
  Switching the key to `employee_id` (falling back to IP when absent)
  would rate-limit per person instead of per network address.
- **Retrieval is uniform across all three roles** - no per-document
  visibility differences (e.g. a manager-only document) - deferred per
  explicit request when this phase was scoped. Would build on the same
  chunk metadata (`doc_category`/`department`) Phase 19 already added.

## Dead code (Phase 22, found 2026-09-15 during comment cleanup)

- **`PineconeClient.query()`/`.upsert()` and `ChromaClient`'s equivalents
  look unused in the real pipeline.** Indexing (`vector_indexer.py`) and
  retrieval (`retriever.py`) both go through LangChain's own vector store
  objects (`langchain_vector_store.py`'s `get_vector_store()`) since Phase
  17/Phase 4 - confirmed by grepping the whole `src/` tree for any other
  caller of `.query(`/`.upsert(` and finding none. `delete()`/
  `update_metadata()` are still real (used directly by
  `documents_service.py`/`vector_indexer.py`'s supersede-flip), so this
  isn't the whole client, just these two methods (and their
  `BaseVectorDBClient` ABC requirement). Worth confirming and removing in
  a dedicated phase, not fixed here - this was noticed while trimming an
  unrelated docstring, not something this task set out to check.

## Retrieval quality (Phase 20, found 2026-09-14 during live verification)

- **RESOLVED by Phase 230 (2026-10-19).** `_parse_self_query_filter()`
  now resolves the LLM's parsed `doc_description` guess to the closest
  real indexed value (substring containment, with a `difflib` fuzzy
  fallback for typos) before the filter is applied - the "401k" vs.
  "401(k) Savings Plan" case below now matches. See
  `docs/agent-reference/RAG-ROADMAP.md`'s Phase 230 entry for the fix detail;
  left below for the historical record of the original failure.
- **Self-Query's `doc_description` filter only matches exact strings,
  but `doc_description` is deliberately free text** (Phase 19's own
  design - "not a fixed enum, real documents vary too much to hardcode a
  closed list"). Confirmed live: querying "what's my 401k vesting
  schedule" reliably makes Self-Query's LLM parse
  `doc_description="401k"` (it's the example in
  `ai/rag_pipeline/query_retrieval/retriever.py`'s own
  `METADATA_FIELD_INFO`), but a real indexed document's actual extracted
  value was `"401(k) Savings Plan"` - an exact-string mismatch that
  correctly-but-uselessly returns zero chunks, even though clearly
  relevant chunks exist. `doc_category` (extraction picks from a short fixed
  list: policy/regulatory/investment/benefits/other) doesn't have this
  problem - confirmed by isolating it, `doc_category=benefits` alone matched
  real chunks every time. Options for later: a `contain`/fuzzy comparator
  instead of `$eq` for `doc_description` specifically, or re-scoping it
  toward a smaller controlled set the way `doc_category` already is. See
  `docs/agent-reference/RAG-ROADMAP.md`'s Phase 20 entry for the full verification
  (field names there are historical - `doc_type`/`doc_classification`,
  renamed to `doc_category`/`doc_description` in Phase 57).

## Data handling

- **PII / sensitive data.** The knowledge base is real HR benefits
  documents. No conscious decision has been made yet about what's logged
  (query text? retrieved chunk contents?) or how long uploaded files and
  their embeddings are retained.
- **No `.env.example`.** Only a real `.env` exists in this repo - there's no
  template a new contributor (or a fresh clone) could copy and fill in
  without seeing real values. Worth creating one, redacted, the way the
  sibling project's `.env.example` documents every setting name with a
  comment on what reads it.

## Cleanup done 2026-09-21

- Removed `resources/db_scripts/` entirely (postgres/ and sqlite/, 13
  files) - described an unrelated, never-built project design (`coco`
  database, `chat_sessions`/`policy_versions`/`leave_rules`/`agent_tasks`/
  `user_feedback` tables, `src/app/common/db_scripts/...` paths that don't
  exist in this repo). Zero overlap with the real schema (`documents`/
  `chunks`, built via `CREATE TABLE IF NOT EXISTS` in `sqlite_client.py`/
  `postgres_client.py`) and zero references anywhere in `src/` or current
  docs - orphaned scaffolding from a different project, not this one's.
- Removed `README_TEST.md` - stale and factually wrong (old `/v1/rag/...`
  prefix, removed header-based auth from Phase 23, a "Phase 6 stub"
  reference long superseded). Fully replaced by `docs/agent-reference/TESTING-GUIDE.md`
  (pytest) and `postman/hrb_chatbot.postman_collection.json` (manual/
  curl-style testing), which the file's own last line already pointed to.
- Removed `postman/hrb_chatbot.postman_collection_v1.json` - a stale
  duplicate collection using a defunct `/index/v1/rag/documents` routing
  scheme, confusing to have alongside the real, actively-maintained
  collection.
- Removed `resources/kb_docs/text/indexing_batch_payload.json` - a sample
  payload for an API shape (`namespace`/`title`/`tags` fields) that was
  never this project's actual contract.
- Removed `src/hrb_chatbot/services/rag_service.py` - a literal one-line
  pass-through (`return await pipeline.answer_query(params)`) with no
  logic of its own, unlike `services/documents_service.py` (real logic:
  content-hash dedup, supersedes handling, file validation), which keeps
  its service layer. `api/rag/retrieve_document.py` now calls
  `ai/rag_pipeline/pipeline.py` directly - see `CLAUDE.md`'s architecture
  section for the updated request flow.
- **Not removed, flagged for the user's own call:** `infra/AgentCore
  Installation and Run Guide.md` (real forward-looking AWS Bedrock
  AgentCore deployment notes, not obviously stale) and
  `resources/kb_docs/text/*.txt` / `resources/kb_docs/word/*.docx`
  (real alternate-format copies of the 6 source PDFs, unreferenced by any
  code but plausibly intentional reference material, not junk like the
  payload JSON above).

## Cleanup done 2026-09-07

- Removed 6 Microsoft Word lock files (`~$MC ....docx`, 162 bytes each,
  under `resources/kb_docs/word/`) - temp files Word creates while a
  document is open, never real content, should never have been committed.
- Removed `resources/postgres/` - a byte-for-byte duplicate of
  `resources/db_scripts/postgres/` (confirmed with `diff -rq`, zero
  differences). Kept the `db_scripts/postgres` copy, matching the sibling
  `db_scripts/sqlite/` naming already in use.

## Orphan config - flagged, not removed (touches `.env`, your call)

Checked every `.env` variable against the actual source - these are
declared but read by nothing:

- `APP_BASE_URL`, `APP_APP_NAME`, `APP_ENVIRONMENT`, `APP_DEBUG`,
  `APP_CSRF_PROTECTION` - still orphaned, tracked above as
  "`app_settings.py`/`app_gateway.py` don't exist yet."
- ~~`APP_RATE_LIMITING`, `APP_RATE_LIMIT_REQUESTS`,
  `APP_RATE_LIMIT_DURATION`~~ - no longer orphaned as of 2026-09-08, now
  read by `common/rate_limiting/rate_limiter.py` - see the "Rate limiting"
  entry above.
- `OPENAI_RAG_MODEL` - not read anywhere; only `OPENAI_CHAT_MODEL` and
  `OPENAI_EMBED_MODEL` are.
- `ANTHROPIC_LLM_ENABLED` - not read anywhere; nothing gates on it.
- `TAVILY_SEARCH_ENABLED`, `TAVILY_MAX_RESULTS`, `TAVILY_SEARCH_DEPTH`,
  `TAVILY_INCLUDE_ANSWER` - `TavilyClient.search()` takes these as function
  parameters with hardcoded defaults, not as env-driven settings, so these
  four `.env` lines currently do nothing.

Also noted, not touched: `common/logging/log_helper.py` still has its own
broken import (`agent_log_tags` module doesn't exist) - this was an
explicit earlier decision to keep as-is for later, not a new finding.

## Guardrails / Evaluation / Observability follow-up (Phases 7-8, 2026-09-22)

- **3 of 6 KB documents not indexed.** 401(k), Unpaid TimeOff, and Sedgwick
  Unpaid Timeoff are missing from the vector store - leftover from the
  earlier live-DB-deletion incident, only 3 PDFs got re-uploaded
  afterward. Found via the DeepEval harness scoring 0.00 on a 401(k)
  question. Re-upload is simple, not done - your call on priority.
- ~~**DeepEval CI gate not wired up.**~~ Resolved, Phase 80 (2026-10-05):
  `eval-gate.yml`/`scripts/run_release_gate.py` wire `get_release_decision()`
  into a real, manually-triggered CI gate. See the "Release gate follow-up"
  section below for genai-rag-only scope and what's still open.
- **PII in a query gets blocked, not masked.** `self check input`'s LLM
  judgment flags SSN-like content before the dedicated `mask sensitive
  data on input` rail gets a turn (rails run in sequence). Defensible
  (safer), but different from "mask, don't block" - flagged for a
  decision if the stricter behavior isn't wanted.
- **Gate 2 (document-level ACL) and Gate 4 (context grading) still
  unbuilt.** Both explicitly out of scope for Phase 7 - real gaps in the
  six-gate framework, not started.
- **LangSmith stays off**, by design - re-enable (`.env`'s
  `LANGSMITH_ENABLED`) specifically when single/multi-agentic-rag work
  begins, per the agreed trace-budget cadence.

## MCP integration & cross-project schema standardization (2026-09-22)

- **`hrb_lms_mcp` integration done as a prototype - Phase 49.** Real,
  running FastMCP server, now actually called live from this project via
  `ai/rag_pipeline/tools/mcp_tools/`, manual keyword routing (not ReAct
  yet) in `pipeline.answer_query()`. See Phase 49 in this file for the
  full spec, the two real dependency bugs found (`mcp` version pin,
  `python-multipart` bump), and the live verification.
- **A third sibling project found**: `hrb_emp_assist`
  (`C:\workspace\poc\2026\hrb_emp_assist`) is the real "Status: Production"
  MCP client `hrb_lms_mcp`'s own README names as its primary consumer -
  Python/FastAPI, ReAct Multi-Agent, MCP Integration already built,
  version 2.0. This looks like the mature version of what `hrb_chatbot_v2`
  is a from-scratch educational rebuild of. Worth treating as a reference
  for "how was this actually built the first time" during future
  ReAct/agentic-rag phases, not just for schema comparison.
- **`hrb_emp_assist`'s missing DDL/DML *files* don't mean missing schema -
  corrected 2026-09-22 after actually querying the live Postgres server**,
  not just the file tree. `coco_schema_extensions.sql`/`coco_schema_dml.sql`/
  `coco_schema_missing_tables.sql`/`coco_schema_missing_tables_dml.sql`
  genuinely don't exist on disk anywhere in the project (confirmed via
  file search) - but the database objects they were meant to create
  **do exist and are live**: `disability_rules`, `retirement_rules`,
  `healthcare_rules`, `tuition_rules`, and the rest of the 9 "missing"
  tables are real tables in the `coco` Postgres database today. The real
  gap is narrower than first reported: those 9 tables are all at **0
  rows** - the DDL ran (or was run manually) at some point, the DML
  (the actual rules data) never landed, or was cleared. `hr_chatbot_schema_hitl.sql`
  (the 5th script) does exist on disk. Not touched - that project's own
  gap to close, flagged here only because it surfaced while checking.
- **The "shared database" design is not abandoned - it's live.** Corrected
  2026-09-22: the local Postgres server hosts 4 real databases -
  `hrb_chatbot_v2` (this project's own, 1 table), `hr_chatbot`, `coco`,
  and `postgres`. `hr_chatbot` has a `hrb_emp_lms` schema (61 employees -
  the 58 original plus the 3 this session added) and a `public` schema
  with real chat history (1,500 rows), sessions (109), HITL escalations
  (66) - `hrb_lms_mcp` and `hrb_emp_assist`/`hrb_copilot` are already
  sharing this one physical database today, split by schema, confirmed by
  querying it directly, not by reading a setup script's comments. Two
  more schemas found this way, undocumented anywhere read so far:
  `app_tracking` (mcp_server_registry/mcp_tools_registry/agent_registry/
  retry_queue - real MCP/agent observability tables, all empty) and
  `state_mngmt` (agent_entities/agent_ltm, has real data) - worth knowing
  about before designing this project's own future agent/memory work, to
  avoid reinventing a schema that already exists next door.
- **OAuth2 extended for app-to-app, alongside the existing human-to-app
  design** (`resources/db_scripts/oauth/oauth_schema_ddl.sql`): a new
  `client_scopes` table gives each `oauth_clients` row (a registered
  caller, not a person) a scoped allowlist - e.g. this project's own
  `hrb-lms-mcp-client` gets `mcp:get_leave_balance`/`mcp:get_leave_history`
  only, read-only until deliberately widened. `hrb_lms_mcp`'s own auth
  today is a single optional `X-API-Key` (not real OAuth2) - this table is
  this project's own record of who's allowed to call out, independent of
  how `hrb_lms_mcp` checks it on its side. Design only, not wired into
  actual token-issuing code yet, same status as the human-to-app half.
- **Known gap, not closed**: MCP-routed answers (Phase 49) skip the output
  guardrail (`check_output()`) - written for LLM-generated text, and
  running it would add a full extra LLM call to a path whose entire point
  is avoiding one. Worth a deliberate decision once real PII fields show
  up in an MCP tool's response, not assumed safe forever.
- **`ai/agents/` and `ai/rag_pipeline/tools/`** (both previously empty
  placeholders) - `tools/mcp_tools/` is no longer empty (Phase 49);
  `ai/agents/` still is, reserved for the actual ReAct orchestration that
  replaces Phase 49's keyword-matching stand-in.
- **Employee ID convention standardized to match `hrb_lms_mcp`'s real data**,
  2026-09-22: this project's `E00001`-style test identities (golden
  dataset era) are now `EMP0xx`/`MGR0xx`, matching `hrb_lms_mcp`'s real
  `employees` table exactly (`EMP001`-`EMP050`, `MGR001`-`MGR005`). Updated
  everywhere: `resources/db_scripts/oauth/*.sql`, 3 test files, Postman,
  README, `docs/agent-reference/endpoint-request-response-contracts.md`. Full suite still
  151 passing after the rename.
- **`hrb_lms_mcp`'s own sample data has an internal inconsistency** -
  3 test employees (`emp_12345`/`emp_67890`/`emp_11111`, lowercase,
  different shape) alongside the dominant `EMP0xx` convention, per that
  file's own comment tied to `tests/test_mcp_tools_integration.py`.
  Flagged, not touched - that project's own call, and the referencing test
  file wasn't verified safe to rename against.
- **A real cross-database FK limitation found while standardizing**: this
  project's OAuth sketch and `hrb_lms_mcp`'s employees table are different
  Postgres databases - a `manager_id` can't literally foreign-key across
  that boundary. `oauth_sample_data_dml.sql`'s new rows (`EMP051`/`EMP052`/
  `MGR006`, added to both projects' sample data for a shared identity)
  leave `manager_id` `NULL` here for that reason - only `hrb_lms_mcp`'s own
  copy of the same rows has a real, resolvable `manager_id`.
- **Superseded, 2026-09-22 (same day, later in the session)**: the note
  above about the shared-database direction "looking abandoned" was wrong
  and is now moot either way - see the next section. This project's own
  copies of `hr_chatbot_schema*.sql` are still deleted, but that no longer
  matters: Phase 50's OAuth2 schema and MCP registry both write directly
  into the real, live `hr_chatbot` database now, not a planned one.
- **RESOLVED by Phase 231 (2026-10-19).** Document ACL is built - both
  role-gated and department-gated (user's explicit choice, not one or the
  other). See `docs/agent-reference/RAG-ROADMAP.md`'s Phase 231 entry.

## Schema/data work completed, 2026-09-22 (Phases 50-51 + OAuth2 redesign)

Five tasks, done in dependency order, each tested/verified live against
the real `hr_chatbot` Postgres database and the real `hrb_lms_mcp` server -
not simulated:

1. **DB model diagram** (`docs/dev-reference/db-model-overview.html`) - built first, to
   design against, then kept accurate to the final state below.
2. **OAuth2 schema redesigned** to reuse real data instead of duplicating
   it: new `hrb_chatbot_v2_auth` Postgres schema, living inside the
   shared `hr_chatbot` database (not a new database, not this project's
   own). `employee_roles.employee_id` is a real FK into
   `hrb_emp_lms.employees` - Postgres schemas in the same database CAN
   foreign-key across each other (unlike across separate databases, the
   real limitation found last time this was attempted). Applied for
   real: `EMP051`/`EMP052`/`MGR006` now have real roles
   (`hr_support`/`employee`/`manager`) in the live database, verified via
   a real join query, not just the SQL files on disk.
3. **MCP registry at startup (Phase 50)** - reuses `hr_chatbot.app_tracking`'s
   existing `mcp_server_registry`/`mcp_tools_registry`/`mcp_server_connections`
   tables (found already existing before this session, previously all
   empty - the exact pattern from the user's own v1 project,
   `hrb_emp_assist`). New `common/clients/db_client/mcp_registry_client.py`
   + `common/observability/mcp_registry_startup.py`, wired into `main.py`'s
   `lifespan`. Verified live: all 6 real `hrb_lms_mcp` tools registered on
   a real startup run. **Three real CHECK-constraint violations found and
   fixed live** (existing tables restrict `connection_type`/`status`/
   `connection_status` to fixed value lists not documented anywhere,
   only discoverable by inserting) - see Phase 50's detail in
   `docs/agent-reference/RAG-ROADMAP.md`.
4. **NFR-specific golden dataset (Phase 51)** -
   `resources/golden_dataset/nfr_golden_dataset.json` (14 cases: prompt
   injection, PII, jailbreak, toxic content, and 4 false-positive
   controls) + `ai/rag_pipeline/evaluations/nfr_golden_dataset_harness.py`,
   run live against the real `check_input()` guardrail. **Two real
   findings, not assumptions**: email/credit-card PII gets *masked*, not
   blocked, unlike SSN (dataset corrected to match verified behavior);
   and a genuine false-positive bug - `EMP052` gets misclassified as
   `<PERSON>` by Presidio's NER recognizer and masked. Kept as a
   documented `known_issue` in the dataset itself, not fixed (out of this
   task's scope) and not hidden by changing the expected outcome to match
   the bug.
5. **Main golden dataset (`golden_dataset.json`) checked, needs no
   update** - zero `employee_id`/identity references in it; it's purely
   query-to-answer pairs about document content, fully decoupled from who's
   asking. Confirmed by direct search, not assumed.

Full suite: 161 passed (2 new unit tests for the registry). Both
eval-marked harnesses (`pytest -m eval`): 2 passed live, including the
new NFR one, real LLM/guardrail calls both times.

**Follow-up, same day: all 3 foreign keys removed from `hrb_chatbot_v2_auth`**
(`employee_roles.employee_id` -> `hrb_emp_lms.employees`, `employee_roles.role_id`
-> `roles`, `client_scopes.client_id` -> `oauth_clients`) - user-directed,
real-world reasoning: a DB-enforced FK across schemas owned by different
services is the exact coupling the "shared database" pattern gets
criticized for (blocks independent migration/sharding, a schema change
on either side can silently break the other). Dropped live
(`ALTER TABLE ... DROP CONSTRAINT`, verified the app-level JOIN still
works identically), `oauth_schema_ddl.sql` updated to match, and
`docs/dev-reference/db-model-overview.html` updated with the reasoning. The 2 FKs
purely within this project's own schema were dropped too, for
consistency, not because they had the same coupling problem - simpler is
the better teaching example for a capstone project. **Not touched**: the
real FK on the shared `app_tracking.mcp_server_connections.server_id ->
mcp_server_registry.server_id` (Phase 50) - those tables are reused
infrastructure this project doesn't own, not this project's call to
redesign.

**Follow-up, same day: schema-per-service bounded-context isolation,
user-directed.** `hrb_chatbot_v2_auth` renamed to `hrb_chatbot_v2_core`
(a more accurate name - it's this project's own identity/RBAC data, not
just auth), and a new, deliberately empty `hrb_chatbot_v2_sessions`
schema created for future conversation/session-state tables - created
ahead of any table, not retrofitted after one lands somewhere less
isolated. Three bounded-context schemas in the one shared `hr_chatbot`
database: `hrb_chatbot_v2_core` (this project, identity),
`hrb_chatbot_v2_sessions` (this project, reserved for session state),
`hrb_emp_lms` (hrb_lms_mcp's own, untouched) - each schema owned by
exactly one service, matching DDD bounded-context conventions even while
physically sharing one Postgres instance. Applied live (`ALTER SCHEMA
RENAME`/`CREATE SCHEMA`), verified data/queries still work identically,
`oauth_schema_ddl.sql`/`oauth_sample_data_dml.sql`/`docs/dev-reference/db-model-overview.html`
all updated to match.

**Real finding while answering how the MCP auth key is configured**:
`hrb_lms_mcp`'s own `.env` has a real, non-empty `API_KEY` set, and its
README documents `X-API-Key` header auth as "optional, configurable" -
but the actual current source code has **zero enforcement of it
anywhere** (checked the whole `src/` tree; only a stale compiled `.pyc`
from an apparently-deleted `mcp_controller.py` still references the
header). The key is configured but dead - not wired into any request
path today. `hrb_chatbot_v2`'s own `HRB_LMS_MCP_API_KEY` is empty in
`.env`, so this project's real calls send no `X-API-Key` header at all,
which is why Phase 49/50's live calls worked without one. Not this
project's bug to fix (a different repo), flagged here since it's
directly relevant to "is this call actually authenticated" - it isn't.

**Superseded, same day (Phase 53): the dead X-API-Key gap above is
closed for real.** Real OAuth2 client-credentials now runs both sides -
`hrb_lms_mcp` issues and enforces signed JWTs (`POST /oauth/token`,
`BearerAuthMiddleware` on `/mcp`), `hrb_chatbot_v2` acquires and caches
one. Verified live both directions: no token -> real 401, wrong secret ->
real 401, valid credentials -> real signed JWT -> real authenticated
call succeeds. Full detail, including the two real repos' worth of new
files, in `docs/agent-reference/RAG-ROADMAP.md`'s Phase 53.

**Planned, not started: Phase 52, an analytics MCP server** for
aggregate/historical HR questions (leave-utilization trends, attrition,
benefits-cost trends) that Phase 49's per-employee tools can't answer -
researched (WebSearch) against real 2026 NL2SQL-MCP patterns from
Oracle/Microsoft/Google Cloud. Parking-lot spec only in
`docs/agent-reference/RAG-ROADMAP.md` - real spec work deferred until ReAct
orchestration exists to route to it, per the user's own sequencing.

## Conversation memory (Phase 58, 2026-09-25)

- **Move conversation history off in-process memory onto a real cache
  DB.** `ai/pre_processing/conversation_memory.py`'s `_CONVERSATIONS` dict
  is deliberately in-memory for now (user-directed: "in-memory for now,
  will plan to expand this to cache db later") - lost on every restart,
  and doesn't survive across multiple worker processes if this app is
  ever scaled beyond one. A real move (Redis or similar) would swap the
  module's internals only; `load_history()`/`save_turn()`/
  `new_conversation_id()`'s signatures are already the only thing
  `pipeline.py`/`orchestration_agent.py` depend on.
- **No API to list/inspect/clear a conversation's history.** A caller can
  only add to it via a query; nothing lets them see what's stored or
  reset it mid-conversation. Not asked for yet.
- **MCP-routed answers (leave balance/history) aren't added to
  conversation history**, even when `enable_conversation_memory` is on -
  `pipeline.py`'s `try_route_to_mcp()` early-return bypasses
  `generate_answer()` entirely, which is the only place a turn gets
  saved. A follow-up referencing an MCP-answered turn won't have it in
  context. See Phase 58's own spec in `docs/agent-reference/RAG-ROADMAP.md`.

## Process

- ~~**No test suite configured.**~~ Added 2026-09-08 - `pytest` +
  `pytest-asyncio` (`requirements-dev.txt`), 20 tests across chunking,
  embedding, indexing (the insert/update/stale-chunk-cleanup logic
  specifically, the highest-value case), the RAG query stub's contract,
  and a reference A/B-comparison pattern - see `docs/agent-reference/TESTING-GUIDE.md` for
  what's covered and why, and the fake-based pattern
  (`tests/conftest.py`) to extend once the hand-written pipeline exists.
  **Linter/formatter still not configured** - `ruff` is set up for the
  sibling `w1_agentic_foundations` project but not this one; still worth a
  conscious decision, same "don't let this become `crewai_app_demo`"
  reasoning as before.
- ~~**Dockerfile is unverified.**~~ Verified 2026-09-07, once Docker Desktop
  was actually running: build, run, and `HEALTHCHECK` all confirmed. Two
  real bugs were caught and fixed in the process, not just "it built":
  `python-magic-bin` (Windows-only) doesn't install on Linux - swapped for
  `python-magic` + `libmagic1` in the image; and `/srv` (and therefore the
  relative `data/` path ChromaDB/SQLite/uploads all write under) wasn't
  writable by the non-root container user - fixed by chowning `data/`
  specifically, not the whole image, before switching to that user.
- **Spec-Driven Development (SDD) adopted 2026-09-14** - see `CLAUDE.md`'s
  SDD section. Every phase picked up from here on needs a written, reviewed
  spec (a `Spec:` sub-list in its `docs/agent-reference/RAG-ROADMAP.md` bullet, via
  `/spec-new`) before implementation starts - this backlog is where planned
  work is tracked, but an item moving from here into an active phase should
  get a spec first, not go straight to code. No new `specs/`/`adr/` folder -
  everything lives in the existing `docs/agent-reference/RAG-ROADMAP.md`/`docs/agent-reference/FAQ.md`
  convention, plus new tooling under `.claude/` (skills, hooks, one
  `implementer` subagent).
- **Action item, deliberately not decided yet (2026-09-14): LangChain vs.
  LlamaIndex, which does what, going forward.** Surfaced while researching
  Phase 17 (moving indexing from LlamaIndex to LangChain's `index()`) -
  the common real-world pattern is actually the opposite split ("LlamaIndex
  for ingestion/indexing - its documented strength - LangChain for
  orchestration"), which cuts against Phase 17's direction. User has asked
  to revisit this later rather than resolve it now - Phase 17 proceeds as
  already spec'd in the meantime. Whoever picks this up next should read
  Phase 17's spec and its "not carried over" note in `CLAUDE.md` first.

## Candidate future use case: unpaid-leave benefits-lapse notification (proposed 2026-10-02, not decided)

User-proposed use case, captured here per their own request - not refined
into a spec, not started, and not yet decided whether this gets built,
narrowed, or dropped. Revisit before doing anything else with it.

- **The use case as proposed:** an employee goes on unpaid leave. They may
  still owe their own share of health-benefit premiums for the plan year
  they enrolled in, since payroll deduction stops during unpaid leave. If
  unpaid, their policy lapses within 30 days. The system should notify
  affected employees by email before that happens. Needs sample data: 10-15
  employees, and an enrollment table covering 100+ employees' benefit
  elections per calendar year, across real US unpaid-leave types (FMLA,
  personal leave of absence, military/USERRA leave, workers'-comp-related
  leave - each has different real-world premium-continuation rules the
  30-day constant above oversimplifies).
- **Separate question raised in the same request:** HR also uploads
  documents containing employee and health-policy information that need
  entity extraction - should that use NLP (rule-based/NER) rather than an
  LLM?
- **Review findings (full discussion in this session's transcript, not
  reproduced in full here):**
  - The eligibility/deadline decision logic is pure date arithmetic - no
    LLM belongs in that path. Recommendation: a scheduled batch job /
    rules engine, not a RAG or agentic feature, and not part of
    `ai/rag_pipeline/` at all.
  - Even the notification email text is a debatable LLM use - a wrong
    date or dollar amount in a benefits-lapse notice is a real-stakes
    mistake. A plain string template may be the safer choice over an LLM
    call here. Phase 63's `build_benefits_lapse_warning_prompt()`
    (`ai/prompts/notification_prompts.py`) exists as the requested
    illustrative example only, not as a recommendation to use it.
  - Entity extraction method should depend on actual document structure,
    not be decided upfront - rule-based/NER for fixed-template forms,
    LLM extraction (see `build_entity_extraction_prompt()`, same file as
    above) for free-text documents, either way routed through this
    project's existing PII-masking guardrails (Phase 7) before anything
    sensitive reaches a log or a prompt.
  - Open architecture question, not resolved: does employee/enrollment
    data live in a new table in this project's own database, or in
    `hrb_lms_mcp` (already the system of record this project queries for
    leave balance/history via MCP, Phase 49)? Duplicating employee data
    here would cut against the "no duplicated employee data" principle
    already established in the OAuth2 schema design (see
    `docs/agent-reference/RAG-ROADMAP.md` Phase 50/53 and
    `docs/dev-reference/database/db-model-overview.html`).
  - Suggested sequencing if this moves forward: (1) decide where the data
    lives, (2) build the deterministic eligibility logic first, with real
    test coverage, zero LLM involvement, (3) decide and record the email
    approach (template vs. LLM) explicitly rather than defaulting to one,
    (4) only then pick an entity-extraction method, once real sample HR
    documents are in hand to evaluate against.
- **Not done:** no sample employee/enrollment dataset, no new database
  table, no notification workflow, no scheduled job, no real email
  sending. A first pass at this also added a prompt template
  (`build_benefits_lapse_warning_prompt()`) parameterized to this exact
  use case's fields - flagged by the user as implementing a piece of an
  undecided use case regardless of being "just a prompt," and removed the
  same session. Nothing from this discussion is implemented anywhere.

## Candidate future requirement: Analytics domain agent needs historical data (proposed 2026-10-03, sequencing confirmed 2026-10-05)

Surfaced while confirming multi-agentic-rag's domain-agent taxonomy (see
`docs/dev-reference/react_agents/multi-agentic-rag-fit-plan.html`, Decision
2 and "What Decision 2 Opens Up"). Not started, not scheduled - but the
*order* of work is now confirmed, driven by a real use case (below), not
assumed generically anymore.

- **Confirmed driving use case (2026-10-05): Caregiver leave approval,
  human-in-the-loop.** In practice, HR benefits reviews whether an employee
  requesting Caregiver leave has already availed the same leave type (e.g.
  STD/LTD) in the last 12 months before approving. This needs data from
  **both** stores, not one: `HRB_LMS_OPS_DB` (live/current leave records -
  what `GetLeaveHistory`, Phase 49, already reads) **and**
  `HRB_LMS_ANALYTICS_DB` (historical/archived records) - a case closed and
  archived into Analytics could still fall inside a 12-month lookback
  window that Ops alone wouldn't show. Confirmed sequencing: **Ops DB
  dataset first, Analytics DB dataset second, HITL build third.**
- **Ops DB dataset (do first):** 30-50 employees with real leave records
  linked to the Ops DB table - `GetLeaveHistory`'s mechanism already works
  today, it just has almost no real data behind it (a handful of test
  employees, not 30-50). **Open, not decided:** whether these are new
  leave records added to *existing* `hrb_emp_lms` employees, or a new
  employee set - the former matches this project's own "no duplicated
  employee data" principle (OAuth schema design) and is the default
  assumption until confirmed otherwise. Also open: the actual mix of leave
  types/patterns needed for a believable demo (some employees with recent
  STD/LTD, some without, so the HITL check has real cases to differ on).
- **Analytics DB dataset (do second):** still what the original ask below
  covers - 100+ historical records for trend-style NL2SQL queries. Now
  understood to be a related but separate dataset from the Ops DB one, not
  interchangeable with it - Ops answers "has this one employee taken this
  leave," Analytics answers trend/aggregate questions across employees.
- **HITL build (do third, after both datasets exist):** the actual
  Caregiver-leave-approval workflow - gathers the employee's Ops+Analytics
  leave history, reads any supporting documentation, and pauses for a
  human (HR benefits) decision. **DeepAgents scoped-adoption decision
  (2026-10-05):** use DeepAgents specifically for this case-prep agent
  (document reading + multi-source gathering is exactly what it's for) -
  not for Vector KB/LMS Ops/SQL DB, which stay plain bounded lookups. The
  pause-for-approval mechanism itself is plain LangGraph `interrupt()`,
  not a DeepAgents-exclusive feature.
- **Original ask, still accurate:** an Analytics domain agent (NL2SQL over
  benefits-cost/leave-pattern trends) needs 100+ historical records to
  demonstrate against - real data, not a handful of rows, so a trend query
  has something to actually aggregate. Maps to Phase 52 (planned, not
  started, per `docs/dev-reference/mcp/mcp-integration-overview.html`) -
  `hrb_lms_analytics` exists in the DB design doc
  (`docs/dev-reference/database/db-model-overview.html`) as a read-only
  MCP-accessed store, not built.
- **Still open, unrelated to this item:** whether the unpaid-leave
  benefits-lapse use case above shares any of this same dataset - not
  assumed; conflating them without checking would risk baking one use
  case's data shape into a different one's demo data.
- **Not done:** no schema, no data in either store, no MCP server for
  Analytics, no domain agents, no HITL workflow.

## Multi-agentic-rag follow-ups (confirmed gaps after Phase 64, 2026-10-04)

Phase 64 (`docs/agent-reference/RAG-ROADMAP.md`) shipped the real Planner/
Orchestration/Reviewer Agent graph. These are the real, verified-against-
the-actual-code gaps left after that - none started. Listed in a sensible
pickup order (cheap/no-dependency items first, items that build on each
other grouped together), not by how they were raised in conversation.

1. ~~**No per-agent model tiering - cost reduction never actually
   built.**~~ Done, Phase 65 (2026-10-04). `planner_agent._build_llm()`
   reads a new `OPENAI_PLANNER_MODEL` setting, falling back to the
   existing `OPENAI_CHAT_MODEL` when unset - scoped to the Planner only,
   per this item's own suggested fix. `.env` carries the new var
   commented out; no real cheaper model picked (a separate cost/quality
   call for the user to make).
2. ~~**Blind spot - no cost/token logging on any agent LLM call.**~~ Done,
   Phase 66 (2026-10-04), combined with #3 (same three call sites).
   `log_backend_call()` + a `response.usage_metadata` token-count log line
   (verified live before writing - a real field, not guessed) now wrap
   `planner_agent.py`/`reviewer_agent.py`/`orchestration_agent.py`'s
   `ainvoke()` calls, same pattern `openai_client.py` already used.
3. ~~**Blind spot - no timeout on any agent LLM call or graph node.**~~
   Done, Phase 66 (2026-10-04). `asyncio.wait_for(..., timeout=
   AGENT_LLM_TIMEOUT_SECONDS)` (30s) wraps the same three call sites as
   #2. An `asyncio.TimeoutError` surfaces as an uncaught 500 today - a
   dedicated error code is a follow-up if timeouts turn out to happen
   often in practice, not assumed necessary yet.
4. ~~**Golden dataset has no multi-part questions, and multi-agentic-rag
   was never validated against it.**~~ Done, Phase 67 (2026-10-04). Added
   `multi-agent-same-domain-01` (same-domain compound, 401k+tuition) and
   `multi-agent-cross-domain-01` (KB + live leave-balance) to
   `golden_dataset.json`, plus a live test
   (`test_multi_agent_pipeline_golden_cases.py`) that runs both through
   `run_multi_agent()` on every `pytest -m eval`. **Found and fixed a real
   local-environment gap along the way, unrelated to multi-agentic-rag
   itself:** only 3 of the 6 KB PDFs the golden dataset assumes were
   actually indexed locally - traced down to confirm it affected genai-rag
   too (not an agent-code bug), fixed by re-ingesting the missing 3 PDFs
   through the real upload endpoint. See Phase 67's own Verified block in
   RAG-ROADMAP.md for the full trace.
5. ~~**Query decomposition (Phase 5.1) is still a 0-byte placeholder.**~~
   Resolved, Phase 68 (2026-10-04) - **no separate component built**, by
   live evidence: once #4's indexing gap was fixed, the Planner split the
   same-domain compound case into two correctly-focused `vector_kb_agent`
   tasks with zero prompt changes. Decision and evidence recorded in
   `query_decompose.py`'s own docstring. Still open: genai-rag's own non-
   agentic pipeline has no equivalent splitting mechanism - a separate,
   unraised question.
6. ~~**DeepEval harness is generic but has never been pointed at the
   agentic pipelines.**~~ Done, Phase 69 (2026-10-04). Two new test-local
   adapters (matching the existing `ask_genai_rag()` pattern) point
   `score_case()` at `run_agent()` and `run_multi_agent()`. Needed a real
   fix first, not a workaround: neither function exposed the raw tool/
   domain-agent output text needed for a meaningful groundedness check -
   added `tool_outputs`/`agent_result_texts` to each function's return
   dict (additive, no public API contract change).
7. **Multi-agentic-rag's Planner still never reads prior turns back into
   reasoning - still open.** `multi_agent_pipeline.run_multi_agent()`
   saves a turn (now durably, see #8) but never calls `load_history()` -
   every call reasons fresh, so "what about last year's number" won't
   resolve correctly for multi-agentic-rag specifically. Single-agentic-rag
   does NOT have this gap - `orchestration_agent.run_agent()` already
   loads and seeds history into its own messages, unchanged by Phase 76.
   **Sequencing note:** this item's own text originally said #8 (storage)
   should wait until after this one was fixed ("no point persisting
   history that reasoning doesn't use yet") - the user explicitly directed
   the opposite order on 2026-10-05, and #8 is now done. Fix still needed:
   thread `conversation_memory.load_history()`'s result into the Planner's
   prompt (and optionally the Reviewer's) in `multi_agent_pipeline.py`.
8. ~~**Conversation storage is in-memory only (STM), no LTM, no
   metadata.**~~ Done, Phase 76 (2026-10-05). `conversation_memory.py` is
   now backed by a real Postgres table (`conversation_turns`, via the new
   `ConversationStore` client) - survives restarts, STM and LTM are the
   same durable store (a fast/durable two-tier split is deferred to a
   future Redis migration, user's explicit choice - Postgres now, Redis
   later, not built as a fake two-tier system today). `employee_id` is
   now recorded per turn (wasn't before) - found needed this while
   designing the delete-my-conversation NFR endpoint (also shipped this
   phase), so deletion can be scoped to the caller's own data. No richer
   metadata (which-agent-answered, token/cost, latency) added - still a
   real gap if that level of detail is wanted later.
9. ~~**Web-search agent (Tavily) was never built as an agent, only as a raw
   client.**~~ Done, Phase 70 (2026-10-04). New `ai/agents/domain_agents/
   web_search_agent.py` wraps the existing `get_client_gateway().tavily()`
   client; added as the Planner's 5th routing option
   (`PLANNER_SYSTEM_PROMPT` describes it as external/current information,
   explicitly distinct from `vector_kb_agent`'s internal-policy scope) and
   as a 5th node/edge in the graph. Live-verified with a real Tavily call
   (current IRS mileage rate question) routed correctly end to end.

Items 7 and 8 above are intentionally on hold (2026-10-04) - explicit user
instruction to pick them up later, after items 1-6 and 9 (done, see above).

Related, already tracked separately above (not repeated here): per-
domain-agent evals / "Reviewer Agent also does evals" (Option A from
`multi-agentic-rag-fit-plan.html`) - not built, Phase 64's Reviewer only
merges; SQL DB Agent / LMS Analytics Agent real logic - blocked on the Ops
DB / Analytics DB datasets in the section above this one, already
sequenced.

## Caching follow-ups (confirmed gaps after Phase 77/78, 2026-10-05)

**Query-time embedding caching was not built, flagged not silently
dropped.** Phase 77 caches ingestion-side embeddings only
(`embedding_generator.generate_embeddings()`) - query embeddings happen
inside LangChain's own `OpenAIEmbeddings` object (`langchain_vector_store
.py::get_embeddings()`), called internally by `Chroma`/`PineconeVectorStore
`'s own `similarity_search()`. There's no explicit "embed the query" step
in `retriever.py` to wrap directly - closing this gap needs a small
`CachingEmbeddings` class subclassing LangChain's `Embeddings` interface
(`embed_query()`/`embed_documents()`, plus their async variants
`aembed_query()`/`aembed_documents()` - both need covering, not just one,
since LangChain's own default async implementations just thread-wrap the
sync ones unless overridden), reusing the same `EmbeddingCache` client
Phase 77 already built (same table, same `hash_text()` key). Real,
same-size effort as Phase 77 itself - not done opportunistically inside
that phase to avoid introducing a subtle sync/async bug in a path every
live query already depends on.

**Answer cache (Phase 78) has 3 confirmed, explicitly-scoped-out
follow-ups:**
- **Tier-2 semantic/similarity matching** - today's cache is exact-match
  only (the user's own confirmed starting scope). Two differently-worded
  questions with the same real answer currently miss the cache entirely.
- **Single/multi-agentic-rag answers aren't cached at all** - Phase 78
  only wired genai-rag's `pipeline.answer_query()` (the one pipeline with
  a plain, deterministic retrieve-then-generate path). Caching "the final
  answer" for an iterative tool-calling loop or a multi-agent dispatch is
  a different, bigger question - what's actually safe to treat as a pure
  function of the input - not resolved, not assumed answerable the same
  way.
- **Invalidation is blunt (clears the whole table on any document
  change), not per-document** - correct and safe, but more aggressive
  than necessary once there are many documents and most changes don't
  actually affect most cached answers. A real refinement if the blunt
  version turns out too costly in practice (frequent re-indexing against
  a large cache) - not a problem yet at this project's current scale.

## Observability gap: genai-rag's own generation calls are invisible (confirmed Phase 79, 2026-10-05)

**`response_generator.py` has zero token/cost/latency telemetry, unlike
the 3 agent files Phase 66 covered.** Confirmed live: `response
.usage_metadata` is `None` on every call through `GatewayChatModel` -
`GatewayChatModel._generate()` calls `OpenAIChatClient.ask()`, which only
ever returns the plain answer string, discarding the real OpenAI response
object (and its `usage` field) before `GatewayChatModel` ever sees it.
Also confirmed not picked up by LangSmith either - `OpenAIChatClient`
calls the raw `openai` SDK directly, never wrapped with `langsmith
.wrappers.wrap_openai()`, so `LANGCHAIN_TRACING_V2` doesn't see these
calls regardless of whether tracing is on. This means genai-rag's own
query endpoint - the most heavily used one in this project - has **no**
token/cost visibility anywhere, a real hole Phase 66 didn't close since
it only touched `planner_agent.py`/`reviewer_agent.py`/
`orchestration_agent.py`. Fix needs either exposing `ask()`'s underlying
response object (a larger change - `ask()` is called from several places
expecting a plain string today) or wrapping `OpenAIChatClient`'s real
`openai.OpenAI` client with `wrap_openai()` for LangSmith visibility
without changing `ask()`'s own return type. Not started.

## Release gate follow-up (confirmed scope after Phase 80, 2026-10-05)

**`eval-gate.yml`/`scripts/run_release_gate.py` cover genai-rag only.**
Single/multi-agentic-rag each already have their own real eval adapters
(Phase 69's `ask_single_agentic_rag()`/`ask_multi_agentic_rag()`) and
could get their own release-gate pass using the exact same pattern Phase
80 just proved out - same `GATE_METRICS` reasoning would apply too (their
own retrieved-context shape differs from genai-rag's chunk list, so the
same precision@k structural-ceiling question would need re-checking, not
assumed to carry over automatically). Not started - a natural, same-shape
follow-up, not bundled into Phase 80 to keep it reviewable as one real,
already-complex CI job.

**`calculate_retrieval_metrics()`'s `k=3` default vs. this project's real
`top_k` is a standing mismatch worth a permanent decision, not just a
one-script workaround.** Phase 80's own script passes the real `k`
explicitly and then excludes precision/f1 from gating entirely (confirmed
with the user) - but `golden_dataset_harness.py`'s shared `score_case()`
still hardcodes `k=3` for every *other* caller
(`test_golden_dataset_harness.py`, `test_single_agentic_rag_golden_dataset
.py`, `test_multi_agentic_rag_golden_dataset.py`), all of which are
light smoke tests today ("confirms real scores come back, not a quality
gate") and don't fail on a low precision score - so this hasn't broken
anything yet, but the same structural ceiling applies there too, silently.
Worth a real decision later: expose `k` as a `score_case()` parameter
(default `3`, course-faithful, opt-in override), or reconsider whether
precision@k belongs in this project's own metric set at all given its
deliberately broad multi-chunk retrieval design. Not decided, not touched
in Phase 80 - that phase's own user instruction was explicitly to leave
`golden_dataset_harness.py` itself untouched.

## Indexing failures are silent to the API caller (confirmed Phase 83, 2026-10-05)

`documents_service.py` catches any exception from the indexing step
(`ai/doc_processing/pipeline.py`) and logs it as `ERROR`, but the upload's
own HTTP response still reports `"status": "uploaded"` for that document -
not `"failed"`. Found for real during Phase 83 (a missing
`llama-index-embeddings-openai` pin broke every indexing attempt for an
unknown period, completely silently - the API never once returned
anything other than `"uploaded"`). The dependency bug is fixed; this is
the separate, still-open design gap it exposed: a caller (a script, a
future React UI, a human in Postman) currently has no way to tell "fully
indexed and searchable" apart from "uploaded but indexing silently failed"
without reading CloudWatch/application logs by hand. Worth a real decision
later: should `DocumentUploadResponse`'s per-file `status` distinguish
`"uploaded"` (saved, not yet confirmed indexed) from `"indexed"`/
`"indexing_failed"`? Not decided, not touched in Phase 83 - that phase's
scope was strictly the missing dependency pin.

## Pinecone relevance threshold is a data-backed stop-gap, not a final calibration (Phase 83 follow-up, 2026-10-05)

`RAG_MIN_PINECONE_SCORE` was `0.5`, which sat right at the boundary of real
data rather than below it - confirmed by querying Pinecone directly for 20
real golden-dataset questions: scores ranged 0.4969-0.8229, with the
lowest *correct* match at 0.4969 (just under the old threshold - would
have been incorrectly filtered). Lowered to `0.45` in both local `.env`
and the live App Runner config, giving real margin below the observed
minimum. This is a deliberate stop-gap, not a finished calibration - the
sample only confirmed where *correct* matches score, not where irrelevant
noise starts scoring too high. Worth a real calibration later: run queries
expected to have no good answer in the KB, find the real separation
point between signal and noise, and ideally do this through the
golden-dataset release gate once it also exercises Pinecone (see
`docs/dev-reference/deployment-guide/03-pinecone-standard.html`'s open
question on extending `eval-gate.yml` beyond ChromaDB) rather than a
one-off manual check like this one.

## ~~Chunk metadata's `filename` field reads `"unknown"` in Pinecone~~ - resolved incidentally, Phase 87, 2026-10-06

Found Phase 83 (2026-10-05): every source chunk returned `"filename":
"unknown"` instead of the real PDF name. Resolved as a side effect of
Phase 87's clean Pinecone-namespace-clear + full re-ingest (done to fix
the metadata-store switch, not to fix this) - confirmed live, every
retrieved source now carries the real PDF name. Never root-caused
directly; most likely the original "unknown" values came from documents
ingested under an earlier code path (before some metadata-patching change
landed) and never got backfilled - a fresh ingest under current code
simply doesn't have the bug. Not worth further investigation now that
it's confirmed gone.

## Phase 88 follow-ups: Lambda reserved concurrency skipped; AWS CLI default region is wrong (2026-10-06)

Two real, non-blocking gaps found while provisioning Phase 88's S3 → SQS →
Lambda pipeline:

1. **No reserved concurrency on `hrb-chatbot-index-document`.** The spec
   called for one (protect Pinecone/Postgres from a batch-upload spike),
   but `PutFunctionConcurrency` failed - this AWS account's total Lambda
   concurrency pool is only 10, and AWS enforces a floor of 10 unreserved
   executions account-wide, leaving zero room to reserve any amount.
   Fixing this needs an AWS support concurrency-limit-increase request,
   not a code or config change. Low urgency at this project's real
   traffic volume - revisit if a real batch-upload test is ever run.
2. **This AWS CLI's configured default region is `us-east-2`, not
   `us-east-1`.** Caught live during Phase 88 (the first `sqs
   create-queue` call landed in the wrong region with no `--region`
   flag) - the same root cause as the already-flagged 5 duplicate
   wrong-region Postgres secrets elsewhere in this backlog. Every AWS
   CLI call in this project should pass `--region us-east-1` explicitly;
   worth fixing the shell/profile's actual default at some point so this
   stops being something every session has to remember by hand.

## Phase 88 follow-ups round 2: no input validation on the async path; cold-start init-timeout is recurring, not a fluke (2026-10-06)

Found while answering direct questions about multi-document/concurrent
uploads - see `docs/agent-reference/RAG-ROADMAP.md`'s Phase 88 entry for
the full test evidence (one real bug found and fixed there too - an
`asyncio.run()`-per-record pattern that broke the Redis embedding cache
across records in the same batch).

1. **`src/hrb_chatbot/lambda_handlers/index_document_handler.py` has no
   file-type/size validation and no cross-document content-hash dedup.**
   `documents_service.validate_file()` and the content-hash check in
   `save_upload()` are both specific to the synchronous upload path and
   were never ported here - the handler will chunk/embed/index whatever
   object sits at the given S3 key, including a 0-byte file, a non-PDF,
   or a huge file. Low risk only because nothing can write to this
   bucket today except a direct, authenticated AWS call - no public
   upload path exists until Phase 89. **Phase 89 (the presigned-upload
   endpoint) is the right place to add this**, not the Lambda - either
   via the presigned POST's own `Conditions` (content-type, size range)
   or a check before issuing the URL at all.
2. **The cold Lambda init-phase timeout noted once in Phase 88's first
   round recurred on the second round too**, on both invocations a fresh
   deploy triggered. SQS's automatic redelivery self-healed it both
   times (no message lost, no DLQ hit) - but this is now confirmed a
   repeatable characteristic of this handler's cold start (heavy
   langchain/llama-index/pinecone-client imports), not a one-off. Worth
   a real tuning pass (more memory - Lambda's CPU allocation scales with
   it - or Lambda SnapStart) if this pipeline ever sees enough cold-start
   frequency for the redelivery delay (seconds, today) to matter at
   real volume.
3. **LangSmith shows nothing for this pipeline, for two independent
   reasons**: the Lambda handler never calls `enable_tracing_if_
   configured()` (only `main.py`'s module top level does, and the
   handler never imports `main.py`), and even if it did, ingestion's own
   OpenAI calls go through this project's raw-SDK wrapper, never a
   LangChain `Runnable` - the exact same root cause as the "Observability
   gap" entry above (confirmed Phase 79) for genai-rag's generation
   calls. Not a new gap, a second symptom of the same one - fixing
   `wrap_openai()` around the raw `openai.OpenAI` client (as that entry
   already proposes) would fix both at once. See `docs/dev-reference/
   deployment-guide/10-observability-howto.html` for what LangSmith/
   CloudWatch actually show today, step by step.

## CI (not Deploy) has been failing since at least Phase 86, undetected until 2026-10-06

Found while checking CI status for Phase 89's push (via `gh run list` -
the GitHub Actions CLI, not watched routinely this session; AWS
verification was always checked directly, but the separate CI workflow's
own pass/fail was not). **`Deploy` has been green the whole time** - this
is specifically the `CI` workflow (`ci.yml`'s "Test suite" job), and
nothing in this project's actual production behavior is affected by it.

**The failure:** 11 tests in `tests/hrb_chatbot/ai/doc_processing/
indexing/test_vector_indexer.py` fail on GitHub's `ubuntu-latest` runner
with `ValueError: Could not load OpenAI embedding model... No API key
found for OpenAI` - LlamaIndex's `OpenAIEmbedding` (its `Settings
.embed_model` default) validating a key eagerly, somewhere inside
`VectorStoreIndex`'s construction path in `vector_indexer.py`, despite
real embeddings already being computed and passed in separately (Phase
44's own documented design - this validation should never be reachable).

**What's been ruled out, each one tested directly, not assumed:**
- Not a stale/missing `.env` issue - reproduced locally with `.env`
  fully removed (`mv .env .env.bak`), still passed.
- Not test-order/global-state pollution - ran the single failing test in
  isolation AND the full local suite together, both passed.
- Not the exact CI command (`--cov=... --cov-fail-under=45`) - ran that
  exact command locally, passed.
- Not dependency version drift - diffed `pip freeze` between this
  project's long-lived local `.venv` and a genuinely fresh clone + fresh
  venv + fresh `pip install` (several transitive packages *did* differ,
  e.g. `aiohttp` 3.10.11 vs 3.14.4) - the fresh install still passed
  cleanly on Windows (283 passed, matching `master` before Phase 89).

**What's left, not yet tested - no Linux environment available this
session:** this now looks like a genuine Windows-vs-Linux behavior
difference in a dependency on the `ubuntu-latest` runner specifically,
since the most faithful possible local reproduction (fresh clone, fresh
venv, fresh install, identical command) still doesn't fail on Windows.
Next step for whoever picks this up: reproduce on an actual Linux box/
container (not WSL necessarily, but anything matching `ubuntu-latest`)
before guessing at a fix - guessing blind at an OS-specific dependency
behavior without being able to reproduce it is how a wrong fix gets
merged and the real bug stays. Once reproduced, the real fix is most
likely either explicitly setting `Settings.embed_model` to something
that doesn't validate a key at all (a local/fake embed model) before
`VectorStoreIndex` is ever constructed in these tests, or a conftest.py-
level `os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")` -
exactly the same category of fix Phase 82/83/85/86 already applied for
other CI-only gaps, just not diagnosable blind.

## ~~No CI/CD automation deploys the Lambda~~ - resolved 2026-10-06, `.github/workflows/deploy-lambda.yml`

Found Phase 89: `deploy.yml` rebuilds and redeploys the main App Runner
image on every push to `master` but has no idea
`hrb-chatbot-index-document` (the Phase 88 Lambda) exists - every Lambda
deploy had been a manual `docker buildx build` + ECR push + `aws lambda
update-function-code`, and this already caused a real bug once (Phase 89
shipped code the Lambda silently never got, caught only by a live test
checking real values, not just HTTP status).

**Fixed**: new `deploy-lambda.yml`, triggered on push to `master`,
`paths:`-scoped to `src/hrb_chatbot/**`/`Dockerfile.lambda`/
`requirements.txt` (the whole tree, not just `lambda_handlers/` - see
`docs/agent-reference/CICD-BRANCHING-STRATEGY.md`'s new section for why).
Needed `hrb-chatbot-github-actions-deploy`'s IAM policy extended
(`ecr:*` on the `hrb-chatbot-lambda` repo, `lambda:UpdateFunctionCode`/
`GetFunctionConfiguration` on the one function) - a manual IAM step,
same as every other credential change this project does by hand.

## `GET /health` with no query params silently checks the wrong backends on AWS (found Phase 92, 2026-10-06, pre-existing)

Not caused by Phase 92 - found while verifying it, confirmed present on
an App Runner instance that started *before* that phase's own push.
`api/dependencies.py`'s `METADATA_PROVIDER_QUERY`/`VECTOR_PROVIDER_QUERY`
hardcode `default=MetadataStore.SQLITE`/`default=VectorDB.CHROMADB` -
their own descriptions even say `"'sqlite' (the active store)"` /
`"'chromadb' (the active store)"`, which was true when written but is
stale now that `ACTIVE_VECTOR_DB`/`RAG_METADATA_STORE` make Postgres/
Pinecone the real active backends on AWS (Phase 31 onward). A plain
`GET /health` on production reports `"healthy"` for chromadb/sqlite -
backends that aren't even the ones serving real traffic - while never
touching Pinecone/Postgres at all unless the caller explicitly passes
`?metadata_provider=postgres&vector_provider=pinecone`. Confirmed the
real backends ARE healthy by passing those params explicitly - this is
a misleading-default bug, not a production incident. Real fix: these
two defaults should resolve dynamically via `get_active_vector_db()`/
the metadata-store equivalent, not a hardcoded Enum literal - not done
here, out of scope for a path-prefix-only phase.

## Re-verified against live AWS/CI, 2026-10-07 - all still open, none regressed

User asked to confirm current status of the "handful of AWS/Lambda infra
items" noted above, against the real account/CI, not from memory. All five
re-checked directly, nothing fixed itself, nothing got worse:

1. **AWS CLI default region still `us-east-2`** (`aws configure get
   region`) - unchanged from the Phase 88 finding above.
2. **`hrb-chatbot-index-document` still has no reserved concurrency**
   (`get-function-concurrency` returns empty) - unchanged, same 10-execution
   account floor. The function itself is healthy and current: `State:
   Active`, `MemorySize: 1024`, `Timeout: 300`, last deployed
   `2026-10-06T13:53:10Z` (matches `deploy-lambda.yml`'s real run history).
3. **`CI` workflow (`ci.yml`) still red** - 5 most recent runs on GitHub all
   `completed failure`, same `ubuntu-latest` OpenAI-embedding-key issue
   documented above, still unreproduced on Linux this session. `Deploy` and
   `Deploy Lambda` are both still green (3/3 most recent runs each) - the
   actual deploy pipeline is unaffected, same as before.
4. **`GET /health` with no params still reports chromadb/sqlite** on
   production, not the real active Pinecone/Postgres backends - confirmed
   live: bare `/health` returns `vector_database.provider: "chromadb"`
   (0 collections), while `?metadata_provider=postgres&vector_provider=
   pinecone` returns the real data (`355` vectors in Pinecone, `9`
   documents in Postgres). Same misleading-default bug, same real fix
   (`get_active_vector_db()` instead of a hardcoded Enum default), still
   not done.
5. **Async-path validation gap (Phase 88 round 2, item 1)** - not
   re-exercised live this pass (would need a real S3 upload + Lambda
   invoke); no code change has touched `index_document_handler.py`'s
   validation since it was written, so there's no reason to expect it
   changed. Still open, still deferred to Phase 89's presigned-upload
   endpoint as documented above.

Net: no new findings, nothing resolved. All five remain real, open,
low-urgency gaps - safe to keep deferring unless one of them starts
actually affecting production traffic.

## Codebase cleanup findings (Phase 93, 2026-10-06)

Two independent Explore-agent audits run first, rather than guessing -
one for real golden-dataset eval numbers (separate finding, see
"Release gate follow-up" above), one specifically for dead code/
duplicate logic/stray files. Headline result: **this codebase has very
little actual dead code** - no unused `.py` files, no unreachable
functions, no 5+ line commented-out blocks found anywhere in `src/`.
One real duplicate found and fixed (see RAG-ROADMAP.md Phase 93 - a
`common/utils/content_hash.py` helper replacing an identical
`hashlib.sha256(...).hexdigest()` line independently written in both
`documents_service.py` and `index_document_handler.py`).

**Not touched, flagged instead:**
- **`requirements.txt` possibly-unused packages** - a direct-import grep
  flagged `presidio-analyzer`/`presidio-anonymizer`, `prometheus-client`,
  `structlog`, `pyjwt`, `sqlalchemy`, and others as having no `import`
  site in `src/`. **Confirmed at least one of these is wrong**: Presidio
  is a real, load-bearing *transitive* dependency of NeMo Guardrails'
  "mask sensitive data" rail (Phase 7/82) - pulled in via its own colang
  config, never a direct Python import. A plain unused-import grep can't
  safely clear any of these - needs a real one-package-at-a-time audit,
  not a bulk prune based on this finding alone.
- **Stray untracked files** (confirmed via `git status` - not committed,
  not something to silently delete): `scratch_gates.txt` (looks like a
  scrape/paste leftover), `docs/dev-reference/production-readiness-
  scorecard.html` (a real, styled page - not obviously disposable),
  `docs/ik-fde-course-docs/` (a whole directory of unrelated IK FDE
  course material, one 820KB notebook). None of these are something
  this session created - flagged for the user's own call.
- **`docs/dev-reference/hrb-chatbot-github-actions-deploy_accessKeys.csv`
  re-confirmed still present and still contains a live-looking plaintext
  AWS key.** The user already stated explicitly (2026-10-05) this file
  was added intentionally and they'd handle it themselves - re-flagging
  here only because a cleanup pass specifically went looking for exactly
  this kind of risk and it's still sitting there; not touched.

**Also found while cross-checking, unrelated to the audit itself**:
this file's own "GitHub repo settings not configured... Default branch
is still `hrb_rag_pipelines`" entry (under "CI/CD & branch strategy")
is now stale - confirmed live via `gh repo view` that the default
branch is `master`, not `hrb_rag_pipelines`. Worth a cleanup pass on
this file's own older entries at some point - several read as still-
open but are actually resolved, just never struck through.

## UI backend-gap findings (Phase 95, 2026-10-06)

Found while re-reviewing `docs/dev-reference/ui-wireframes-review.html`
against this project's actual current backend code, ahead of starting
`hrb_chatbot_ui` (the separate React project). Per the user's explicit
instruction for this first UI-build phase: don't change a backend
feature unless it's critical/blocking (CORS was - see RAG-ROADMAP.md
Phase 95); everything else below is deliberately deferred, logged here
instead of implemented.

- ~~**No way to list or fetch conversation history.**~~ Resolved, Phase
  116 (2026-10-07): `GET /v1/conversations` (own conversation list) and
  `GET /v1/conversations/{id}` (one conversation's turns) both exist now,
  alongside the original `DELETE`. The frontend's `ChatPage.tsx` lazy-
  loads from these on login, merging server-side conversations into
  local state - no longer browser-only.
- **No feedback-submission endpoint at all.** Nothing in `src/` stores
  or accepts a "Helpful"/"Not quite" signal from a chat message. The
  wireframed feedback popup has nowhere to send its payload - the UI's
  first phase accepts the input but doesn't persist it past the
  browser tab, clearly labeled as not yet wired to the backend.
- **No API surfaces cost/token/tool-call/trace data.** Confirmed again:
  `common/logging/call_logger.py`'s `log_backend_call()` logs this per
  call, but no response field or endpoint returns it. The explainability
  popup can show real `model_used` and real retrieval sources/scores
  (both already in `RagQueryResponse`), but cost/tokens/latency/call-trace
  fields show as "not available yet" rather than being invented client-side.

None of these block building the UI - each is a real, scoped,
independently doable backend phase (a conversations list/detail `GET`
endpoint; a feedback table + `POST` endpoint; a trace/metrics response
field or endpoint) to pick up later, each wanting its own `**Spec:**`
block before implementation, same as every other phase.

## Output guardrail false positive: "Roth" masked as a name (found 2026-10-06)

Found live, through the new UI: asking "What is the 401(k) employer
match?" returned *"JPMorgan Chase matches 100% of employee before-tax
and/or **\<PERSON\>** contributions..."* - the NeMo Guardrails "mask
sensitive data on output" rail (Presidio, Phase 7/82) misidentifies the
word "Roth" as a person's name and redacts it. Confirmed reproducible -
not a one-off. Real answer-quality bug (the sentence becomes
nonsensical), but not critical/blocking, so not touched this round per
the "don't change backend features unless critical" instruction for the
UI-build phase. Likely fix is a Presidio allowlist/exclusion entry for
"Roth" (a financial term, not a name) rather than disabling the rail -
needs its own `**Spec:**` block, not a quick inline patch, since
guardrail config changes affect every response, not just this one term.

~~## multi-agentic-rag 500s whenever conversation memory is enabled~~ Fixed
2026-10-06 (Phase 97) - root cause was a PDF-ligature NUL byte reaching a
Postgres TEXT column, not the LangGraph state wiring guessed at here when
this was first found. See `RAG-ROADMAP.md`'s Phase 97 entry for the real
fix. Entry kept struck-through rather than deleted outright, so the
original (wrong) root-cause guess doesn't get silently lost.

## Token cost (in dollars), not just token counts, in Explainability

Found 2026-10-06, user-directed, deliberately deferred alongside the
identity-keyed rate-limiting item above. Once real token counts are
captured and surfaced (see `RAG-ROADMAP.md`'s metrics-capture phase),
converting to a dollar estimate is a small additional step - a per-model
pricing table (prompt/completion rate, by `model_used`) multiplied against
the already-captured counts. Not built now - token counts themselves are
the priority; cost-in-dollars is a cheap follow-on once that lands, not
before.

## `chunking_strategy` is never persisted, only `chunk_size`/`chunk_overlap`

Found 2026-10-06, building Phase 103's documents-table chunk-info display.
`DocumentRecord.chunk_info.chunking_strategy` is always `null` for every
real indexed document, confirmed live - `sqlite_client.py` has no
`chunking_strategy` column at all (only `chunk_size`/`chunk_overlap` exist,
confirmed by grep), even though `record_successful_index()` receives the
real resolved strategy name as a parameter and simply never writes it.
UI handles the `null` gracefully (omits the parenthetical rather than
showing "(null)"), not fixed here - adding the column is a small,
real, separate backend change (new column + migration + one more field
in the `UPDATE` in `record_successful_index()`), out of this phase's scope.

## multi-agentic-rag has no per-domain-agent token usage, and no caching

Found 2026-10-06, Phase 110 (explainability/cache parity across all three
retrieval modes). `explainability_info.token_usage` is always `null` for
multi-agentic-rag specifically - real token capture would mean touching
all 7 files the LangGraph graph fans out across (planner, 5 domain
agents, reviewer), each calling an LLM independently, which this phase
didn't otherwise need to change. genai-rag and single-agentic-rag both
have real token counts (Phase 107/110). Separately, this pipeline also has
no answer caching at all, unlike the other two (Phase 105/110) -
`web_search_agent`/`lms_analytics_agent` can return live, time-sensitive
data the same way `GetLeaveBalance` can, and there's no cheap per-node
signal yet (unlike single-agentic-rag's `tools_used` list) to tell a
cacheable turn from a live-data one without one. Both are real, scoped
follow-ups, not silently skipped - see `RAG-ROADMAP.md`'s Phase 110 entry
for the full reasoning. **Update 2026-10-07 (Phase 115): multi-agentic-rag
now does have caching** - the `token_usage`-stays-null half of this finding
is still accurate, but the caching half is resolved, see Phase 115's own
roadmap entry.

## ~~`HRB_LMS_MCP_URL` never configured on AWS~~ - resolved 2026-10-07, Phase 118

`GetLeaveBalance`/`GetLeaveHistory` (single-agentic-rag) and the MCP
fast-path (genai-rag) all call out to `hrb_lms_mcp`, a separate sibling
project (its own GitHub repo, `rvsree/hrb_lms_mcp`). Every verification
of this integration on record (Phase 49/50/53, this file's "MCP
integration & cross-project schema standardization" section above) was
done against a **locally-running** `hrb_lms_mcp` instance - `mcp_tools/
__init__.py`'s `read_setting(None, "HRB_LMS_MCP_URL", "http://
127.0.0.1:8190/mcp")` falls back to localhost when the setting is unset.

**Confirmed broken live, 2026-10-07**: checked App Runner's actual
runtime configuration (`aws apprunner describe-service`) - no
`HRB_LMS_MCP_URL`/`HRB_LMS_MCP_OAUTH_*` keys exist there at all, neither
as plain env vars nor as secrets. A real `POST /v1/single-agentic-rag-
retrieval/query` asking "How many PTO days do I have left?" against
`https://hrb-chatbot.rvsree.dev` confirms the failure mode: the agent
correctly picks `GetLeaveBalance` as the tool to call, then gets a
connection failure (the container tries to reach `127.0.0.1:8190` on
*itself*, where nothing listens) and falls back to a generic "unable to
retrieve... due to a connection issue" answer instead of a real number.

**Resolved, Phase 118 (2026-10-07, see RAG-ROADMAP.md for the full
write-up)**: `hrb_lms_mcp` deployed to its own AWS App Runner service
(`hrb-lms-mcp`, custom domain `hrb-lms-mcp.rvsree.dev`) with
`hrb_emp_lms`/`hrb_lms_mcp_auth` schemas added to the same Neon
`HR_Benefits` database this project already uses, and the real
URL/OAuth2 credentials wired into this project's own App Runner config.
A second, independent bug surfaced and got fixed along the way -
`hrb_lms_mcp`'s `FastMCP("lms")` defaulted to DNS-rebinding Host-header
protection that rejected every real (non-localhost) hostname with 421,
masked by generic `ExceptionGroup` logging here until `exc_info=True`
was added to surface it. Live-verified: the exact question that used to
return the connection-issue fallback now returns a real PTO balance.

## MCP gaps found by reviewing a cohort-mate's M1 MCP submission (2026-10-15)

Compared `hrb_chatbot_v2`'s MCP client (`ai/rag_pipeline/tools/mcp_tools/
__init__.py`) and `hrb_lms_mcp`'s MCP server against the FDE cohort's M1
MCP module as submitted by a cohort-mate (`jeev1992/real-estate-
negotiation-simulator`, `m1_mcp/` - two `FastMCP` servers, a stdio client,
an SSE client). Full table (transport, tool registration, auth, Resources/
Prompts primitives, multi-server orchestration, structured outputs,
logging, retries, concurrency, testing) in this session's own record, not
reproduced here - most rows are a wash or we're already ahead (real OAuth2
vs. none, real structured logging vs. none, real test coverage vs. none).
Three real, worth-tracking items:

- ~~**`_call_mcp_tool()` callers each hand-roll `json.loads(result["content"]
  [0])`**~~ - resolved 2026-10-15. Collapsed into one shared
  `_call_mcp_tool_json()` helper in `mcp_tools/__init__.py`, used by all 9
  in-file wrapper functions plus the 2 external call sites
  (`manage_admin.py`, `unpaid_leave.py`) that called `_call_mcp_tool()`
  directly - 11 duplicated unwraps down to 1. No behavior change; full
  suite (676/676) confirmed passing after.
- ~~**No distinction between "MCP server unreachable" (transport failure)
  and "tool call failed"**~~ - substantially addressed 2026-10-15 by
  Phase 185's circuit breaker (see `RAG-ROADMAP.md`): every real
  `_call_mcp_tool()` attempt now records its own outcome, and a pre-
  flight check raises a distinct "known unreachable" message before even
  attempting a call once 2+ consecutive failures are on record - the
  exact pattern-visibility gap this entry described. Not done: a
  dedicated exception *class* (today it's still a `RuntimeError` either
  way, distinguishable by message text, not type) - left as a smaller,
  optional follow-up if a caller ever needs to branch on it
  programmatically, not just log it.
- **Multi-server tool-catalog merging has no precedent here** -
  `orchestration_agent.py`'s `TOOL_FUNCTIONS` dict already mixes one
  MCP-backed tool with non-MCP tools in a single loop, but there's only
  ever been one real MCP server. m1_mcp's `sse_agent_client.py --both`
  demonstrates discovering + merging two independent servers' tool
  catalogs into one LLM-visible list. Not urgent - Phase 52 (a second,
  analytics MCP server) is parking-lot-only today - but worth designing
  for up front whenever that phase's spec gets written, rather than
  hand-rolling a second one-off `_call_mcp_tool`-style module next to the
  first. Flagged per CLAUDE.md's "flag, don't fix," not acted on here.

Deliberately not pursued: Resources/Prompts primitives (m1_mcp uses both;
every MCP interaction in this project is per-employee parameterized data,
which is inherently tool-shaped - no static document exists to attach as
a Resource) and concurrent tool-call execution (m1_mcp doesn't do this
either; this project's tool-calls-per-turn count is 1-2, not worth the
complexity yet).

## No reranking step anywhere in hybrid search; RRF fusion discards per-chunk dense/sparse scores (found 2026-10-19)

User asked why the Explainability panel's Retrieval Strategy tab doesn't
show a hybrid answer's chunks broken down by semantic-score vs keyword-
score, or any "ranking process" info, and whether ranking is the
Reviewer agent's job or retrieval's. Investigated directly, not assumed:

- **No reranking/cross-encoder step exists at all** - `grep -rniI
  "rerank" src/hrb_chatbot` returns zero matches anywhere in the
  codebase. `reviewer_agent.py` only merges domain agents' final TEXT
  answers (one LLM call); it never touches chunk order or scores -
  ranking, to the extent it happens, is entirely inside retrieval
  (`ai/rag_pipeline/query_retrieval/bm25_search.py`), not the Reviewer.
- **`search_hybrid()`'s Reciprocal Rank Fusion (`_reciprocal_rank_fusion`,
  `bm25_search.py`) keeps only one fused RRF score plus a categorical
  `matched_by` tag** (`["sparse"]`/`["dense"]`/both) per chunk - the
  original per-list dense similarity score and sparse BM25 score are
  each computed, then discarded once fused. `ExplainabilityModal.tsx`'s
  "Dense/Sparse Contribution" panel already surfaces `matched_by`
  honestly (aggregate counts only); it can't show a numeric semantic-
  vs-keyword breakdown because the backend doesn't retain one.
- A real production hybrid pipeline (sparse list + dense list kept
  separate → RRF → a cross-encoder reranker re-scoring the fused
  top-N) would need both: (1) retaining each chunk's own dense/sparse
  score through fusion, and (2) a real reranking model/library choice -
  the latter is a new-library decision, not something to pick
  unilaterally (project convention: no unreviewed library additions).
  Flagged, not started - needs a confirmed library choice before any
  spec gets written.

## No corrective action when an answer's eval score is below threshold (found 2026-10-19)

`eval_score_threshold` (Settings → RAG Config) only ever flags an
already-generated answer for display - confirmed by reading
`ai/rag_core/eval_threshold.py`'s `check_eval_threshold()` (compares
scores, returns `(breached, breached_metrics)`, takes no corrective
action) and its 3 call sites (`pipeline.py`, `orchestration_agent.py`,
`multi_agent_pipeline.py`), none of which branch on the result - the
flag is stored straight into `eval_scores["below_threshold"]` for the
UI. No retry, re-retrieval, or regeneration happens anywhere when a
score is low; this was previously undocumented as its own gap (the
existing `BACKLOG.md` "Retry / circuit breaker" entry is scoped to
transient API failures, not low eval scores - a different problem).
The Explainability panel's own "Loop Engineering" card already says
this honestly ("No loop - one-shot parallel fan-out... no agent re-
runs"), so the UI isn't misrepresenting anything. Building a real
corrective loop (e.g. re-retrieve with a wider top_k, or regenerate
once with a stricter prompt, when groundedness/completeness/precision
breaches threshold) is new scope - needs its own spec (loop-exit
condition, max-retries bound, latency/cost impact) before
implementation, not started here.

## 2 NFR golden-dataset cases now fail - confirmed pre-existing model/library drift, not a regression (found 2026-10-19, during Phase 229)

While live-verifying Phase 229's guardrails refactor (`check_input()`/
`check_output()` switched from NeMo's `check_async()` convenience
wrapper to calling `generate_async()` directly - see RAG-ROADMAP.md),
running the real (non-mocked, `pytest -m eval`) NFR suite surfaced 2
new failures beyond the 1 already-documented `false_positive-04` issue:
`pii-01` (SSN in a question) now scores `pass` instead of the dataset's
expected `blocked`; `pii-03` (credit card number) now scores `blocked`
instead of the dataset's expected `masked`. Both reproduced consistently
across 3 repeated runs each (not flaky/non-deterministic noise).

**Confirmed NOT caused by Phase 229's refactor** - the exact same 2
queries run through NeMo's own, completely unmodified `check_async()`
(bypassing this project's code entirely) produce the identical results
(`PASSED`/`None` for pii-01, `BLOCKED`/`self check input` for pii-03).
This is real drift in the underlying `self check input` LLM judgment
(and/or the `gpt-4.1-mini` model version behind it) since the dataset's
own "verified live 2026-09-22" notes were written, not a code bug -
flagged, not silently fixed by editing the dataset's expected values or
papering over the test. `nfr_golden_dataset_harness.py`'s own test
already separates "known, already-documented" failures from new ones in
its output, so these 2 show up correctly as new - not something to
silence there either. Needs a decision: re-verify and update the
dataset's expected outcomes, or treat this as a real quality signal
worth investigating (why self-check's own judgment shifted) - not
decided here.

## 2 pre-existing bugs found while reading retriever.py/bm25_search.py for Phase 231 (Document ACL) - confirmed, not fixed (2026-10-19)

Neither is caused by or related to ACL's own correctness (the `$nin`
clause Phase 231 adds is always a sibling of any self-query clause under
`$and`, never nested inside one) - found incidentally while reading this
code closely for an unrelated change, flagged per "flag, don't fix," not
silently patched alongside Phase 231's own diff.

- **`DocumentRecord.from_row()` (`models/documents.py`) passes `chunk_ids`
  straight from a metadata-store row into a `list[str] | None` Pydantic
  field without `json.loads()`-ing it first** - both `sqlite_client.py`
  and `postgres_client.py` store it as a JSON-encoded string (confirmed:
  `json.dumps(chunk_ids)` on write, same convention this phase's own
  `restricted_roles` column follows correctly). Confirmed live with a
  direct Pydantic check: `list[str]` rejects a raw JSON string outright
  (`validation error ... Input should be a valid list`), not silently
  coerced. This means `GET /v1/genai-rag/ingest-document/documents` or
  `GET .../{id}` would 500 for any REAL indexed document (non-null
  `chunk_ids`) against a real SQLite/Postgres backend - not exercised by
  the existing test suite, which uses `FakeMetadataStore` but apparently
  no test combines "index a document" + "assert the full `DocumentRecord`
  response shape" in one place. Worth a dedicated fix-and-regression-test
  phase, not touched here (out of Document ACL's own scope).
- **`bm25_search.py`'s `_matches_metadata_filter()` (now `_matches_filter_clause()`)
  mishandles a `$eq`-wrapped equality clause** - the shape Self-Query's
  own LangChain translators actually produce (e.g. `{"doc_category":
  {"$eq": "benefits"}}`), not a flat value. The existing code only special-
  cased `$ne` inside a dict condition; a `$eq`-wrapped dict falls through
  to `actual != condition`, comparing a plain metadata value to a dict,
  which can never be equal - so a Self-Query filter combined with
  `search_keyword`/`search_hybrid`/`search_knn` (the BM25/exact-KNN
  strategies, all three share this function) silently returns zero
  results whenever Self-Query parses a filter, not the real candidate
  set. Only noticed because Phase 231 added `$and`/`$nin` support to this
  same function and had to read it closely; the `$eq` gap predates this
  phase and is unrelated to ACL's own correctness. Worth a dedicated fix
  (add `$eq` handling, parallel to the existing `$ne` case) with its own
  regression test, not folded into this phase's diff.
