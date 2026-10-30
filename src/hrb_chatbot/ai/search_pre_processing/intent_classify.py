"""Intent classification (Phase 277) - a cheap, deterministic, zero-cost
keyword classifier (no LLM call - unlike mode_router.py's own real-LLM
"single vs multi" complexity classifier, this is a topic/domain bucket,
a different axis entirely) run on every live query, purely for
observability: a LangSmith trace tag (filterable in the Tracing view) and
the live_queries table's own category column (always NULL before this -
the column existed, nothing ever wrote to it). Never changes routing or
retrieval behavior - see maybe_capture_live_query()'s own call site."""

LEAVE_BALANCE_KEYWORDS = ("leave balance", "pto balance", "how many days off", "sick balance")
LEAVE_HISTORY_KEYWORDS = ("leave history", "past leave", "leave requests")
LEAVE_REQUEST_KEYWORDS = ("request leave", "apply for leave", "take time off", "unpaid leave", "caregiver leave")

INTENT_LEAVE_BALANCE = "leave_balance"
INTENT_LEAVE_HISTORY = "leave_history"
INTENT_LEAVE_REQUEST = "leave_request"
INTENT_BENEFITS_FAQ = "benefits_faq"


def classify_query_intent(query: str) -> str:
    """Same keyword-matching style as mcp_tools.py's own is_leave_balance_query()/
    is_leave_history_query() - reused here rather than imported, since those
    2 are specifically about MCP tool routing eligibility (a different,
    narrower purpose this classifier doesn't want to couple itself to).
    Falls back to "benefits_faq", the actual majority case for this HR
    chatbot - never "general"/"unknown", which would be true for almost
    nothing this bot is actually asked."""
    lowered = query.lower()
    if any(keyword in lowered for keyword in LEAVE_BALANCE_KEYWORDS):
        return INTENT_LEAVE_BALANCE
    if any(keyword in lowered for keyword in LEAVE_HISTORY_KEYWORDS):
        return INTENT_LEAVE_HISTORY
    if any(keyword in lowered for keyword in LEAVE_REQUEST_KEYWORDS):
        return INTENT_LEAVE_REQUEST
    return INTENT_BENEFITS_FAQ
