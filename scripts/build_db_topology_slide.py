"""Builds the Database & Schema Topology slide for docs/dev-reference/
database/db-model-overview.html - that doc had tables/cards but no real
box-and-arrow diagram (milestone 2, doc-gap pass, 2026-10-14). Grounded in
the doc's own verified content (snapshot 2026-09-22), not re-derived.
Appends to whatever the deck already has. Run as:
python scripts/build_db_topology_slide.py"""

import os

from pptx import Presentation
from pptx.dml.color import RGBColor

from deck_common import (
    EMPLOYEE_FILL, EMPLOYEE_LINE, AGENT_FILL, AGENT_LINE, TOOL_FILL, TOOL_LINE,
    WHITE, SLATE_DARK, SLATE_MED, STORE_FILL, STORE_LINE,
    new_slide, add_header, legend_chip, box, arrow, bullet_panel, even_columns, save_deck,
)

DST = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11.pptx"
DST_TMP = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11_wip.pptx"
SRC = DST if os.path.exists(DST) else DST_TMP

RESERVED_FILL, RESERVED_LINE = RGBColor(0xEC, 0xEC, 0xEC), RGBColor(0xB8, 0xB8, 0xB8)


def build(prs):
    slide = new_slide(prs)
    add_header(slide, "Database & Schema Topology", "hrb_chatbot_v2 \u2192 what it reads/writes directly vs. via MCP only")

    legend_chip(slide, 7500000, 660400, 1150000, STORE_FILL, STORE_LINE, "Direct SQL, live")
    legend_chip(slide, 8750000, 660400, 1150000, EMPLOYEE_FILL, EMPLOYEE_LINE, "MCP-only, external")
    legend_chip(slide, 10000000, 660400, 1150000, RESERVED_FILL, RESERVED_LINE, "Reserved, empty")

    app_w, app_h = 2700000, 420000
    app_x = (12192000 - app_w) // 2
    app_y = 1000000
    box(slide, app_x, app_y, app_w, app_h, AGENT_FILL, AGENT_LINE,
        "hrb_chatbot_v2 (this app)", "the only writer/reader in this diagram",
        title_size=9, body_size=6.8)
    app_cx = app_x + app_w // 2
    app_bottom = app_y + app_h

    row_y = 1750000
    row_h = 950000
    xs, box_w = even_columns(227000, 12192000 - 2 * 227000, 6)

    nodes = [
        ("hrb_chatbot_v2 DB", "SQLite or Postgres - own document/chunk metadata", STORE_FILL, STORE_LINE),
        ("hrb_chatbot_v2_core", "roles, employee_roles, oauth_clients - no cross-schema FK", STORE_FILL, STORE_LINE),
        ("hrb_chatbot_v2_sessions", "reserved, empty - future conversation memory", RESERVED_FILL, RESERVED_LINE),
        ("app_tracking (MCP registry)", "mcp_server_registry/tools/connections - reused, not owned", STORE_FILL, STORE_LINE),
        ("hrb_lms_mcp_auth", "credential registered only - never queried directly", EMPLOYEE_FILL, EMPLOYEE_LINE),
        ("hrb_emp_lms + public + ...", "employees, leave_*, chat_history - MCP calls only", EMPLOYEE_FILL, EMPLOYEE_LINE),
    ]

    for (title, body, fill, line), x in zip(nodes, xs):
        box(slide, x, row_y, box_w, row_h, fill, line, title, body, title_size=7.6, body_size=6.2)
        center_x = x + box_w // 2
        arrow(slide, app_cx, app_bottom, center_x, row_y)

    bullet_panel(
        slide, 227000, row_y + row_h + 180000, 11738000, 1050000,
        WHITE, RGBColor(0xD9, 0xDF, 0xE9),
        "Two physical databases, one shared with other apps",
        [
            "hrb_chatbot_v2's own metadata DB is small and isolated - this project's alone.",
            "Everything else above lives in the shared hr_chatbot Postgres database, on the same server, used by hrb_lms_mcp/hrb_emp_assist too.",
            "coco (a third shared DB on the same server) is real and populated but not touched by this project - omitted above, noted here only.",
            "No DB-enforced foreign key crosses a schema boundary anywhere - a deliberate choice, applied live, not a gap.",
        ],
        heading_color=SLATE_DARK, bullet_color=SLATE_MED,
    )


def main():
    prs = Presentation(SRC)
    build(prs)
    save_deck(prs, DST, DST_TMP)


if __name__ == "__main__":
    main()
