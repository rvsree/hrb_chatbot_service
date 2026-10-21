"""PreToolUse hook for hrb_chatbot_service - blocks a Write/Edit under
src/hrb_chatbot/** unless at least one phase in
docs/agent-reference/RAG-ROADMAP.md has a written, not-yet-done spec.

Deliberately scoped to src/hrb_chatbot/** only (via `should_gate` below) -
never .claude/, tests/, or docs/ - so this hook can never lock out fixing
itself, writing tests, or writing the next spec. See CLAUDE.md's SDD
section for why a *written* spec is the bar, not a matching-scope spec:
this hook cannot verify a given edit falls inside a spec's declared
boundary, only that some spec is in flight. That's implementer.md's job
("stay inside the phase's declared scope"), not this hook's.

Detection: scans docs/agent-reference/RAG-ROADMAP.md's "## Phases" section for a top-level
"- [ ]" bullet (not yet done) that has a nested "- **Spec:**" sub-item
(see .claude/skills/spec-new/SKILL.md for the format). Any match -> allow.

Run manually with: python .claude/scripts/spec_gate.py < payload.json
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ROADMAP = PROJECT_ROOT / "docs" / "agent-reference" / "RAG-ROADMAP.md"


def should_gate(file_path: str) -> bool:
    if not file_path.endswith(".py"):
        return False
    try:
        relative = Path(file_path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        relative = file_path.replace("\\", "/")
    return relative.startswith("src/hrb_chatbot")


def has_open_spec() -> bool:
    text = ROADMAP.read_text(encoding="utf-8")

    # Scan the whole file for phase bullets rather than bounding by heading -
    # confirmed live (2026-09-14) that phase content actually spans two
    # separate "## " headings ("## Phases", then later "## Phase 5 onward
    # - ..."), which a "stop at the next ## heading" bound silently missed.
    # The "- [ ]"/"- [x]" + "**Phase" bullet shape is specific enough on its
    # own - no need to bound by section at all.
    blocks = re.split(r"\n(?=- \[[ x]\] \*\*Phase)", text)

    for block in blocks:
        if block.startswith("- [ ]") and re.search(r"^\s+- \*\*Spec:\*\*", block, re.MULTILINE):
            return True
    return False


def deny(reason: str) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output))
    sys.exit(2)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return  # can't read the payload - fail open, don't block on our own error

    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not should_gate(file_path):
        return

    if not has_open_spec():
        deny(
            "No open spec found in docs/agent-reference/RAG-ROADMAP.md's ## Phases section "
            "(a '- [ ]' phase with a nested '- **Spec:**' block). Write one "
            "with /spec-new before editing src/hrb_chatbot/**."
        )


if __name__ == "__main__":
    main()
