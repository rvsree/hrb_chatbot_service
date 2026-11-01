"""Tests for activity_tracker.py (Phase 262) - the require_role() hook that
records real app usage for the planned idle-timeout auto-pause Lambda."""

import asyncio
import time

from src.hrb_chatbot.api.gateway import activity_tracker


def test_track_activity_if_due_schedules_a_write(monkeypatch):
    gateway = _FakeGateway()
    monkeypatch.setattr(activity_tracker, "get_db_gateway", lambda: gateway)
    monkeypatch.setattr(activity_tracker, "_last_attempt_monotonic", 0.0)

    async def run():
        activity_tracker.track_activity_if_due()
        await asyncio.sleep(0)  # let the scheduled task actually run

    asyncio.run(run())

    assert activity_tracker.ACTIVITY_SETTING_KEY in gateway.app_settings_store()._settings


def test_track_activity_if_due_is_debounced(monkeypatch):
    gateway = _FakeGateway()
    monkeypatch.setattr(activity_tracker, "get_db_gateway", lambda: gateway)
    monkeypatch.setattr(activity_tracker, "_last_attempt_monotonic", 0.0)

    async def run():
        activity_tracker.track_activity_if_due()  # schedules a write
        first_attempt_time = activity_tracker._last_attempt_monotonic
        activity_tracker.track_activity_if_due()  # within the debounce window - no-op
        await asyncio.sleep(0)
        return first_attempt_time

    first_attempt_time = asyncio.run(run())

    assert gateway.app_settings_store()._settings[activity_tracker.ACTIVITY_SETTING_KEY] is not None
    # second call was debounced - _last_attempt_monotonic never advanced past the first call
    assert activity_tracker._last_attempt_monotonic == first_attempt_time


def test_track_activity_if_due_with_no_running_loop_does_not_raise(monkeypatch):
    monkeypatch.setattr(activity_tracker, "_last_attempt_monotonic", 0.0)

    activity_tracker.track_activity_if_due()  # called from sync test context - no event loop


class _FakeAppSettingsStore:
    def __init__(self):
        self._settings = {}

    async def set_setting(self, key, value, updated_by=None):
        self._settings[key] = value


class _FakeGateway:
    def __init__(self):
        self._store = _FakeAppSettingsStore()

    def app_settings_store(self):
        return self._store


# Phase 286 - session presence (count_other_active_sessions/
# remove_session_presence/record_session_presence_if_due). A tiny fake
# Redis sorted set - no real Redis connection, matching this project's
# existing fake-based convention.


def _as_float_bound(value):
    """Real Redis accepts "-inf"/"+inf" sentinel strings for an unbounded
    range - this fake must handle those too, or a real call shape (like
    count_other_active_sessions' own zrangebyscore(cutoff, "+inf")) would
    TypeError on a float-vs-str comparison. That TypeError was silently
    swallowed by the real function's own fail-open except-Exception
    before this fix, masking the bug as a false-positive test pass."""
    if value == "+inf":
        return float("inf")
    if value == "-inf":
        return float("-inf")
    return value


class _FakeRedisSortedSet:
    def __init__(self):
        self._scores: dict[str, float] = {}

    async def zadd(self, key, mapping):
        self._scores.update(mapping)

    async def zrem(self, key, member):
        self._scores.pop(member, None)

    async def zremrangebyscore(self, key, min_score, max_score):
        min_score, max_score = _as_float_bound(min_score), _as_float_bound(max_score)
        self._scores = {member: score for member, score in self._scores.items() if not (min_score <= score <= max_score)}

    async def zrangebyscore(self, key, min_score, max_score):
        min_score, max_score = _as_float_bound(min_score), _as_float_bound(max_score)
        return [member for member, score in self._scores.items() if min_score <= score <= max_score]


class _RaisingRedisClient:
    async def zrangebyscore(self, *args, **kwargs):
        raise ConnectionError("redis unreachable")

    async def zremrangebyscore(self, *args, **kwargs):
        raise ConnectionError("redis unreachable")


def test_record_session_presence_if_due_schedules_a_zadd(monkeypatch):
    fake_redis = _FakeRedisSortedSet()
    monkeypatch.setattr(activity_tracker, "_get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(activity_tracker, "_last_presence_attempt_by_employee", {})

    async def run():
        activity_tracker.record_session_presence_if_due("EMP052")
        await asyncio.sleep(0)

    asyncio.run(run())

    assert "EMP052" in fake_redis._scores


def test_record_session_presence_if_due_is_debounced_per_employee(monkeypatch):
    fake_redis = _FakeRedisSortedSet()
    monkeypatch.setattr(activity_tracker, "_get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(activity_tracker, "_last_presence_attempt_by_employee", {})

    async def run():
        activity_tracker.record_session_presence_if_due("EMP052")
        await asyncio.sleep(0)
        first_attempt = activity_tracker._last_presence_attempt_by_employee["EMP052"]
        activity_tracker.record_session_presence_if_due("EMP052")  # within debounce window - no-op
        # A different employee is NOT debounced by EMP052's own timer.
        activity_tracker.record_session_presence_if_due("EMP053")
        await asyncio.sleep(0)
        return first_attempt

    first_attempt = asyncio.run(run())

    assert activity_tracker._last_presence_attempt_by_employee["EMP052"] == first_attempt
    assert "EMP053" in fake_redis._scores


async def test_remove_session_presence_removes_the_member(monkeypatch):
    fake_redis = _FakeRedisSortedSet()
    fake_redis._scores["EMP052"] = 1000.0
    monkeypatch.setattr(activity_tracker, "_get_redis_client", lambda: fake_redis)

    await activity_tracker.remove_session_presence("EMP052")

    assert "EMP052" not in fake_redis._scores


async def test_count_other_active_sessions_excludes_the_asking_employee(monkeypatch):
    fake_redis = _FakeRedisSortedSet()
    now = time.time()
    fake_redis._scores = {"EMP052": now, "EMP053": now}
    monkeypatch.setattr(activity_tracker, "_get_redis_client", lambda: fake_redis)

    count = await activity_tracker.count_other_active_sessions(excluding_employee_id="EMP052")

    assert count == 1


async def test_count_other_active_sessions_is_zero_when_only_the_asker_was_present(monkeypatch):
    fake_redis = _FakeRedisSortedSet()
    fake_redis._scores = {"EMP052": time.time()}
    monkeypatch.setattr(activity_tracker, "_get_redis_client", lambda: fake_redis)

    count = await activity_tracker.count_other_active_sessions(excluding_employee_id="EMP052")

    assert count == 0


async def test_count_other_active_sessions_ignores_stale_entries_past_the_window(monkeypatch):
    fake_redis = _FakeRedisSortedSet()
    stale_time = time.time() - activity_tracker.PRESENCE_WINDOW_SECONDS - 60
    fake_redis._scores = {"EMP053": stale_time}
    monkeypatch.setattr(activity_tracker, "_get_redis_client", lambda: fake_redis)

    count = await activity_tracker.count_other_active_sessions(excluding_employee_id="EMP052")

    assert count == 0


async def test_count_other_active_sessions_fails_open_on_redis_error(monkeypatch):
    monkeypatch.setattr(activity_tracker, "_get_redis_client", lambda: _RaisingRedisClient())

    count = await activity_tracker.count_other_active_sessions(excluding_employee_id="EMP052")

    assert count == 1  # fails open toward "someone else might be active" - never pause on an uncertain read
