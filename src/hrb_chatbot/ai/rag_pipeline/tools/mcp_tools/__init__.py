"""Manual keyword routing to hrb_lms_mcp's MCP server - a prototype before real ReAct tool selection."""

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
