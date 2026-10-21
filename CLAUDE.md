# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An HR benefits chatbot backed by a RAG pipeline over the JPMC benefits knowledge base (`resources/kb_docs/`). Being built by hand, one feature at a time, to apply RAG concepts from the Interview Kickstart FDE cohort. **[docs/agent-reference/RAG-ROADMAP.md](docs/agent-reference/RAG-ROADMAP.md) is the source of truth for what's actually done** - phase-by-phase history, not aspirational. [docs/agent-reference/BACKLOG.md](docs/agent-reference/BACKLOG.md) lists known gaps and planned work; don't assume something is missing/broken without checking there first.

FastAPI backend, Python 3.12 only (not 3.13/3.14 - `chromadb` depends on removed Pydantic v1 internals). Everything imports as `from src.hrb_chatbot....` - `src/__init__.py` exists on purpose, always run as a module from the repo root, never from inside `src/`.

## Commands

```powershell
# install
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

# run (local dev)
.venv\Scripts\python.exe -m uvicorn src.hrb_chatbot.main:app --reload --port 8093

# full test suite
.venv\Scripts\python.exe -m pytest -v

# single test file / single test
.venv\Scripts\python.exe -m pytest tests/hrb_chatbot/api/rag/test_routes_documents.py -v
.venv\Scripts\python.exe -m pytest tests/hrb_chatbot/api/rag/test_routes_documents.py::test_name -v

# with coverage (CI enforces --cov-fail-under=45, a ratchet floor, not a target)
.venv\Scripts\python.exe -m pytest -v --cov=src/hrb_chatbot --cov-report=term-missing --cov-fail-under=45

# security gates CI runs (bandit blocks on MEDIUM+, pip-audit is report-only)
bandit -r src/hrb_chatbot -ll
pip-audit -r requirements.txt

# docker
docker buildx build --provenance=false --sbom=false --output type=docker -t hrb-chatbot:local .
docker run --rm --env-file .env -p 8093:8093 hrb-chatbot:local
```

No test needs a real API key, network call, or costs money - `tests/conftest.py`'s fakes match every real client's method signature exactly, so tests run identically with or without `.env` configured. `pytest.ini` sets `asyncio_mode = auto`, so `async def test_...` needs no `@pytest.mark.asyncio` decorator. Test files mirror `src/` paths 1:1 (e.g. `src/hrb_chatbot/ai/doc_processing/chunking/text_chunker.py` -> `tests/hrb_chatbot/ai/doc_processing/chunking/test_text_chunker.py`).

`git config core.hooksPath .githooks` (not on by default) enables a pre-commit hook that blocks committing anything matching a real API key pattern.

## Architecture

### Request flow

`main.py` (FastAPI app + global exception handlers) -> **gateway** (`api/gateway/`, Phase 23 - role-based access, wired as `dependencies=[...]` at `app.include_router(...)` level, not inside individual routes) -> `api/**/*.py` (routers, one per resource, Pydantic request/response models only - see `models/`; `routes_health.py` keeps the old `routes_*.py` naming, but ingestion/retrieval are `ingest_document.py`/`retrieve_document.py` - named for the resource, not prefixed) -> `services/*.py` (thin orchestration layer, exists so routers never import `ai/` directly - **except `retrieve_document.py`**, which calls `ai/rag_pipeline/pipeline.py` directly; `services/rag_service.py` was removed 2026-09-21 after review found it was a literal one-line pass-through with no logic of its own, unlike `documents_service.py`, which has real logic - content-hash dedup, supersedes handling, file validation - and keeps its layer) -> `ai/**/pipeline.py` (the actual RAG logic) -> `common/clients/**` (one class per external backend, behind a gateway).

There are **two separate pipelines** under `ai/`, easy to confuse by name:
- `ai/doc_processing/pipeline.py` - **ingestion**: extract PDF text -> chunk -> embed -> index, all in one call. Driven by `POST /v1/genai-rag/ingest-document/documents` (`api/rag/ingest_document.py`). Gateway-restricted to `HR_SUPPORT` only.
- `ai/rag_pipeline/pipeline.py` - **query**: decompose -> retrieve -> generate. Driven by `POST /v1/genai-rag-retrieval/query` (`api/rag/retrieve_document.py`; Phase 99 renamed this path, alongside `single-agentic-rag`/`multi-agentic-rag`'s own query paths, to a consistent `-retrieval` suffix - ingestion's own path is untouched). Gateway-open to `EMPLOYEE`/`MANAGER`/`HR_SUPPORT`, uniformly.

**Three retrieval modes share one guardrail/memory/logging core - Phase 98:** `genai-rag` (`ai/rag_pipeline/pipeline.py`), `single-agentic-rag` (`ai/agents/workflow_agents/orchestration_agent.py`), and `multi-agentic-rag` (`ai/agents/workflow_agents/multi_agent_pipeline.py`) each do their own answer-generation (fixed retrieve-then-generate vs. a tool-calling loop vs. a LangGraph multi-agent graph - genuinely different, not shared) but funnel through `ai/rag_core/guarded_pipeline.py::run_guarded_pipeline()` for input guardrail / conversation-memory load-save / output guardrail / logging. This exists because three pipelines each independently deciding whether to wire those in is exactly how `single-agentic-rag` shipped with **no guardrails at all** until this phase - found by a direct code review, not assumed. `multi-agentic-rag` still calls `check_input`/`check_output` directly rather than through the shared core (an earlier, still-correct implementation, not yet migrated - its own later phase, not a currently-known gap). The answer cache (Phase 78) and the MCP keyword fast-path both stay `genai-rag`-only, deliberately - caching a tool-driven answer that can depend on live data (e.g. a leave balance) would be a real correctness bug, so neither moved into the shared core.

**Gateway identity is a placeholder, not real auth** - `api/gateway/rbac.py`'s `require_role(user_profile, *roles)` reads an unsigned, caller-supplied `user_profile` sub-object (`employee_id`/`full_name`/`role`) straight from the JSON request body, on every endpoint including `GET`/`DELETE` (Phase 45 - non-standard HTTP, a deliberate choice so there's one identity mechanism everywhere, not several) - not headers, not query params, both tried and rejected during that phase. It's a single function: 401 if `user_profile` is missing or its role isn't a real `Role` value, 403 if the role isn't one of the ones the route allows. Real OAuth is deferred (empty placeholder: `common/clients/auth_client/oauth_client.py`). Since `role` is self-asserted in the same request it gates, RBAC today is a formality, not a real control - accepted deliberately, see `docs/agent-reference/endpoint-request-response-contracts.md`.

**One narrow, confirmed exception to "not query params" - Phase 96:** the three `GET` routes in `api/rag/ingest_document.py` (`list_documents`, `get_document`, `preview_test_noise_documents`) read identity from query params via `api/gateway/rbac.py`'s `identity_from_query_params()`, not the body. This isn't a reversal of Phase 45's reasoning for POST/DELETE (those keep the body, unchanged) - it's new information Phase 45 didn't have: the Fetch spec forbids a body on `GET`/`HEAD` entirely, confirmed by `fetch()` throwing `TypeError: Request with GET/HEAD method cannot have body` before any network call. A real browser client - `hrb_chatbot_ui`, concretely - can never call a body-based `GET` route at all; this was discovered building that project's document-management page, not guessed at. `require_role()` itself is unchanged; only the transport for these three routes' identity changed.

`ai/agents/`, `ai/pre_processing/` (guardrails, query decomposition, search filtering), `ai/rag_pipeline/helper/access_control.py`, `ai/rag_pipeline/tools/`, and `common/observability/` are empty placeholder files (0 bytes) - scaffolding for future phases per the roadmap, not dead code to clean up.

### Three different libraries, one per pipeline stage, deliberately

This mirrored the workshop's own module structure originally - not an
accident. **Indexing moved off LlamaIndex onto LangChain in Phase 17**
(2026-09-14); see `docs/agent-reference/FAQ.md`'s "Why indexing moved off LlamaIndex" entry
for the reason given at the time (LangChain's `index()` gives real
skip-if-unchanged + cleanup for free). **This was never actually settled -
the user's standing preference, restated 2026-09-19, is the course's own
LlamaIndex-based indexing approach** (`VectorStoreIndex`, per the original
Phase 3 implementation at commit `b5870b9`, before Phase 17 replaced it).
Phase 44 is reverting indexing back onto LlamaIndex for this reason - see
`docs/agent-reference/RAG-ROADMAP.md`. Don't further "consolidate" chunking or retrieval
onto a different library without a recorded reason confirmed with the user,
not just asserted:
- **Chunking** (`ai/doc_processing/chunking/text_chunker.py`) - LangChain's own splitters, 6 selectable strategies via a `CHUNKING_STRATEGIES` dict (name -> function), auto-selected by `decide_chunking_strategy()` when not given explicitly.
- **Indexing** (`ai/doc_processing/indexing/vector_indexer.py`) - LangChain's own `index()` + `SQLRecordManager` (Phase 17) for the actual vector write, via the shared builder in `common/clients/db_client/langchain_vector_store.py`; everything around it (which document supersedes which, `is_current` flips) stays this project's own logic - `SQLRecordManager` has no concept of one document replacing a different one.
- **Search/retrieval** (`ai/rag_pipeline/query_retrieval/retriever.py`) - raw LangChain (`langchain_chroma`/`langchain_pinecone`), two plain functions (similarity, MMR) via a `SEARCH_STRATEGIES` dict, no classes - matches the workshop demo's own style. Phase 20 layers LangChain's own `MultiQueryRetriever`/`SelfQueryRetriever` classes on top of either (`RagQueryRequest.use_multi_query`/`use_self_query`) - these two are genuine LangChain classes, not hand-written, since the retrieval-rewriting/filter-parsing logic they implement isn't something this project's own code needs to reinvent. Both need a real LangChain `BaseChatModel`; see `common/clients/llm_client/langchain_chat_model.py`'s `GatewayChatModel` (a small adapter over this project's own multi-provider `ask()` clients, not one of LangChain's own per-provider packages - `docs/agent-reference/RAG-ROADMAP.md`'s Phase 20 entry has the real dependency conflict that ruled those out).

### Backend abstraction: gateways + enums, not scattered if/elif

Every external backend (LLM provider, vector store, metadata store) has a `Base*Client` ABC (`common/clients/*/base_*.py`) that every concrete client implements identically, and a singleton `*Gateway` (`client_gateway.py`, `db_gateway.py`) that builds each client lazily and caches it. Calling code never branches on provider outside the gateway. Which provider to use is a `src/hrb_chatbot/common/enums.py` `StrEnum` (`VectorDB`, `MetadataStore`, `LlmProvider`) everywhere it's a request parameter (Pydantic model field or FastAPI `Query`) - this is what makes an unknown provider name a clean 422 at the API boundary instead of silently falling through to a default or failing deep in the pipeline. Free-text fields that are genuinely open-ended (model names like `gpt-4.1-mini`) stay plain `str`, not enums.

### Health checks: two endpoints, not a toggle

`GET /ping` - process-is-up only, no provider calls, instant. This is what Docker's `HEALTHCHECK` and the CI deploy smoke test point at. `GET /health` - always makes one real (but free) call per backend and reports `{"status": "healthy"|"unhealthy", "message": "..."}`; `health_check()` never raises. See [docs/agent-reference/CODING-STANDARDS.md](docs/agent-reference/CODING-STANDARDS.md) for the full convention (error-handling-by-layer, comment style, naming) - read it before touching client or route code.

### Error handling by layer (see CODING-STANDARDS.md for the full table)

Client layer (`common/clients/**`) returns errors as data (`{"status": "unhealthy", ...}`), never raises from `health_check()`. Service layer raises exceptions. Route layer (`api/**/routes_*.py`) catches them and returns a consistent `{"error": "...", "code": "..."}` shape via `api/dependencies.py`'s `json_error()` - `code` is a stable value from `common/error_codes.py`, always picked explicitly, never defaulted.

## Docs worth reading before non-trivial changes

- [docs/agent-reference/HANDOFF.md](docs/agent-reference/HANDOFF.md) - **read this one first** if picking up the project with no prior context; it's the orientation layer everything else points into (also has the real current branch names - `master`/`develop`/`feature-langchain-rag-pipeline` - after a GitHub rename that left stale `main`/`developer` references elsewhere in git history).
- [docs/agent-reference/RAG-ROADMAP.md](docs/agent-reference/RAG-ROADMAP.md) - phase-by-phase history and current status; historical, not updated retroactively.
- [docs/agent-reference/CODING-STANDARDS.md](docs/agent-reference/CODING-STANDARDS.md) - error handling, logging, comment style, naming, API contract conventions.
- [docs/agent-reference/FAQ.md](docs/agent-reference/FAQ.md) - design-decision rationale (document update strategy, where RAG metadata lives, indexing/categorization).
- [docs/agent-reference/BACKLOG.md](docs/agent-reference/BACKLOG.md) - known gaps, deliberately deferred work.
- [docs/agent-reference/CICD-BRANCHING-STRATEGY.md](docs/agent-reference/CICD-BRANCHING-STRATEGY.md) - branch roles (`feature-*` -> `develop` -> `master`), every CI gate and its threshold.
- [docs/agent-reference/AWS-DEVOPS-RUNBOOK.md](docs/agent-reference/AWS-DEVOPS-RUNBOOK.md) - container -> ECR -> App Runner pipeline, required build flags and why.
- [docs/agent-reference/TESTING-GUIDE.md](docs/agent-reference/TESTING-GUIDE.md) - what's covered, why those cases, the fake-based pattern to copy.
- [docs/agent-reference/S3-ASYNC-UPLOAD-DESIGN.md](docs/agent-reference/S3-ASYNC-UPLOAD-DESIGN.md) - design only, not implemented: today's upload/index is synchronous, local-disk, in-request - don't assume S3/Lambda/async exists anywhere in the actual code.
- [docs/agent-reference/SDD-SPEC-SHEET.md](docs/agent-reference/SDD-SPEC-SHEET.md) - the SDD lifecycle, file map, and a worked example (Phase 16), written as a standalone reference for learning the process, not just following it.
- [postman/hrb_chatbot.postman_collection.json](postman/hrb_chatbot.postman_collection.json) - every endpoint's happy path + edge cases, kept in sync with actual behavior; update it alongside any request/response contract change.

**Developer reference diagrams** (`docs/dev-reference/`, separated 2026-09-25 from the docs above): visual/status companions built to understand the system at a glance - not load-bearing for the SDD process itself (no hook or skill reads anything in this folder), safe to skim, skip, or regenerate without affecting `spec_gate.py` or any skill.

- [docs/dev-reference/rag-pipeline-status.md](docs/dev-reference/rag-pipeline-status.md) - IK FDE cohort Modules 1-6 vs what's actually implemented, plus a colored Mermaid diagram tracing the full `POST /v1/genai-rag/retrieve-document/query` request lifecycle against the six-layer validation gateway framework (this project's own addition, not part of the FDE course); regenerate after Module 5/6 work or gateway-layer work lands rather than hand-editing, since it can drift from `docs/agent-reference/RAG-ROADMAP.md`'s own status table.
- [docs/dev-reference/rag-validation-gates.html](docs/dev-reference/rag-validation-gates.html) - same six-gate content as the file above, as a standalone visual infographic (numbered pill bands, one per gate, real stages as colored cards) for sharing/presenting rather than reading in an editor; regenerate alongside `rag-pipeline-status.md` so the two never drift apart.
- [docs/dev-reference/rag-architecture-layers.html](docs/dev-reference/rag-architecture-layers.html) - the same query request traced by **system layer** (API -> Gateway -> Orchestration -> Retrieval -> Generation -> Response) instead of validation gate, with the actual library/framework and model per stage - complementary to `rag-validation-gates.html`, not a duplicate of it.
- [docs/dev-reference/rag-guardrails-design.html](docs/dev-reference/rag-guardrails-design.html) - originally a pre-Phase-7 design blueprint; both input/output guardrails are implemented now (`ai/pre_processing/guardrails_input.py`, `ai/rag_pipeline/response_generation/guardrails_output/` are no longer empty) - the page itself was updated in Milestone 4 to reflect that, kept for the real due-diligence trail (why NeMo Guardrails over Guardrails AI, the RunnableRails pivot).
- [docs/dev-reference/database/db-model-overview.html](docs/dev-reference/database/db-model-overview.html) - every Postgres database/schema this project touches or could touch: its own document-metadata store, the shared `hr_chatbot` database's `hrb_chatbot_service_core`/`hrb_chatbot_service_sessions` schemas (bounded-context, no FKs - a deliberate capstone-project simplification), the reused MCP registry, and the external `hrb_emp_lms` tables accessed only via MCP, never direct SQL.
- [docs/dev-reference/auth/oauth2-auth-architecture.html](docs/dev-reference/auth/oauth2-auth-architecture.html) - human-to-app (still design only) and app-to-app (real, live, Phase 53) OAuth2 - the real client-credentials flow between this project and `hrb_lms_mcp`, including the dead-API-key finding it replaced.
- [docs/dev-reference/mcp/mcp-integration-overview.html](docs/dev-reference/mcp/mcp-integration-overview.html) - the four MCP phases (49 routing, 50 registry, 53 auth, 52 planned analytics server) tied together into one request-flow picture.
- [docs/dev-reference/auth/oauth2-cot-feasibility.html](docs/dev-reference/auth/oauth2-cot-feasibility.html) - feasibility assessment (historical) for human-to-app OAuth2 and Chain-of-Thought/reasoning-trace capture; its app-to-app section is superseded by `oauth2-auth-architecture.html` (real now), human-to-app half still accurate.
- [docs/dev-reference/design/scaling-latency-design.html](docs/dev-reference/design/scaling-latency-design.html) - this project's own request-latency budget, caching/scaling levers, and what changes once agentic-rag adds multi-step tool calls - written for the "scale beyond Docker/Kubernetes" interview question.
- [docs/dev-reference/auth/auth-server-project-scope.html](docs/dev-reference/auth/auth-server-project-scope.html) - scope/design for a possible separate `hrb_auth_server` project (Authorization Server, separate from both `hrb_chatbot_service` and `hrb_lms_mcp`'s Resource Server roles) - planning only, not started.
- [docs/dev-reference/rag-retrieval/rag-pipeline-current-state.html](docs/dev-reference/rag-retrieval/rag-pipeline-current-state.html) - the target-state multi-layer architecture (Client/Edge/API/Workflow/Agents lanes) filled in with what's actually built and live-verified vs. future scope, lane-for-lane comparable to a target-state diagram from outside this project.
- [docs/dev-reference/IK-FDE/course-topic-coverage-review.html](docs/dev-reference/IK-FDE/course-topic-coverage-review.html) - all 69 techniques named across the IK FDE cohort's 6 workshop modules, checked against this project's real code - status only (built/partial/not built), no ranking or defer/drop recommendation.
- [docs/dev-reference/react_agents/multi-agent-orchestration.html](docs/dev-reference/react_agents/multi-agent-orchestration.html) - beginner walkthrough of the IK FDE Multi-Agent Travel Planner class (LangGraph orchestrator -> parallel workers -> synthesizer, `Send()` fan-out, sub-agent-as-a-tool) plus a status check against this project's current single-agentic-rag - planning material for a future multi-agentic-rag phase, nothing implemented yet.
- [docs/dev-reference/react_agents/multi-agentic-rag-fit-plan.html](docs/dev-reference/react_agents/multi-agentic-rag-fit-plan.html) - a direct critique of gaps in the FDE sample notebook's own implementation, plus how real orchestration logic would fit on top of Phase 61's scaffold (`POST /v1/multi-agentic-rag/query`) by reusing genai-rag/single-agentic-rag's existing building blocks (retrieval, tools, conversation memory, guardrails) without changing either endpoint - two open decisions flagged (parallel-dispatch mechanism, domain-agent file layout), not made here.

## Spec-Driven Development (SDD)

Adopted 2026-09-14, adapted from a reference pattern (Joshua McDonald's
"Spec-Driven Development with Claude Code") written for an unrelated project.
The core idea, unchanged: **skills are guidance the model can ignore on a
given turn; hooks run on a deterministic path outside the model's control.**
Neither alone is enough - a skill can be skipped under time pressure, a hook
can't be talked out of running.

**No separate `specs/`/`adr/` folder exists here, on purpose.** This project
already had the equivalent: [docs/agent-reference/RAG-ROADMAP.md](docs/agent-reference/RAG-ROADMAP.md) is
both the plan and the history (phase-by-phase, with a "Status at a glance"
table), and [docs/agent-reference/FAQ.md](docs/agent-reference/FAQ.md) already carries decision rationale the
way an ADR would. Adding parallel spec/ADR folders would just create a second
source of truth for the same information - the opposite of what this
codebase's own conventions (single source of truth for defaults, one gateway
per backend type, etc.) are built around. So: **a spec is a `Spec:` sub-list
written into a phase's own bullet** in `docs/agent-reference/RAG-ROADMAP.md`'s `## Phases`
section, before that phase's code starts - see
`.claude/skills/spec-new/SKILL.md` for the exact template. The 14 phases
shipped before this convention existed are marked `Retrofitted (pre-SDD)` in
the "Status at a glance" table's `Spec` column rather than reconstructed after
the fact - their detailed write-ups in `## Phases` already serve as the
historical record.

**One deliberate exception to "no separate file," added 2026-09-20:**
[docs/agent-reference/endpoint-request-response-contracts.md](docs/agent-reference/endpoint-request-response-contracts.md)
holds every endpoint's finalized request/response/error shape, confirmed
there directly with the user *before* a phase's own Spec block is written,
not folded into a phase's bullet. Endpoint shapes get renegotiated over many
turns before a phase number even exists (Phase 45's identity redesign is
the example that forced this) - cramming that back-and-forth into one
phase's bullet made both hard to read. A phase's own `**Spec:**` block
points at the relevant section of that file instead of re-deriving the wire
shape inline; `.claude/skills/spec-new/SKILL.md`,
`spec-review/SKILL.md`, and `spec-implement/SKILL.md` all reference it. This
is a recorded exception, not a drift back toward parallel spec/ADR folders -
everything else still lives in `docs/agent-reference/RAG-ROADMAP.md`/`docs/agent-reference/FAQ.md`.

**Four working norms that apply everywhere, not just to SDD:**
- **One task at a time.** No multi-file autonomous changes across unrelated
  concerns. Finish one phase/task, report, wait for review.
- **Flag, don't fix.** Something noticed outside the current task's scope
  gets a one-line note in the delivery note (see below), not an unprompted
  fix.
- **Nothing gets pushed/deployed/synced to AWS without the user's own local
  review and explicit go-ahead first - 2026-10-14.** Implement and self-
  verify locally, then stop and wait for confirmation before any `git push`,
  `scripts/sync_admin_docs.py` run, or other action that changes what's
  live in production. This applies even when a push is clearly the obvious
  next step - ask anyway, every time, not just the first time.
- **Docs stay in sync with reality - 2026-10-14.** Any design, architecture,
  or major implementation change must be reflected in that feature's own
  `docs/dev-reference/<feature>/` doc set (Spec/Architecture/Design/
  Decisions) before the work is considered done - not left for a later
  catch-up pass. The updated docs then need `python -m
  scripts.sync_admin_docs` run against them so the live admin-docs S3
  bucket and the `doc_metadata` table (which tracks `doc_version` by
  content-hash, so an unchanged file is a no-op) actually reflect what's
  in the repo - gated by the no-push-without-go-ahead norm just above,
  same as any other push.

**Available skills** (`.claude/skills/<name>/SKILL.md`, each also a
`/<name>` slash command):
`session-start` (loads branch/open work), `delivery-note` (concise end-of-
task summary), `spec-new` (write a phase's spec), `spec-review` (audit a spec
before implementation), `spec-verify` (map tests back to a spec's acceptance
criteria after), `spec-implement` (execute one spec'd phase),
`coding-standards` (thin wrapper over `docs/agent-reference/CODING-STANDARDS.md`),
`architecture-review` (check a design against settled decisions in this file
and `docs/agent-reference/FAQ.md`).

**Subagents:** `.claude/agents/implementer.md` - executes one already-spec'd
phase in an isolated context. `.claude/agents/code-reviewer.md` - read-only,
flags `docs/agent-reference/CODING-STANDARDS.md`/scope/security issues on a phase's diff
before its roadmap checkbox flips to done; never edits or fixes ("flag,
don't fix" applies to it most of all). No `integrator` subagent (that
exists in the reference pattern for a multi-engineer team running parallel
mini-specs in separate worktrees - this is a solo developer plus one
Claude Code session, so there's nothing to integrate). No `spec-decompose`
skill for the same reason.

**No Core-AI-Engineering-is-owner-only restriction.** Some SDD setups (the
reference pattern's own source project included) restrict the agent from
touching retrieval/chunking/prompt-assembly code, reserving it for a human
owner. That doesn't apply here - Claude Code has built this project's full
RAG pipeline directly, phase by phase, with the user's explicit request and
review each time (see `docs/agent-reference/RAG-ROADMAP.md`'s Phase 4/14 entries). The
`implementer` subagent may work in any layer; its boundary is the phase's
spec, not an architectural layer.

**Hooks** (`.claude/settings.json`): `SessionStart` runs the session-start
check automatically; `PreToolUse` (`.claude/scripts/spec_gate.py`) blocks a
`Write`/`Edit` under `src/hrb_chatbot/**` unless `docs/agent-reference/RAG-ROADMAP.md` has at
least one `- [ ]` phase with a written `**Spec:**` block - added 2026-09-14
after Phase 16 (the content-hash duplicate-upload fix) proved the spec-first
convention out on a real change; `PostToolUse` runs the test suite in the
background after a `src/`/`tests/` edit and surfaces only failures; `Stop`
asks a small model whether the turn's own final message describes something
left untested/incomplete before letting the turn end, and denies (asks for
more work) only on a clear-cut case.

**What the `PreToolUse` gate does and doesn't check:** it confirms *a* spec
is open, not that the specific edit falls inside that spec's declared scope
- it can't verify that automatically. Staying in scope is `implementer.md`'s
job (a stated hard rule), not this hook's. It's also scoped to
`src/hrb_chatbot/**` only, deliberately - never `.claude/`, `tests/`, or
`docs/` - so a bug in the gate itself, or in any skill/hook file, can never
lock out fixing it (this is why the `Stop` hook's own prompt bug, found and
fixed live on 2026-09-14, was fixable at all: `.claude/settings.json` isn't
gated).
