"""Manual keyword routing to hrb_lms_mcp's MCP server - a prototype before real ReAct tool selection."""

import json
import time

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.hrb_chatbot.common.clients.auth_client.oauth_client import get_access_token
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_pipeline.tools.mcp_tools")

LEAVE_BALANCE_KEYWORDS = ("leave balance", "pto balance", "how many days off", "sick balance")
LEAVE_HISTORY_KEYWORDS = ("leave history", "past leave", "leave requests")


def is_leave_balance_query(query: str) -> bool:
    lowered = query.lower()
    return any(keyword in lowered for keyword in LEAVE_BALANCE_KEYWORDS)


def is_leave_history_query(query: str) -> bool:
    lowered = query.lower()
    return any(keyword in lowered for keyword in LEAVE_HISTORY_KEYWORDS)


async def _call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """Opens one MCP session, calls one tool, closes it - raises on any failure."""
    mcp_url = read_setting(None, "HRB_LMS_MCP_URL", "http://127.0.0.1:8190/mcp")
    # Phase 53: real OAuth2 Bearer token, not the dead X-API-Key header -
    # hrb_lms_mcp's server actually enforces this one.
    access_token = await get_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    async with streamablehttp_client(mcp_url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.isError:
                raise RuntimeError(f"MCP tool {tool_name!r} returned an error: {result.content}")
            return {"tool": tool_name, "content": [block.text for block in result.content if block.type == "text"]}


async def get_leave_balance(employee_id: str) -> dict:
    return await _call_mcp_tool("get_leave_balance", {"employee_id": employee_id})


async def get_leave_history(employee_id: str) -> dict:
    return await _call_mcp_tool("get_leave_history", {"employee_id": employee_id})


async def get_leave_history_parsed(employee_id: str, limit: int = 50) -> dict:
    """Phase 162 - same call as get_leave_history(), but parsed into a real
    dict (requests/total/...), not display text. Confirmed live that FastMCP
    returns exactly one pretty-printed JSON text block per call - every new
    Phase 162 wrapper that needs structured data parses it the same way."""
    result = await _call_mcp_tool("get_leave_history", {"employee_id": employee_id, "limit": limit})
    return json.loads(result["content"][0])


async def submit_unpaid_leave_request(
    employee_id: str,
    start_date: str,
    end_date: str,
    purpose: str,
    is_repeat_within_12_months: bool,
    leave_type_code: str = "UNPAID",
    document_reference: str | None = None,
) -> dict:
    """Phase 162 - always routes to HR specialist review via a HITL request;
    these leave types have no balance, so submit_leave_request()'s balance-
    exception path doesn't apply. Phase 165 added leave_type_code - this
    wrapper's own name predates that, kept for backward compatibility
    (same MCP tool name hrb_lms_mcp already exposes)."""
    result = await _call_mcp_tool(
        "submit_unpaid_leave_request",
        {
            "employee_id": employee_id,
            "start_date": start_date,
            "end_date": end_date,
            "purpose": purpose,
            "is_repeat_within_12_months": is_repeat_within_12_months,
            "leave_type_code": leave_type_code,
            "document_reference": document_reference,
        },
    )
    return json.loads(result["content"][0])


async def resolve_hitl_request(
    hitl_request_context_id: int,
    decision: str,
    response_text: str,
    resolved_by: str | None = None,
    resolved_by_employee_id: str | None = None,
) -> dict:
    """Phase 162 - the specialist's own decision. Never an LLM call - a
    human makes this call, the agent only carries it to hrb_lms_mcp. Phase
    165 added resolved_by_employee_id - a real employee_id, separate from
    resolved_by (a display name) - so hrb_lms_mcp's own review row can
    carry a real FK to the specialist, not just a name string.
    Phase 169 renamed this wrapper's own param to hitl_request_context_id
    (A2A-flavored naming - this id is what threads the submission and the
    resolution together) - the wire-level key below stays hitl_request_id,
    matching hrb_lms_mcp's own unrenamed MCP tool argument/column, a
    separate repo's schema not touched by this rename."""
    result = await _call_mcp_tool(
        "resolve_hitl_request",
        {
            "hitl_request_id": hitl_request_context_id,
            "decision": decision,
            "response_text": response_text,
            "resolved_by": resolved_by,
            "resolved_by_employee_id": resolved_by_employee_id,
        },
    )
    return json.loads(result["content"][0])


async def register_leave_document(
    employee_id: str, s3_key: str, original_filename: str, content_type: str | None = None
) -> dict:
    """Phase 165 - registers the document manifest row at upload time,
    before the leave request it belongs to exists yet - closes the orphan-
    upload gap (a failed submit after a successful S3 upload used to leave
    nothing in any database pointing at the uploaded file)."""
    result = await _call_mcp_tool(
        "register_leave_document",
        {
            "employee_id": employee_id,
            "s3_key": s3_key,
            "original_filename": original_filename,
            "content_type": content_type,
        },
    )
    return json.loads(result["content"][0])


async def list_leave_documents(leave_request_id: int) -> dict:
    """Phase 165 - the manifest rows for one leave request's uploaded
    document(s), used for both the HR review queue's and the employee's
    own "My Requests" view's document-download links."""
    result = await _call_mcp_tool("list_leave_documents", {"leave_request_id": leave_request_id})
    return json.loads(result["content"][0])


async def list_my_leave_requests(employee_id: str) -> dict:
    """Phase 165 - the employee's own "My Requests" view."""
    result = await _call_mcp_tool("list_my_leave_requests", {"employee_id": employee_id})
    return json.loads(result["content"][0])


async def list_all_leave_requests(status: str | None = None) -> dict:
    """Phase 168 (round 2) - the HR specialist grid: every leave request
    across every employee, with full status/decision/comments/timestamps -
    unlike /pending, not limited to PENDING only."""
    result = await _call_mcp_tool("list_all_leave_requests", {"status": status})
    return json.loads(result["content"][0])


async def admin_delete_hitl_request(hitl_request_context_id: int) -> dict:
    """Phase 168 - admin-only hard delete of a HITL request and everything
    that hangs off it. Returns any S3 keys the caller still needs to
    delete the real objects for - hrb_lms_mcp has no AWS client of its own."""
    result = await _call_mcp_tool("admin_delete_hitl_request", {"hitl_request_id": hitl_request_context_id})
    return json.loads(result["content"][0])


async def set_review_brief(hitl_request_context_id: int, review_brief: str) -> dict:
    """Phase 172 - stores the review-brief agent's generated summary onto
    hrb_lms_mcp's review row, before the graph pauses waiting on the
    specialist."""
    result = await _call_mcp_tool(
        "set_review_brief", {"hitl_request_id": hitl_request_context_id, "review_brief": review_brief}
    )
    return json.loads(result["content"][0])


async def record_produced_artifact(hitl_request_context_id: int, artifact: dict) -> dict:
    """Phase 172 - records one Artifact-shaped side effect (e.g. the
    decision email) the finalize step produced, after it actually happened -
    hrb_lms_mcp has no email client of its own, so it can't record this at
    resolve time."""
    result = await _call_mcp_tool(
        "record_produced_artifact", {"hitl_request_id": hitl_request_context_id, "artifact": artifact}
    )
    return json.loads(result["content"][0])


async def try_route_to_mcp(query: str, employee_id: str | None) -> dict | None:
    """Returns a pipeline-shaped answer dict if MCP-routable, else None (caller falls through to RAG)."""
    if not employee_id:
        return None

    if is_leave_balance_query(query):
        tool_name, caller = "get_leave_balance", get_leave_balance
    elif is_leave_history_query(query):
        tool_name, caller = "get_leave_history", get_leave_history
    else:
        return None

    call_started_at = time.perf_counter()
    try:
        mcp_result = await caller(employee_id)
    except Exception as error:
        logger.warning("MCP call to %s failed for %r, falling back to RAG: %s", tool_name, employee_id, error)
        return None
    call_latency_ms = round((time.perf_counter() - call_started_at) * 1000, 1)

    answer_text = "\n".join(mcp_result["content"]) or "No data returned."
    logger.info("Routed query %r to MCP tool %s for employee_id=%s", query, tool_name, employee_id)
    return {
        "query": query,
        "answer": answer_text,
        "model_used": f"mcp:{tool_name}",  # no LLM call happened - names the real source instead
        "sources": [],
        "vector_db": "n/a (mcp)",
        "search_strategy": "n/a (mcp)",
        "applied_filter": None,
        "routed_to": tool_name,
        "tool_latency_ms": call_latency_ms,
        # Phase 132 - the raw call, previously discarded after being joined into answer_text.
        "mcp_arguments": {"employee_id": employee_id},
        "mcp_raw_result": mcp_result["content"],
    }
