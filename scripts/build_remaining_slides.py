"""Builds the 5 remaining swim-lane deck slides (GenAI Chat Workflow, RAG
Ingestion real-current-state, and the 3 retrieval modes), grounded directly
in the real pipeline code (ai/doc_processing/pipeline.py,
ai/rag_pipeline/pipeline.py, orchestration_agent.py, multi_agent_pipeline.py,
adhoc_document_agent.py) - same swim-lane template as slide 18. Reads
whatever deck already has slide 18 (SRC below), appends these 5 on top.
Run as: python scripts/build_remaining_slides.py"""

import os

from pptx import Presentation

from deck_common import (
    EMPLOYEE_FILL, EMPLOYEE_LINE, AGENT_FILL, AGENT_LINE, TOOL_FILL, TOOL_LINE,
    HR_FILL, HR_LINE, WHITE, PINK_TEXT, SLATE_DARK, SLATE_MED, PANEL_BG, STORE_FILL, STORE_LINE,
    new_slide, add_header, add_section_label, legend_chip, swim_lane, bullet_panel,
    even_columns, save_deck,
)
from pptx.dml.color import RGBColor

DST = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11.pptx"
DST_TMP = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11_wip.pptx"
# Always read the freshest output of build_unpaid_leave_slide.py (that
# script always prefers writing DST, only falling back to DST_TMP when DST
# is locked) - reading a hardcoded DST_TMP here raced against a stale wip
# file from an earlier run and silently duplicated every slide (28 slides
# instead of 23, confirmed live).
SRC = DST if os.path.exists(DST) else DST_TMP

PANEL_BORDER = RGBColor(0xC7, 0xD2, 0xDE)


def add_legend(slide):
    legend_chip(slide, 7800000, 660400, 700000, EMPLOYEE_FILL, EMPLOYEE_LINE, "Employee / HR")
    legend_chip(slide, 8550000, 660400, 900000, AGENT_FILL, AGENT_LINE, "Agent / LangGraph")
    legend_chip(slide, 9500000, 660400, 700000, TOOL_FILL, TOOL_LINE, "Tool / MCP")
    legend_chip(slide, 10260000, 660400, 870000, HR_FILL, HR_LINE, "HR specialist")
    legend_chip(slide, 11180000, 660400, 850000, STORE_FILL, STORE_LINE, "Store / service")


def add_differentiator(slide, y, heading, bullets):
    bullet_panel(slide, 127000, y, 11938000, 980000, PANEL_BG, PANEL_BORDER, heading, bullets)


def build_genai_chat_workflow(prs):
    slide = new_slide(prs)
    add_header(slide, "GenAI Chat Workflow: Ad-hoc Document Q&A", "companion to the architecture page \u00b7 in-process ReAct loop, no shared KB")
    add_section_label(slide, "Layered swim lane - process (top row) vs. the real stores & services each step touches (bottom row)")
    add_legend(slide)

    xs, bw = even_columns(254000, 11684000, 5)
    top = [
        (xs[0], bw, EMPLOYEE_FILL, EMPLOYEE_LINE, "Employee attaches & asks", "chat composer \u2013 up to 3 files (PDF/DOCX/CSV) + question", SLATE_DARK, SLATE_MED),
        (xs[1], bw, AGENT_FILL, AGENT_LINE, "validate + extract text", "in-request only \u2013 nothing written to S3 or disk", SLATE_DARK, SLATE_MED),
        (xs[2], bw, AGENT_FILL, AGENT_LINE, "guardrail each file + question", "check_input() independently per file, same as typed text", SLATE_DARK, SLATE_MED),
        (xs[3], bw, AGENT_FILL, AGENT_LINE, "ReAct loop", "ReadDocument / SearchWeb / SendEmailWithAnswer", SLATE_DARK, SLATE_MED),
        (xs[4], bw, AGENT_FILL, AGENT_LINE, "output guardrail + persist", "check_output() then saves the turn (best-effort)", SLATE_DARK, SLATE_MED),
    ]
    bottom = [
        (xs[3], bw, "Tavily / SES", "SearchWeb (reuses multi-agentic-rag's Tavily) + SendEmailWithAnswer (boto3 SES)"),
        (xs[4], bw, "Postgres", "chat_session_records, chat_turn_records, email_send_events \u2013 no FKs between them"),
    ]
    bottom_y = swim_lane(slide, "Request flow (live, Phase 136\u2013165)", 870000, top, bottom)

    add_differentiator(slide, bottom_y + 150000, "Why this is NOT genai-rag", [
        "No shared KB \u2013 answers only from files attached THIS turn, never indexed",
        "No agent framework \u2013 a plain bounded loop, not LangGraph",
        "The only one of the 4 retrieval modes with a real email tool",
    ])


def build_rag_ingestion(prs):
    slide = new_slide(prs)
    add_header(slide, "RAG Ingestion: Real Current-State Pipeline", "companion to the architecture page \u00b7 synchronous, in-request \u2013 not slide 12's target state")
    add_section_label(slide, "Layered swim lane - process (top row) vs. the real stores & services each step touches (bottom row)")
    add_legend(slide)

    xs, bw = even_columns(254000, 11684000, 5)
    top = [
        (xs[0], bw, HR_FILL, HR_LINE, "HR uploads document", "multipart POST, HR_SUPPORT role only", WHITE, PINK_TEXT),
        (xs[1], bw, TOOL_FILL, TOOL_LINE, "content-hash dedup check", "find_by_content_hash() \u2013 same bytes = same document, any filename", SLATE_DARK, SLATE_MED),
        (xs[2], bw, AGENT_FILL, AGENT_LINE, "extract + chunk", "extract_text_from_pdf \u2192 chunk_text_with_sections (6 strategies)", SLATE_DARK, SLATE_MED),
        (xs[3], bw, AGENT_FILL, AGENT_LINE, "embed", "generate_embeddings() \u2013 OpenAI embedding model", SLATE_DARK, SLATE_MED),
        (xs[4], bw, TOOL_FILL, TOOL_LINE, "write_chunks + metadata", "LangChain index() + SQLRecordManager \u2013 skip-if-unchanged", SLATE_DARK, SLATE_MED),
    ]
    bottom = [
        (xs[1], bw, "Postgres + local disk", "doc_metadata row (status: parsing\u2192chunking\u2192embedding\u2192indexing) + UPLOAD_DIRECTORY/document_id/"),
        (xs[4], bw, "Vector DB", "Chroma / Pinecone \u2013 supersedes/is_current handling is this project's own logic, not LangChain's"),
    ]
    bottom_y = swim_lane(slide, "Upload \u2192 index, one call, in-process (live)", 870000, top, bottom)

    add_differentiator(slide, bottom_y + 150000, "Real system vs. the deck's own target-state slide 12", [
        "Synchronous, in-request \u2013 no S3 event, no SQS, no Lambda worker (that's slide 12's design, not what's built)",
        "One call does extract \u2192 chunk \u2192 embed \u2192 index end to end, inside the upload request itself",
        "Content-hash dedup + supersedes/is_current stay this project's own logic \u2013 LangChain's index() has no concept of one document replacing another",
    ])


def build_genai_rag(prs):
    slide = new_slide(prs)
    add_header(slide, "GenAI RAG: Retrieve-Then-Generate", "companion to the architecture page \u00b7 the fixed baseline pipeline, no agent loop")
    add_section_label(slide, "Layered swim lane - process (top row) vs. the real stores & services each step touches (bottom row)")
    add_legend(slide)

    xs, bw = even_columns(254000, 11684000, 5)
    top = [
        (xs[0], bw, AGENT_FILL, AGENT_LINE, "normalize + guardrail", "normalize_query() \u2192 check_input()", SLATE_DARK, SLATE_MED),
        (xs[1], bw, TOOL_FILL, TOOL_LINE, "answer cache check", "exact match on (query, params) \u2013 Phase 78", SLATE_DARK, SLATE_MED),
        (xs[2], bw, AGENT_FILL, AGENT_LINE, "decompose", "splits a compound question into sub-questions (1 LLM call)", SLATE_DARK, SLATE_MED),
        (xs[3], bw, TOOL_FILL, TOOL_LINE, "MCP route or retrieve+generate", "try_route_to_mcp() first, else retrieve_chunks() + generate_answer() per sub-question", SLATE_DARK, SLATE_MED),
        (xs[4], bw, AGENT_FILL, AGENT_LINE, "merge + guardrail + eval + cache", "reviewer_agent.review() if >1 sub-answer; groundedness/completeness scored live", SLATE_DARK, SLATE_MED),
    ]
    bottom = [
        (xs[1], bw, "Postgres", "answer_cache \u2013 skipped whenever any sub-answer used live MCP data"),
        (xs[3], bw, "Vector DB / hrb_lms_mcp", "retrieve_chunks() for KB questions, GetLeaveBalance/GetLeaveHistory via MCP for live data"),
        (xs[4], bw, "Postgres", "conversation_turns \u2013 only when enable_conversation_memory is set"),
    ]
    bottom_y = swim_lane(slide, "Query \u2192 grounded answer (live)", 870000, top, bottom)

    add_differentiator(slide, bottom_y + 150000, "Why this is the baseline, not an agent", [
        "Fixed retrieve-then-generate \u2013 no tool-calling loop, no LangGraph",
        "Decomposition handles compound questions without needing agentic reasoning",
        "The only mode with BOTH an answer cache and live eval-judge scoring on every call",
    ])


def build_single_agentic_rag(prs):
    slide = new_slide(prs)
    add_header(slide, "Single-Agentic RAG: ReAct Tool-Calling Loop", "companion to the architecture page \u00b7 one agent, 3 tools")
    add_section_label(slide, "Layered swim lane - process (top row) vs. the real stores & services each step touches (bottom row)")
    add_legend(slide)

    xs, bw = even_columns(254000, 11684000, 5)
    top = [
        (xs[0], bw, AGENT_FILL, AGENT_LINE, "normalize query", "normalize_query()", SLATE_DARK, SLATE_MED),
        (xs[1], bw, TOOL_FILL, TOOL_LINE, "answer cache check", "exact match, keyed by (query, max_iterations)", SLATE_DARK, SLATE_MED),
        (xs[2], bw, AGENT_FILL, AGENT_LINE, "ReAct loop", "SystemMessage + history + query \u2192 llm.ainvoke(), bound to 3 tools", SLATE_DARK, SLATE_MED),
        (xs[3], bw, TOOL_FILL, TOOL_LINE, "tool dispatch", "SearchKnowledgeBase / GetLeaveBalance / GetLeaveHistory", SLATE_DARK, SLATE_MED),
        (xs[4], bw, AGENT_FILL, AGENT_LINE, "guardrail + cache write + memory", "GetLeaveBalance/History turns excluded from the cache (Phase 110)", SLATE_DARK, SLATE_MED),
    ]
    bottom = [
        (xs[1], bw, "Postgres", "answer_cache"),
        (xs[3], bw, "Vector DB / hrb_lms_mcp", "SearchKnowledgeBase hits the vector store; GetLeaveBalance/History call MCP"),
        (xs[4], bw, "Postgres", "conversation_turns"),
    ]
    bottom_y = swim_lane(slide, "Query \u2192 grounded answer (live)", 870000, top, bottom)

    add_differentiator(slide, bottom_y + 150000, "Why this is an agent, not fixed retrieval", [
        "One ReAct loop decides for itself whether to search the KB or call a leave-data tool",
        "Bound to exactly 3 tools: SearchKnowledgeBase, GetLeaveBalance, GetLeaveHistory",
        "No decomposition step \u2013 the loop itself handles multi-part questions by calling tools repeatedly",
    ])


def build_multi_agentic_rag(prs):
    slide = new_slide(prs)
    add_header(slide, "Multi-Agentic RAG: Planner \u2192 Parallel Domain Agents \u2192 Reviewer", "companion to the architecture page \u00b7 real LangGraph Send() fan-out")
    add_section_label(slide, "Planner dispatches via Send() - boxes 2-6 run in TRUE parallel, not sequentially", width=9000000)
    add_legend(slide)

    xs, bw = even_columns(254000, 11684000, 7)
    top = [
        (xs[0], bw, AGENT_FILL, AGENT_LINE, "planner", "classifies the query \u2192 decides which domain agents to dispatch", SLATE_DARK, SLATE_MED),
        (xs[1], bw, TOOL_FILL, TOOL_LINE, "vector_kb_agent", "RAG retrieval over the KB", SLATE_DARK, SLATE_MED),
        (xs[2], bw, TOOL_FILL, TOOL_LINE, "lms_ops_agent", "leave ops via hrb_lms_mcp", SLATE_DARK, SLATE_MED),
        (xs[3], bw, TOOL_FILL, TOOL_LINE, "sql_db_agent", "SQL read via hrb_lms_mcp", SLATE_DARK, SLATE_MED),
        (xs[4], bw, TOOL_FILL, TOOL_LINE, "lms_analytics_agent", "analytics via hrb_lms_mcp", SLATE_DARK, SLATE_MED),
        (xs[5], bw, TOOL_FILL, TOOL_LINE, "web_search_agent", "Tavily web search", SLATE_DARK, SLATE_MED),
        (xs[6], bw, AGENT_FILL, AGENT_LINE, "reviewer", "merges every dispatched agent's result (1 LLM call)", SLATE_DARK, SLATE_MED),
    ]
    bottom = [
        (xs[1], bw, "Vector DB", "vector_kb_agent's own retrieval"),
        (xs[2], (xs[4] + bw) - xs[2], "hrb_lms_mcp", "lms_ops_agent + sql_db_agent + lms_analytics_agent, all via OAuth2 A2A"),
        (xs[5], bw, "Tavily", "web_search_agent"),
    ]
    bottom_y = swim_lane(slide, "Planner \u2192 Send() fan-out \u2192 Reviewer (live, Phase 64)", 870000, top, bottom)

    add_differentiator(slide, bottom_y + 150000, "Why this needs a real graph, not a loop", [
        "Planner dispatches to however many of the 5 domain agents the query actually needs \u2013 not all 5 every time",
        "LangGraph's Send() API runs dispatched agents in true parallel, not asyncio.gather() or a sequential loop",
        "Reviewer is a second, separate LLM call that merges results \u2013 not simple concatenation",
    ])


def main():
    prs = Presentation(SRC)
    build_genai_chat_workflow(prs)
    build_rag_ingestion(prs)
    build_genai_rag(prs)
    build_single_agentic_rag(prs)
    build_multi_agentic_rag(prs)
    save_deck(prs, DST, DST_TMP)


if __name__ == "__main__":
    main()
