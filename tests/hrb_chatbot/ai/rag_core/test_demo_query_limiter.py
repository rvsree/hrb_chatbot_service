"""Phase 265: demo_query_limiter - caps anonymous demo-visitor queries per
conversation, with a per-IP-per-day backstop and an admin-grantable waiver.
Redis/Postgres are faked - no real network call, matching every other test
in this project. conftest.py forces APP_DEMO_QUERY_LIMIT_ENABLED=false by
default (same off-by-default-in-tests pattern as APP_RATE_LIMITING), so each
test that needs the limiter active sets it explicitly via monkeypatch.setenv."""

from src.hrb_chatbot.ai.rag_core import demo_query_limiter
from tests.conftest import FakeAppSettingsStore, FakeDBGateway, FakeDemoVisitorStore


class _FakeRedisClient:
    def __init__(self, raise_on_incr=False):
        self._counts: dict[str, int] = {}
        self.raise_on_incr = raise_on_incr

    async def incr(self, key):
        if self.raise_on_incr:
            raise ConnectionError("redis unreachable")
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key, seconds):
        pass


def _patch_gateway(monkeypatch, app_settings=None, demo_visitors=None):
    gateway = FakeDBGateway(
        app_settings_store=FakeAppSettingsStore(app_settings or {}),
        demo_visitor_store=demo_visitors or FakeDemoVisitorStore(),
    )
    monkeypatch.setattr(demo_query_limiter, "get_db_gateway", lambda: gateway)
    return gateway


def _patch_redis(monkeypatch, client=None):
    monkeypatch.setattr(demo_query_limiter, "_get_redis_client", lambda: client or _FakeRedisClient())


async def test_disabled_by_default_returns_not_blocked_without_touching_storage(monkeypatch):
    def _should_not_be_called():
        raise AssertionError("get_db_gateway must not be called when the limiter is disabled")

    monkeypatch.setattr(demo_query_limiter, "get_db_gateway", _should_not_be_called)

    result = await demo_query_limiter.check_and_record("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4")

    assert result.blocked is False
    assert result.to_response_dict() is None


async def test_exempt_admin_role_returns_not_blocked_without_touching_storage(monkeypatch):
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")

    def _should_not_be_called():
        raise AssertionError("get_db_gateway must not be called for an exempt role")

    monkeypatch.setattr(demo_query_limiter, "get_db_gateway", _should_not_be_called)

    result = await demo_query_limiter.check_and_record("conv-1", "ADM001", "Sree Rad", "admin", "1.2.3.4")

    assert result.blocked is False


async def test_missing_conversation_id_returns_not_blocked(monkeypatch):
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")

    def _should_not_be_called():
        raise AssertionError("get_db_gateway must not be called with no conversation_id")

    monkeypatch.setattr(demo_query_limiter, "get_db_gateway", _should_not_be_called)

    result = await demo_query_limiter.check_and_record(None, "EMP052", "Eddy Employee", "employee", "1.2.3.4")

    assert result.blocked is False


async def test_under_limit_allows_through_and_reports_remaining(monkeypatch):
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")
    _patch_gateway(monkeypatch, app_settings={"demo_query_limit": 15, "demo_query_limit_per_ip_per_day": 50})
    _patch_redis(monkeypatch)

    result = await demo_query_limiter.check_and_record("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4")

    assert result.blocked is False
    assert result.to_response_dict() == {"query_count": 1, "effective_limit": 15, "remaining": 14}


async def test_exceeding_the_conversation_limit_blocks(monkeypatch):
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")
    demo_visitors = FakeDemoVisitorStore({"conv-1": {"conversation_id": "conv-1", "query_count": 2, "waiver_count": 0}})
    _patch_gateway(monkeypatch, app_settings={"demo_query_limit": 2, "demo_query_limit_per_ip_per_day": 50}, demo_visitors=demo_visitors)
    _patch_redis(monkeypatch)

    result = await demo_query_limiter.check_and_record("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4")

    assert result.blocked is True
    assert result.effective_limit == 2
    assert result.query_count == 3


async def test_admin_granted_waiver_raises_the_effective_limit(monkeypatch):
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")
    demo_visitors = FakeDemoVisitorStore({"conv-1": {"conversation_id": "conv-1", "query_count": 15, "waiver_count": 15}})
    _patch_gateway(monkeypatch, app_settings={"demo_query_limit": 15, "demo_query_limit_per_ip_per_day": 50}, demo_visitors=demo_visitors)
    _patch_redis(monkeypatch)

    result = await demo_query_limiter.check_and_record("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4")

    assert result.blocked is False
    assert result.effective_limit == 30
    assert result.remaining == 14


async def test_ip_daily_cap_exceeded_blocks_even_under_the_conversation_limit(monkeypatch):
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")
    _patch_gateway(monkeypatch, app_settings={"demo_query_limit": 15, "demo_query_limit_per_ip_per_day": 1})
    redis_client = _FakeRedisClient()
    _patch_redis(monkeypatch, redis_client)

    await demo_query_limiter.check_and_record("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4")
    result = await demo_query_limiter.check_and_record("conv-2", "EMP053", "Mia Manager", "employee", "1.2.3.4")

    assert result.blocked is True


async def test_redis_failure_fails_open_the_ip_cap(monkeypatch):
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")
    _patch_gateway(monkeypatch, app_settings={"demo_query_limit": 15, "demo_query_limit_per_ip_per_day": 1})
    _patch_redis(monkeypatch, _FakeRedisClient(raise_on_incr=True))

    result = await demo_query_limiter.check_and_record("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4")

    assert result.blocked is False


async def test_postgres_failure_fails_open_entirely(monkeypatch):
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")

    class _BrokenDemoVisitorStore(FakeDemoVisitorStore):
        async def record_query(self, *args, **kwargs):
            raise ConnectionError("postgres unreachable")

    _patch_gateway(monkeypatch, demo_visitors=_BrokenDemoVisitorStore())
    _patch_redis(monkeypatch)

    result = await demo_query_limiter.check_and_record("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4")

    assert result.blocked is False
    assert result.to_response_dict() is None


async def test_user_session_id_aggregates_across_different_conversation_ids(monkeypatch):
    """Phase 296 - the whole point of user_session_id: a visitor who starts
    a new conversation (new conversation_id) mid-visit must not reset the
    cap, as long as the same user_session_id is sent both times."""
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")
    _patch_gateway(monkeypatch, app_settings={"demo_query_limit": 2, "demo_query_limit_per_ip_per_day": 50})
    _patch_redis(monkeypatch)

    await demo_query_limiter.check_and_record(
        "conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4", user_session_id="sess-1",
    )
    result = await demo_query_limiter.check_and_record(
        "conv-2", "EMP052", "Eddy Employee", "employee", "1.2.3.4", user_session_id="sess-1",
    )

    assert result.blocked is False
    assert result.query_count == 2
    result = await demo_query_limiter.check_and_record(
        "conv-3", "EMP052", "Eddy Employee", "employee", "1.2.3.4", user_session_id="sess-1",
    )
    assert result.blocked is True


async def test_user_session_id_absent_falls_back_to_conversation_id(monkeypatch):
    """A caller that never sends user_session_id (old UI build, direct API
    caller) keeps today's exact per-conversation behavior - starting a new
    conversation_id resets the cap for that caller, unchanged."""
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")
    _patch_gateway(monkeypatch, app_settings={"demo_query_limit": 2, "demo_query_limit_per_ip_per_day": 50})
    _patch_redis(monkeypatch)

    await demo_query_limiter.check_and_record("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4")
    await demo_query_limiter.check_and_record("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4")
    result = await demo_query_limiter.check_and_record("conv-2", "EMP052", "Eddy Employee", "employee", "1.2.3.4")

    assert result.blocked is False
    assert result.query_count == 1


async def test_guest_user_name_is_recorded(monkeypatch):
    monkeypatch.setenv("APP_DEMO_QUERY_LIMIT_ENABLED", "true")
    demo_visitors = FakeDemoVisitorStore()
    gateway = _patch_gateway(monkeypatch, app_settings={"demo_query_limit": 15}, demo_visitors=demo_visitors)
    _patch_redis(monkeypatch)

    await demo_query_limiter.check_and_record(
        "conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4",
        user_session_id="sess-1", guest_user_name="Taylor Friend",
    )

    rows = await gateway.demo_visitor_store().list_visitors()
    assert rows[0]["guest_user_name"] == "Taylor Friend"
