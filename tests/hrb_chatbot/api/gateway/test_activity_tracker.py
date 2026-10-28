"""Tests for activity_tracker.py (Phase 262) - the require_role() hook that
records real app usage for the planned idle-timeout auto-pause Lambda."""

import asyncio

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
