"""Phase 162 - "Request Unpaid Leave": a small, real LangGraph StateGraph.

Phase 172 rebuilt this into a genuine A2A/HITL showcase instead of a
deterministic 2-function pipeline:
  - A real Postgres-backed checkpointer (AsyncPostgresSaver) + interrupt()/
    Command(resume=...) - the graph actually pauses at await_specialist_decision,
    durably, and resumes in a LATER request (/resolve), days apart - not two
    unrelated function calls that happen to share a foreign key.
  - 2 real LLM calls restored from the original design
    (docs/dev-reference/leave-approval-a2a-design.html §04), dropped during
    Phase 162's own implementation: intake_node (flags anything a specialist
    should double-check) and review_brief_node (the specialist-facing
    summary - the "Review-support agent" that design called for).
  - A2A-shaped vocabulary on hrb_lms_mcp's existing schema: task_state
    (submitted/working/input_required/completed/rejected), review_brief,
    decision_message (Message/Parts shape), produced_artifacts (Artifact
    shape) - additive columns, the pre-existing status/decision/hr_comments
    columns are untouched.

The specialist's own decision is still never an LLM call - a human makes
it; the agent only carries it forward (unchanged from Phase 162)."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Coroutine, TypedDict
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.hrb_chatbot.ai.agents._llm_helpers import AGENT_LLM_TIMEOUT_SECONDS, build_agent_llm
from src.hrb_chatbot.ai.rag_pipeline.tools.mcp_tools import (
    get_leave_history_parsed,
    record_produced_artifact,
    resolve_hitl_request,
    set_review_brief,
    submit_unpaid_leave_request,
)
from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.clients.email_client.ses_client import send_email
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("agents.unpaid_leave_agent")

ELIGIBILITY_LOOKBACK_DAYS = 365


class UnpaidLeaveState(TypedDict):
    employee_id: str
    start_date: str
    end_date: str
    purpose: str
    leave_type_code: str
    document_reference: str | None
    is_repeat_within_12_months: bool
    intake_notes: str | None
    submit_result: dict | None
    review_brief: str | None
    decision: dict | None
    finalize_result: dict | None


def _build_postgres_uri() -> str:
    host = read_setting(None, "POSTGRES_DB_HOST")
    port = read_setting(None, "POSTGRES_DB_PORT", "5432")
    db_name = read_setting(None, "POSTGRES_DB_NAME")
    user = read_setting(None, "POSTGRES_DB_USER")
    password = read_setting(None, "POSTGRES_DB_PASSWORD")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _run_in_isolated_selector_loop(coro: Coroutine) -> object:
    """Runs one coroutine to completion on a brand-new SelectorEventLoop,
    in whatever thread calls this - always via asyncio.to_thread() below,
    never directly on the main event loop.

    Why this exists: AsyncPostgresSaver needs real async psycopg, which
    raises psycopg.InterfaceError outright on a ProactorEventLoop -
    confirmed directly, not assumed. Windows defaults every new asyncio
    event loop to Proactor (via the process-wide event loop policy), so a
    plain asyncio.to_thread(the_coroutine) would still hit a Proactor loop
    in that worker thread. Constructing SelectorEventLoop directly here,
    rather than going through asyncio.run()/the global policy, keeps this
    fix local to this one module - the main app's own event loop (uvicorn,
    every other async client) is never touched or reconfigured."""
    loop = asyncio.SelectorEventLoop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(None)


async def _run_graph(initial_state_or_command, config: dict) -> dict:
    """Builds a fresh checkpointer + graph and runs one ainvoke() call,
    isolated on its own SelectorEventLoop (see above) in a worker thread -
    shared by both run_unpaid_leave_request() (initial run, pauses at the
    interrupt) and resume_unpaid_leave_decision() (resumes via
    Command(resume=...))."""

    async def _inner() -> dict:
        async with AsyncPostgresSaver.from_conn_string(_build_postgres_uri()) as checkpointer:
            await checkpointer.setup()
            graph = _build_graph().compile(checkpointer=checkpointer)
            return await graph.ainvoke(initial_state_or_command, config=config)

    return await asyncio.to_thread(_run_in_isolated_selector_loop, _inner())


async def intake_node(state: UnpaidLeaveState) -> dict:
    """Restored LLM call #1 - flags anything a specialist should double
    check (e.g. a purpose that doesn't match the stated leave type, or an
    unusually long duration). Never blocks submission on its own judgment -
    a demo-grade LLM call shouldn't be able to reject a legitimate request
    on a hallucinated concern; it only annotates for review_brief_node."""
    llm = build_agent_llm()
    prompt = (
        f"Leave type: {state['leave_type_code']}\n"
        f"Dates: {state['start_date']} to {state['end_date']}\n"
        f"Purpose: {state['purpose']}\n\n"
        "In 1-2 sentences, note anything a specialist should double-check "
        "about this request (e.g. a purpose that seems to not match the "
        "leave type, or an unusually long duration). If nothing stands "
        "out, say so plainly. Do not approve or reject - only note."
    )
    response = await llm.ainvoke(
        [
            SystemMessage(content="You screen leave-request intake forms before HR review. You never decide, only note."),
            HumanMessage(content=prompt),
        ],
        config={"timeout": AGENT_LLM_TIMEOUT_SECONDS},
    )
    intake_notes = response.content.strip()
    logger.info("Intake notes for employee_id=%s: %s", state["employee_id"], intake_notes)
    return {"intake_notes": intake_notes}


async def eligibility_check_node(state: UnpaidLeaveState) -> dict:
    """Checks whether the employee has taken this same leave type within
    the last 12 months - purely a data/date comparison, no LLM needed
    (forcing one here would be pointless indirection, not genuine
    reasoning). Phase 165: scoped to the same leave_type_code only (a 2nd
    STD request within 12 months flags; an unrelated CCG request doesn't) -
    a real HR-policy distinction, not a technical default."""
    history = await get_leave_history_parsed(state["employee_id"])
    cutoff = date.today() - timedelta(days=ELIGIBILITY_LOOKBACK_DAYS)

    is_repeat = any(
        request["leaveType"] == state["leave_type_code"] and date.fromisoformat(request["startDate"]) >= cutoff
        for request in history.get("requests", [])
    )
    logger.info(
        "Eligibility check for employee_id=%s: is_repeat_within_12_months=%s (checked %d prior requests)",
        state["employee_id"],
        is_repeat,
        len(history.get("requests", [])),
    )
    return {"is_repeat_within_12_months": is_repeat}


async def submit_to_mcp_node(state: UnpaidLeaveState) -> dict:
    result = await submit_unpaid_leave_request(
        employee_id=state["employee_id"],
        start_date=state["start_date"],
        end_date=state["end_date"],
        purpose=state["purpose"],
        is_repeat_within_12_months=state["is_repeat_within_12_months"],
        leave_type_code=state["leave_type_code"],
        document_reference=state.get("document_reference"),
    )
    return {"submit_result": result}


async def review_brief_node(state: UnpaidLeaveState) -> dict:
    """Restored LLM call #2 - the "Review-support agent" from the original
    design (docs/dev-reference/leave-approval-a2a-design.html §04):
    summarizes the request for the specialist. Never recommends a decision -
    the specialist still reads the real underlying fields too, this is a
    summary layer on top, not a replacement for them. Persisted onto
    hrb_lms_mcp's review row before the graph pauses, so it's already there
    the moment a specialist opens the queue."""
    llm = build_agent_llm()
    prompt = (
        f"Employee: {state['employee_id']}\n"
        f"Leave type: {state['leave_type_code']}\n"
        f"Dates: {state['start_date']} to {state['end_date']}\n"
        f"Purpose: {state['purpose']}\n"
        f"Repeat request within 12 months: {state['is_repeat_within_12_months']}\n"
        f"Intake notes: {state.get('intake_notes') or 'none'}\n\n"
        "Write a 2-3 sentence plain-English summary for an HR specialist "
        "reviewing this request. Do not recommend approve or reject - only summarize."
    )
    response = await llm.ainvoke(
        [
            SystemMessage(content="You summarize leave requests for a human HR specialist. You never decide."),
            HumanMessage(content=prompt),
        ],
        config={"timeout": AGENT_LLM_TIMEOUT_SECONDS},
    )
    review_brief = response.content.strip()

    hitl_request_context_id = state["submit_result"]["hitlRequestId"]
    await set_review_brief(hitl_request_context_id, review_brief)
    logger.info("Review brief set for hitl_request_context_id=%s", hitl_request_context_id)
    return {"review_brief": review_brief}


async def await_specialist_decision_node(state: UnpaidLeaveState) -> dict:
    """The real pause - durably checkpointed by AsyncPostgresSaver. A
    LATER, separate request (/resolve, days apart) resumes this exact
    paused run via Command(resume=...), not a fresh, unrelated call."""
    hitl_request_context_id = state["submit_result"]["hitlRequestId"]
    decision_payload = interrupt(
        {
            "hitl_request_context_id": hitl_request_context_id,
            "task_state": "input_required",
        }
    )
    return {"decision": decision_payload}


async def finalize_node(state: UnpaidLeaveState) -> dict:
    """Runs only after resume. Carries the specialist's human decision to
    hrb_lms_mcp (never an LLM call), then produces the decision-email
    Artifact and records it - moved here from the route (Phase 162/165) so
    it's genuinely part of the resumed Task's own work, not a side-channel
    the route bolts on afterward."""
    decision = state["decision"]
    result = await resolve_hitl_request(
        hitl_request_context_id=decision["hitl_request_context_id"],
        decision=decision["decision"],
        response_text=decision["response_text"],
        resolved_by=decision.get("resolved_by"),
        resolved_by_employee_id=decision.get("resolved_by_employee_id"),
    )

    employee_email = result.get("employeeEmail")
    if employee_email:
        subject = f"Your leave request has been {result['decision'].lower()}"
        body = (
            f"Your leave request has been {result['decision'].lower()} by "
            f"{decision.get('resolved_by') or 'HR'}.\n\nComments: {decision['response_text']}"
        )
        send_result = send_email(employee_email, subject, body)
        artifact = {
            "type": "email",
            "recipient": employee_email,
            "sent": send_result.get("sent", False),
            "message": send_result.get("message"),
            "sent_at": datetime.now(UTC).isoformat(),
        }
        try:
            await record_produced_artifact(decision["hitl_request_context_id"], artifact)
        except Exception as error:
            # Best-effort, same reasoning as the email send itself - the
            # decision is already recorded by this point.
            logger.warning(
                "Recording produced artifact for hitl_request_context_id=%s failed: %s",
                decision["hitl_request_context_id"],
                error,
            )

    return {"finalize_result": result}


def _build_graph() -> StateGraph:
    graph = StateGraph(UnpaidLeaveState)
    graph.add_node("intake", intake_node)
    graph.add_node("eligibility_check", eligibility_check_node)
    graph.add_node("submit", submit_to_mcp_node)
    graph.add_node("generate_review_brief", review_brief_node)
    graph.add_node("await_specialist_decision", await_specialist_decision_node)
    graph.add_node("finalize", finalize_node)
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "eligibility_check")
    graph.add_edge("eligibility_check", "submit")
    graph.add_edge("submit", "generate_review_brief")
    graph.add_edge("generate_review_brief", "await_specialist_decision")
    graph.add_edge("await_specialist_decision", "finalize")
    graph.add_edge("finalize", END)
    return graph


async def run_unpaid_leave_request(
    employee_id: str,
    start_date: str,
    end_date: str,
    purpose: str,
    leave_type_code: str = "UNPAID",
    document_reference: str | None = None,
) -> dict:
    """Runs the graph from START up to the pause at
    await_specialist_decision, then returns - the graph is durably
    checkpointed, not finished. Returns the same dict shape
    submit_unpaid_leave_request's own MCP response has (requestId,
    employeeId, leaveType, status, isRepeatWithin12Months, hitlRequestId,
    hitlStatus, days) - unchanged response contract from Phase 162/165."""
    agent_thread_id = str(uuid4())
    config = {"configurable": {"thread_id": agent_thread_id}}
    initial_state: UnpaidLeaveState = {
        "employee_id": employee_id,
        "start_date": start_date,
        "end_date": end_date,
        "purpose": purpose,
        "leave_type_code": leave_type_code,
        "document_reference": document_reference,
        "is_repeat_within_12_months": False,
        "intake_notes": None,
        "submit_result": None,
        "review_brief": None,
        "decision": None,
        "finalize_result": None,
    }

    result = await _run_graph(initial_state, config)

    submit_result = result["submit_result"]
    hitl_request_context_id = submit_result["hitlRequestId"]
    await get_db_gateway().agent_thread_store().save_thread_mapping(hitl_request_context_id, agent_thread_id)
    logger.info(
        "Graph paused at await_specialist_decision - hitl_request_context_id=%s, agent_thread_id=%s",
        hitl_request_context_id,
        agent_thread_id,
    )
    return submit_result


async def resume_unpaid_leave_decision(
    hitl_request_context_id: int,
    decision: str,
    response_text: str,
    resolved_by: str | None = None,
    resolved_by_employee_id: str | None = None,
) -> dict:
    """Resumes the SAME paused graph run run_unpaid_leave_request() left
    checkpointed - a real resume, not a fresh unrelated call. Returns the
    same dict shape resolve_hitl_request's own MCP response has
    (hitlRequestId, status, decision, response, respondedAt, assignedTo,
    relatedLeaveRequestUpdated, employeeEmail) - unchanged response
    contract from Phase 162/165."""
    agent_thread_id = await get_db_gateway().agent_thread_store().get_thread_id(hitl_request_context_id)
    if agent_thread_id is None:
        raise ValueError(
            f"No agent thread found for hitl_request_context_id={hitl_request_context_id} - "
            "was this request ever submitted through run_unpaid_leave_request()?"
        )

    config = {"configurable": {"thread_id": agent_thread_id}}
    decision_payload = {
        "hitl_request_context_id": hitl_request_context_id,
        "decision": decision,
        "response_text": response_text,
        "resolved_by": resolved_by,
        "resolved_by_employee_id": resolved_by_employee_id,
    }

    result = await _run_graph(Command(resume=decision_payload), config)

    logger.info("Graph resumed and completed - hitl_request_context_id=%s", hitl_request_context_id)
    return result["finalize_result"]
