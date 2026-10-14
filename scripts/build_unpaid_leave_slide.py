"""Builds the Request Unpaid Leave deck slide (A2A/HITL swim-lane flow).
Appends to the deck, saves as v11. Run as:
python scripts/build_unpaid_leave_slide.py"""

from pptx import Presentation
from pptx.dml.color import RGBColor

from deck_common import (
    EMPLOYEE_FILL, EMPLOYEE_LINE, AGENT_FILL, AGENT_LINE, TOOL_FILL, TOOL_LINE,
    HR_FILL, HR_LINE, WHITE, SLATE_DARK, SLATE_MED, PINK_TEXT, PANEL_BG,
    NOTE_MAGENTA, STORE_FILL, STORE_LINE, new_slide, add_header, add_section_label,
    legend_chip, swim_lane, bullet_panel, save_deck,
)

SRC = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v10.pptx"
DST = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11.pptx"
DST_TMP = r"C:\Users\sreed\Downloads\HRB_V2_Architecture_Deck_v11_wip.pptx"

COMM_BORDER = RGBColor(0xC7, 0xD2, 0xDE)
CREAM_FILL = RGBColor(0xFF, 0xF7, 0xED)
CREAM_BORDER = RGBColor(0xF3, 0xD7, 0xB3)
RUST_TEXT = RGBColor(0x92, 0x56, 0x1A)


def main():
    prs = Presentation(SRC)
    slide = new_slide(prs)
    add_header(slide, "Request Unpaid Leave: A2A / HITL Workflow", "companion to the architecture page \u00b7 LangGraph interrupt \u2192 resume, Postgres-checkpointed")
    add_section_label(slide, "Layered swim lanes - process (top row) vs. the real stores & services each step touches (bottom row)")

    legend_chip(slide, 7800000, 660400, 700000, EMPLOYEE_FILL, EMPLOYEE_LINE, "Employee")
    legend_chip(slide, 8550000, 660400, 900000, AGENT_FILL, AGENT_LINE, "Agent / LangGraph")
    legend_chip(slide, 9500000, 660400, 700000, TOOL_FILL, TOOL_LINE, "Tool / MCP")
    legend_chip(slide, 10260000, 660400, 870000, HR_FILL, HR_LINE, "HR specialist")
    legend_chip(slide, 11180000, 660400, 850000, STORE_FILL, STORE_LINE, "Store / service")

    # Band 1 - Submission: synchronous, runs to the pause point
    b1_x = [254000, 2604800, 4955600, 7306400, 9657200]
    b1_w = 2280800
    top1 = [
        (b1_x[0], b1_w, EMPLOYEE_FILL, EMPLOYEE_LINE, "Employee submits", "Request Leave form: dates, type, document", SLATE_DARK, SLATE_MED),
        (b1_x[1], b1_w, AGENT_FILL, AGENT_LINE, "intake \u2192 eligibility_check", "validates shape, same-type 12mo repeat check", SLATE_DARK, SLATE_MED),
        (b1_x[2], b1_w, TOOL_FILL, TOOL_LINE, "submit (MCP, OAuth2)", "create_leave_request + create_hitl_request", SLATE_DARK, SLATE_MED),
        (b1_x[3], b1_w, AGENT_FILL, AGENT_LINE, "generate_review_brief", "1 real LLM call \u2013 summarizes, decides nothing", SLATE_DARK, SLATE_MED),
        (b1_x[4], b1_w, WHITE, HR_LINE, "interrupt() \u2013 PAUSED", "state checkpointed to Postgres, hrs\u2013days", NOTE_MAGENTA, NOTE_MAGENTA),
    ]
    bottom1 = [
        (b1_x[1], (b1_x[2] + b1_w) - b1_x[1], "hrb_lms_mcp", "get_leave_history_parsed \u2192 create_leave_request + create_hitl_request (OAuth2 A2A)"),
        (b1_x[3], (b1_x[4] + b1_w) - b1_x[3], "Postgres", "AsyncPostgresSaver \u2013 state checkpointed continuously as the graph runs"),
    ]
    swim_lane(slide, "1 \u00b7 Submission \u2013 synchronous, runs to the pause point (live, Phase 162/165)", 870000, top1, bottom1)

    # Band 2 - Resolution: HR specialist decides, hours/days later, graph resumes
    b2_w = 2868500
    b2_x = [254000, 3192500, 6131000, 9069500]
    top2 = [
        (b2_x[0], b2_w, HR_FILL, HR_LINE, "HR specialist reviews & decides", "Leave Approvals queue \u2013 brief + document", WHITE, PINK_TEXT),
        (b2_x[1], b2_w, AGENT_FILL, AGENT_LINE, "POST /resolve \u2192 resume", "Command(resume=decision_payload) \u2013 same checkpointed run", SLATE_DARK, SLATE_MED),
        (b2_x[2], b2_w, AGENT_FILL, AGENT_LINE, "finalize", "writes decision + sends email + records artifact", SLATE_DARK, SLATE_MED),
        (b2_x[3], b2_w, EMPLOYEE_FILL, EMPLOYEE_LINE, "Employee notified", "decision email + My Requests view", SLATE_DARK, SLATE_MED),
    ]
    bottom2 = [
        (b2_x[0], b2_w, "HR console", "Leave Approvals queue \u2013 pending HITL requests"),
        (b2_x[1], b2_w, "Postgres", "checkpoint resumed \u2013 AsyncPostgresSaver loads the exact paused state"),
        (b2_x[2], b2_w, "hrb_lms_mcp", "resolve_hitl_request + record_produced_artifact (OAuth2 A2A)"),
        (b2_x[3], b2_w, "SES", "decision email sent to the employee"),
    ]
    swim_lane(slide, "2 \u00b7 Resolution \u2013 HR specialist decides, hours/days later; graph resumes from the exact checkpoint", 2650000, top2, bottom2)

    add_section_label(slide, "3 \u00b7 Communication & state management \u2013 the A2A/HITL mechanics", y=4550800, width=8000000)

    bullet_panel(
        slide, 254000, 4830200, 5842000, 1524000, PANEL_BG, COMM_BORDER,
        "A2A: OAuth2 client-credentials, not a shared DB",
        [
            "Bearer token from hrb_lms_mcp's /oauth/token, cached in module state",
            "Refreshed 30s before expiry \u2013 not re-fetched on every call",
            "5 real MCP calls: submit, set_review_brief, resolve_hitl_request,",
            "record_produced_artifact, get_leave_history_parsed",
        ],
    )

    bullet_panel(
        slide, 6286500, 4830200, 5842000, 1524000, CREAM_FILL, CREAM_BORDER,
        "State: AsyncPostgresSaver checkpoints the whole graph",
        [
            "UnpaidLeaveState: employee_id, dates, purpose, leave_type_code,",
            "document_reference, is_repeat_within_12_months, intake_notes,",
            "submit_result, review_brief, decision, finalize_result",
            "Survives a redeploy \u2013 resume reads the checkpoint, never replays nodes",
        ],
        bullet_color=RUST_TEXT,
    )

    save_deck(prs, DST, DST_TMP)


if __name__ == "__main__":
    main()
