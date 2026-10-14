"""Builds slide 25: the real retrieval-strategies pipeline - grounded
directly in ai/rag_pipeline/query_retrieval/retriever.py's own
retrieve_chunks()/SEARCH_STRATEGIES. Same swim-lane template as slides
18-24. Run as: python scripts/build_retrieval_strategies_slide.py"""

import os

from pptx import Presentation
from pptx.dml.color import RGBColor

from deck_common import (
    AGENT_FILL, AGENT_LINE, TOOL_FILL, TOOL_LINE,
    SLATE_DARK, SLATE_MED, PANEL_BG, STORE_FILL, STORE_LINE,
    new_slide, add_header, add_section_label, legend_chip, swim_lane, bullet_panel,
    even_columns, save_deck,
)

DST = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11.pptx"
DST_TMP = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11_wip.pptx"
SRC = DST if os.path.exists(DST) else DST_TMP

PANEL_BORDER = RGBColor(0xC7, 0xD2, 0xDE)


def add_legend(slide):
    legend_chip(slide, 8550000, 660400, 900000, AGENT_FILL, AGENT_LINE, "Agent / LLM call")
    legend_chip(slide, 9500000, 660400, 700000, TOOL_FILL, TOOL_LINE, "Deterministic")
    legend_chip(slide, 10260000, 660400, 870000, STORE_FILL, STORE_LINE, "Store / service")


def main():
    prs = Presentation(SRC)
    slide = new_slide(prs)
    add_header(
        slide,
        "Retrieval Strategies: 4 Search Modes, 2 Optional Rewrites",
        "companion to the architecture page \u00b7 query_retrieval/retriever.py :: retrieve_chunks()",
    )
    add_section_label(slide, "Layered swim lane - process (top row) vs. the real stores & services each step touches (bottom row)")
    add_legend(slide)

    xs, bw = even_columns(254000, 11684000, 6)
    top = [
        (xs[0], bw, TOOL_FILL, TOOL_LINE, "resolve strategy", "search_strategy param, defaults to \u201csimilarity\u201d if not given", SLATE_DARK, SLATE_MED),
        (xs[1], bw, AGENT_FILL, AGENT_LINE, "Self-Query (optional)", "1 LLM call \u2013 parses doc_category/department/doc_description into a real filter", SLATE_DARK, SLATE_MED),
        (xs[2], bw, TOOL_FILL, TOOL_LINE, "4 search strategies", "similarity / mmr / keyword / hybrid \u2013 SEARCH_STRATEGIES dict dispatch", SLATE_DARK, SLATE_MED),
        (xs[3], bw, AGENT_FILL, AGENT_LINE, "MultiQuery (optional)", "LLM rewrites into several phrasings, searches each, merges/dedupes", SLATE_DARK, SLATE_MED),
        (xs[4], bw, TOOL_FILL, TOOL_LINE, "relevance-bar filter", "similarity only \u2013 Chroma distance \u2264 1.1 or Pinecone score \u2265 0.5", SLATE_DARK, SLATE_MED),
        (xs[5], bw, TOOL_FILL, TOOL_LINE, "attach filenames", "1 metadata lookup per distinct document_id, not per chunk", SLATE_DARK, SLATE_MED),
    ]
    bottom = [
        (xs[2], (xs[2] + bw) - xs[2], "Vector DB", "Chroma / Pinecone \u2013 is_current: $ne false always AND-ed in, never overridable by a parsed filter"),
        (xs[5], bw, "Postgres", "metadata_store.get_document()"),
    ]
    bottom_y = swim_lane(slide, "Query \u2192 ranked chunks (live)", 870000, top, bottom)

    bullet_panel(slide, 127000, bottom_y + 150000, 11938000, 980000, PANEL_BG, PANEL_BORDER, "Why 4 strategies, not 1", [
        "similarity (default): plain relevance-ranked, drops anything below the relevance bar",
        "mmr: trades relevance for diversity via lambda_mult (1.0 = pure relevance, 0.0 = pure diversity, LangChain's own 0.5 default)",
        "keyword / hybrid: BM25-based (bm25_search.py), for queries where exact terms matter more than semantic similarity",
        "Self-Query and MultiQuery are real LangChain classes layered on top of any of the 4 \u2013 not reimplemented, see CLAUDE.md's Phase 20 note",
    ])

    save_deck(prs, DST, DST_TMP)


if __name__ == "__main__":
    main()
