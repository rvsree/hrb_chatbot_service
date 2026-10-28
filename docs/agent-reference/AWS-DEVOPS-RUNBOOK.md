# AWS infrastructure & DevOps runbook

How to review, validate, and reproduce this project's real AWS deployment - from a
local `uvicorn` process to a running container in App Runner - and what to check
for each AWS service actually involved. Every command below was run for real
while building Phase 10/11 (see `docs/agent-reference/RAG-ROADMAP.md`), not written from
documentation alone. **Account ID, ARNs, and other real resource
identifiers are redacted to `<AWS_ACCOUNT_ID>`/`<SERVICE_ID>`-style
placeholders here on purpose** - this repo is public; the real values live
in a private ops runbook one level up, not committed to any public repo.

**Read this first if you only read one section**: [What's actually live vs. planned](#whats-actually-live-vs-planned)
and [Three real bugs found the hard way](#three-real-bugs-found-the-hard-way) -
the second section exists specifically because "it should work" and "it works"
turned out to be different things three separate times during this deployment.

## What's actually live vs. planned

The user's own request for this doc named `bedrock, s3, lambda, postgres` - here
is honestly which of those are real today and which are design-only, so this
runbook doesn't imply something is deployed when it isn't:

| Service | Status | Where |
|---|---|---|
| **ECR** | Live | `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/hrb-chatbot` |
| **App Runner** | Live, `RUNNING` | see [Resource identifiers](#resource-identifiers) |
| **Secrets Manager** | Live | 5 secrets, `hrb-chatbot/*` prefix |
| **IAM (roles + users)** | Live | see [IAM](#iam-roles-and-users) |
| **Bedrock** | Live, via IAM role (no static keys) | scoped `bedrock:InvokeModel*` on the instance role |
| **Pinecone** | Live (not AWS - a third-party vector DB) | `RAG_VECTOR_DB=pinecone`, already the active backend |
| **Postgres** | **Not live in the deployment** | code fully implemented (Phase 2.5); deployed service still runs `RAG_METADATA_STORE=sqlite` because a hosted Postgres (Neon) hasn't been provisioned yet - blocked on the user, not on infrastructure |
| **S3** | **Not implemented at all** | a *design only* doc exists at `docs/agent-reference/S3-ASYNC-UPLOAD-DESIGN.md` for a future presigned-upload + event-driven-Lambda-indexing architecture - nothing to validate today |
| **Lambda** | **Not implemented at all** | same design doc; the current architecture uses App Runner running the whole FastAPI app continuously, not a Lambda per request |
| **GitHub Actions CI** | Live, verified | [run 34184448804](https://github.com/rvsree/hrb_chatbot_service/actions/runs/34184448804) passed both jobs |
| **GitHub Actions Deploy** | Written, **not yet exercised** | triggers only on `master` (renamed from `main` on 2026-09-08 - see [`CICD-BRANCHING-STRATEGY.md`](CICD-BRANCHING-STRATEGY.md)), which has no new commits yet; two GitHub Secrets still need to be added manually (see [CI/CD](#cicd-github-actions)) |

## Resource identifiers

Write these down - they are not derivable from the code, only from AWS itself.

| What | Value |
|---|---|
| AWS account | `<AWS_ACCOUNT_ID>`, region `us-east-1` |
| ECR repository | `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/hrb-chatbot` |
| App Runner service ARN | `arn:aws:apprunner:us-east-1:<AWS_ACCOUNT_ID>:service/hrb-chatbot/<SERVICE_ID>` |
| App Runner URL | `https://<app-runner-url>.us-east-1.awsapprunner.com` |
| App Runner access role (ECR pull) | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/hrb-chatbot-apprunner-access-role` |
| App Runner instance role (app's own AWS calls) | `arn:aws:iam::<AWS_ACCOUNT_ID>:role/hrb-chatbot-apprunner-instance-role` |
| GitHub Actions deploy user | `hrb-chatbot-github-actions-deploy` (static key, GitHub Secrets only) |
| Secrets | `hrb-chatbot/OPENAI_API_KEY`, `hrb-chatbot/ANTHROPIC_API_KEY`, `hrb-chatbot/OPENROUTER_API_KEY`, `hrb-chatbot/TAVILY_API_KEY`, `hrb-chatbot/PINECONE_API_KEY` |

The deploying identity itself (an IAM user named `BedrockAgentCore`, holding
full `AdministratorAccess`) is **not** listed as a resource of this project -
it's the user's own general AWS sandbox account, used with informed consent
(see Phase 9/10 in `docs/agent-reference/RAG-ROADMAP.md`). None of the roles or the GitHub
Actions user above have anywhere near that level of access - see
[IAM](#iam-roles-and-users) for exactly what each one can actually do.

---

## The manual git workflow, start to finish

Everything from "I changed some code" to "it's live in AWS," as a real
sequence of commands - this is what actually happened building this
project, not a generic git tutorial. **This section predates the
`feature/develop/master` branch structure** (it's the history of the
original `hrb_rag_pipelines` branch, kept as-is because it's what actually
happened) - for how a *new* feature area should branch going forward, see
[`CICD-BRANCHING-STRATEGY.md`](CICD-BRANCHING-STRATEGY.md); the short
version is `git checkout -b feature-<short-name>` off `develop` in place
of step 1 below, and step 6 becomes a PR into `develop` first, `master`
only once that's tested.

### 1. Branch, before the first commit

```bash
git checkout -b hrb_rag_pipelines
```
Created **before** any commits existed, deliberately - a branch created
after commits already exist on the trunk branch is a different (also
fine) workflow, but starting a new feature area on its own branch from the
very first commit keeps the trunk clean the whole time, never briefly
holding in-progress work.

### 2. Stage deliberately, never `git add -A` blindly

```bash
git status                      # see what's actually changed, and what's untracked
git diff <file>                 # review one file's changes before staging it
git add <file1> <file2> ...     # stage exactly what belongs in this commit
```
Staging file-by-file (or a small deliberate group) rather than `git add -A`
matters most when a `.env` or a scratch file with real values might be
sitting in the working directory - `git add -A` doesn't know the
difference between your code and a secret you forgot was there.

### 3. Scan for secrets before every commit - by hand, then by the hook

```bash
git diff --cached | grep -Ei 'sk-ant-[A-Za-z0-9_-]{60,}|sk-proj-[A-Za-z0-9_-]{60,}|sk-or-v1-[A-Za-z0-9]{50,}|pcsk_[A-Za-z0-9_-]{40,}|tvly-[A-Za-z0-9_-]{25,}|AKIA[A-Z0-9]{16}'
```
This exact pattern (tuned twice - see `.githooks/pre-commit`'s own commit
history for why a naive version either false-positived on plain English or
failed to match a real key at all) also runs automatically once you opt in:
```bash
git config core.hooksPath .githooks   # once per clone
```
After that, every `git commit` runs this scan itself and refuses the
commit if it finds something that looks like a real key - a
`--no-verify` override exists for a genuine false positive, not as a
habit.

### 4. Commit with a real message, not a label

```bash
git commit -m "$(cat <<'EOF'
Short summary line, imperative mood, under ~70 characters

The why, not the what - what problem this solves or what broke
without it. The diff already shows what changed; this is for
context the diff can't carry on its own.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
The heredoc (`<<'EOF' ... EOF`) is there specifically so a multi-line
message with blank lines and punctuation survives intact - a plain
`-m "..."` string fights the shell the moment the message has a quote
or a line break in it.

### 5. Push, then verify CI actually ran (don't just assume)

```bash
git push origin hrb_rag_pipelines

# no gh CLI or GitHub token needed - Actions on a public repo are readable anonymously
curl -s "https://api.github.com/repos/rvsree/hrb_chatbot_service/actions/runs?branch=hrb_rag_pipelines&per_page=1" \
  | python -c "import json,sys; r=json.load(sys.stdin)['workflow_runs'][0]; print(r['status'], r['conclusion'])"
```
Poll that second command every 10-15 seconds until it prints
`completed success` (or `completed failure`, which means go read the run's
logs, not push again hoping it was a fluke).

### 6. Merge to `master` when ready - not done automatically by anything above

Nothing in this project auto-merges. When a feature branch is ready, it
goes through `develop` first, then `master`:
```bash
git checkout develop
git pull origin develop
git merge feature-<short-name>
git push origin develop
# once develop's own CI gate is green (see CICD-BRANCHING-STRATEGY.md):
git checkout master
git pull origin master
git merge develop
git push origin master
```
or open pull requests on GitHub for both hops instead, if the repo ever
gets a second contributor and review actually matters (there are no
branch-protection rules requiring this yet - see
[`CICD-BRANCHING-STRATEGY.md`](CICD-BRANCHING-STRATEGY.md)). **The `master`
push is the step that arms `deploy.yml`** - it only triggers on `master`
(see [CI/CD](#cicd-github-actions)), so nothing deploys to AWS until this
happens, no matter how many times a feature branch or `develop` itself is
pushed.

---

## The full pipeline: local → container → ECR → App Runner

### 1. Run it locally first

```powershell
.venv\Scripts\python.exe -m uvicorn src.hrb_chatbot.main:app --reload --port 8093
curl http://127.0.0.1:8093/health
```

If this doesn't return `{"status": "healthy", ...}`, nothing downstream will
work either - don't skip straight to Docker.

### 2. Containerize - and use the exact right build flags

```bash
docker buildx build \
  --provenance=false --sbom=false \
  --output type=image,name=<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/hrb-chatbot:latest,oci-mediatypes=false,push=true \
  .
```

**Every one of those three flags is load-bearing**, not stylistic - see
[Three real bugs found the hard way](#three-real-bugs-found-the-hard-way).
A plain `docker build -t hrb-chatbot .` produces an image that pulls fine
into App Runner and then silently never starts the container, with zero
application-level logs to explain why.

To validate the image before pushing:

```bash
docker image inspect hrb-chatbot:local --format "{{.Os}}/{{.Architecture}}"
# expect: linux/amd64
```

To validate what actually got pushed:

```bash
docker manifest inspect <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/hrb-chatbot:latest
# expect mediaType: "application/vnd.docker.distribution.manifest.v2+json"
# NOT "application/vnd.oci.image.manifest.v1+json" or an index/manifest-list
```

If that second check ever shows the OCI mediaType again, someone has
rebuilt without the flags above - fix the build command, don't try to patch
around it in App Runner.

### 3. Push to ECR (already done by the `docker buildx build ... push=true` above)

Manual login, if you need to push a differently-built image:

```bash
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/hrb-chatbot:latest
```

### 4. Deploy to App Runner

App Runner's `AutoDeploymentsEnabled` is deliberately `false` on this
service - pushing a new `:latest` to ECR does **not** redeploy it by
itself. Trigger a deployment explicitly:

```bash
aws apprunner start-deployment \
  --service-arn arn:aws:apprunner:us-east-1:<AWS_ACCOUNT_ID>:service/hrb-chatbot/<SERVICE_ID>
```

Then watch it:

```bash
aws apprunner describe-service \
  --service-arn arn:aws:apprunner:us-east-1:<AWS_ACCOUNT_ID>:service/hrb-chatbot/<SERVICE_ID> \
  --query 'Service.Status'
```

Valid end states are `RUNNING` (success) or `CREATE_FAILED`/`UPDATE_FAILED`
(something's wrong - go straight to [reading logs](#reading-app-runner-logs),
don't guess).

---

## How to validate each AWS service

### ECR

```bash
aws ecr describe-repositories --repository-names hrb-chatbot --region us-east-1
aws ecr describe-images --repository-name hrb-chatbot --region us-east-1
```
Confirm the repository exists and the `latest` tag's `imagePushedAt` matches
your most recent push.

### IAM roles and users

```bash
# Trust policy - who can assume this role
aws iam get-role --role-name hrb-chatbot-apprunner-access-role --query 'Role.AssumeRolePolicyDocument'
aws iam get-role --role-name hrb-chatbot-apprunner-instance-role --query 'Role.AssumeRolePolicyDocument'

# Attached / inline permissions - what it can actually do
aws iam list-attached-role-policies --role-name hrb-chatbot-apprunner-access-role
aws iam list-role-policies --role-name hrb-chatbot-apprunner-instance-role
aws iam get-role-policy --role-name hrb-chatbot-apprunner-instance-role --policy-name bedrock-invoke-only
aws iam get-role-policy --role-name hrb-chatbot-apprunner-instance-role --policy-name secrets-manager-read-own

# The GitHub Actions deploy user - confirm it's scoped, not broad
aws iam list-user-policies --user-name hrb-chatbot-github-actions-deploy
aws iam get-user-policy --user-name hrb-chatbot-github-actions-deploy --policy-name deploy-hrb-chatbot-only
```

What "correct" looks like: the access role's policy is exactly
`AWSAppRunnerServicePolicyForECRAccess` (a managed policy, nothing more);
the instance role's two inline policies only ever mention `bedrock:*` and
`secretsmanager:GetSecretValue` scoped to `hrb-chatbot/*`; the GitHub user's
policy only mentions the one ECR repo and `apprunner:StartDeployment` /
`DescribeService` scoped to this one service. If any of these ever shows a
wildcard resource (`"Resource": "*"`) beyond `ecr:GetAuthorizationToken`
(which is unavoidably account-wide), that's a real regression to fix, not a
convenience to leave in place.

### Secrets Manager

```bash
aws secretsmanager list-secrets --filters Key=name,Values=hrb-chatbot/ --region us-east-1
```
This lists names and **full ARNs including the random suffix** - the exact
thing that broke deployment #1 (see below). Never hand-type a secret ARN;
always resolve it from this call.

To confirm a secret has a value without ever printing it:
```bash
aws secretsmanager describe-secret --secret-id hrb-chatbot/OPENAI_API_KEY --region us-east-1
```
(`describe-secret`, not `get-secret-value` - the former never returns the
actual secret string.)

### App Runner

```bash
aws apprunner describe-service --service-arn <ARN>
aws apprunner list-operations --service-arn <ARN> --max-results 5
```
Check `Service.Status` (`RUNNING` is healthy), and confirm
`SourceConfiguration.ImageRepository.ImageConfiguration.RuntimeEnvironmentVariables`
matches what you expect (especially `RAG_VECTOR_DB` and
`RAG_METADATA_STORE` - it's easy to forget which one is live).

#### Reading App Runner logs

```bash
aws logs describe-log-groups --log-group-name-prefix "/aws/apprunner/hrb-chatbot"
aws logs describe-log-streams --log-group-name "/aws/apprunner/hrb-chatbot/<service-id>/service" --order-by LastEventTime --descending
aws logs get-log-events --log-group-name "/aws/apprunner/hrb-chatbot/<service-id>/service" --log-stream-name "<stream>"
```
**Important limitation, confirmed the hard way**: when a deployment fails
because the *container itself* never starts (as opposed to starting and
then crashing), there is no separate `/application` log group with your
own `structlog`/`loguru` output - only the generic `/service` log group
exists, and its messages ("Successfully pulled your application image...
Failed to deploy your application image") don't say why. If you see this
generic pattern with zero app-level output, the cause is almost always
something about the **image itself** (manifest format, architecture,
missing entrypoint) rather than your Python code - see the next section
before spending time debugging application logic that never even ran.

### Bedrock

**There is no separate "deploy to Bedrock" step** - worth being explicit
about, since it's an easy thing to expect given every other service in
this list gets its own deploy. Bedrock is a managed LLM API this app
*calls at runtime* (through `BedrockChatClient`), not a place the
application's own code ever gets uploaded to or runs on. "Deploying
Bedrock support" means exactly what already happened in Phase 9: writing
the client, wiring it into `/health`, and granting the App Runner instance
role `bedrock:InvokeModel*` permission (see [IAM](#iam-roles-and-users)) -
there's no image, container, or function to push to Bedrock itself.

```bash
# From inside the running container's identity, or locally with equivalent creds:
aws bedrock list-foundation-models --region us-east-1 --query 'modelSummaries[*].modelId' | head -5
```
The app's own `GET /health?provider=bedrock` does the equivalent check over
HTTP and is the easier way to validate it end-to-end.

### Postgres (Neon) - once provisioned

Not live yet. Once a Neon (or any reachable Postgres) instance exists:

1. Create 5 secrets: `hrb-chatbot/POSTGRES_DB_HOST`, `_PORT`, `_NAME`,
   `_USER`, `_PASSWORD` - same `secretsmanager create-secret` pattern as the
   existing 5, no new IAM permission needed (the instance role's policy
   already covers the whole `hrb-chatbot/*` prefix).
2. `aws apprunner update-service` (or re-run the create script with these
   added to `RuntimeEnvironmentSecrets`, plus `RAG_METADATA_STORE=postgres`
   in `RuntimeEnvironmentVariables`) - config-only, no image rebuild.
3. Validate: `GET /health?metadata_provider=postgres` against the
   deployed URL should report `"status": "healthy"`.

### S3 and Lambda

Nothing to validate - neither is provisioned. If this ever gets built,
`docs/agent-reference/S3-ASYNC-UPLOAD-DESIGN.md` is the starting design (presigned upload
URL → S3 event notification → Lambda calls the existing indexing
pipeline). Worth remembering going in: ChromaDB's embedded/persistent mode
doesn't fit Lambda's ephemeral filesystem - that document already flags
Pinecone/Postgres as the natural fit for that future architecture, which
lines up with what Phase 10 chose for App Runner anyway.

---

## CI/CD (GitHub Actions)

Two workflows, `.github/workflows/ci.yml` and `.github/workflows/deploy.yml`
- what each *gate* actually checks and why those thresholds were picked is
[`CICD-BRANCHING-STRATEGY.md`](CICD-BRANCHING-STRATEGY.md)'s job; this
section stays focused on the AWS side of what runs.

**CI** runs on every push/PR to any branch and needs **no AWS credentials at
all** - it proves the app imports, the test suite passes at an enforced
coverage floor, `bandit` finds no MEDIUM+ static-security issue, and the
Docker image builds (with the same load-bearing flags as production, so a
regression there is caught here too, before it ever reaches a real
deploy). `pip-audit` also runs here but is report-only for now, not
blocking - see the branching-strategy doc's security-gate section for why.

**Deploy** runs only on push to `master` (renamed from `main` on
2026-09-08, along with `developer` → `develop` and
`feature-kb-indexing-rag-pipeline` → `feature-langchain-rag-pipeline` - a
GitHub rename deletes the old ref outright, so `deploy.yml`'s trigger had
to be updated in the same change or it would have silently stopped firing)
and needs the two secrets below, added once via GitHub's own UI (Settings
→ Secrets and variables → Actions), not via API - there was no `gh` CLI or
GitHub token available when this was built, so the values were written to
a local, gitignored scratch file and never appeared in any tool output or
chat message:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Both belong to `hrb-chatbot-github-actions-deploy` (see
[IAM](#iam-roles-and-users) for exactly what it can do). **This step is
still pending** - confirm it's done before expecting `deploy.yml` to
succeed on a real push to `master`. Once triggered, the workflow now also
waits for the new App Runner deployment to reach `RUNNING` and runs a real
`curl /ping` against the live URL before calling itself done - added
2026-09-08, see the branching-strategy doc's "Deployment testing" section.

To validate CI/CD wiring without waiting for a real merge to `main`:
```bash
curl -s "https://api.github.com/repos/rvsree/hrb_chatbot_service/actions/runs?branch=<branch>&per_page=3"
```
No auth needed for a public repo's Actions API.

---

## Three real bugs found the hard way

Documented here in full because each one produced the *exact same* generic
symptom (`CREATE_FAILED`, image pulled fine, zero application logs), and a
future person hitting that symptom should check these three things in
order rather than re-discovering them from scratch.

1. **Secret ARN missing its random suffix.** Secrets Manager appends one
   to every secret name (`hrb-chatbot/OPENAI_API_KEY-LdC1Q6`, not
   `hrb-chatbot/OPENAI_API_KEY`); App Runner requires the exact full ARN
   in `RuntimeEnvironmentSecrets`. **Fix**: never hand-type a secret ARN -
   resolve it via `secretsmanager list-secrets` at deploy time (see the
   `resolve_secret_arns()` pattern the deploy script uses).
2. **BuildKit's default provenance/SBOM attestation manifests.** A plain
   `docker build` (no flags) wraps the real image in an OCI image *index*
   alongside an attestation manifest - AWS services that expect a single
   plain image manifest (this is also a documented issue for AWS Lambda)
   pull it "successfully" and then never actually run it. **Fix**:
   `--provenance=false --sbom=false`.
3. **OCI-format manifest instead of classic Docker v2 schema2, even with
   attestations off.** Confirmed via `docker manifest inspect` showing
   `application/vnd.oci.image.manifest.v1+json` after fix #2 was already
   applied - a *second*, independent cause of the identical symptom.
   **Fix**: `--output type=image,...,oci-mediatypes=false,push=true`
   (`docker buildx build`, not plain `docker build`).

All three fixes are already baked into `deploy.yml` and this runbook's
[containerize step](#2-containerize---and-use-the-exact-right-build-flags)
- the risk from here forward is someone "simplifying" the build command
back to a bare `docker build -t ... .` and silently reintroducing one of
these. If you ever need to touch that line, re-run the two verification
commands in step 2 before pushing, not after a failed deploy.
