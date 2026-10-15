# Branching strategy and CI/CD gates

How code is meant to move from a new feature to a live deployment in this
repository, and exactly what has to pass along the way before it can. This
doc covers the *process* (branches, gates, thresholds);
[`AWS-DEVOPS-RUNBOOK.md`](AWS-DEVOPS-RUNBOOK.md) covers the *AWS mechanics*
(what each service is, how to validate it, the three real deployment bugs) -
read that one for "how does App Runner actually work here," this one for
"what has to be true before code gets there."

## The branch model

```
feature/<name>  --PR-->  develop  --PR-->  master
   (your work)          (integration,       (production -
                          tested)             what's deployed)
```

| Branch | What it's for | What deploys from it |
|---|---|---|
| `feature-<short-name>` | One area of new work - one per effort, not one per person | Nothing directly - CI runs (tests, coverage, security), nothing deploys |
| `develop` | Integration branch - where finished feature branches land and get tested together before they're trusted | Nothing today - see [Deployment targets](#deployment-targets---what-deploys-from-where) below for why, and the option to change that |
| `master` | Production - what's actually live | `deploy.yml` - every push here builds, pushes to ECR, and redeploys the real App Runner service |

**Real branches on GitHub as of 2026-09-08**: `master`, `develop`,
`feature-langchain-rag-pipeline` (the current work), plus the original
`hrb_rag_pipelines` branch, kept around rather than deleted since it's
where every commit up to this restructuring actually happened - not part
of the ongoing flow going forward. The old `master`/`developer`/
`feature-kb-indexing-rag-pipeline` names existed only briefly before being
renamed to these on GitHub's own UI - a rename deletes the old ref
outright (no redirect), which is why `deploy.yml`'s and `ci.yml`'s branch
triggers had to be updated in the same change that documents this, or
`deploy.yml` would have silently never run again.

**Naming convention for new feature branches**: `feature-<short-kebab-name>`,
matching `feature-langchain-rag-pipeline`. For the work mentioned as
upcoming - a ReAct multi-agent setup, MCP workflows, conversation memory,
session/state management/caching - that's `feature-react-multi-agent`,
`feature-mcp-workflows`, `feature-conversation-memory`,
`feature-session-state-cache`, one branch per area, each going through the
same `develop` gate independently rather than one giant branch accumulating
all four.

**Not yet done, worth doing**: the repo's *default* branch on GitHub is
still `hrb_rag_pipelines` (visible on the Branches page) - that's a
GitHub Settings action (Settings → Branches → change default branch to
`master`), not something a `git push` can do. Branch protection rules
(require a passing CI run and at least one approval before merging into
`develop`/`master`) are the same kind of action, also not yet configured.
Neither is enforced today, so nothing stops a direct push straight to
`master` bypassing every gate below - the gates exist in CI, but nothing
today *requires* going through them.

## The testing gates, and where each one actually runs

`.github/workflows/ci.yml` runs on **every branch, every push** - not just
on the way into `develop` - so a gate failing is visible on your feature
branch immediately, not as a surprise when you open a PR.

| Gate | Enforced by | Threshold today | Blocking? |
|---|---|---|---|
| Import sanity | `ci.yml` `test` job | app must import cleanly | Yes |
| Unit + integration tests | `ci.yml` `test` job, `pytest` | 100% pass rate | Yes - zero flaky tolerance |
| Coverage floor | `ci.yml` `test` job, `pytest-cov` | `--cov-fail-under=45` | Yes |
| Static security analysis | `ci.yml` `security` job, `bandit -ll` | zero MEDIUM+ findings | Yes |
| Dependency CVE scan | `ci.yml` `security` job, `pip-audit` | none set yet - report only | **No, `continue-on-error: true`** |
| Docker image builds | `ci.yml` `docker-build` job | must build with the load-bearing flags | Yes |
| Golden-dataset release gate (genai-rag only) | `eval-gate.yml`, `scripts/run_release_gate.py` - manual `workflow_dispatch` only, not on every push | `get_release_decision()`'s PASS/REVIEW/BLOCK thresholds (recall/groundedness/completeness) | Yes, when run - but not automatic, so a push can still land without it |
| A/B eval (variant comparison) | Not wired into CI yet - hand-written harness is Phase 8, still planned. Different from the release gate above: this compares two variants against each other, not one variant against a fixed threshold | see [A/B testing](#ab-testing-once-phase-8-exists) below | Not yet applicable |

### Why 45%, not some rounder number

The first version of this gate used `--cov-fail-under=70` before it had
ever been run for real. Actually running it turned up **46%** measured
coverage - a 70% floor would have failed on its very first run, on code
nobody had touched. `--cov-fail-under=45` was chosen *after* measuring,
not before, with a small margin under the real number so the gate does its
actual job (catch a regression) without being a coin flip on unrelated
line-count noise.

Most of the uncovered 54% is two things this suite deliberately doesn't
touch, both by design (see
[`docs/agent-reference/TESTING-GUIDE.md`](TESTING-GUIDE.md)): the provider clients'
real-network branches (`openai_client.py` is 25% covered - the
settings/base-URL logic is tested, the actual `requests.post` call isn't,
because no test here may need a key or make a network call), and
`ai/rag_pipeline/pipeline.py`'s still-stubbed hand-written logic. **Raise
this number as real tests get added for real code - never lower it to
make a failing build pass.** A reasonable cadence: revisit it each time a
hand-written phase (5.1-8) lands with its own tests, since that's when
genuinely new, testable logic enters the codebase.

### The security gate, in two parts

**bandit (static analysis of `src/hrb_chatbot`) is blocking today**,
because it's clean today - zero findings at `-ll` (MEDIUM severity and
above; LOW findings are mostly stylistic, like flagging any `subprocess`
call regardless of whether it's exploitable, and would make the gate noisy
enough to get ignored). A future finding here should be read and either
fixed or explicitly suppressed with a `# nosec` comment naming *why* it's
a false positive - never suppressed silently.

**pip-audit (known CVEs in pinned dependencies) is report-only today**,
`continue-on-error: true` in `ci.yml`. Running it for real turned up
dozens of pre-existing CVEs across `langchain*`, `chromadb`, `starlette`,
and `pillow` - versions pinned months ago for compatibility (see
`README.md`'s Dependencies section and the `chromadb`/Python-3.12
constraint in Prerequisites), never audited against CVEs as they were
pinned. Flipping this to blocking today would fail every run, including
the very next one, before anyone has looked at a single finding. The path
to making it blocking:
1. Run `pip-audit -r requirements.txt` locally and read the actual list.
2. For each finding, decide: upgrade the pin (verify nothing breaks -
   `chromadb` in particular has the Python 3.13 fragility noted in
   Prerequisites, so bumping it needs the same care), or accept the risk
   explicitly with `pip-audit --ignore-vuln <id>` and a comment saying why.
3. Once the list is either fixed or explicitly accepted, remove
   `continue-on-error: true` so the next *new* CVE actually blocks a merge
   instead of joining an ignored pile.

This is real, standalone maintenance work - not part of the branch
restructuring that prompted this doc - tracked as its own item in
[`BACKLOG.md`](BACKLOG.md).

### A/B testing, once Phase 8 exists

The A/B harness itself is hand-written work, not yet built (Phase 8 in
[`RAG-ROADMAP.md`](RAG-ROADMAP.md) - the golden dataset it will run
against, 22 cases in `resources/golden_dataset/golden_dataset.json`, is
already done). When it exists, here's the recommended bar, and why it's
different from a textbook A/B test:

A classical A/B test wants a p-value (commonly α = 0.05) computed over a
large enough sample that noise averages out. **22 cases is not that
sample** - running a formal significance test over 22 golden-dataset
queries per variant will mostly report "not significant" even for a real
improvement, because the sample is too small for the math to have power,
not because the change didn't help. Two honest options:

- **Practical-significance threshold (recommended to start)**: define a
  minimum *meaningful* improvement instead of a statistical one - e.g. the
  challenger's mean of (faithfulness + relevance + F1) must beat the
  baseline's by **≥ 5 percentage points** across all 22 cases, and must
  not regress on any single case by more than some tolerance (e.g. 10
  points) even if the average improves. This catches "better on average
  but silently worse for one real question," which a pure average would
  hide.
- **Formal significance testing (once the dataset grows)**: once the
  golden dataset is meaningfully larger (a rough rule of thumb: 50+ cases
  per variant before a p-value means much), switch to a paired test (e.g.
  a paired t-test or Wilcoxon signed-rank test over per-case score deltas)
  at α = 0.05. Growing the dataset is itself hand-written work, gated the
  same way as the harness itself.

Either way, **the gate should compare against the previous baseline
score, not a hardcoded number** - the threshold is about "did this change
help," not "is quality above X" (that's a separate, absolute quality bar,
also worth having, but a different question).

## Packaging - is a wheel the same idea as a JAR?

Close, not identical. A Python **wheel** (`.whl`) is a built, versioned,
installable package - `pip install some_wheel.whl` - conceptually the
same *role* a JAR plays: a single artifact you build once and either run
directly or hand to something else that installs it. Where the analogy
breaks: a JAR can be *self-contained enough to run* (`java -jar app.jar`)
because the JVM's bytecode is portable across machines; a wheel is not
self-contained the same way - it still needs a matching Python interpreter
and its dependencies present wherever it's installed. A wheel alone
doesn't solve "does the target machine have the right Python and
libraries" the way a JAR mostly does - a container still has to do that
part.

**This project doesn't build a wheel today, and the recommendation is:
don't add one, for now.** Here's why, concretely: `Dockerfile` already
does the equivalent job the multi-stage way - stage 1 builds a full venv
(`pip install -r requirements.txt`), stage 2 copies that finished venv
wholesale into the runtime image (`COPY --from=builder /opt/venv
/opt/venv`). The *Docker image itself* is this project's single
versioned, installable, deployable artifact - building a wheel in between
would package the same `src/` a second time for no consumer that needs
it, since nothing here installs this project as a dependency of something
else. A wheel earns its place the day this code needs to be **imported by
a different project** (e.g. if the RAG pipeline logic became a shared
library used by more than one service) or **published to a private
package index** (AWS CodeArtifact) for reuse outside a container - neither
is true today.

**A more valuable next step than wheel-building**: `deploy.yml` tags the
image `:latest` only, meaning there is no way to redeploy the previous
image if a new one breaks something App Runner's own health check doesn't
catch - `:latest` gets overwritten every deploy, so the old image is only
recoverable if it's still sitting in ECR's history and someone remembers
its digest. Tagging every build with both `:latest` and `:${{ github.sha
}}` would fix that (`aws apprunner update-service` or a redeploy pointed
at the specific SHA tag rolls back cleanly). **Not implemented here
deliberately** - `deploy.yml`'s build command has caused three real,
hard-to-diagnose failures before (see
[`AWS-DEVOPS-RUNBOOK.md`](AWS-DEVOPS-RUNBOOK.md)'s "Three real bugs found
the hard way"), and that doc's own advice is to re-verify the two manifest
checks before touching that exact line, not after a failed deploy. Treat
this as a queued, well-understood follow-up rather than something to
change in the same pass as a branch rename.

## Deployment targets - what deploys from where

**Today: only `master` deploys, to the one existing App Runner service.**
`develop` has no deploy target at all - merging into it runs the full test
gate above, nothing more.

That's a real gap against what was asked (test on `develop`, then deploy
from there) - here's the honest trade-off rather than quietly picking one:

- **Option A - keep it this way (no extra cost, what's implemented today)**.
  `develop` is purely a tested-integration branch; going live still means a
  further PR from `develop` into `master`. Nothing new to provision, no
  second AWS bill. The cost is that "tested on develop" and "actually
  running in an environment" are two different things until the `master`
  merge happens - there's no environment that mirrors production before
  that point.
- **Option B - add a second, smaller App Runner service for `develop`**
  (a real staging environment `deploy.yml` would also need a second
  workflow, or a branch-conditional step, targeting a *different* service
  ARN and URL). This gives an actual pre-prod environment to point
  the Postman collection's manual checks and a future automated smoke
  suite at before anything reaches production - closer to what was described. The
  real cost: App Runner bills continuously for a running service (not
  per-request), so this is an ongoing AWS charge for a second always-on
  service, on top of the existing one.

**Not implemented - this is a decision for you, not a code change I made
unprompted**, since it's an ongoing AWS cost, the same category of
decision as the Neon Postgres signup already tracked in
[`HANDOFF.md`](HANDOFF.md). Say the word and Option B is straightforward
to build: a second App Runner service (same image, same IAM pattern as
today's), a `develop`-triggered job in `deploy.yml` (or a sibling
`deploy-staging.yml`) pointed at its ARN/URL instead of production's.

## Deployment testing - now real, not just a health check on a schedule

`deploy.yml` used to end at `aws apprunner start-deployment` - which only
*starts* a deployment and returns almost immediately, well before the new
container is actually serving traffic. Two steps were added after it:

1. **Wait for `RUNNING`** - polls `aws apprunner describe-service`'s
   `Service.Status` every 10 seconds (up to 5 minutes) instead of a fixed
   sleep, and fails the job outright if App Runner reports anything other
   than `OPERATION_IN_PROGRESS` while waiting or times out - both real
   outcomes seen during Phase 10's three `CREATE_FAILED` attempts, not
   hypothetical.
2. **Smoke test** - one `curl --fail` against the live URL's `/ping` (not
   `/health` - this job has no reason to spend a provider call just to
   confirm the container booted). A non-200 fails the job.

This means a deploy that "succeeds" by AWS's own accounting but produces a
container that never actually comes up now fails the GitHub Actions run
too, instead of leaving a broken container quietly live until someone
happens to check `curl /ping` by hand.

## Quick reference - thresholds at a glance

| What | Threshold | Where set |
|---|---|---|
| Test pass rate | 100% | `ci.yml`, `pytest` |
| Coverage floor | 45% (ratchet up only) | `ci.yml`, `--cov-fail-under=45` |
| bandit severity gate | MEDIUM+ blocks | `ci.yml`, `bandit -ll` |
| pip-audit | report-only today; triage plan above before flipping to blocking | `ci.yml`, `continue-on-error: true` |
| A/B practical-significance bar (once Phase 8 exists) | ≥ 5 point average improvement, no single-case regression > 10 points | Not wired up yet - guidance only |
| A/B formal significance (once dataset ≥ ~50/variant) | paired test, α = 0.05 | Not wired up yet - guidance only |
| Deployment health check | new container reaches `RUNNING` + `/ping` returns 200 | `deploy.yml`, post-deploy steps |
| Lambda deployment health check | `LastUpdateStatus` reaches `Successful` | `deploy-lambda.yml`, post-deploy step |

## Lambda deploys are separate from the App Runner deploy (added Phase 89-follow-up, 2026-10-06)

`deploy.yml` only ever knew about the main App Runner image - it has no
idea `hrb-chatbot-index-document` (the Phase 88 async-ingestion Lambda)
exists. Every Lambda deploy before `deploy-lambda.yml` existed was a
manual `docker buildx build` + ECR push + `aws lambda update-function-code`,
run by hand - this already caused a real bug once: Phase 89 shipped real
code changes, `deploy.yml`'s own deploy went green, and the Lambda
silently kept running the *previous* version until the manual steps were
run separately (caught only because that phase's own live test checked
the actual override values, not just the HTTP status code).

`deploy-lambda.yml` closes this gap - triggered on push to `master`,
scoped via `paths:` to `src/hrb_chatbot/**`/`Dockerfile.lambda`/
`requirements.txt` (the whole tree, not just `lambda_handlers/`, since
`Dockerfile.lambda` bundles all of `src/hrb_chatbot` into the image - a
change to shared pipeline code affects the Lambda exactly the same way
it affects the main app). It rebuilds with the same
`--provenance=false --sbom=false` flags `deploy.yml` already needs (same
root cause, see Phase 88/10's own entries in `RAG-ROADMAP.md`), pushes
to the `hrb-chatbot-lambda` ECR repo, calls `update-function-code`, and
polls `LastUpdateStatus` until `Successful` before the job ends - same
"don't just trust the API call returned, confirm it actually finished"
pattern `deploy.yml` already uses for App Runner's `RUNNING` status.

Needs `hrb-chatbot-github-actions-deploy`'s IAM policy extended with
`ecr:*` on the `hrb-chatbot-lambda` repo and `lambda:UpdateFunctionCode`/
`lambda:GetFunctionConfiguration` scoped to this one function - a real
AWS IAM change, not something applied automatically here (the same
category of action as every other IAM/credential change this session,
done by hand with the exact policy document recorded in this commit's
history).
