---
name: coding-standards
description: >
  Apply hrb_chatbot_service's existing coding standards to a file being generated
  or reviewed. Invoke automatically when writing or editing Python source
  under src/ or tests/, or explicitly as /coding-standards <file-path>.
argument-hint: "[file-path]"
allowed-tools: Read Grep
---

# Coding standards check

This is a thin wrapper, not a second copy of the rules - the actual
standards live in **`docs/agent-reference/CODING-STANDARDS.md`**. Read that file, then apply
it to the file in question. Do not duplicate its content here; if it's ever
out of date with this skill's expectations, `docs/agent-reference/CODING-STANDARDS.md` is
correct and this skill should be updated to match, not the other way round.

## What to check, in short (full reasoning is in the doc)

1. **Comments explain *why*, briefly** - not what the code already says by
   being well-named. **Two-line hard limit** (inline comments, docstrings,
   module docstrings alike); a third line only at a genuinely critical spot,
   sparingly - move real design reasoning to `docs/agent-reference/FAQ.md` or the phase's
   own spec in `docs/agent-reference/RAG-ROADMAP.md` instead of a long docstring.
2. **Errors, by layer:** client layer (`common/clients/**`) returns errors
   as data, never raises from `health_check()`; service layer raises;
   route layer (`api/**/routes_*.py`) catches and returns the consistent
   `{"error": "...", "code": "..."}` shape via `api/dependencies.py`'s
   `json_error()`, always with an explicit `common/error_codes.py` code.
3. **Every client follows the same shape** - a new provider client
   implements its `Base*Client` ABC fully, no partial implementations.
4. **API contracts:** business/data endpoints declare a Pydantic request
   model and a `response_model`; health/diagnostic endpoints are the
   documented exception (no fixed schema, growing checks dict).
5. **Naming:** full English words, not abbreviated - `check_database`, not
   `chk_db`. If a name needs a comment to say *what* it does, the name is
   wrong, not the comment.
6. **Provider/backend selection is a `common/enums.py` `StrEnum`**, not a
   raw `str`, everywhere it's a request parameter - see `VectorDB`,
   `MetadataStore`, `LlmProvider`. Free-text fields that are genuinely
   open-ended (model names) stay `str`.

Report violations found before writing them to disk, referencing the
specific rule in `docs/agent-reference/CODING-STANDARDS.md` (or this list) each one
violates - not a vague "this could be cleaner."
