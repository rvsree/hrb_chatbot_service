"""Every doc's Spec/Architecture/Design/Decisions nav links are hardcoded
to https://hrb-chatbot-ui.rvsree.dev - correct for a real user, but it
means clicking through docs while running the app locally always bounces
to production, needing a separate production login. Same production
behavior must stay the default (no code fork between local/AWS) - so
instead the APP itself (DocLink.tsx, identical code everywhere) tells each
opened doc what origin it was opened from, via a URL fragment
(#app_base=...), which S3 never sees or signs. This script injects a small
script into every registered doc that reads that fragment, if present, and
rewrites /admin/open-doc links to the SAME origin instead of the hardcoded
default - production is untouched when no fragment is present (e.g. a
bookmarked S3 link opened on its own). Idempotent: skips a file that
already has the marker comment. Run as:
python -m scripts.patch_app_base_nav"""

import os

from scripts.sync_admin_docs import DOCS_TO_SYNC

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MARKER = "<!-- app-base-nav -->"

SCRIPT = f"""{MARKER}
<script>
(function () {{
  if (location.protocol === "file:") return;
  var hashMatch = location.hash.match(/app_base=([^&]+)/);
  if (!hashMatch) return;
  var appBase = decodeURIComponent(hashMatch[1]).replace(/\\/$/, "");
  document.querySelectorAll('a[href*="/admin/open-doc"]').forEach(function (a) {{
    try {{
      var url = new URL(a.href);
      a.href = appBase + url.pathname + url.search + "#app_base=" + encodeURIComponent(appBase);
    }} catch (e) {{}}
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

            content = content.rstrip() + "\n" + SCRIPT

            with open(abs_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(content)
            patched += 1
            print(f"patched: {feature_name}/{doc_type}")

    print(f"\n{patched} patched, {skipped} already had the app-base fallback")


if __name__ == "__main__":
    main()
