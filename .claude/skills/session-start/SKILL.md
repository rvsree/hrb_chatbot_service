---
name: session-start
description: >
  Run at the start of a Claude Code session on hrb_chatbot_service. Loads current
  branch, recent commits, and open work from docs/agent-reference/RAG-ROADMAP.md and
  docs/agent-reference/BACKLOG.md, so a session that starts with no memory of prior ones
  still knows what's in flight. Invoke automatically on session start, or
  explicitly as /session-start.
allowed-tools: Read Bash(git *) Grep
---

# Session start checklist

Run these checks and report one short summary - not a wall of text. This
project pays real API-usage cost per session; don't pad output.

1. `git branch --show-current` and `git log --oneline -5`.
2. Count rows in `docs/agent-reference/RAG-ROADMAP.md`'s "Status at a glance" table (under
   `## Status at a glance`) whose Status column contains `📋` (Planned) or
   `🚧` (in progress, not done). Report the count and the lowest-numbered
   open phase by name.
3. Count open (non-strikethrough, not under `## Cleanup done ...`) items in
   `docs/agent-reference/BACKLOG.md`.
4. `git status --short` - report a count of uncommitted files, or "none".

Output format:
```
Session ready.
Branch: <branch-name> | Last commit: <one-line message>
RAG-ROADMAP: <count> phase(s) still open - next: <phase name>
BACKLOG: <count> open item(s)
Uncommitted changes: <count or "none">
```

Then wait for the user's instruction. Do not start work, and do not read the
full RAG-ROADMAP.md or BACKLOG.md files unless the user's next instruction
actually needs the detail - this check only needs the status table and
section headers, not the full history each file carries.
