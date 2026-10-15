"""Builds the Course Topic Coverage slide for docs/dev-reference/IK-FDE/
course-topic-coverage-review.html - that doc had only a status-pill table,
no real diagram (milestone 2, doc-gap pass, 2026-10-14). Counts are read
straight from the HTML's own status pills, not re-derived or guessed.
Appends to whatever the deck already has. Run as:
python scripts/build_course_coverage_slide.py"""

import os
import re

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Emu

from deck_common import (
    WHITE, SLATE_DARK, SLATE_MED, STORE_FILL, STORE_LINE, PANEL_BORDER,
    new_slide, add_header, legend_chip, box, bullet_panel, even_columns, save_deck,
)

DST = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11.pptx"
DST_TMP = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11_wip.pptx"
SRC = DST if os.path.exists(DST) else DST_TMP

HTML_PATH = "docs/dev-reference/IK-FDE/course-topic-coverage-review.html"

PARTIAL_FILL, PARTIAL_LINE = RGBColor(0xFB, 0xF1, 0xDD), RGBColor(0xED, 0xD6, 0xA2)
GAP_FILL, GAP_LINE = RGBColor(0xEE, 0xF0, 0xF4), RGBColor(0xD5, 0xD9, 0xE3)
BUILT_SOLID = RGBColor(0x14, 0x6B, 0x3F)
PARTIAL_SOLID = RGBColor(0x9A, 0x5A, 0x0C)
GAP_SOLID = RGBColor(0x8A, 0x91, 0xA3)


def count_modules(html_path):
    html = open(html_path, encoding="utf-8").read()
    sections = re.split(r'(?=<section class="module">)', html)
    modules = []
    for section in sections[1:]:
        name = re.search(r'm-name display">([^<]+)', section).group(1)
        built = len(re.findall(r'status-pill built', section))
        partial = len(re.findall(r'status-pill partial', section))
        gap = len(re.findall(r'status-pill gap"', section))
        modules.append((name, built, partial, gap))
    return modules


def segmented_bar(slide, x, y, w, h, built, partial, gap):
    total = max(built + partial + gap, 1)
    cursor = x
    for count, fill in ((built, BUILT_SOLID), (partial, PARTIAL_SOLID), (gap, GAP_SOLID)):
        seg_w = int(w * count / total)
        if seg_w <= 0:
            continue
        shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(cursor), Emu(y), Emu(seg_w), Emu(h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
        shape.line.fill.background()
        shape.shadow.inherit = False
        cursor += seg_w


def build(prs, modules):
    grand_total = sum(built + partial + gap for _name, built, partial, gap in modules)
    slide = new_slide(prs)
    add_header(slide, "Course Topic Coverage Review",
                f"{grand_total} IK FDE techniques, Modules 1-6 \u2192 built vs. partially built vs. not built")

    legend_chip(slide, 7700000, 660400, 850000, STORE_FILL, STORE_LINE, "Built")
    legend_chip(slide, 8650000, 660400, 1000000, PARTIAL_FILL, PARTIAL_LINE, "Partial")
    legend_chip(slide, 9750000, 660400, 1000000, GAP_FILL, GAP_LINE, "Not built")

    xs, box_w = even_columns(227000, 12192000 - 2 * 227000, 6)
    box_y = 1050000
    box_h = 780000
    bar_y = box_y + box_h + 60000
    bar_h = 160000

    totals = [0, 0, 0]
    for (name, built, partial, gap), x in zip(modules, xs):
        total = built + partial + gap
        totals[0] += built
        totals[1] += partial
        totals[2] += gap
        box(slide, x, box_y, box_w, box_h, WHITE, PANEL_BORDER,
            name, f"{built} built \u00b7 {partial} partial \u00b7 {gap} gap  ({total})",
            title_size=8.2, body_size=6.6)
        segmented_bar(slide, x, bar_y, box_w, bar_h, built, partial, gap)

    grand_total = sum(totals)
    bullet_panel(
        slide, 227000, bar_y + bar_h + 220000, 11738000, 950000,
        WHITE, PANEL_BORDER,
        f"{totals[0]} built / {totals[1]} partial / {totals[2]} not built, of {grand_total} named techniques",
        [
            "Status only - this page makes no ranking or defer/drop call, counts are read straight from the page's own status pills.",
            "Weighted toward Embeddings and Chunking (15 topics each) - the two modules this project went deepest on first.",
            "Full per-topic detail, including why each gap is a gap, stays in the table below this diagram - not duplicated here.",
        ],
        heading_color=SLATE_DARK, bullet_color=SLATE_MED,
    )


def main():
    modules = count_modules(HTML_PATH)
    prs = Presentation(SRC)
    build(prs, modules)
    save_deck(prs, DST, DST_TMP)


if __name__ == "__main__":
    main()
