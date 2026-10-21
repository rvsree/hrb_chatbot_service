"""Tests for the Phase 49 MCP routing prototype (ai/rag_pipeline/tools/
mcp_tools/__init__.py). get_leave_balance/get_leave_history are faked here -
no real network call to hrb_lms_mcp, matching every other client test in
this project."""

from datetime import UTC, datetime, timedelta

import pytest

from src.hrb_chatbot.ai.rag_pipeline.tools import mcp_tools


class FakeMcpRegistryClient:
    """Stands in for McpRegistryClient (Phase 185's circuit breaker) - no
    real database connection, same async interface."""

    def __init__(self, status: dict | None = None):
        self.status = status
        self.recorded_calls: list[dict] = []

    async def get_connection_status(self, server_id):
        if self.status is None:
            return None
        return self.status

    async def record_connection_attempt(self, server_id, success, result, error_message=None):
        self.recorded_calls.append({"server_id": server_id, "success": success, "error_message": error_message})


def test_leave_balance_keywords_match():
    assert mcp_tools.is_leave_balance_query("What's my PTO balance?")
    assert mcp_tools.is_leave_balance_query("How many days off do I have left")
    assert not mcp_tools.is_leave_balance_query("How does 401k vesting work?")


def test_leave_history_keywords_match():
    assert mcp_tools.is_leave_history_query("Show me my leave history")
    assert not mcp_tools.is_leave_history_query("What's my PTO balance?")


async def test_matched_query_with_employee_id_routes_to_mcp(monkeypatch):
    async def _fake_get_leave_balance(employee_id):
        return {"tool": "get_leave_balance", "content": [f"balance for {employee_id}"]}

    monkeypatch.setattr(mcp_tools, "get_leave_balance", _fake_get_leave_balance)

    result = await mcp_tools.try_route_to_mcp("What's my PTO balance?", "EMP052")

    assert result is not None
    assert result["routed_to"] == "get_leave_balance"
    assert result["answer"] == "balance for EMP052"
    assert result["sources"] == []


async def test_unmatched_query_falls_through_to_none():
    result = await mcp_tools.try_route_to_mcp("How does 401k vesting work?", "EMP052")
    assert result is None


async def test_matched_query_without_employee_id_falls_through_to_none():
    result = await mcp_tools.try_route_to_mcp("What's my PTO balance?", None)
    assert result is None


async def test_mcp_failure_falls_through_to_none_not_raise(monkeypatch):
    async def _fake_get_leave_balance_raising(employee_id):
        raise ConnectionError("hrb_lms_mcp unreachable")

    monkeypatch.setattr(mcp_tools, "get_leave_balance", _fake_get_leave_balance_raising)

    result = await mcp_tools.try_route_to_mcp("What's my PTO balance?", "EMP052")

    assert result is None


async def test_circuit_breaker_allows_a_call_when_no_status_row_exists(monkeypatch):
    fake_registry = FakeMcpRegistryClient(status=None)
    monkeypatch.setattr(mcp_tools, "_get_mcp_registry_client", lambda: fake_registry)

    await mcp_tools._check_circuit_breaker()  # must not raise


async def test_circuit_breaker_allows_a_call_when_status_is_connected(monkeypatch):
    fake_registry = FakeMcpRegistryClient(
        status={"connection_status": "connected", "consecutive_failures": 0, "last_health_check_at": datetime.now(UTC)}
    )
    monkeypatch.setattr(mcp_tools, "_get_mcp_registry_client", lambda: fake_registry)

    await mcp_tools._check_circuit_breaker()  # must not raise


async def test_circuit_breaker_allows_a_call_below_the_failure_threshold(monkeypatch):
    fake_registry = FakeMcpRegistryClient(
        status={"connection_status": "error", "consecutive_failures": 1, "last_health_check_at": datetime.now(UTC)}
    )
    monkeypatch.setattr(mcp_tools, "_get_mcp_registry_client", lambda: fake_registry)

    await mcp_tools._check_circuit_breaker()  # 1 failure < threshold of 2, must not raise


async def test_circuit_breaker_trips_within_the_cooldown_window(monkeypatch):
    fake_registry = FakeMcpRegistryClient(
        status={"connection_status": "error", "consecutive_failures": 3, "last_health_check_at": datetime.now(UTC)}
    )
    monkeypatch.setattr(mcp_tools, "_get_mcp_registry_client", lambda: fake_registry)

    with pytest.raises(RuntimeError, match="known unreachable"):
        await mcp_tools._check_circuit_breaker()


async def test_circuit_breaker_allows_a_call_once_the_cooldown_elapses(monkeypatch):
    stale_check = datetime.now(UTC) - timedelta(seconds=mcp_tools.MCP_CIRCUIT_BREAKER_COOLDOWN_SECONDS + 5)
    fake_registry = FakeMcpRegistryClient(
        status={"connection_status": "error", "consecutive_failures": 5, "last_health_check_at": stale_check}
    )
    monkeypatch.setattr(mcp_tools, "_get_mcp_registry_client", lambda: fake_registry)

    await mcp_tools._check_circuit_breaker()  # cooldown elapsed, must not raise


async def test_circuit_breaker_fails_open_when_the_registry_read_itself_fails(monkeypatch):
    class _RaisingRegistryClient:
        async def get_connection_status(self, server_id):
            raise ConnectionError("hr_chatbot database unreachable")

    monkeypatch.setattr(mcp_tools, "_get_mcp_registry_client", lambda: _RaisingRegistryClient())

    await mcp_tools._check_circuit_breaker()  # must not raise - fails open, never blocks a real call


async def test_record_mcp_outcome_records_success(monkeypatch):
    fake_registry = FakeMcpRegistryClient()
    monkeypatch.setattr(mcp_tools, "_get_mcp_registry_client", lambda: fake_registry)

    await mcp_tools._record_mcp_outcome(True, None)

    assert fake_registry.recorded_calls == [{"server_id": "hrb_lms_mcp", "success": True, "error_message": None}]


async def test_record_mcp_outcome_never_raises_when_recording_itself_fails(monkeypatch):
    class _RaisingRegistryClient:
        async def record_connection_attempt(self, server_id, success, result, error_message=None):
            raise ConnectionError("hr_chatbot database unreachable")

    monkeypatch.setattr(mcp_tools, "_get_mcp_registry_client", lambda: _RaisingRegistryClient())

    await mcp_tools._record_mcp_outcome(False, "some error")  # must not raise


# Phase 239 - get_mcp_tool_catalog() tests. discover_mcp_tools() itself (the
# raw session.list_tools() call) is faked out here, same philosophy as
# get_leave_balance being faked above rather than mocking the raw MCP
# transport - no precedent exists anywhere in this project for faking
# streamablehttp_client/ClientSession at that level.
class TestGetMcpToolCatalog:
    def setup_method(self):
        # Module-level cache - reset before every test so one test's
        # result can't leak into the next.
        mcp_tools._tool_catalog_cache = None

    async def test_merges_the_one_configured_server_into_a_tools_list(self, monkeypatch):
        fake_tools = [
            {"name": "get_leave_balance", "description": "...", "input_schema": {}, "server_id": "hrb_lms_mcp"},
        ]

        async def _fake_discover(server_id, url_setting_name):
            return fake_tools

        monkeypatch.setattr(mcp_tools, "discover_mcp_tools", _fake_discover)

        result = await mcp_tools.get_mcp_tool_catalog()

        assert result == {"tools": fake_tools, "error": None}

    async def test_caches_and_does_not_rediscover_on_a_second_call(self, monkeypatch):
        call_count = 0

        async def _fake_discover(server_id, url_setting_name):
            nonlocal call_count
            call_count += 1
            return [{"name": "get_leave_balance", "description": "", "input_schema": {}, "server_id": server_id}]

        monkeypatch.setattr(mcp_tools, "discover_mcp_tools", _fake_discover)

        await mcp_tools.get_mcp_tool_catalog()
        await mcp_tools.get_mcp_tool_catalog()

        assert call_count == 1

    async def test_force_refresh_bypasses_the_cache(self, monkeypatch):
        call_count = 0

        async def _fake_discover(server_id, url_setting_name):
            nonlocal call_count
            call_count += 1
            return [{"name": "get_leave_balance", "description": "", "input_schema": {}, "server_id": server_id}]

        monkeypatch.setattr(mcp_tools, "discover_mcp_tools", _fake_discover)

        await mcp_tools.get_mcp_tool_catalog()
        await mcp_tools.get_mcp_tool_catalog(force_refresh=True)

        assert call_count == 2

    async def test_a_failed_server_surfaces_as_error_not_a_raise(self, monkeypatch):
        async def _fake_discover_raising(server_id, url_setting_name):
            raise ConnectionError("hrb_lms_mcp unreachable")

        monkeypatch.setattr(mcp_tools, "discover_mcp_tools", _fake_discover_raising)

        result = await mcp_tools.get_mcp_tool_catalog()

        assert result["tools"] == []
        assert "hrb_lms_mcp" in result["error"]
