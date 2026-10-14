---
name: delivery-note
description: >
  Generate a concise delivery note after finishing a task on hrb_chatbot_v2.
  Invoke automatically at the end of a task, or explicitly as /delivery-note.
  Keeps the summary short and cost-conscious instead of padded prose.
allowed-tools: Bash(git diff --stat *) Bash(git status --short *)
---

# Delivery note

After completing a task, produce this note - under 20 lines total. No
"hope this helps," no restating what the diff already shows.

```
## Delivery note - <task name>

**Done:**
- <one line per file created/changed, with path>

**Files changed:** <git diff --stat output>

**Tests:** <passed/failed, with counts if run - or "not run" if genuinely
not applicable>

**Flagged, not fixed:** <any out-of-scope issue noticed while working, one
line each, or "none">

**Docs in sync:** <if this task changed design/architecture/a contract, did
the feature's own docs/dev-reference/<feature>/ set get updated and re-
synced (see CLAUDE.md)? "yes, synced" / "yes, not yet synced - needs your
go-ahead" / "n/a - no design/architecture/contract change">

**Next step (suggested):** <one sentence>
```

Stop after the note. Wait for the next instruction rather than continuing
into a new task unprompted - matches this project's "one task at a time"
convention (see CLAUDE.md).
