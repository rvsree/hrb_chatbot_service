# LinkedIn Article Ideas — Reference List

Personal reference only - not part of the project's own docs/agent-reference or
docs/dev-reference sets, not synced anywhere, just a working list. Saved
2026-10-20.

Each idea is grounded in something actually built and verified in this
project (hrb_chatbot_service / hrb_chatbot_ui / hrb_lms_mcp) - not generic RAG/AI
advice. Ordered simple -> moderate -> advanced.

**Before publishing anything from this list:** genericize real company
names (the project's own docs/code already use "Amazing Bank" as the
fictional stand-in; also check for Empower Retirement, Guild Education,
mySedgwick) - e.g. "a Fortune 500 HR benefits system" instead. This is a
personal learning project built from real public document text, not a
company deliverable, and the engineering lessons don't depend on the real
names.

## Simple

| # | Topic | Problem it solves | Core architecture |
|---|---|---|---|
| 1 | Presigned S3 uploads | Keeping large file bytes off your app server | Client gets a signed URL from the API, uploads straight to S3, API never touches the bytes |
| 2 | Two health endpoints, not one | `/ping` (process up) vs `/health` (can it actually reach every backend) get conflated constantly | Two routes, two different jobs, one cheap and instant, one real but slower |
| 3 | RBAC that's honest about being fake | Most demo auth either pretends to be real or doesn't exist at all | Self-asserted identity, documented as a formality, with a clear line for when it stops being acceptable (money moving) |
| 4 | Chunking strategy auto-selection | One chunking approach doesn't fit every document type | 6 strategies, picked by document shape, not hardcoded |

## Moderate

| # | Topic | Problem it solves | Core architecture |
|---|---|---|---|
| 5 | Why your RAG precision score might be lying to you | Teams trust eval numbers without checking if the metric fits the dataset | A metric structurally capped at 1/k when the dataset only labels 1 correct doc per question - the number looks bad, isn't |
| 6 | Three eval methods, one dashboard | Live eval, offline eval, and judge-based eval get conflated into "the eval score" | Exact-match for the golden dataset, LLM-as-judge for groundedness/completeness, a third live estimate for real queries - each answering a different question |
| 7 | Document ACL inside retrieval, not after it | Access control bolted on after search leaks what exists | Role/department filter applied at the vector search call itself, denial count surfaced, not silently dropped |
| 8 | Answer + embedding caching without stale data | Caching an LLM answer can serve wrong info once source docs change | Cache keyed off content hash, invalidated on re-index, not time-based |
| 9 | Content-hash dedup for document re-uploads | Re-uploading the same PDF shouldn't double-index it | Hash compared before chunking starts, supersedes the old version instead of duplicating |

## Advanced

| # | Topic | Problem it solves | Core architecture |
|---|---|---|---|
| 10 | Async batch ingestion: presigned upload -> S3 -> SQS -> Lambda | Synchronous ingestion blocks the request and doesn't scale with upload volume | Event-driven pipeline, partial-batch failure handling, DLQ, real concurrency bug found and fixed (asyncio event loop outliving a cached client) |
| 11 | Human-in-the-loop as a real pause/resume, not a status flag | Most "approval workflow" demos fake the pause with a boolean | LangGraph `interrupt()`/`Command(resume=...)` with a durable Postgres checkpoint - the workflow actually stops and picks back up later, survives a restart |
| 12 | Three RAG architectures, same problem, deliberately different | Picking one agentic pattern and pretending it's the only answer | Fixed retrieve-then-generate, ReAct tool-calling loop, and a LangGraph multi-agent graph, built side by side so the tradeoffs are visible, not asserted |
| 13 | Multi-agent orchestration, the parts that actually go wrong | Fan-out/reviewer patterns look clean in diagrams, break in metrics | Planner -> parallel domain agents -> reviewer, plus a real bug where non-LLM dispatch was miscounted as LLM calls |
| 14 | When not to adopt a hot new protocol | Agentic AI hype pushes teams to adopt protocols before they have the use case for them | Real A2A protocol reasoning: it's built for agents that are separate, independently-deployed services - adopting it for an in-process multi-agent system duplicates a framework already there |
| 15 | Cross-service agent tooling over MCP with real OAuth2 | Service-to-service LLM tool calls often skip real auth entirely | Client-credentials flow between two separate deployed services, not a shared secret or an open endpoint |

## Notes

- Several of these already have a close-to-draft writeup in `docs/dev-reference/` -
  check there first before writing from scratch.
- Publishing order doesn't have to match this table's order - pick whichever
  makes the strongest opening post, then let engagement/feedback guide the rest.
