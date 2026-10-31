"""Inlines each exported deck-slide PNG (scripts/export_deck_slides.py's
output) as a base64 data URI directly in its HTML doc - a relative <img
src> would 404 once synced to S3, since the admin-docs bucket is private
and only reachable via a presigned URL for one object at a time. Matches
the pattern rag-ingestion/architecture.html's own target-state diagram
already uses. Run AFTER export_deck_slides.py, before sync_admin_docs.py.
Run as: python scripts/embed_deck_slides.py"""

import base64
import os

# html path -> the PNG file it currently references by a plain relative
# <img src="...">, as scripts/export_deck_slides.py wrote it.
EMBEDS = {
    "docs/dev-reference/request-unpaid-leave/architecture.html": "architecture-slide.png",
    "docs/dev-reference/genai-chat-workflow/architecture.html": "architecture-slide.png",
    "docs/dev-reference/rag-ingestion/architecture.html": "architecture-slide.png",
    "docs/dev-reference/rag-architecture-layers.html": "rag-architecture-layers-slide.png",
    "docs/dev-reference/rag-retrieval/rag-pipeline-current-state.html": "rag-pipeline-current-state-slide.png",
    "docs/dev-reference/react_agents/multi-agent-graph.html": "multi-agent-graph-slide.png",
    "docs/dev-reference/deployment-guide/01-deployment-aws.html": "deployment-aws-slide.png",
    "docs/dev-reference/rag-validation-gates.html": "rag-validation-gates-slide.png",
    "docs/dev-reference/database/db-model-overview.html": "db-model-overview-slide.png",
    "docs/dev-reference/course-material/course-topic-coverage-review.html": "course-topic-coverage-review-slide.png",
    "docs/dev-reference/genai-rag-chat/architecture.html": "architecture-slide.png",
    # 2 images in one doc (high-level + low-level deployment diagrams) -
    # a list value, unlike every single-image entry above.
    "docs/dev-reference/developer-onboarding/guide.html": [
        "deployment-view-slide.png", "deploy-pipelines-slide.png",
    ],
}


def embed_one(html_path, png_filename):
    png_path = os.path.join(os.path.dirname(html_path), png_filename)
    if not os.path.exists(png_path):
        # Already embedded earlier - export_deck_slides.py's sibling PNG
        # gets deleted right after a successful embed, so a missing file
        # here just means there's nothing new to do for this entry.
        print(f"SKIPPED (no sibling PNG, already embedded): {html_path}")
        return
    with open(png_path, "rb") as png_file:
        encoded = base64.b64encode(png_file.read()).decode("ascii")

    with open(html_path, encoding="utf-8") as html_file:
        html = html_file.read()

    old_src = f'src="{png_filename}"'
    new_src = f'src="data:image/png;base64,{encoded}"'
    if old_src not in html:
        print(f"SKIPPED (already embedded or src not found): {html_path}")
        return
    html = html.replace(old_src, new_src, 1)

    with open(html_path, "w", encoding="utf-8") as html_file:
        html_file.write(html)
    print(f"Embedded {png_filename} into {html_path}")

    os.remove(png_path)


def main():
    for html_path, png_filename in EMBEDS.items():
        # a list means several images in one doc - embed each one in turn.
        if isinstance(png_filename, list):
            for one_filename in png_filename:
                embed_one(html_path, one_filename)
        else:
            embed_one(html_path, png_filename)


if __name__ == "__main__":
    main()
