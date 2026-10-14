---
name: spec-implement
description: >
  Execute one already-reviewed phase spec from docs/agent-reference/RAG-ROADMAP.md end to
  end. Invoke as /spec-implement <phase-name-or-number>. For a scoped,
  isolated execution, use the implementer subagent instead
  (.claude/agents/implementer.md); this skill is the same checklist run
  directly in the main session.
argument-hint: "<phase name or number>"
allowed-tools: Read Edit Write Bash(.venv/Scripts/python.exe -m pytest *) Bash(git *)
---

# Implement a phase from its spec

Preconditions - stop and report if either is missing, don't proceed anyway:
1. The target phase has a `**Spec:**` block in `docs/agent-reference/RAG-ROADMAP.md` (see
   `/spec-new`). No spec, no implementation.
2. The spec has been reviewed (`/spec-review` run, or the user has
   explicitly said it's approved).

## Steps

1. Re-read the spec's "Data/API contracts", "User-visible behavior", and
   "Failure modes" sections - these are the acceptance criteria. If "Data/API
   contracts" points at `docs/agent-reference/endpoint-request-response-contracts.md`, read
   that section too and implement the wire shape exactly as written there -
   it is the actual source of truth, not the spec's summary of it.
2. Implement in the smallest coherent slice that satisfies them, following
   `docs/agent-reference/CODING-STANDARDS.md` (or invoke `/coding-standards` explicitly on
   each new/changed file).
3. Write a test for every acceptance criterion in the spec - `tests/`
   mirrors `src/` 1:1.
4. Run `.venv\Scripts\python.exe -m pytest -v` - all tests pass, not just
   the new ones.
5. If anything in the spec is ambiguous or contradicts existing code, stop
   and ask rather than guessing - do not silently reinterpret the spec.
6. Update the phase's checkbox in `docs/agent-reference/RAG-ROADMAP.md` (`- [ ]` -> `- [x]`),
   its row in the "Status at a glance" table, and add a short "Verified:
   ..." line to the bullet describing what was actually checked - the same
   pattern every other completed phase in that file already follows.
7. If this phase changed design, architecture, or a request/response
   contract that the feature's own `docs/dev-reference/<feature>/` doc set
   already describes (Spec/Architecture/Design/Decisions), update those
   docs to match now - don't leave them to drift and get caught later.
   Re-syncing them (`python -m scripts.sync_admin_docs`) is still a real
   push to production, so it's gated by `CLAUDE.md`'s no-push-without-go-
   ahead norm - update the docs locally, then ask before running the sync.

Do not start a second phase in the same turn. One phase, reviewed, then
stop - matches `CLAUDE.md`'s "one task at a time" rule.
