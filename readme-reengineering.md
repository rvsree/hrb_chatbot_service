# HRB Chatbot — Microservices Re-engineering Reference

Working reference for the microservices decoupling effort discussed across
several sessions starting 2026-10-20. Not a spec (no `**Spec:**` block in
RAG-ROADMAP.md yet — nothing here has started implementation) — a map of
what's been decided, what's documented, and what's still open, kept at the
repo root the same way `readme-linkedin-articles.md` is.

## Documentation map

All docs live in `docs/dev-reference/`. The first four are cross-cutting;
the rest are per-component, each a full 5-tab set (Overview / Spec /
Architecture / Design / Decisions) matching this project's existing feature
doc convention (e.g. `multi-agentic-rag/`, `request-unpaid-leave/`).

| Doc | Covers | Status |
|---|---|---|
| `service-boundary-decision.html` | What splits and why; modular-monolith-first recommendation | done |
| `microservices-rollout-plan.html` | Shared-library strategy, schema naming, 4-phase sequence | done |
| `microservices-interface-matrix.html` | Per-component upstream/downstream, backend touchpoints, connector dependency matrix, NFR callouts, doc template | done |
| `user-journey-capability-map.html` | 7 real user journeys, capabilities derived from each, not assumed top-down | done |
| `nfr-platform-components/` | Prerequisite: shared resiliency/observability/security-baseline layer | done, 5 tabs |
| `common-libs-connectors/` | Prerequisite: `hrb_common_libs`, 10 extras mapped to real `common/clients/` folders | done, 5 tabs |
| `api-gateway-service/` | First service to build | done, 5 tabs |
| `rag-ingestion-service/` | RAG ingestion split | not started |
| `rag-retrieval-service/` | RAG retrieval split, houses Support/platform internally | not started |
| `chat-audio-service/` | Future capability | not started |
| `employee-401k-service/` | Future capability (A2A hub + sub-agents) | not started |
| platform package's own doc | CI/CD dashboard, interview-qa, mcp-tools | not started — co-located in rag-retrieval-service, still gets its own doc |

## Repos created (scaffolding only, no business logic yet)

| Repo | Contains | Status |
|---|---|---|
| [hrb_common_libs](https://github.com/rvsree/hrb_common_libs) | 11-extra connector package (an eleventh, `vectorstore`, was added after finding a real scope gap) | **All phases done**, 53/53 tests passing, tagged `v0.3.0` |
| [hrb_api_gateway_service](https://github.com/rvsree/hrb_api_gateway_service) | RBAC/CORS/rate-limit/contract-validation Gateway | Phase 1 (CORS + rate limit) done, 9/9 tests passing |
| [hrb_platform_components](https://github.com/rvsree/hrb_platform_components) | interview_qa, build_deployment, mcp_catalog | scaffolded, pushed — deployment model (standalone vs. mounted) still open, flagged in its own CLAUDE.md |

Each has its own `CLAUDE.md`, `ROADMAP.md` (empty of specs, phases listed), and `.claude/` (skills, agents, `spec_gate.py` hook) — independently workable by a fresh Claude Code session against any one of them.

## Implementation plan, starting from prerequisites

**Phase 0 — Foundations (zero behavior change, lowest risk)**
1. `hrb_common_libs` repo — extract `common/clients/`'s 9 folders into 10
   installable extras (`observability` new, the rest extracted).
2. Postgres schema migration — create `rag_ingestion`, `rag_retrieval`,
   `chat_hitl`, `chat_audio`, `interview_qa`, `build_deployment`,
   `chat_metrics`, `admin_controls`, `employee_401k`, `mcp_registry`; move
   existing tables via `ALTER TABLE ... SET SCHEMA`; update every
   `*_store.py` to qualify table names.
3. Rename `hrb_chatbot_service` → `hrb_chatbot_service` (repo/folder/LangSmith
   default — AWS resources already named `hrb-chatbot`, so this is cheap).

**Phase 1 — `api_gateway_service` (additive, fronts the still-undivided backend)**
4. Redis live in production — hard prerequisite now (rate-limiting needs
   shared state across replicas), not a nice-to-have.
5. Build the Gateway: absorbs `api/gateway/rbac.py`'s role, CORS, rate-limit,
   contract validation. See `api-gateway-service/` for the full design.
6. Point `hrb_chatbot_ui` at the Gateway, which forwards 1:1 to
   `hrb_chatbot_service` — proves the Gateway before anything else splits.

**Phase 2 — Split RAG ingestion / retrieval (the real migration, highest risk)**
7. New repos: `hrb_rag_ingestion_service`, `hrb_rag_retrieval_service`, both
   depending on `hrb_common_libs`.
8. Move code per the interface matrix's boundaries; Support/platform
   co-locates inside `hrb_rag_retrieval_service`.
9. New ECR/App Runner/IAM per service, mirroring the existing deploy.yml
   pattern.
10. Keep `hrb_chatbot_service` dormant as rollback safety net until both
    new services are verified against real production traffic.

**Phase 3 — New capabilities (parallel-safe, zero migration risk)**
11. `chat_audio_service`, `employee_401k_service` — new repos, can start
    anytime since they touch no existing working code.

## Known blind spots — not yet decided

Carried over from earlier review plus a few found while writing the
per-service docs:

- **Local dev orchestration.** Once there are 4+ services, running a full
  user journey locally needs a `docker-compose.yml` spinning up Gateway +
  ingestion + retrieval + (optionally) `hrb_lms_mcp` together. No such file
  exists yet — today everything is one `uvicorn` command.
- **Cross-service contract/integration testing.** Each service's own unit
  tests don't catch a Gateway/backend contract drift. Needs a decision:
  consumer-driven contract tests, or a thin cross-repo integration suite,
  or accept the risk and catch it via Postman/manual testing for now.
- **LangSmith project naming once split.** Today: `hrb_chatbot_service_local`/
  `_prod`. Once there are 5+ services, is it one shared project tagged by
  service name, or one project per service? Not decided.
- **Health-check aggregation.** The Gateway's own `/health` checking each
  downstream's `/ping` is proposed in `api-gateway-service/design.html`
  but not yet validated against a real multi-service deployment.
- **Secrets duplication across repos.** `POSTGRES_DB_HOST` etc. will be
  needed by multiple services once split — each repo gets its own copy in
  Secrets Manager today; no shared-secret mechanism decided.
- **API versioning across service boundaries.** Once Gateway and backends
  deploy independently, a breaking change to a backend's contract needs a
  real versioning story (URL versioning already exists as a pattern via
  `/v1/`; whether that's sufficient once contracts change independently
  per-service is untested).
- **mcp_registry's real ownership** — still unconfirmed whether it's
  genuinely a separate shared database/service or belongs in this
  project's own schema list (flagged since `service-boundary-decision.html`
  v1, not yet resolved).
- **`rag_search` vs `rag_retrieval` naming** — resolved in favor of
  `rag_retrieval` (matches the live `-retrieval` route suffix), flagged for
  final confirmation, not yet explicitly confirmed by the user.

## Working norms for this effort specifically

- One service's doc set at a time, full depth (Overview/Spec/Architecture/
  Design/Decisions) — not a combined summary across services. This file
  itself exists because a combined summary was tried first and found
  insufficient.
- No repo gets created until its phase actually starts (see Phase sequence
  above) — confirmed with the user 2026-10-20.
- Every new repo gets its own `CLAUDE.md` + `.claude/` folder at creation
  time — the workflow pieces (skills, hooks, subagents, the 4 working
  norms) port over with paths repointed; the project-specific docs
  (coding standards, roadmap history) start empty and earn their content
  the same way this repo's did.
