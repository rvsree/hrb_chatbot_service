"""Tests for Phase 162/172's LangGraph StateGraph (intake -> eligibility-
check -> submit -> review brief -> await specialist decision -> finalize).
Every hrb_lms_mcp call and LLM call is faked, no real MCP/network call,
matching every other agent test in this project. The checkpointer is a
real in-memory LangGraph MemorySaver, not the real Postgres-backed one -
genuine pause/resume semantics are still exercised (MemorySaver fully
implements the same async checkpointer interface), just without a real
database connection."""

from langgraph.checkpoint.memory import MemorySaver

from src.hrb_chatbot.ai.agents.workflow_agents import unpaid_leave_agent
from tests.conftest import FakeDBGateway


def _patch_db_gateway(monkeypatch, gateway=None):
    gateway = gateway or FakeDBGateway()
    monkeypatch.setattr(unpaid_leave_agent, "get_db_gateway", lambda: gateway)
    return gateway


def _patch_checkpointer(monkeypatch):
    saver = MemorySaver()

    async def _fake_run_graph(initial_state_or_command, config):
        graph = unpaid_leave_agent._build_graph().compile(checkpointer=saver)
        return await graph.ainvoke(initial_state_or_command, config=config)

    monkeypatch.setattr(unpaid_leave_agent, "_run_graph", _fake_run_graph)


def _patch_llm(monkeypatch):
    class _FakeResponse:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, messages, config=None):
            return _FakeResponse("Nothing stands out.")

    monkeypatch.setattr(unpaid_leave_agent, "build_agent_llm", lambda: _FakeLLM())


def _patch_review_brief(monkeypatch):
    async def _fake_set_review_brief(hitl_request_context_id, review_brief):
        return {"hitlRequestId": hitl_request_context_id, "reviewBriefSet": True}

    monkeypatch.setattr(unpaid_leave_agent, "set_review_brief", _fake_set_review_brief)


def _patch_history(monkeypatch, requests):
    async def _fake_get_leave_history_parsed(employee_id):
        return {"employeeId": employee_id, "total": len(requests), "requests": requests}

    monkeypatch.setattr(unpaid_leave_agent, "get_leave_history_parsed", _fake_get_leave_history_parsed)


def _patch_submit(monkeypatch, captured_calls):
    async def _fake_submit_unpaid_leave_request(**kwargs):
        captured_calls.append(kwargs)
        return {
            "requestId": 1,
            "employeeId": kwargs["employee_id"],
            "leaveType": "UNPAID",
            "startDate": kwargs["start_date"],
            "endDate": kwargs["end_date"],
            "days": 3.0,
            "status": "PENDING_HITL",
            "approverId": "MGR001",
            "isRepeatWithin12Months": kwargs["is_repeat_within_12_months"],
            "hitlRequestId": 7,
            "hitlStatus": "PENDING",
            "createdAt": "2026-10-11T00:00:00",
        }

    monkeypatch.setattr(unpaid_leave_agent, "submit_unpaid_leave_request", _fake_submit_unpaid_leave_request)


async def test_no_prior_unpaid_leave_is_not_flagged_as_repeat(monkeypatch):
    _patch_history(monkeypatch, [])
    captured_calls = []
    _patch_submit(monkeypatch, captured_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)

    result = await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052", start_date="2026-12-01", end_date="2026-12-03", purpose="Family caregiving"
    )

    assert captured_calls[0]["is_repeat_within_12_months"] is False
    assert result["isRepeatWithin12Months"] is False


async def test_unpaid_leave_within_last_365_days_is_flagged_as_repeat(monkeypatch):
    _patch_history(
        monkeypatch,
        [{"requestId": 1, "leaveType": "UNPAID", "startDate": "2026-06-01", "endDate": "2026-06-05", "days": 5.0, "status": "APPROVED"}],
    )
    captured_calls = []
    _patch_submit(monkeypatch, captured_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)

    result = await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052", start_date="2026-12-01", end_date="2026-12-03", purpose="Family caregiving"
    )

    assert captured_calls[0]["is_repeat_within_12_months"] is True
    assert result["isRepeatWithin12Months"] is True


async def test_unpaid_leave_older_than_365_days_is_not_flagged_as_repeat(monkeypatch):
    _patch_history(
        monkeypatch,
        [{"requestId": 1, "leaveType": "UNPAID", "startDate": "2024-01-01", "endDate": "2024-01-05", "days": 5.0, "status": "APPROVED"}],
    )
    captured_calls = []
    _patch_submit(monkeypatch, captured_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)

    await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052", start_date="2026-12-01", end_date="2026-12-03", purpose="Family caregiving"
    )

    assert captured_calls[0]["is_repeat_within_12_months"] is False


async def test_other_leave_types_within_12_months_do_not_count_as_a_repeat(monkeypatch):
    _patch_history(
        monkeypatch,
        [{"requestId": 1, "leaveType": "PTO", "startDate": "2026-09-01", "endDate": "2026-09-05", "days": 5.0, "status": "APPROVED"}],
    )
    captured_calls = []
    _patch_submit(monkeypatch, captured_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)

    await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052", start_date="2026-12-01", end_date="2026-12-03", purpose="Family caregiving"
    )

    assert captured_calls[0]["is_repeat_within_12_months"] is False


async def test_leave_type_code_defaults_to_unpaid(monkeypatch):
    _patch_history(monkeypatch, [])
    captured_calls = []
    _patch_submit(monkeypatch, captured_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)

    await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052", start_date="2026-12-01", end_date="2026-12-03", purpose="Family caregiving"
    )

    assert captured_calls[0]["leave_type_code"] == "UNPAID"


async def test_leave_type_code_is_threaded_through_to_submit(monkeypatch):
    _patch_history(monkeypatch, [])
    captured_calls = []
    _patch_submit(monkeypatch, captured_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)

    await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052",
        start_date="2026-12-01",
        end_date="2026-12-03",
        purpose="Recovering from surgery",
        leave_type_code="STD",
    )

    assert captured_calls[0]["leave_type_code"] == "STD"


async def test_repeat_check_is_scoped_to_the_same_leave_type_only(monkeypatch):
    """Phase 165 regression - a prior UNPAID request must not flag a new
    STD request as a repeat. Same-leave-type-only is a real HR-policy
    distinction, not incidental behavior."""
    _patch_history(
        monkeypatch,
        [{"requestId": 1, "leaveType": "UNPAID", "startDate": "2026-09-01", "endDate": "2026-09-05", "days": 5.0, "status": "APPROVED"}],
    )
    captured_calls = []
    _patch_submit(monkeypatch, captured_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)

    await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052",
        start_date="2026-12-01",
        end_date="2026-12-03",
        purpose="Recovering from surgery",
        leave_type_code="STD",
    )

    assert captured_calls[0]["is_repeat_within_12_months"] is False


async def test_repeat_check_flags_a_second_request_of_the_same_leave_type(monkeypatch):
    _patch_history(
        monkeypatch,
        [{"requestId": 1, "leaveType": "STD", "startDate": "2026-09-01", "endDate": "2026-09-05", "days": 5.0, "status": "APPROVED"}],
    )
    captured_calls = []
    _patch_submit(monkeypatch, captured_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)

    await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052",
        start_date="2026-12-01",
        end_date="2026-12-03",
        purpose="Recovering from surgery again",
        leave_type_code="STD",
    )

    assert captured_calls[0]["is_repeat_within_12_months"] is True


async def test_document_reference_is_threaded_through_to_submit(monkeypatch):
    _patch_history(monkeypatch, [])
    captured_calls = []
    _patch_submit(monkeypatch, captured_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)

    await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052",
        start_date="2026-12-01",
        end_date="2026-12-03",
        purpose="Family caregiving",
        document_reference="s3-key-token/cert.pdf",
    )

    assert captured_calls[0]["document_reference"] == "s3-key-token/cert.pdf"


# Phase 172 - real pause/resume, and the decision-email/Artifact step moved
# into finalize_node (out of the route, which only tests RBAC/response
# shaping now - see test_unpaid_leave.py).


def _patch_resolve(monkeypatch, employee_email=None):
    captured_calls = []

    async def _fake_resolve_hitl_request(**kwargs):
        captured_calls.append(kwargs)
        return {
            "hitlRequestId": kwargs["hitl_request_context_id"],
            "status": "COMPLETED",
            "decision": kwargs["decision"],
            "response": kwargs["response_text"],
            "assignedTo": kwargs["resolved_by"],
            "relatedLeaveRequestUpdated": True,
            "employeeEmail": employee_email,
        }

    monkeypatch.setattr(unpaid_leave_agent, "resolve_hitl_request", _fake_resolve_hitl_request)
    return captured_calls


async def test_full_submit_then_resolve_round_trip_resumes_the_same_paused_graph(monkeypatch):
    """The real point of Phase 172 - proves this is genuine pause/resume,
    not two unrelated calls that happen to share an id. The same shared
    MemorySaver checkpointer (from _patch_checkpointer) and the same
    FakeDBGateway's agent_threads table (from _patch_db_gateway) persist
    across both calls, exactly as the real Postgres-backed versions would
    across two real, separate HTTP requests."""
    _patch_history(monkeypatch, [])
    captured_submit_calls = []
    _patch_submit(monkeypatch, captured_submit_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    gateway = _patch_db_gateway(monkeypatch)
    captured_resolve_calls = _patch_resolve(monkeypatch, employee_email=None)

    submit_result = await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052", start_date="2026-12-01", end_date="2026-12-03", purpose="Family caregiving"
    )
    hitl_request_context_id = submit_result["hitlRequestId"]

    # The mapping is real, durable state - not just a return value in memory.
    assert await gateway.agent_thread_store().get_thread_id(hitl_request_context_id) is not None

    finalize_result = await unpaid_leave_agent.resume_unpaid_leave_decision(
        hitl_request_context_id=hitl_request_context_id,
        decision="APPROVED",
        response_text="Looks good.",
        resolved_by="Hana Support",
        resolved_by_employee_id="EMP051",
    )

    assert finalize_result["status"] == "COMPLETED"
    assert captured_resolve_calls[0]["hitl_request_context_id"] == hitl_request_context_id


async def test_resume_with_an_unknown_hitl_request_context_id_raises(monkeypatch):
    """No agent_threads mapping exists for an id that was never submitted
    through run_unpaid_leave_request() - must fail clearly, not silently
    start a brand-new, unrelated graph run."""
    _patch_db_gateway(monkeypatch)

    try:
        await unpaid_leave_agent.resume_unpaid_leave_decision(
            hitl_request_context_id=999999, decision="APPROVED", response_text="ok"
        )
        assert False, "expected a ValueError"
    except ValueError as error:
        assert "999999" in str(error)


async def test_resolve_sends_a_decision_email_when_employee_email_is_present(monkeypatch):
    """Moved here from test_unpaid_leave.py (Phase 172) - decision-email
    sending is now finalize_node's own work, not the route's."""
    _patch_history(monkeypatch, [])
    captured_submit_calls = []
    _patch_submit(monkeypatch, captured_submit_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)
    _patch_resolve(monkeypatch, employee_email="eddy.employee@example.com")

    sent_calls = []

    def _fake_send_email(recipient, subject, body, cc_addresses=None):
        sent_calls.append({"recipient": recipient, "subject": subject, "body": body})
        return {"sent": True, "message": "ok"}

    async def _fake_record_artifact(hitl_request_context_id, artifact):
        return {"hitlRequestId": hitl_request_context_id, "artifactRecorded": True}

    monkeypatch.setattr(unpaid_leave_agent, "send_email", _fake_send_email)
    monkeypatch.setattr(unpaid_leave_agent, "record_produced_artifact", _fake_record_artifact)

    submit_result = await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052", start_date="2026-12-01", end_date="2026-12-03", purpose="Family caregiving"
    )
    await unpaid_leave_agent.resume_unpaid_leave_decision(
        hitl_request_context_id=submit_result["hitlRequestId"],
        decision="APPROVED",
        response_text="Looks good.",
        resolved_by="Hana Support",
    )

    assert sent_calls[0]["recipient"] == "eddy.employee@example.com"
    assert "approved" in sent_calls[0]["subject"].lower()


async def test_resolve_still_succeeds_if_recording_the_artifact_fails(monkeypatch):
    """Best-effort, same reasoning as the email send itself - the decision
    is already recorded by this point, so recording the Artifact
    afterward must not turn a successful resolve into an error."""
    _patch_history(monkeypatch, [])
    captured_submit_calls = []
    _patch_submit(monkeypatch, captured_submit_calls)
    _patch_llm(monkeypatch)
    _patch_review_brief(monkeypatch)
    _patch_checkpointer(monkeypatch)
    _patch_db_gateway(monkeypatch)
    _patch_resolve(monkeypatch, employee_email="eddy.employee@example.com")

    def _fake_send_email(recipient, subject, body, cc_addresses=None):
        return {"sent": True, "message": "ok"}

    async def _failing_record_artifact(hitl_request_context_id, artifact):
        raise RuntimeError("hrb_lms_mcp unreachable")

    monkeypatch.setattr(unpaid_leave_agent, "send_email", _fake_send_email)
    monkeypatch.setattr(unpaid_leave_agent, "record_produced_artifact", _failing_record_artifact)

    submit_result = await unpaid_leave_agent.run_unpaid_leave_request(
        employee_id="EMP052", start_date="2026-12-01", end_date="2026-12-03", purpose="Family caregiving"
    )
    finalize_result = await unpaid_leave_agent.resume_unpaid_leave_decision(
        hitl_request_context_id=submit_result["hitlRequestId"],
        decision="APPROVED",
        response_text="Looks good.",
        resolved_by="Hana Support",
    )

    assert finalize_result["status"] == "COMPLETED"
