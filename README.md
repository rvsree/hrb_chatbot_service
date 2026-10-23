# HRB Chatbot v2

An HR benefits chatbot backed by a RAG pipeline over the JPMC benefits
knowledge base (`resources/kb_docs/`). Being built by hand, one feature at a
time, to apply RAG concepts from the Interview Kickstart FDE cohort - see
[docs/agent-reference/RAG-ROADMAP.md](docs/agent-reference/RAG-ROADMAP.md) for the phase-by-phase plan and
current status (that file is the source of truth for "what's done" - this
README doesn't repeat it).

## Environments

| App | Local | AWS (production) |
| --- | --- | --- |
| Backend (this repo, `hrb_chatbot_service`) | `http://127.0.0.1:8093` | `https://hrb-chatbot.rvsree.dev` |
| Frontend (`hrb_chatbot_ui`, separate repo) | `http://localhost:5173` (`npm run dev`) | `https://hrb-chatbot-ui.rvsree.dev` |
| MCP server (`hrb_lms_mcp`, separate repo - leave balance/history tools) | `http://127.0.0.1:8190` | `https://hrb-lms-mcp.rvsree.dev` |

The AWS backend runs on App Runner (Phase 10, see
[AWS-DEVOPS-RUNBOOK.md](docs/agent-reference/AWS-DEVOPS-RUNBOOK.md)); the AWS
frontend is a static build on S3 behind CloudFront (Phase 117, manually
provisioned - no CI/CD pipeline for it yet, unlike the backend's `deploy.yml`);
`hrb_lms_mcp` is its own App Runner service with a real `deploy.yml` (Phase
118). All three point at each other by default: the frontend's
`.env.production` bakes in the production backend URL above, the backend's
CORS config (`main.py`) allows the production frontend origin, and the
backend's `HRB_LMS_MCP_URL`/OAuth2 settings (App Runner secrets, not
committed anywhere) point at the production MCP server.

## Prerequisites

- **Python 3.12** - not 3.13/3.14. `chromadb` depends on Pydantic v1
  internals that Python 3.13 removed.
- An **OpenAI API key** at minimum (`OPENAI_API_KEY` in `.env`). Anthropic
  and OpenRouter keys are optional - the app runs fully on OpenAI alone.

## 1. Running locally, from a terminal

The venv already exists at `.venv/`. From the repository root:

```powershell
# install (only needed after requirements.txt changes)
.venv\Scripts\python.exe -m pip install -r requirements.txt

# run
.venv\Scripts\python.exe -m uvicorn src.hrb_chatbot.main:app --reload --port 8093
```

Confirm it came up:

```powershell
curl http://127.0.0.1:8093/health
```

`200` with `"status":"healthy"` means it's ready. `/docs` gives the
interactive Swagger UI.

Note the import root: everything is written as `from src.hrb_chatbot....`,
not `from hrb_chatbot....` - `src/__init__.py` exists on purpose, and the app
is always run as a module from the repository root, never from inside `src/`.

## 2. IntelliJ IDEA / PyCharm - run & debug configurations

Needs the **Python** plugin (Community edition has it; PyCharm ships with it
built in).

### Setup - once per machine

1. **Point the project at the venv.** *File → Project Structure → SDKs → +
   → Add Python SDK → Existing environment*, then choose
   `...\hrb_chatbot_service\.venv\Scripts\python.exe`. Assign that SDK to the
   module.
2. **Mark the repository root as the Sources Root** (not `src/`). Right-click
   the repo root → *Mark Directory as → Sources Root*. This is what makes
   `from src.hrb_chatbot...` resolve - marking `src/` itself instead makes
   every import underline red even though the code runs fine from a terminal.

### Run configuration - "hrb-chatbot-server"

*Run → Edit Configurations → + → Python*:

| Field | Value |
|---|---|
| Name | `hrb-chatbot-server` |
| Run target | `Module name` (switch the radio from *Script path*) |
| Module name | `uvicorn` |
| Parameters | `src.hrb_chatbot.main:app --reload --port 8093` |
| Working directory | the repository root |
| Python interpreter | the project SDK (`.venv`) |
| Environment variables | *(leave empty - `.env` is loaded by the app itself)* |

### Debug configuration - "hrb-chatbot-debug"

Duplicate the run configuration above and **delete `--reload`**. That's the
only difference - `--reload` runs the app in a child process, which breaks
an attached debugger.

## 3. Testing the endpoints

### Health - every backend service currently wired up

```powershell
# just confirms the process is up - no network call, no cost
curl http://127.0.0.1:8093/ping

# the real diagnostic - one real but free call per service (no chat completion, no tokens spent)
curl http://127.0.0.1:8093/health

# check a specific LLM provider
curl "http://127.0.0.1:8093/health?provider=anthropic"
curl "http://127.0.0.1:8093/health?provider=openrouter"
```

`/health` reports three checks - `llm` (whichever provider you asked for,
`openai` by default), `vector_database` (`chromadb` by default, pass
`vector_provider=pinecone` to check the other), and `metadata_database`
(`sqlite` by default, pass `metadata_provider=postgres` to check the
other). **Tavily has a client
(`common/clients/web_client/tavily_client.py`) but is not wired into
`/health` yet** - a known gap, tracked in
[docs/agent-reference/BACKLOG.md](docs/agent-reference/BACKLOG.md), not something broken.

### Upload documents, index them, and ask the knowledge base

All of these are implemented and verified live (see
[docs/agent-reference/TESTING-GUIDE.md](docs/agent-reference/TESTING-GUIDE.md) for the automated test
suite, and `postman/hrb_chatbot.postman_collection.json` for every
request/response case, happy path and edge case, importable into Postman):

```powershell
# upload a real PDF - chunks, embeds, and indexes in the same call (no
# separate index step since Phase 26); identity travels as a JSON string in
# the payload form field, not headers - copy the document_id from the response
curl -F "files=@resources/kb_docs/JPMC Healthcare Benefits.pdf;type=application/pdf" -F "payload={\"user_profile\": {\"employee_id\": \"EMP051\", \"full_name\": \"Hana Support\", \"role\": \"hr_support\"}}" http://127.0.0.1:8093/v1/genai-rag/ingest-document/documents

# ask a question - real retrieval + grounded generation (spends: one real
# embedding call + one real chat completion). Input/output guardrails and
# conversation memory run on every call (Phase 98's shared guarded-pipeline
# core) - see docs/agent-reference/RAG-ROADMAP.md for exactly what's in
curl -X POST http://127.0.0.1:8093/v1/genai-rag-retrieval/query -H "Content-Type: application/json" -d "{\"user_profile\": {\"employee_id\": \"EMP052\", \"full_name\": \"Eddy Employee\", \"role\": \"employee\"}, \"query\": \"How many weeks of parental leave do I get?\"}"
```

Re-uploading identical PDF content is content-hash deduped (Phase 16) -
the second upload resolves to the existing document instead of creating a
duplicate; a changed file for the same `document_id` is handled as a
supersede, not a dedup hit. The `Idempotency-Key` header approach tried
earlier was removed 2026-09-13 in favor of this content-hash approach -
see `docs/agent-reference/RAG-ROADMAP.md`'s phase entries for why.

For testing every endpoint from a GUI instead of curl, import
[postman/hrb_chatbot.postman_collection.json](postman/hrb_chatbot.postman_collection.json)
into Postman - it covers the same happy-path and edge cases as
README_TEST.md, ready to run against `{{base_url}}` (local or the deployed
App Runner URL).
[resources/golden_dataset/golden_dataset.json](resources/golden_dataset/golden_dataset.json)
has 22 real question/expected-answer pairs grounded in the actual
`resources/kb_docs/` PDFs, for evaluating whether real answers are grounded
and correct rather than hallucinated - exercisable against the real query
endpoint now.

### Logging in

Login (`POST /v1/auth/login`) checks `employee_id`/`full_name`/`role`
against a fixed roster (`common/known_personas.py`, see
[docs/agent-reference/KNOWN-PERSONAS.md](docs/agent-reference/KNOWN-PERSONAS.md)
for the full list) - not real authentication, just enough to reject a
typo'd or made-up identity. The `admin` role additionally requires a
secret code (hashed in Postgres, `admin_credential_store.py`) - admin
access is restricted to the project owner, so no seed credential is
documented here; see `POST /v1/admin/reset-secret-code` in the code if
you are the owner and need to rotate it.

An `admin` identity unlocks `GET /v1/admin/conversations`,
`/v1/admin/feedback`, `/v1/admin/leave-requests`, and `/v1/admin/docs` -
the last being an in-app viewer (Phase 170) over a small set of
architecture/design docs synced into S3
(`scripts/sync_admin_docs.py`), surfaced in `hrb_chatbot_ui`'s Admin
Dashboard and as small book-icon links next to specific feature labels
throughout the UI. `GET /v1/admin/docs/{doc_id}/content` returns a
presigned, time-limited S3 URL to the actual doc rather than the content
itself.

### Leave requests (human-in-the-loop approval)

`POST /v1/unpaid-leave/request` files an unpaid-leave request that an
`hr_support` identity approves or rejects via `POST /v1/unpaid-leave/resolve`
(`GET /pending` lists what's waiting, `GET /my-requests` is the
requester's own view) - a human-in-the-loop approval flow, not an agent
auto-approving itself. `admin` can file requests and view every request
(`GET /all`) the same way `hr_support` can, but deliberately cannot
resolve/approve one - that stays an `hr_support`-only action. See
[docs/dev-reference/react_agents/](docs/dev-reference/react_agents/) and
the relevant `docs/agent-reference/RAG-ROADMAP.md` phase entries (search
for "HITL"/"A2A") for the design.

## Running in a container

```powershell
docker buildx build --provenance=false --sbom=false --output type=docker -t hrb-chatbot:local .
docker run --rm --env-file .env -p 8093:8093 hrb-chatbot:local
```

Build- and run-verified, including a real deployment to AWS App Runner -
see [docs/agent-reference/AWS-DEVOPS-RUNBOOK.md](docs/agent-reference/AWS-DEVOPS-RUNBOOK.md) for the full
containerize → ECR → App Runner pipeline, exactly which build flags are
required and why (three separate real bugs were found and fixed getting
this image to actually run in App Runner, not just build locally), and how
to review/validate every AWS resource this project provisions.

## Branching and CI/CD

`feature-<name>` branches → `develop` (integration, fully gated) →
`master` (production - `deploy.yml` deploys from here only). See
[docs/agent-reference/CICD-BRANCHING-STRATEGY.md](docs/agent-reference/CICD-BRANCHING-STRATEGY.md) for the
branch roles, every CI gate and the threshold it enforces (test pass rate,
coverage floor, security scanning, and the A/B-testing bar for once
Phase 8's eval harness exists), and the deployment-testing step that now
runs after every real deploy.

## Running the tests

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # once
.venv\Scripts\python.exe -m pytest -v
```

No test needs a real API key or network call - see
[docs/agent-reference/TESTING-GUIDE.md](docs/agent-reference/TESTING-GUIDE.md) for what's covered, why
those specific cases, and the fake-based pattern (`tests/conftest.py`'s
fakes match every real client's method signature exactly) to copy for new
tests.

## Dependencies

`requirements.txt` pins exact versions (`==`) deliberately, not loose ranges
- `chromadb`'s Python-version fragility (see Prerequisites) and the fact that
a Dockerfile now exists are both reasons a silent version drift is worse than
a pin that occasionally needs a deliberate bump. `requirements-dev.txt` is
test-only dependencies, kept separate so a production image never installs
them.

## Project conventions

See [docs/agent-reference/CODING-STANDARDS.md](docs/agent-reference/CODING-STANDARDS.md) for the error
handling, logging, and API contract conventions this codebase follows.

## Known gaps and planned work

See [docs/agent-reference/BACKLOG.md](docs/agent-reference/BACKLOG.md).

## Design questions and FAQ

[docs/agent-reference/FAQ.md](docs/agent-reference/FAQ.md) - deep-dive answers on document update
strategy, where RAG metadata lives and which store is right for filtering
search results, and how document indexing/categorization works - each
split clearly into what this project does today vs. general RAG design
reasoning, written for both gap-finding and interview prep.
