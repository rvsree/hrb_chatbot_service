---
name: spec-verify
description: >
  Map test coverage back to a phase's spec acceptance criteria in
  hrb_chatbot_service, after implementation. Invoke as /spec-verify
  <phase-name-or-number>.
argument-hint: "<phase name or number>"
allowed-tools: Read Grep Glob Bash(.venv/Scripts/python.exe -m pytest *)
---

# Verify a spec's acceptance criteria are actually tested

1. Read the target phase's `**Spec:**` block in `docs/agent-reference/RAG-ROADMAP.md`.
2. For each "User-visible behavior" and "Failure modes" line, find the test
   that exercises it. `tests/` mirrors `src/` 1:1 (see `CLAUDE.md`), so a
   change in `src/hrb_chatbot/ai/doc_processing/chunking/text_chunker.py`
   should have coverage in
   `tests/hrb_chatbot/ai/doc_processing/chunking/test_text_chunker.py`.
3. For "Retrieval quality criteria" (when present), confirm at least one
   test or a documented manual run exercises the named
   `resources/golden_dataset/golden_dataset.json` rows - a golden-dataset
   check doesn't have to be a `pytest` test if none exists yet, but say so
   explicitly rather than marking it covered.
4. Run `.venv\Scripts\python.exe -m pytest -v -k "<relevant keyword>"` to
   confirm the tests you mapped actually exist and pass - don't just grep
   for a plausible-looking test name.

Report a table: acceptance criterion -> test file:test name (or "no test
found" / "manual verification only, see <where>"). Do not write new tests
yourself in this step unless the user asks - flag the gap (see CLAUDE.md's
SDD section, "flag don't fix") and let the user decide whether closing it is
this task or the next one.
