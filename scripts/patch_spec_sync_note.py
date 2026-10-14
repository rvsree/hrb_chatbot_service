"""Adds a one-line governance note to every registered "spec" doc_type
page - see CLAUDE.md's "Docs stay in sync with reality" norm (2026-10-14).
Idempotent: skips a file that already has the marker comment. Run as:
python -m scripts.patch_spec_sync_note"""

import os

from scripts.sync_admin_docs import DOCS_TO_SYNC

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MARKER = "<!-- spec-sync-note -->"

NOTE_HTML = (
    f'{MARKER}\n'
    '    <p style="margin-top:8px; font-size:11.5px;">'
    "Keep this in sync: any design, architecture, or major implementation change "
    "must be reflected in this doc set and re-synced to S3 "
    "(<code>python -m scripts.sync_admin_docs</code>, tracked by doc_version) "
    "before the work is considered done."
    "</p>\n"
)


def main() -> None:
    patched = 0
    skipped = 0
    for feature_name, docs_by_type in DOCS_TO_SYNC.items():
        spec_entry = docs_by_type.get("spec")
        if spec_entry is None:
            continue
        _title, local_path, content_type = spec_entry
        if content_type != "text/html":
            continue
        abs_path = os.path.join(REPO_ROOT, local_path)
        with open(abs_path, encoding="utf-8") as file_handle:
            content = file_handle.read()

        if MARKER in content:
            skipped += 1
            continue

        if "</footer>" not in content:
            print(f"SKIPPED (no </footer> found): {feature_name}/spec")
            continue

        content = content.replace("</footer>", NOTE_HTML + "  </footer>", 1)

        with open(abs_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(content)
        patched += 1
        print(f"patched: {feature_name}/spec")

    print(f"\n{patched} patched, {skipped} already had the note")


if __name__ == "__main__":
    main()
