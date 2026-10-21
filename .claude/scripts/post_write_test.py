"""PostToolUse hook for hrb_chatbot_service - runs the test suite after a
Write/Edit under src/hrb_chatbot or tests/, and surfaces failures only.

Reads the hook's JSON payload on stdin (see Claude Code's hooks reference
for the exact shape - includes tool_name/tool_input.file_path). Any other
file (docs, .claude/ itself, etc.) is a silent no-op - this project's suite
is fast (~88 tests, ~8-12s) but there's no reason to run it for a markdown
edit.

PostToolUse stdout is NOT shown to Claude automatically - only a specific
JSON shape on stdout is. On a passing run this script prints nothing and
exits 0. On a failing run it prints
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "systemMessage": "..."}}
so the failure actually reaches the conversation instead of only a log file.

Run manually with: python .claude/scripts/post_write_test.py < payload.json
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
LOG_FILE = PROJECT_ROOT / ".claude" / "scripts" / "last_test_run.log"

WATCHED_PREFIXES = ("src/hrb_chatbot", "src\\hrb_chatbot", "tests")


def should_run(file_path: str) -> bool:
    if not file_path.endswith(".py"):
        return False
    try:
        relative = Path(file_path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        relative = file_path.replace("\\", "/")
    return relative.startswith(("src/hrb_chatbot", "tests"))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return

    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not should_run(file_path):
        return

    python_exe = str(VENV_PYTHON) if VENV_PYTHON.exists() else "python"
    result = subprocess.run(
        [python_exe, "-m", "pytest", "-q"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    LOG_FILE.write_text(result.stdout + result.stderr, encoding="utf-8")

    if result.returncode != 0:
        summary_lines = [
            line
            for line in result.stdout.splitlines()
            if "failed" in line.lower() or "error" in line.lower()
        ]
        summary = "\n".join(summary_lines[-15:]) or "pytest exited non-zero - see .claude/scripts/last_test_run.log"
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "systemMessage": (
                    f"Tests failed after editing {file_path}:\n{summary}\n"
                    "Full output in .claude/scripts/last_test_run.log"
                ),
            }
        }
        print(json.dumps(output))


if __name__ == "__main__":
    main()
