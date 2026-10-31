# Architecture Diagrams Index

**Moved 2026-10-26**: every diagram except `hrb_api_gateway_service`'s 3
(load-bearing here - registered in this repo's own `sync_admin_docs.py`,
which needs a local file to hash/upload) now lives in the shared
`hrb_emp_assist` repo's own `docs/architecture/diagrams/` - a stale local
duplicate set for the other applications was found and removed 2026-10-30
(it had silently drifted out of sync with the real, current versions).

Every `.drawio` diagram for this platform, one row per application, grouped by type. All editable in [draw.io](https://app.diagrams.net) (free, no account) or the VS Code draw.io extension — File → Open, no import step needed.

For the one-page cross-service picture (business capabilities + request flow + links out to everything, including these diagrams), start at [`platform-overview.html`](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/platform-overview.html) instead of this file.

## By application

| Application | Current-state / process architecture | Target-state (scaling) architecture | Deployment architecture (AWS) | Status |
|---|---|---|---|---|
| **hrb_chatbot_ui** | [hrb-chatbot-ui-current-state-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/hrb-chatbot-ui-current-state-architecture.drawio) | — not built (static SPA via CloudFront scales without a scaling story) | — covered by an HTML doc, not a `.drawio` | 1 of 3 |
| **hrb_api_gateway_service** | [api-gateway-current-state-architecture.drawio](api-gateway-current-state-architecture.drawio) | [api-gateway-target-state-scaling-architecture.drawio](api-gateway-target-state-scaling-architecture.drawio) | [api-gateway-deployment-architecture.drawio](api-gateway-deployment-architecture.drawio) | **3 of 3 — full set, lives here, synced to S3/Postgres (confirmed live 2026-10-30).** |
| **hrb_chatbot_service** | [hrb-chatbot-service-current-state-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/hrb-chatbot-service-current-state-architecture.drawio) | [hrb-chatbot-service-target-state-scaling-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/hrb-chatbot-service-target-state-scaling-architecture.drawio) | [hrb-chatbot-service-deployment-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/hrb-chatbot-service-deployment-architecture.drawio) | 3 of 3 |
| **rag_ingestion_service** | [rag-ingestion-batch-pipeline.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/rag-ingestion-batch-pipeline.drawio) *(named for the batch/async process, predates the current/target/deployment naming convention)* | [rag-ingestion-service-target-state-scaling-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/rag-ingestion-service-target-state-scaling-architecture.drawio) | [rag-ingestion-deployment-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/rag-ingestion-deployment-architecture.drawio) | 3 of 3 |
| **rag_retrieval_service** | [rag-retrieval-service-current-state-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/rag-retrieval-service-current-state-architecture.drawio) | [rag-retrieval-service-target-state-scaling-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/rag-retrieval-service-target-state-scaling-architecture.drawio) | [rag-retrieval-service-deployment-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/rag-retrieval-service-deployment-architecture.drawio) | 3 of 3 |
| **hrb_platform_components** | [hrb-platform-components-current-state-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/hrb-platform-components-current-state-architecture.drawio) | [hrb-platform-components-target-state-scaling-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/hrb-platform-components-target-state-scaling-architecture.drawio) *(honest "mostly unchanged" case — no employee-growth scaling story applies)* | [hrb-platform-components-deployment-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/hrb-platform-components-deployment-architecture.drawio) | 3 of 3 |
| **hrb-common-libs** | [hrb-common-libs-consumption-architecture.drawio](https://github.com/rvsree/hrb_emp_assist/blob/master/docs/architecture/diagrams/hrb-common-libs-consumption-architecture.drawio) *(a library, not a running service — "current-state/target-state/deployment" don't apply the same way)* | n/a | n/a | complete as scoped |

## Reading the diagrams

- **White box background, colored border** — the color is the category (navy = service, orange = compute/worker, green = storage, purple = Postgres/external, gold = queue). Text is always neutral dark for readability.
- **Dashed orange border** — proposed / target-state, **not built**. Solid border — real, built, verified.
- **Small corner badges** — real AWS icons (`mxgraph.aws4.*`) for AWS-native services (Lambda, S3, SQS, IAM, Secrets Manager, ECR, App Runner); plain "SVC"/"S3" text badges where no AWS icon applies, or where I couldn't independently render-verify the exact icon stencil.
- **Numbered circles on arrows** — step order through a real request/process flow.
- Every diagram's footer states what was verified and how (AWS CLI calls, direct source reads) as of its own date — check that date before trusting a specific number.

## Known gaps in this index

- `hrb_chatbot_ui` has no target-state or `.drawio` deployment diagram — covered only by the earlier HTML build-and-deploy docs.
- `hrb_api_gateway_service`'s 3 diagrams are the only ones registered in S3 / `doc_metadata` (confirmed live 2026-10-30, synced to production) - everything else in this table is a documentation-only `.drawio` in the shared `hrb_emp_assist` repo, not wired into any admin-docs sync.
- `rag-ingestion-batch-pipeline.drawio`'s name doesn't match the `*-current-state-architecture.drawio` convention every other service uses — a naming inconsistency from before that convention was settled, flagged here rather than silently renamed.
