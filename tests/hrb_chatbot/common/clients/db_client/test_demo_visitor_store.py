"""Phase 265: DemoVisitorStore - direct against the store, _connect() faked,
same zero-real-network-call pattern as test_feedback_store.py."""

from datetime import datetime, timezone

from src.hrb_chatbot.common.clients.db_client.demo_visitor_store import DemoVisitorStore


class _FakeCursor:
    def __init__(self, result):
        self._result = result
        self.queries: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))

    def fetchone(self):
        return self._result

    def fetchall(self):
        return self._result


class _FakeConnection:
    def __init__(self, result):
        self.cur = _FakeCursor(result)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        pass  # _ensure_table_sync's own CREATE SCHEMA/TABLE calls

    def cursor(self, row_factory=None):
        return self.cur

    def commit(self):
        self.committed = True


def _store_with_fake_connection(monkeypatch, result):
    store = DemoVisitorStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")
    store._table_ready = True  # skip _ensure_table's own CREATE SCHEMA/TABLE calls
    conn = _FakeConnection(result)
    monkeypatch.setattr(store, "_connect", lambda: conn)
    return store, conn


async def test_record_query_returns_counts_from_the_upsert(monkeypatch):
    store, conn = _store_with_fake_connection(monkeypatch, {"query_count": 3, "waiver_count": 0})

    result = await store.record_query(
        conversation_id="conv-1", employee_id="EMP052", full_name="Eddy Employee",
        role="employee", ip_address="1.2.3.4", timezone="America/New_York",
    )

    assert result == {"query_count": 3, "waiver_count": 0}
    assert conn.committed is True
    _sql, params = conn.cur.queries[0]
    assert params == ("conv-1", "EMP052", "Eddy Employee", "employee", "1.2.3.4", "America/New_York")


async def test_grant_waiver_adds_the_increment_and_returns_new_counts(monkeypatch):
    store, conn = _store_with_fake_connection(
        monkeypatch, {"conversation_id": "conv-1", "query_count": 10, "waiver_count": 15}
    )

    result = await store.grant_waiver("conv-1", increment=15)

    assert result == {"conversation_id": "conv-1", "query_count": 10, "waiver_count": 15}
    assert conn.committed is True
    _sql, params = conn.cur.queries[0]
    assert params == ("conv-1", 15, 15)


async def test_grant_waiver_defaults_to_an_increment_of_fifteen(monkeypatch):
    store, conn = _store_with_fake_connection(
        monkeypatch, {"conversation_id": "conv-1", "query_count": 0, "waiver_count": 15}
    )

    await store.grant_waiver("conv-1")

    _sql, params = conn.cur.queries[0]
    assert params == ("conv-1", 15, 15)


async def test_list_visitors_converts_timestamps_to_isoformat_strings(monkeypatch):
    row = {
        "conversation_id": "conv-1", "employee_id": "EMP052", "full_name": "Eddy Employee",
        "role": "employee", "ip_address": "1.2.3.4", "timezone": "America/New_York",
        "query_count": 5, "waiver_count": 0,
        "last_query_at": datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc),
        "created_at": datetime(2026, 10, 28, 11, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc),
    }
    store, _conn = _store_with_fake_connection(monkeypatch, [row])

    rows = await store.list_visitors()

    assert len(rows) == 1
    assert rows[0]["last_query_at"] == "2026-10-28T12:00:00+00:00"
    assert rows[0]["created_at"] == "2026-10-28T11:00:00+00:00"
    assert rows[0]["updated_at"] == "2026-10-28T12:00:00+00:00"


async def test_list_visitors_with_no_last_query_at_leaves_it_none(monkeypatch):
    row = {
        "conversation_id": "conv-1", "employee_id": None, "full_name": None, "role": None,
        "ip_address": None, "timezone": None, "query_count": 0, "waiver_count": 0,
        "last_query_at": None,
        "created_at": datetime(2026, 10, 28, 11, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 28, 11, 0, 0, tzinfo=timezone.utc),
    }
    store, _conn = _store_with_fake_connection(monkeypatch, [row])

    rows = await store.list_visitors()

    assert rows[0]["last_query_at"] is None
