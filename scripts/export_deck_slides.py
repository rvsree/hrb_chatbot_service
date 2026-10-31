"""Exports specific deck slides as PNGs into each feature's own docs
folder, so the HTML architecture doc always shows the same diagram as the
real deck slide - this script IS the sync mechanism. Re-run after any
deck edit that changes a slide listed below. Run as:
python scripts/export_deck_slides.py"""

import shutil
import subprocess
from pathlib import Path

from pptx import Presentation

DECK_PATH = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11.pptx"
LIBREOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"

# docs/ path (relative to repo root) -> 1-indexed slide number in DECK_PATH.
SLIDE_EXPORTS = {
    "docs/dev-reference/hrb_chatbot_v3/agents-and-workflows/request-unpaid-leave/architecture-slide.png": 18,
    "docs/dev-reference/hrb_chatbot_v3/agents-and-workflows/genai-chat-workflow/architecture-slide.png": 19,
    "docs/dev-reference/hrb_chatbot_v3/rag-pipeline/ingestion/rag-ingestion/architecture-slide.png": 20,
    "docs/dev-reference/_archive/rag-architecture-layers-slide.png": 21,
    "docs/dev-reference/_archive/rag-retrieval/rag-pipeline-current-state-slide.png": 22,
    "docs/dev-reference/hrb_chatbot_v3/rag-pipeline/retrieval/multi-agent-graph-slide.png": 23,
    "docs/dev-reference/hrb_chatbot_v3/deployment-and-ops/deployment-guide/deployment-aws-slide.png": 24,
    "docs/dev-reference/_archive/rag-validation-gates-slide.png": 25,
    "docs/dev-reference/hrb_chatbot_v3/architecture/database/db-model-overview-slide.png": 26,
    "docs/dev-reference/course-material/course-topic-coverage-review-slide.png": 27,
    "docs/dev-reference/hrb_chatbot_v3/rag-pipeline/retrieval/genai-rag-chat/architecture-slide.png": 28,
    "docs/dev-reference/hrb_chatbot_v3/deployment-and-ops/developer-onboarding/deployment-view-slide.png": 29,
    "docs/dev-reference/hrb_chatbot_v3/deployment-and-ops/developer-onboarding/deploy-pipelines-slide.png": 30,
}


def export_slide(deck_path, slide_number, output_path):
    tmp_pptx = Path("_export_slide_tmp.pptx")
    prs = Presentation(deck_path)
    xml_slides = prs.slides._sldIdLst
    slides = list(xml_slides)
    target_index = slide_number - 1
    for i, slide_entry in enumerate(slides):
        if i != target_index:
            xml_slides.remove(slide_entry)
    prs.save(tmp_pptx)

    subprocess.run(
        [LIBREOFFICE, "--headless", "--convert-to", "png", "--outdir", str(tmp_pptx.parent), str(tmp_pptx)],
        check=True,
    )
    png_tmp = tmp_pptx.with_suffix(".png")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(png_tmp), output)
    tmp_pptx.unlink()
    print(f"Exported slide {slide_number} -> {output_path}")


def main():
    for output_path, slide_number in SLIDE_EXPORTS.items():
        export_slide(DECK_PATH, slide_number, output_path)


if __name__ == "__main__":
    main()
