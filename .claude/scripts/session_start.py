"""SessionStart hook for hrb_chatbot_service.

Prints a short "what's in flight" summary: current branch, last commit,
how many phases in docs/agent-reference/RAG-ROADMAP.md's status table are
still open, and how many docs/agent-reference/BACKLOG.md items are open.
Cheap and read-only - no test run, no network call - so it's safe to run on
every session start.

Run manually with: python .claude/scripts/session_start.py
"""

import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def count_open_roadmap_phases() -> tuple[int, str | None]:
    """Count '📋' and '🚧' rows in RAG-ROADMAP.md's status table, return
    (count, name-of-first-open-phase-or-None)."""
    roadmap = PROJECT_ROOT / "docs" / "agent-reference" / "RAG-ROADMAP.md"
    text = roadmap.read_text(encoding="utf-8")

    table_start = text.find("## Status at a glance")
    table_end = text.find("\n## ", table_start + 1)
    table = text[table_start:table_end] if table_end != -1 else text[table_start:]

    open_rows = []
    for line in table.splitlines():
        if line.startswith("|") and ("📋" in line or "🚧" in line):
            match = re.match(r"\|\s*([^|]+)\|", line)
            if match:
                open_rows.append(match.group(1).strip())

    first = open_rows[0] if open_rows else None
    return len(open_rows), first


def count_open_backlog_items() -> int:
    """Count '- **' bullet items in BACKLOG.md that are not struck through
    (~~...~~) - a rough proxy for "not yet resolved"."""
    backlog = PROJECT_ROOT / "docs" / "agent-reference" / "BACKLOG.md"
    text = backlog.read_text(encoding="utf-8")

    open_count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- **") and "~~" not in stripped:
            open_count += 1
    return open_count


def main() -> None:
    branch = run_git("branch", "--show-current") or "(detached)"
    last_commit = run_git("log", "-1", "--format=%s") or "(no commits)"
    uncommitted = run_git("status", "--short")
    uncommitted_count = len(uncommitted.splitlines()) if uncommitted else 0

    open_phases, next_phase = count_open_roadmap_phases()
    open_backlog = count_open_backlog_items()

    print("Session ready.")
    print(f"Branch: {branch} | Last commit: {last_commit}")
    if next_phase:
        print(f"RAG-ROADMAP: {open_phases} phase(s) still open - next: {next_phase}")
    else:
        print(f"RAG-ROADMAP: {open_phases} phase(s) still open")
    print(f"BACKLOG: {open_backlog} open item(s)")
    print(f"Uncommitted changes: {uncommitted_count if uncommitted_count else 'none'}")


if __name__ == "__main__":
    main()
