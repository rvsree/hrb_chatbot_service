# Hand-off - start here

Written 2026-09-08, at the end of a session, because the user's laptop is
about to restart and this conversation's memory will be gone. If you are
a fresh agent (or the user, in a new session) picking this project back
up with zero context, **read this file first, before any other doc** -
it's the orientation layer; everything else in `docs/` is the depth layer
it points into.

## Update, 2026-09-08 - branches created, then renamed, plus real CI/CD gates

Branches were created, and then **renamed on GitHub's own UI within the
same session** - if you're reading git history and see `main`/`developer`/
`feature-kb-indexing-rag-pipeline` mentioned anywhere (including in
`docs/agent-reference/RAG-ROADMAP.md`'s Phase 13 write-up, which documents this
chronologically), those are the *original* names, already gone. **The
names that exist on GitHub right now are these:**

| Branch | Intent |
|---|---|
| `master` | Production/deploy branch - `deploy.yml` triggers on push here (was `main`) |
| `develop` | Integration branch - feature branches merge here first, fully gated (was `developer`) |
| `feature-langchain-rag-pipeline` | This session's working branch (was `feature-kb-indexing-rag-pipeline`) |

The generic `feature` parent branch from the first pass was deleted rather
than renamed - going forward, one `feature-<short-name>` branch per effort
instead (see [`CICD-BRANCHING-STRATEGY.md`](CICD-BRANCHING-STRATEGY.md)
for the naming convention and four concrete names already picked out for
planned work: `feature-react-multi-agent`, `feature-mcp-workflows`,
`feature-conversation-memory`, `feature-session-state-cache`).

**`hrb_rag_pipelines` (the original branch) still exists too** - not
deleted, just superseded. It's also still GitHub's *default* branch
(Settings → Branches hasn't been changed to `master` - a manual action,
not something a `git push` can do).

**A GitHub branch rename deletes the old ref outright, no redirect** - this
mattered for real: `deploy.yml`'s and `ci.yml`'s branch triggers both said
`main` literally, so after the rename they were triggers pointing at a
branch that no longer existed - silently (no error, the workflow just
never runs). **Both were fixed to `master` in the same change that
discovered this.**

**New this update - real CI/CD gates, not just the branch rename**: a full
branching-and-testing strategy doc now exists,
[`CICD-BRANCHING-STRATEGY.md`](CICD-BRANCHING-STRATEGY.md) - coverage
floor (`--cov-fail-under=45`, measured against the real 46% rather than
guessed), `bandit` static-security scanning (blocking, clean today),
`pip-audit` dependency-CVE scanning (report-only for now - real,
pre-existing CVEs were found; see that doc's triage plan before it can be
made blocking), and a real post-deploy smoke test in `deploy.yml` (waits
for App Runner to reach `RUNNING`, then `curl`s the live `/health`
endpoint - previously the workflow declared success the moment
`start-deployment` was *called*, not once the new container actually
answered). None of this needed AWS credentials or spent any money to add
or verify locally.

**Left as an open decision, not built without asking**: whether `develop`
should get its own staging App Runner deployment (a second, always-on AWS
service - real ongoing cost) versus staying test-only until a further PR
into `master`. Both options are laid out with their trade-offs in
`CICD-BRANCHING-STRATEGY.md`'s "Deployment targets" section - say the word
and it's a small, well-scoped follow-up.

Going forward, the flow is: work happens on a `feature-<name>` branch → PR
into `develop` (gated by the tests/coverage/security checks above) → PR
into `master` when ready to actually deploy. Nothing enforces this by
itself yet - no branch protection rules exist on GitHub (Settings →
Branches → Branch protection rules), so a direct push straight to `master`
still bypasses every gate; that's a repo-settings action, not something
done from here.

## TL;DR

This is a hand-built HR benefits RAG chatbot (AmazingBank benefits PDFs → chunk →
embed → index → retrieve → answer), built by the user personally to learn
RAG concepts from an Interview Kickstart FDE cohort. **Claude Code builds
boilerplate and infrastructure; the user hand-writes the actual RAG logic**
(chunking strategy, retrieval, generation, evaluation) - this split is the
single most important thing to not violate, see
[Division of labor](#division-of-labor---read-before-touching-anything-under-ai). Thirteen
phases are done (upload, index, deploy to real AWS, CI/CD, a full REST API
hardening pass, and now a real branch/testing strategy). **Update
2026-09-10**: the RAG query pipeline (`ai/rag_pipeline/pipeline.py`) is no
longer a stub - real retrieval + grounded generation exist now, built by
Claude Code on the user's explicit request (an override of the original
hand-written boundary, same pattern as Phase 4). Query decomposition
(Phase 5.1), guardrails (Phase 7), and evaluations (Phase 8) remain
hand-written and still open - see Phase 6 in `docs/agent-reference/RAG-ROADMAP.md` for
exactly what shipped and what's deliberately still missing.

## Current status snapshot

| Area | Status |
|---|---|
| Local dev (upload, index, health) | ✅ Working, verified live |
| Deployed to AWS App Runner | ✅ `RUNNING` - confirmed again right before this handoff was written (real `200` from `GET /health`) |
| RAG query (retrieval + generation) | ✅ MVP working, verified live with a real grounded answer - Claude-Code override, 2026-09-10. Decomposition/guardrails/evaluations still hand-written, still open |
| Document metadata + upload dedup | ✅ Done, 2026-09-10 - version/chunk_count/embedding info tracked. **Dedup removed 2026-09-13** - identical-content re-uploads are no longer detected, every upload creates a new document |
| Document versioning, table extraction, doc-metadata extraction | ✅ Done, 2026-09-11 - explicit supersede flow, retrieval excludes superseded chunks (verified live: a real query returned 0 sources from a superseded document, 5/5 from the current one), PDF tables extracted as markdown, LLM extracts owner/department/doc_category/purpose on first index (renamed from doc_type in Phase 57). Built/tested against ChromaDB; Pinecone portability by design (same interface), not yet exercised live - see Phase 4.4 in RAG-ROADMAP.md |
| CI (GitHub Actions) | ✅ Green - verified passing on GitHub itself, not just locally |
| CD (GitHub Actions → App Runner) | 🚧 Written, never actually triggered - see [Blocked on the user](#blocked-on-the-user---four-concrete-items) |
| Golden dataset | ✅ Done (22 cases, real facts from the real PDFs) - a one-time Claude-Code override of the hand-written boundary, same as chunking/embedding/indexing was. Now exercisable against the real query endpoint |
| REST API hardening (versioning, idempotency, rate limiting, error handling) | ✅ Done. **Idempotency removed 2026-09-13** (see BACKLOG.md) - versioning/rate limiting/error handling unaffected |
| Test suite | ✅ 56 tests, all passing, no test needs a key or network call |

Full phase-by-phase detail: [`docs/agent-reference/RAG-ROADMAP.md`](RAG-ROADMAP.md)'s
"Status at a glance" table - this snapshot is a summary of that summary;
if the two ever disagree, RAG-ROADMAP.md is the authority, not this file
(this file isn't kept live-updated the way that one is meant to be).

## Blocked on the user - four concrete items

Nothing here blocks continuing local development. These only block the
*deployment* pipeline going further:

1. **Neon Postgres signup** (free, at neon.tech) - `.env` still has
   `POSTGRES_DB_HOST=localhost` (confirmed right before writing this
   handoff), meaning the deployed App Runner service still runs
   `RAG_METADATA_STORE=sqlite` (ephemeral - wiped on every redeploy) as a
   documented, temporary compromise. Once Neon exists: create 5 secrets
   in AWS Secrets Manager (`hrb-chatbot/POSTGRES_DB_HOST/PORT/NAME/USER/PASSWORD`),
   flip `RAG_METADATA_STORE` to `postgres` via `apprunner update-service` -
   config-only, no rebuild. Full steps in
   [`docs/agent-reference/AWS-DEVOPS-RUNBOOK.md`](AWS-DEVOPS-RUNBOOK.md).
2. **Two GitHub Actions secrets never confirmed added** -
   `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` for the
   `hrb-chatbot-github-actions-deploy` IAM user, needed for `deploy.yml`.
   **A real, live AWS access key is still sitting in plaintext** at
   `C:\Users\sreed\AppData\Local\Temp\claude\...\scratchpad\github_actions_credentials.txt`
   on this machine - confirmed still present right before this handoff was
   written. Either copy it into GitHub (Settings → Secrets and variables →
   Actions) and delete the file, or delete the file and rotate the key if
   it's no longer wanted - don't leave it sitting there indefinitely.
3. ~~`main` branch doesn't exist on GitHub at all yet~~ **Resolved
   2026-09-08** - `master`, `develop`, and `feature-langchain-rag-pipeline`
   all now exist on GitHub (renamed from `main`/`developer`/
   `feature-kb-indexing-rag-pipeline` within the same session - see
   [Update, 2026-09-08](#update-2026-09-08---branches-created-then-renamed-plus-real-cicd-gates)
   above). `deploy.yml`'s trigger was updated to match. `deploy.yml` still
   hasn't actually run a real deploy though - the branch was created and
   renamed with plain `git push`/GitHub-UI actions, no new commits, and the
   next push to `master` that *would* trigger it will fail until item 2
   above (the GitHub secrets) is done.
4. **Two smaller, non-blocking decisions, both documented, neither urgent**:
   (a) whether `develop` should get its own staging App Runner deployment
   - a real ongoing AWS cost either way, see
   [`CICD-BRANCHING-STRATEGY.md`](CICD-BRANCHING-STRATEGY.md)'s
   "Deployment targets" section for the two options; (b) GitHub repo
   settings - the default branch is still `hrb_rag_pipelines`, not
   `master`, and no branch-protection rules exist requiring CI to pass
   before a merge - both are Settings-page actions, not code.

None of these are code problems - they're real-world account actions only
the user can do (an email signup, pasting a value into GitHub's own UI,
deciding when to merge, deciding whether a second AWS service is worth its
monthly cost).

## Division of labor - read before touching anything under `ai/`

This is the rule most likely to be violated by a fresh agent who hasn't
internalized it:

| Layer | Owner | Where |
|---|---|---|
| FastAPI routes, request/response models, infra (rate limiting, idempotency, versioning) | **Claude Code** | `api/`, `models/`, `common/` |
| Client/gateway layer (LLM providers, vector stores, metadata stores) | **Claude Code** | `common/clients/` |
| Chunking, embedding, indexing | Claude Code, **but only because of an explicit one-time override** the user granted (matches the golden dataset's own override) | `ai/doc_processing/` |
| Retrieval, grounded generation (MVP) | Claude Code, **same kind of explicit override**, granted 2026-09-10 - see Phase 6 in `docs/agent-reference/RAG-ROADMAP.md` | `ai/rag_pipeline/query_retrieval/`, `ai/rag_pipeline/response_generation/` |
| Query decomposition, guardrails, evaluations | **Still hand-written by the user** - still stubs/empty files, on purpose | `ai/pre_processing/`, `ai/rag_pipeline/evaluations/` |

**Do not implement `ai/pre_processing/`'s real logic (query decomposition,
guardrails) or `ai/rag_pipeline/evaluations/` without the user explicitly
asking again the same way they asked for the chunking/embedding/indexing
and retrieval/generation overrides** - that's the whole point of this
project for them. If asked to "move the project forward" without
qualification, the correct read is: continue
Claude-Code-owned infrastructure work, or ask which specific hand-written
phase (5.1-8 in RAG-ROADMAP.md) they want to do together, not silently
write their RAG logic for them.

## Doc map - where to find depth

Don't re-derive any of this from the code - it's already written down:

| Doc | What's in it |
|---|---|
| [`RAG-ROADMAP.md`](RAG-ROADMAP.md) | **The source of truth.** Full phase-by-phase history, every real bug found and fixed, exact reasoning behind every architectural decision. Start here for "what happened and why." |
| [`BACKLOG.md`](BACKLOG.md) | Known gaps, explicitly not blocking, with resolved items struck through rather than deleted |
| [`FAQ.md`](FAQ.md) | Deep-dive Q&A - document update strategy, metadata storage, indexing/categorization, performance, evaluation metrics (Precision@K/Recall@K/F1), golden datasets, A/B testing, and REST API contract-first design (versioning/idempotency/rate limiting/error handling) - written for interview prep as much as for this project |
| [`TESTING-GUIDE.md`](TESTING-GUIDE.md) | What's tested, why those cases, the fake-based pattern to copy for the hand-written pipeline |
| [`AWS-DEVOPS-RUNBOOK.md`](AWS-DEVOPS-RUNBOOK.md) | The full local→container→ECR→App Runner pipeline, every AWS resource and how to validate it, the manual git workflow, and three real deployment bugs documented in enough detail to never rediscover them the hard way |
| [`CICD-BRANCHING-STRATEGY.md`](CICD-BRANCHING-STRATEGY.md) | The `feature-* → develop → master` branch model, every CI/CD gate and the reasoning behind its threshold (coverage floor, security scanning, the A/B-testing bar for once Phase 8 exists), the wheel-vs-JAR packaging question, and the open staging-deployment decision |
| [`S3-ASYNC-UPLOAD-DESIGN.md`](S3-ASYNC-UPLOAD-DESIGN.md) | Design-only, not implemented - a future event-driven ingestion architecture |
| [`CODING-STANDARDS.md`](CODING-STANDARDS.md) | Error handling, logging, API contract conventions |
| [`README.md`](../README.md) | How to run it locally |
| `resources/golden_dataset/golden_dataset.json` | 22 real Q&A cases, grounded in the actual PDFs, ready for Phase 6 |
| `postman/hrb_chatbot.postman_collection.json` | Every endpoint, importable, including rate-limit/validation demo cases (idempotency demo cases removed 2026-09-13, see BACKLOG.md) |
| [`docs/dev-reference/developer-onboarding/guide.html`](../dev-reference/developer-onboarding/guide.html) | For a Java/Spring Boot background specifically: a concept-mapping table (Spring DI/JPA/Actuator/etc. → this project's actual equivalents, each citing a real file). Trimmed 2026-10-15 to this table only - the AWS/LangSmith dashboard-reading content and the build/deploy manual that used to live on this same page were split into the 3 rows below. Also listed in the Admin Dashboard's Architecture Docs tab once synced. |
| [`docs/dev-reference/build-guide/guide.html`](../dev-reference/build-guide/guide.html) | How to build and ship a change: the local dev loop, branch strategy, every real CI gate and its threshold, the Docker build - 3 real bugs and the exact load-bearing flags - and the ECR push. Stops before the actual App Runner deploy; see the deployment-verification-guide row below. Split out of `developer-onboarding/guide.html` 2026-10-15. |
| [`docs/dev-reference/deployment-verification-guide/guide.html`](../dev-reference/deployment-verification-guide/guide.html) | Confirming a change actually landed: triggering the App Runner deployment, polling for `RUNNING`, smoke-testing `/ping`, the GitHub Secrets `deploy.yml` needs, the honest no-rollback-procedure-yet state, the "nothing deploys without a human looking first" norm, and both system diagrams (what runs where; the deploy pipeline, visually). Split out of `developer-onboarding/guide.html` 2026-10-15. |
| [`docs/dev-reference/production-monitoring-guide/guide.html`](../dev-reference/production-monitoring-guide/guide.html) | Reading this project's real dashboards day to day: the App Runner service dashboard, tailing CloudWatch logs (including the "no app-level log group when the container never starts" finding), reading a LangSmith trace (local-vs-prod project split), and the secrets-vs-plain-env-vars table. Split out of `developer-onboarding/guide.html` 2026-10-15. |

## Known gotchas - condensed, full detail in the docs above

- **Document endpoints live under `/v1/genai-rag/ingest-document/...`, query endpoints
  under `/v1/genai-rag-retrieval/...`** (`GET /health` is the one exception,
  deliberately unversioned). One shared `/v1`, then a mode segment
  (`genai-rag` today; `single-agentic-rag`/`multi-agentic-rag` reserved for
  later), then a resource segment - a fresh agent testing against an
  old memory of `/v1/rag/...` or
  `/rag/documents` will get a `404`, not a bug.
- **Git Bash's MSYS layer mangles absolute Unix-style paths** (`/tmp/...`)
  passed to `curl -F` or AWS CLI args - corrupts them before the tool even
  sees them. Use relative paths from the repo root instead.
- **The shell's working directory resets to a different project between
  tool calls** in this environment - always `cd` explicitly in the same
  command as anything using a relative path, or a `curl -F "files=@..."`
  silently fails with a confusing `curl: (26)` read error that looks
  unrelated to the real cause.
- **App Runner deployments failed twice before succeeding** - not a
  fluke, two independent real bugs (a hand-typed secret ARN missing its
  random suffix, and BuildKit's default image manifest format being
  incompatible with App Runner) - both root-caused and now permanently
  fixed in `deploy.yml`'s build command. Full story in
  `AWS-DEVOPS-RUNBOOK.md`'s "Three real bugs found the hard way."
- **The AWS identity used for all of this (`BedrockAgentCore` user) has
  full `AdministratorAccess`** on a shared personal AWS account that also
  hosts unrelated projects - used deliberately with the user's informed
  consent, not a mistake, but worth knowing before assuming every AWS
  action here is scoped down (the *deploying* identity is broad; the
  *deployed service's own* roles are deliberately narrow - see
  `AWS-DEVOPS-RUNBOOK.md`'s IAM section for the distinction).
- **In-memory state doesn't survive a restart**: the rate limiter is
  single-process, in-memory - documented in its own module docstring, not
  a surprise. (The idempotency-key cache that used to share this same
  limitation was removed 2026-09-13 - see BACKLOG.md.)

## Real resource identifiers - useless from memory, write them down

| What | Value |
|---|---|
| AWS account / region | `418884736369`, `us-east-1` |
| App Runner service (final, working) | `arn:aws:apprunner:us-east-1:418884736369:service/hrb-chatbot/f957548202f343aa8ca91f341d71d85a` → `https://mrgysvt6ye.us-east-1.awsapprunner.com` (original URL, still works) / `https://compute.rvsree.dev` (custom domain, Phase 91, 2026-10-06 - both work identically) |
| ECR repo | `418884736369.dkr.ecr.us-east-1.amazonaws.com/hrb-chatbot` |
| GitHub repo | `https://github.com/rvsree/hrb_chatbot_service` - branches: `master` (production, deploys), `develop` (integration), `feature-langchain-rag-pipeline` (this session's work), `hrb_rag_pipelines` (original branch, superseded but still GitHub's *default* - not yet changed in Settings) |

Full list including IAM role ARNs and Secrets Manager entries:
`AWS-DEVOPS-RUNBOOK.md`'s "Resource identifiers" section.

## Immediate next steps, ranked

1. **Nothing is broken or waiting on Claude Code right now** - the four
   items in [Blocked on the user](#blocked-on-the-user---four-concrete-items)
   are the only open threads, and none of them need code.
2. If continuing development: work on new features now happens on a
   `feature-<short-name>` branch off `develop`, not directly on
   `hrb_rag_pipelines` - see
   [`CICD-BRANCHING-STRATEGY.md`](CICD-BRANCHING-STRATEGY.md) for the
   naming convention. The natural next Claude-Code-owned work is Phase 6.1
   (contracts/validation for the query path) - but it's **gated on Phase 6
   existing first**, which is the user's hand-written work. Ask which
   hand-written phase (5.1 query decomposition, 6 retrieval+generation, 7
   guardrails, 8 evaluations/A/B harness) they want to tackle, rather than
   guessing.
3. If asked to "test everything" or "make sure nothing's broken": `cd`
   into the repo root and run
   `.venv\Scripts\python.exe -m pytest -v --cov=src/hrb_chatbot --cov-fail-under=45` -
   35 tests, all should pass with no setup beyond
   `pip install -r requirements-dev.txt`. `bandit -r src/hrb_chatbot -ll`
   and `pip-audit -r requirements.txt` are the other two CI gates - see
   `CICD-BRANCHING-STRATEGY.md` before assuming a `pip-audit` finding is
   new; most of what it reports today is a known, already-documented
   backlog item, not something introduced by whatever you just changed.

## Things worth remembering that don't fit neatly anywhere else

- The user is a Java-background developer explicitly learning Python and
  RAG concepts - code was refactored this session away from dense
  Python idioms (response_generator expressions in `sum()`/`all()`, terse
  ternaries) toward explicit loops/if-else, with comments explaining the
  Java-equivalent concept where one exists. Keep matching that density
  and that audience in new code, not reverting to terser idioms.
- The user explicitly asked "did you update requirements.txt?" at one
  point - a good habit worth continuing: state plainly whether a
  dependency file needed changes and why (or why not), rather than
  assuming it's obvious.
- Every commit in this repo ends with `Co-Authored-By: Claude Sonnet 5
  <noreply@anthropic.com>` - keep that convention.
- A pre-commit hook (`.githooks/pre-commit`) scans for real-looking API
  keys before every commit, opt-in via `git config core.hooksPath
  .githooks` - already enabled in this local clone. It had two real bugs
  in its own regex before landing on a version that correctly catches
  real keys without false-positiving on ordinary English text - worth
  reading its own comments before ever touching the pattern again.
