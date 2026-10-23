"""Phase 104: FeedbackStore mirrors ConversationStore's own tests - same
NUL-byte defense (Phase 97) on question/answer, and its own datetime->str
conversion for TIMESTAMPTZ rows. Direct against FeedbackStore - no real
Postgres, _connect() faked, matching this project's zero-network-call test
guarantee."""

from datetime import datetime, timezone

from src.hrb_chatbot.common.clients.db_client.feedback_store import FeedbackStore


class _FakeConnection:
    """Records every (sql, params) pair passed to execute() - enough to
    assert what would have reached Postgres, without a real connection."""

    def __init__(self, recorded_calls, fetchone_result=(1,)):
        self._recorded_calls = recorded_calls
        self._fetchone_result = fetchone_result

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self._recorded_calls.append((sql, params))
        return self

    def fetchone(self):
        return self._fetchone_result

    def commit(self):
        pass


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeListConnection:
    """Stands in for the connection used by _list_feedback_sync(), which
    opens its own cursor(row_factory=...) instead of calling execute()
    directly on the connection."""

    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def cursor(self, row_factory=None):
        return _FakeCursor(self._rows)


def _store_with_fake_connection(monkeypatch, fetchone_result=(1,)):
    store = FeedbackStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")
    store._table_ready = True  # skip _ensure_table's own CREATE TABLE/INDEX calls
    recorded_calls = []
    monkeypatch.setattr(store, "_connect", lambda: _FakeConnection(recorded_calls, fetchone_result))
    return store, recorded_calls


async def test_a_nul_byte_in_question_or_answer_is_stripped_before_the_insert(monkeypatch):
    store, recorded_calls = _store_with_fake_connection(monkeypatch)

    await store.save_feedback(
        "EMP052", "conv-1", "msg-1", "helpful", ["accurate"], None,
        "What dental plans are o\x00ered?", "JPMorgan Chase o\x00ers two dental plan options",
    )

    assert len(recorded_calls) == 1
    _sql, params = recorded_calls[0]
    question, answer = params[6], params[7]
    assert "\x00" not in question
    assert "\x00" not in answer
    assert question == "What dental plans are oered?"
    assert answer == "JPMorgan Chase oers two dental plan options"


async def test_question_and_answer_with_no_nul_byte_are_unchanged(monkeypatch):
    store, recorded_calls = _store_with_fake_connection(monkeypatch)

    await store.save_feedback(
        "EMP052", "conv-1", "msg-1", "helpful", ["accurate"], None,
        "What dental plans are offered?", "Two dental plan options.",
    )

    _sql, params = recorded_calls[0]
    assert params[6] == "What dental plans are offered?"
    assert params[7] == "Two dental plan options."


async def test_list_feedback_converts_timestamptz_datetime_to_isoformat_string(monkeypatch):
    store = FeedbackStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")
    store._table_ready = True
    row = {
        "id": 1,
        "employee_id": "EMP052",
        "conversation_id": "conv-1",
        "message_id": "msg-1",
        "vote": "helpful",
        "reason_tags": "[\"accurate\"]",
        "notes": None,
        "question": "What dental plans are offered?",
        "answer": "Two dental plan options.",
        "created_at": datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc),
    }
    monkeypatch.setattr(store, "_connect", lambda: _FakeListConnection([row]))

    rows = await store.list_feedback("EMP052")

    assert len(rows) == 1
    assert rows[0]["created_at"] == "2026-10-06T12:00:00+00:00"
    assert rows[0]["reason_tags"] == ["accurate"]


async def test_get_latest_feedback_for_conversation_with_no_conversation_id_skips_the_connection(monkeypatch):
    """Phase 248 - None is returned before _ensure_table()/_connect() are
    ever called, same short-circuit stm_cache.py's own callers rely on."""
    store = FeedbackStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")

    def _should_not_connect():
        raise AssertionError("_connect() must not be called when conversation_id is falsy")

    monkeypatch.setattr(store, "_connect", _should_not_connect)

    result = await store.get_latest_feedback_for_conversation(None)

    assert result is None


async def test_get_latest_feedback_for_conversation_converts_timestamptz_and_reason_tags(monkeypatch):
    store = FeedbackStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")
    store._table_ready = True
    row = {
        "id": 2,
        "employee_id": "EMP052",
        "conversation_id": "conv-1",
        "message_id": "msg-2",
        "vote": "helpful",
        "reason_tags": "[\"accurate\"]",
        "notes": None,
        "question": "What dental plans are offered?",
        "answer": "Two dental plan options.",
        "created_at": datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc),
    }
    monkeypatch.setattr(store, "_connect", lambda: _FakeListConnection([row]))

    result = await store.get_latest_feedback_for_conversation("conv-1")

    assert result["created_at"] == "2026-10-06T12:00:00+00:00"
    assert result["reason_tags"] == ["accurate"]


async def test_get_latest_feedback_for_conversation_with_no_rows_returns_none(monkeypatch):
    store = FeedbackStore(host="fake-host", port="5432", db_name="fake_db", user="fake_user", password="fake_pw")
    store._table_ready = True
    monkeypatch.setattr(store, "_connect", lambda: _FakeListConnection([]))

    result = await store.get_latest_feedback_for_conversation("conv-1")

    assert result is None
