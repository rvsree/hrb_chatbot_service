"""Phase 283: FinopsSnapshotStore - direct against the store, _connect()
faked, same zero-real-network-call pattern as test_demo_visitor_store.py."""

from datetime import date, datetime, timezone

from src.hrb_chatbot.common.clients.db_client.finops_snapshot_store import FinopsSnapshotStore


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
    store = FinopsSnapshotStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")
    store._table_ready = True  # skip _ensure_table's own CREATE SCHEMA/TABLE calls
    conn = _FakeConnection(result)
    monkeypatch.setattr(store, "_connect", lambda: conn)
    return store, conn


async def test_insert_snapshot_converts_timestamps_and_returns_the_row(monkeypatch):
    row = {
        "id": 1, "provider": "aws",
        "captured_at": datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc),
        "period_start": date(2026, 10, 1), "period_end": date(2026, 10, 31),
        "total_cost": 17.35, "cost_breakdown": {"ECS": 12.35, "Route53": 5.0}, "created_by": "ADM001",
    }
    store, conn = _store_with_fake_connection(monkeypatch, row)

    result = await store.insert_snapshot(
        provider="aws", period_start="2026-10-01", period_end="2026-10-31",
        total_cost=17.35, cost_breakdown={"ECS": 12.35, "Route53": 5.0}, created_by="ADM001",
    )

    assert result["id"] == 1
    assert result["captured_at"] == "2026-10-31T12:00:00+00:00"
    assert result["period_start"] == "2026-10-01"
    assert result["period_end"] == "2026-10-31"
    assert conn.committed is True
    _sql, params = conn.cur.queries[0]
    assert params[0] == "aws"
    assert params[3] == 17.35


async def test_insert_snapshot_allows_a_null_total_cost(monkeypatch):
    row = {
        "id": 2, "provider": "langsmith",
        "captured_at": datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc),
        "period_start": date(2026, 10, 1), "period_end": date(2026, 10, 31),
        "total_cost": None, "cost_breakdown": {"2026-10-01": 5}, "created_by": "ADM001",
    }
    store, _conn = _store_with_fake_connection(monkeypatch, row)

    result = await store.insert_snapshot(
        provider="langsmith", period_start="2026-10-01", period_end="2026-10-31",
        total_cost=None, cost_breakdown={"2026-10-01": 5}, created_by="ADM001",
    )

    assert result["total_cost"] is None


async def test_get_latest_snapshot_returns_none_when_never_fetched(monkeypatch):
    store, _conn = _store_with_fake_connection(monkeypatch, None)

    result = await store.get_latest_snapshot("aws")

    assert result is None


async def test_get_latest_snapshot_converts_timestamps(monkeypatch):
    row = {
        "id": 3, "provider": "aws",
        "captured_at": datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc),
        "period_start": date(2026, 10, 1), "period_end": date(2026, 10, 31),
        "total_cost": 17.35, "cost_breakdown": {}, "created_by": "ADM001",
    }
    store, _conn = _store_with_fake_connection(monkeypatch, row)

    result = await store.get_latest_snapshot("aws")

    assert result["period_start"] == "2026-10-01"


async def test_list_history_converts_every_row(monkeypatch):
    rows = [
        {
            "id": 1, "provider": "aws",
            "captured_at": datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
            "period_start": date(2026, 10, 1), "period_end": date(2026, 10, 31),
            "total_cost": 10.0, "cost_breakdown": {}, "created_by": "ADM001",
        },
        {
            "id": 2, "provider": "aws",
            "captured_at": datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc),
            "period_start": date(2026, 10, 1), "period_end": date(2026, 10, 31),
            "total_cost": 12.0, "cost_breakdown": {}, "created_by": "ADM001",
        },
    ]
    store, conn = _store_with_fake_connection(monkeypatch, rows)

    result = await store.list_history("aws", limit=30)

    assert len(result) == 2
    assert result[0]["captured_at"] == "2026-10-01T00:00:00+00:00"
    _sql, params = conn.cur.queries[0]
    assert params == ("aws", 30)
