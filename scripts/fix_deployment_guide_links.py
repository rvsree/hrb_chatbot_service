"""The deployment-guide series (docs/dev-reference/deployment-guide/) used
plain relative links (href="02-neon-postgres.html") between sibling pages -
fine for local file:// review, but a confirmed-live 403 once served via S3
presigned URLs (the bucket is private; an unsigned sibling GET fails - see
CLAUDE.md's "Docs stay in sync" norm, verified directly before writing this
script, not assumed). Rewrites every such href to the same absolute
/admin/open-doc pattern every other doc in this project already uses, so
the existing local-nav-fallback and app-base-nav scripts apply to this
series too once it's registered in DOCS_TO_SYNC. Idempotent: a href already
rewritten won't match the plain-filename pattern again. Run as:
python -m scripts.fix_deployment_guide_links"""

import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GUIDE_DIR = os.path.join(REPO_ROOT, "docs", "dev-reference", "deployment-guide")

FILENAME_TO_DOC_TYPE = {
    "index.html": "index",
    "01-deployment-aws.html": "deployment-aws",
    "02-neon-postgres.html": "neon-postgres",
    "03-pinecone-standard.html": "pinecone-standard",
    "04-redis-cache.html": "redis-cache",
    "05-rag-ingestion-batch.html": "rag-ingestion-batch",
    "06-nfr-reliability-resilience.html": "nfr-reliability-resilience",
    "07-reactjs-ui.html": "reactjs-ui",
    "08-milestone-plan.html": "milestone-plan",
    "09-custom-domain-setup.html": "custom-domain-setup",
    "10-observability-howto.html": "observability-howto",
}


def replacement_href(doc_type: str) -> str:
    url = f"https://hrb-chatbot-ui.rvsree.dev/admin/open-doc?feature=deployment-guide&type={doc_type}"
    return f'href="{url}" target="_blank" rel="noopener noreferrer"'


def fix_one_file(filename: str) -> int:
    path = os.path.join(GUIDE_DIR, filename)
    with open(path, encoding="utf-8") as file_handle:
        content = file_handle.read()

    replacements = 0
    for sibling_filename, doc_type in FILENAME_TO_DOC_TYPE.items():
        pattern = f'href="{sibling_filename}"'
        count = content.count(pattern)
        if count:
            content = content.replace(pattern, replacement_href(doc_type))
            replacements += count

    if replacements:
        with open(path, "w", encoding="utf-8") as file_handle:
            file_handle.write(content)
    return replacements


def main() -> None:
    total = 0
    for filename in FILENAME_TO_DOC_TYPE:
        count = fix_one_file(filename)
        total += count
        print(f"{filename}: {count} link(s) rewritten")
    print(f"\n{total} total links rewritten")


if __name__ == "__main__":
    main()
