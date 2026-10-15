"""Builds the real-current-state architecture slide for genai-rag-chat -
GR-1's deferred redraw (docs/dev-reference/genai-rag-chat/decisions.html).
Slide 8 in the deck depicts a target-state microservices/LangGraph/SQS
design that doesn't match the real code; this is a fresh slide grounded
directly in ai/rag_pipeline/pipeline.py and ai/rag_core/guarded_pipeline.py
(both read in full before writing this), same swim-lane visual language as
slide 20 (RAG Ingestion real-current-state). Appends to whatever the deck
already has. Run as: python scripts/build_genai_rag_chat_slide.py"""

import os

from pptx import Presentation

from deck_common import (
    AGENT_FILL, AGENT_LINE, STORE_FILL, STORE_LINE, PANEL_BORDER, WHITE,
    SLATE_DARK, SLATE_MED, new_slide, add_header, legend_chip, box, arrow,
    bullet_panel, even_columns, save_deck,
)

DST = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11.pptx"
DST_TMP = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11_wip.pptx"
SRC = DST if os.path.exists(DST) else DST_TMP


def build(prs):
    slide = new_slide(prs)
    add_header(
        slide, "GenAI RAG Chat: Real Current-State Pipeline",
        "companion to slide 8's target-state design \u2013 synchronous, in-request, single process",
    )

    legend_chip(slide, 8700000, 660400, 1500000, AGENT_FILL, AGENT_LINE, "Pipeline step")
    legend_chip(slide, 10300000, 660400, 1300000, STORE_FILL, STORE_LINE, "Store / external")

    top_y = 1050000
    top_h = 780000
    xs, box_w = even_columns(227000, 12192000 - 2 * 227000, 6)

    steps = [
        ("1. Normalize + Input Guardrail", "normalize_query(), check_input() - NeMo Guardrails, a real LLM call, every turn"),
        ("2. Answer Cache Check", "exact-match on (query, params) - a hit saves the turn and returns, zero further calls"),
        ("3. Load History + Decompose", "on a miss only: load_history() if memory on, decompose() splits into sub-questions"),
        ("4. Per Sub-Q: MCP or Retrieve", "try_route_to_mcp() first (e.g. leave balance); else vector search (+ Multi/Self-Query)"),
        ("5. Generate + Merge + Guardrail", "LLM answers each sub-Q; reviewer_agent merges if >1; check_output() always runs"),
        ("6. Eval + Cache Write + Save", "DeepEval judge scores groundedness/completeness; cache write skipped if live MCP data used"),
    ]
    tops = []
    for (title, body), x in zip(steps, xs):
        box(slide, x, top_y, box_w, top_h, AGENT_FILL, AGENT_LINE, title, body, title_size=7.6, body_size=6.0)
        tops.append(x + box_w // 2)

    store_y = top_y + top_h + 650000
    store_h = 460000
    store_xs, store_w = even_columns(227000, 12192000 - 2 * 227000, 4)
    stores = [
        ("Redis", "answer cache"),
        ("Postgres", "conversation memory"),
        ("Vector Store", "ChromaDB / Pinecone"),
        ("LLM + MCP", "provider + hrb_lms_mcp"),
    ]
    store_centers = []
    for (title, body), x in zip(stores, store_xs):
        box(slide, x, store_y, store_w, store_h, STORE_FILL, STORE_LINE, title, body, title_size=8, body_size=6.5)
        store_centers.append(x + store_w // 2)

    redis_c, pg_c, vec_c, llm_c = store_centers
    store_top = store_y
    # one primary arrow per step, two where a step genuinely touches two stores
    arrow(slide, tops[0], top_y + top_h, llm_c, store_top)           # guardrail -> LLM
    arrow(slide, tops[1], top_y + top_h, redis_c, store_top)         # cache check -> Redis
    arrow(slide, tops[2], top_y + top_h, pg_c, store_top)            # load history -> Postgres
    arrow(slide, tops[3], top_y + top_h, vec_c, store_top)           # retrieve -> Vector Store
    arrow(slide, tops[3], top_y + top_h, llm_c, store_top)           # MCP route -> LLM+MCP
    arrow(slide, tops[4], top_y + top_h, llm_c, store_top)           # generate/merge -> LLM
    arrow(slide, tops[5], top_y + top_h, redis_c, store_top)         # cache write -> Redis
    arrow(slide, tops[5], top_y + top_h, pg_c, store_top)            # save turn -> Postgres

    bullet_panel(
        slide, 227000, store_y + store_h + 220000, 11738000, 950000,
        WHITE, PANEL_BORDER,
        "Real system vs. the deck's own target-state slide 8",
        [
            "No LangGraph here - genai-rag is a fixed retrieve-then-generate pipeline (single-agentic-rag/multi-agentic-rag are the LangGraph modes).",
            "No separate Chat Gateway / Conversation / Knowledge Retrieval / Agent Orchestrator services - one process, one call stack.",
            "No SQS - the answer-cache write and conversation-turn save both happen synchronously, in-request, same as every other write in this pipeline.",
        ],
        heading_color=SLATE_DARK, bullet_color=SLATE_MED,
    )


def main():
    prs = Presentation(SRC)
    build(prs)
    save_deck(prs, DST, DST_TMP)


if __name__ == "__main__":
    main()
