---
name: architecture-review
description: >
  Review a proposed design, new module, or non-trivial change against
  hrb_chatbot_service's established architecture and recorded decisions, before
  implementation. Invoke as /architecture-review <description>, or
  automatically before generating a new module/pipeline stage.
argument-hint: "<file-path or design description>"
allowed-tools: Read Grep Glob
---

# Architecture review

This project has no separate ADR folder - recorded decisions and their
rationale live in **`docs/agent-reference/FAQ.md`** (design Q&A) and in `CLAUDE.md`'s
architecture section. Check a proposed design against both before writing
code.

## What's already settled (see `CLAUDE.md` for detail)

- **Two separate pipelines under `ai/`:** `ai/doc_processing/pipeline.py`
  (ingestion) and `ai/rag_pipeline/pipeline.py` (query). A change belongs in
  exactly one; don't blur them.
- **One library per pipeline stage, deliberately:** LangChain splitters for
  chunking, LlamaIndex `VectorStoreIndex` for indexing, raw LangChain for
  retrieval. Don't "consolidate" onto one library without a real reason
  recorded in `docs/agent-reference/FAQ.md` first.
- **Backend selection is gateway + enum, never scattered if/elif:** a new
  LLM/vector/metadata provider gets a `Base*Client` ABC implementation and a
  `common/enums.py` `StrEnum` member - see `common/clients/*/db_gateway.py`
  /`client_gateway.py`.
- **`GET /ping` vs `GET /health`:** liveness (no provider calls) vs the real
  diagnostic (always makes one free call per backend). Don't reintroduce a
  shallow/deep toggle on `/health` - that was deliberately removed.
- **Error handling by layer** - see `docs/agent-reference/CODING-STANDARDS.md`.

## How to run a review

1. Read the proposed change/description.
2. Check it against the settled points above and against `docs/agent-reference/FAQ.md` for
   anything more specific to the area being touched.
3. Check `docs/agent-reference/BACKLOG.md` and `docs/agent-reference/RAG-ROADMAP.md`'s open phases (see
   `/session-start`) for whether this overlaps or conflicts with already-
   planned work.
4. Report:

```
## Architecture review: <description>

### Consistency with established decisions
| Area | Status | Note |
|---|---|---|
| Pipeline placement | OK / conflict / n/a | |
| Library choice (chunking/indexing/retrieval) | | |
| Backend selection pattern | | |
| Error handling by layer | | |

### Overlaps with planned/open work
<anything from RAG-ROADMAP/BACKLOG this touches>

### Recommendation
PROCEED / STOP / MODIFY - one sentence why.
```

If the change is genuinely new ground (no existing precedent to check
against), say so plainly rather than forcing a fit - and suggest it's
worth a `docs/agent-reference/FAQ.md` entry once decided, so the next review has something
to check against.
