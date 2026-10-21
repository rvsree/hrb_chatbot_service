"""Manual keyword routing to hrb_lms_mcp's MCP server - a prototype before real ReAct tool selection."""

import json
import time
from datetime import UTC, datetime

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from src.hrb_chatbot.common.clients.auth_client.oauth_client import get_access_token
from src.hrb_chatbot.common.clients.db_client.mcp_registry_client import McpRegistryClient
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("rag_pipeline.tools.mcp_tools")

LEAVE_BALANCE_KEYWORDS = ("leave balance", "pto balance", "how many days off", "sick balance")
LEAVE_HISTORY_KEYWORDS = ("leave history", "past leave", "leave requests")

# Phase 185 - a circuit breaker, not just the existing reactive fallback
# (any MCP failure already falls back to RAG, documented elsewhere). This
# adds a pre-flight check so a *known*, ongoing outage fails fast on the
# 3rd+ request instead of every single request paying a real network
# timeout first. Module-level singleton, not a DI container - same
# pattern as every other lazily-built client in this project.
MCP_SERVER_ID = "hrb_lms_mcp"
MCP_CIRCUIT_BREAKER_COOLDOWN_SECONDS = int(read_setting(None, "MCP_CIRCUIT_BREAKER_COOLDOWN_SECONDS", 10))
MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD = 2

_mcp_registry_client: McpRegistryClient | None = None


def _get_mcp_registry_client() -> McpRegistryClient:
    global _mcp_registry_client
    if _mcp_registry_client is None:
        _mcp_registry_client = McpRegistryClient()
    return _mcp_registry_client


async def _check_circuit_breaker() -> None:
    """Fails open on any problem reading the cached status (unknown
    registry client, DB unreachable, no row yet) - a pre-flight check that
    can itself fail must never block a real call, only skip one it's
    confident is pointless."""
    try:
        status = await _get_mcp_registry_client().get_connection_status(MCP_SERVER_ID)
    except Exception as error:
        logger.warning("MCP circuit breaker: could not read cached status, attempting the real call: %s", error)
        return

    if status is None or status["connection_status"] != "error":
        return
    if status["consecutive_failures"] < MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD:
        return

    last_check = status["last_health_check_at"]
    if last_check is None:
        return
    age_seconds = (datetime.now(UTC) - last_check).total_seconds()
    if age_seconds > MCP_CIRCUIT_BREAKER_COOLDOWN_SECONDS:
        return

    raise RuntimeError(
        f"hrb_lms_mcp known unreachable ({status['consecutive_failures']} consecutive failures, "
        f"last checked {int(age_seconds)}s ago) - skipping a live call until the {MCP_CIRCUIT_BREAKER_COOLDOWN_SECONDS}s cooldown elapses."
    )


async def _record_mcp_outcome(success: bool, error_message: str | None) -> None:
    """Best-effort - a recording failure must never surface to the real
    caller, same fire-and-forget principle as response_metrics.py."""
    try:
        await _get_mcp_registry_client().record_connection_attempt(
            MCP_SERVER_ID, success=success, result={}, error_message=error_message
        )
    except Exception as error:
        logger.warning("MCP circuit breaker: could not record this call's outcome: %s", error)


def is_leave_balance_query(query: str) -> bool:
    lowered = query.lower()
    return any(keyword in lowered for keyword in LEAVE_BALANCE_KEYWORDS)


def is_leave_history_query(query: str) -> bool:
    lowered = query.lower()
    return any(keyword in lowered for keyword in LEAVE_HISTORY_KEYWORDS)


async def _call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """Opens one MCP session, calls one tool, closes it - raises on any
    failure. Phase 185: a pre-flight circuit-breaker check runs first, and
    every real attempt's outcome (success or failure) is recorded for the
    *next* call's own pre-flight check to use."""
    await _check_circuit_breaker()

    mcp_url = read_setting(None, "HRB_LMS_MCP_URL", "http://127.0.0.1:8190/mcp")
    # Phase 53: real OAuth2 Bearer token, not the dead X-API-Key header -
    # hrb_lms_mcp's server actually enforces this one.
    access_token = await get_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with streamablehttp_client(mcp_url, headers=headers) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if result.isError:
                    raise RuntimeError(f"MCP tool {tool_name!r} returned an error: {result.content}")
                parsed = {"tool": tool_name, "content": [block.text for block in result.content if block.type == "text"]}
    except Exception as error:
        await _record_mcp_outcome(False, str(error))
        raise

    await _record_mcp_outcome(True, None)
    return parsed


async def _call_mcp_tool_json(tool_name: str, arguments: dict) -> dict:
    """MCP cohort-review gap #1 (BACKLOG.md, 2026-10-15) - every wrapper
    below used to hand-roll json.loads(result["content"][0]) itself,
    each one independently knowing FastMCP's own "one pretty-printed JSON
    text block per call" convention (Phase 162). One shared unwrap, no
    behavior change."""
    result = await _call_mcp_tool(tool_name, arguments)
    return json.loads(result["content"][0])


# Phase 239 - MCP cohort-review gap #2 (BACKLOG.md, 2026-10-15), the real
# prerequisite for it: the course's own m1_mcp/sse_agent_client.py merges
# multiple servers' session.list_tools() catalogs into one combined list
# plus a tool_name -> server routing table (its own server_sessions dict).
# That pattern needs real discovery to exist first - this project had none
# at all, for even the one real server it has today; every tool above is
# its own hardcoded function instead. MCP_SERVERS has one entry today -
# the course's own multi-server merge is genuinely out of scope until a
# second real MCP server exists (see RAG-ROADMAP.md Phase 239's own "Out
# of scope") - but adding one later means extending this dict, not
# rewriting how a tool call gets routed.
MCP_SERVERS: dict[str, str] = {MCP_SERVER_ID: "HRB_LMS_MCP_URL"}

_tool_catalog_cache: dict[str, dict] | None = None


async def discover_mcp_tools(server_id: str, url_setting_name: str) -> list[dict]:
    """One server's own real tool catalog via session.list_tools() - name,
    description, and input_schema exactly as that server advertises them,
    not inferred from reading this module's own hardcoded wrapper
    functions. Raises on failure - the caller (get_mcp_tool_catalog)
    decides how to degrade, matching every other MCP call in this module
    keeping that decision at the edge, not inside the low-level call."""
    mcp_url = read_setting(None, url_setting_name, "http://127.0.0.1:8190/mcp")
    access_token = await get_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    async with streamablehttp_client(mcp_url, headers=headers) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema,
                    "server_id": server_id,
                }
                for tool in tools_response.tools
            ]


async def get_mcp_tool_catalog(force_refresh: bool = False) -> dict:
    """Every configured server's own catalog (MCP_SERVERS), merged into one
    tool_name -> tool dict - the course's own server_sessions merge,
    generalized to N servers even though exactly 1 is configured today.
    In-process cached (the catalog rarely changes within a process
    lifetime) - force_refresh bypasses it. Never raises - error-as-data,
    same convention every other MCP-backed call in this project follows;
    a failed server's tools are simply absent from the merged catalog,
    not a partial/corrupt entry."""
    global _tool_catalog_cache
    if _tool_catalog_cache is not None and not force_refresh:
        return {"tools": list(_tool_catalog_cache.values()), "error": None}

    catalog: dict[str, dict] = {}
    errors: list[str] = []
    for server_id, url_setting_name in MCP_SERVERS.items():
        try:
            tools = await discover_mcp_tools(server_id, url_setting_name)
        except Exception as error:
            logger.warning("MCP tool discovery failed for %s: %s", server_id, error)
            errors.append(f"{server_id}: {error}")
            continue
        for tool in tools:
            catalog[tool["name"]] = tool

    _tool_catalog_cache = catalog
    return {"tools": list(catalog.values()), "error": "; ".join(errors) if errors else None}


async def get_leave_balance(employee_id: str) -> dict:
    return await _call_mcp_tool("get_leave_balance", {"employee_id": employee_id})


async def get_leave_history(employee_id: str) -> dict:
    return await _call_mcp_tool("get_leave_history", {"employee_id": employee_id})


async def get_leave_history_parsed(employee_id: str, limit: int = 50) -> dict:
    """Phase 162 - same call as get_leave_history(), but parsed into a real
    dict (requests/total/...), not display text. Confirmed live that FastMCP
    returns exactly one pretty-printed JSON text block per call - every new
    Phase 162 wrapper that needs structured data parses it the same way."""
    return await _call_mcp_tool_json("get_leave_history", {"employee_id": employee_id, "limit": limit})


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
    return await _call_mcp_tool_json(
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
    return await _call_mcp_tool_json(
        "resolve_hitl_request",
        {
            "hitl_request_id": hitl_request_context_id,
            "decision": decision,
            "response_text": response_text,
            "resolved_by": resolved_by,
            "resolved_by_employee_id": resolved_by_employee_id,
        },
    )


async def register_leave_document(
    employee_id: str, s3_key: str, original_filename: str, content_type: str | None = None
) -> dict:
    """Phase 165 - registers the document manifest row at upload time,
    before the leave request it belongs to exists yet - closes the orphan-
    upload gap (a failed submit after a successful S3 upload used to leave
    nothing in any database pointing at the uploaded file)."""
    return await _call_mcp_tool_json(
        "register_leave_document",
        {
            "employee_id": employee_id,
            "s3_key": s3_key,
            "original_filename": original_filename,
            "content_type": content_type,
        },
    )


async def list_leave_documents(leave_request_id: int) -> dict:
    """Phase 165 - the manifest rows for one leave request's uploaded
    document(s), used for both the HR review queue's and the employee's
    own "My Requests" view's document-download links."""
    return await _call_mcp_tool_json("list_leave_documents", {"leave_request_id": leave_request_id})


async def list_my_leave_requests(employee_id: str) -> dict:
    """Phase 165 - the employee's own "My Requests" view."""
    return await _call_mcp_tool_json("list_my_leave_requests", {"employee_id": employee_id})


async def list_all_leave_requests(status: str | None = None) -> dict:
    """Phase 168 (round 2) - the HR specialist grid: every leave request
    across every employee, with full status/decision/comments/timestamps -
    unlike /pending, not limited to PENDING only."""
    return await _call_mcp_tool_json("list_all_leave_requests", {"status": status})


async def admin_delete_hitl_request(hitl_request_context_id: int) -> dict:
    """Phase 168 - admin-only hard delete of a HITL request and everything
    that hangs off it. Returns any S3 keys the caller still needs to
    delete the real objects for - hrb_lms_mcp has no AWS client of its own."""
    return await _call_mcp_tool_json("admin_delete_hitl_request", {"hitl_request_id": hitl_request_context_id})


async def set_review_brief(hitl_request_context_id: int, review_brief: str) -> dict:
    """Phase 172 - stores the review-brief agent's generated summary onto
    hrb_lms_mcp's review row, before the graph pauses waiting on the
    specialist."""
    return await _call_mcp_tool_json(
        "set_review_brief", {"hitl_request_id": hitl_request_context_id, "review_brief": review_brief}
    )


async def record_produced_artifact(hitl_request_context_id: int, artifact: dict) -> dict:
    """Phase 172 - records one Artifact-shaped side effect (e.g. the
    decision email) the finalize step produced, after it actually happened -
    hrb_lms_mcp has no email client of its own, so it can't record this at
    resolve time."""
    return await _call_mcp_tool_json(
        "record_produced_artifact", {"hitl_request_id": hitl_request_context_id, "artifact": artifact}
    )


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
