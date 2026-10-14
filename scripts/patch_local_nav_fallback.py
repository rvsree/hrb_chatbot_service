"""Phase 180 (round 11) - every doc's Spec/Architecture/Design/Decisions
nav links point at the live hrb-chatbot-ui.rvsree.dev admin viewer, which
needs a real logged-in session - opening a doc locally via file:// can
never authenticate against it, so local review of cross-document links
was impossible before this. Injects a small script into every registered
doc that detects file:// access and rewrites those links to the sibling
doc's real local file:// path instead - production behavior (S3 presigned
URLs via /admin/open-doc) is untouched, this only fires when opened
locally. Idempotent: skips a file that already has the marker comment.
Run as: python -m scripts.patch_local_nav_fallback"""

import os

from scripts.sync_admin_docs import DOCS_TO_SYNC

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MARKER = "<!-- local-nav-fallback -->"


def build_script(feature_name: str, docs_by_type: dict) -> str:
    entries = []
    for doc_type, (_title, local_path, _content_type) in docs_by_type.items():
        abs_path = os.path.abspath(os.path.join(REPO_ROOT, local_path)).replace("\\", "/")
        # Quoted key - an unquoted one breaks for any doc_type with a
        # hyphen (e.g. "deployment-aws" parses as subtraction in JS),
        # confirmed live once the deployment-guide series registered
        # hyphenated doc_types for the first time.
        entries.append(f'    "{doc_type}": "file:///{abs_path}"')
    local_docs_js = ",\n".join(entries)

    return f"""{MARKER}
<script>
(function () {{
  if (location.protocol !== "file:") return;
  var LOCAL_DOCS = {{
{local_docs_js}
  }};
  document.querySelectorAll('a[href*="/admin/open-doc"]').forEach(function (a) {{
    var match = a.href.match(/[?&]type=([^&]+)/);
    if (!match) return;
    var localPath = LOCAL_DOCS[match[1]];
    if (localPath) {{
      a.href = localPath;
      a.removeAttribute("target");
    }}
  }});
}})();
</script>
"""


def main() -> None:
    patched = 0
    skipped = 0
    for feature_name, docs_by_type in DOCS_TO_SYNC.items():
        for doc_type, (_title, local_path, content_type) in docs_by_type.items():
            if content_type != "text/html":
                continue
            abs_path = os.path.join(REPO_ROOT, local_path)
            with open(abs_path, encoding="utf-8") as file_handle:
                content = file_handle.read()

            if MARKER in content:
                skipped += 1
                continue

            script = build_script(feature_name, docs_by_type)
            content = content.rstrip() + "\n" + script

            with open(abs_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(content)
            patched += 1
            print(f"patched: {feature_name}/{doc_type}")

    print(f"\n{patched} patched, {skipped} already had the fallback")


if __name__ == "__main__":
    main()
