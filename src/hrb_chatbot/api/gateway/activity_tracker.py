"""Phase 262 - records "someone with a real identity is using this app
right now", for a scheduled Lambda's idle-timeout auto-pause check.
Hooked into require_role() (not a new ASGI middleware) deliberately -
every protected route already funnels through require_role() to resolve
identity, so this is the one chokepoint that covers login, chat, HITL
actions, and every admin route uniformly, without re-parsing request
bodies or touching the request stream. Reuses app_settings_store (Phase
257) instead of a new table - a timestamp fits its existing JSONB value
column fine.

Fire-and-forget by design: the write happens as a background asyncio task,
never awaited by require_role() itself, so a slow or failing Postgres
write can never add latency to - or break - the real request it's riding
along on. Debounced in-process so a burst of requests only attempts one
write per ~60s, not one per request.

Phase 286 adds a second, separate signal below - a per-identity Redis
presence set, answering "how many distinct people right now," which the
single global timestamp above genuinely cannot answer. Deliberately kept
apart from the Postgres-backed signal above - Phase 262's own Lambda and
tests read only ACTIVITY_SETTING_KEY and are untouched by this addition."""

import asyncio
import time
from datetime import UTC, datetime

import redis.asyncio as redis

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("activity_tracker")

ACTIVITY_SETTING_KEY = "active_user_last_seen_at"
DEBOUNCE_SECONDS = 60

_last_attempt_monotonic: float = 0.0

# Phase 286 - a session counts as "active" within this window. Deliberately
# much shorter than the 60-minute idle-timeout threshold (Phase 262) - this
# answers "is anyone here right now," not "has it been broadly idle."
PRESENCE_SET_KEY = "active_sessions"
PRESENCE_WINDOW_SECONDS = 180
_PRESENCE_DEBOUNCE_SECONDS = 60

_last_presence_attempt_by_employee: dict[str, float] = {}
_redis_client: redis.Redis | None = None


def _get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(read_setting(None, "REDIS_URL"), decode_responses=True)
    return _redis_client


async def _record_session_presence(employee_id: str) -> None:
    try:
        await _get_redis_client().zadd(PRESENCE_SET_KEY, {employee_id: time.time()})
    except Exception as error:
        logger.debug("Session presence write failed, skipping this tick: %s", error)


def record_session_presence_if_due(employee_id: str) -> None:
    """Same fire-and-forget, debounced-in-process pattern as
    track_activity_if_due() above, but keyed per employee_id - several
    distinct identities can be active at once, each needing its own
    debounce window, unlike the single shared timer above."""
    now = time.monotonic()
    last_attempt = _last_presence_attempt_by_employee.get(employee_id, 0.0)
    if now - last_attempt < _PRESENCE_DEBOUNCE_SECONDS:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running event loop - skipping presence tracking tick")
        return
    _last_presence_attempt_by_employee[employee_id] = now
    loop.create_task(_record_session_presence(employee_id))


async def remove_session_presence(employee_id: str) -> None:
    """Awaited directly (not fire-and-forget) - the sign-out endpoint needs
    this removal to have actually happened before it checks whether anyone
    else is still active, or it would see its own now-stale entry."""
    try:
        await _get_redis_client().zrem(PRESENCE_SET_KEY, employee_id)
    except Exception as error:
        logger.debug("Session presence removal failed: %s", error)


async def count_other_active_sessions(excluding_employee_id: str) -> int:
    """How many *other* distinct identities have been active within
    PRESENCE_WINDOW_SECONDS. Fails open toward "someone else might be
    active" (returns a nonzero count) on any Redis error - the sign-out
    accelerant must never pause on an uncertain read, same fail-closed
    philosophy Phase 262's own Lambda already applies to AppRunner calls."""
    try:
        client = _get_redis_client()
        cutoff = time.time() - PRESENCE_WINDOW_SECONDS
        await client.zremrangebyscore(PRESENCE_SET_KEY, "-inf", cutoff)
        members = await client.zrangebyscore(PRESENCE_SET_KEY, cutoff, "+inf")
    except Exception as error:
        logger.debug("Could not read session presence, assuming others may be active: %s", error)
        return 1
    return len([member for member in members if member != excluding_employee_id])


async def _record_activity() -> None:
    try:
        timestamp = datetime.now(UTC).isoformat()
        await get_db_gateway().app_settings_store().set_setting(ACTIVITY_SETTING_KEY, timestamp)
    except Exception as error:
        # Never let a failed activity write be visible anywhere - this is
        # a background task with nothing awaiting it, so a raised
        # exception here would only ever become an unhandled asyncio
        # warning in the logs, not a broken request. Logged at debug
        # since a missed tick is harmless (the idle-check Lambda just
        # uses the next real request's timestamp instead).
        logger.debug("Activity tracker write failed, skipping this tick: %s", error)


def track_activity_if_due() -> None:
    """Call this once a real identity has been confirmed (inside
    require_role(), after every check passes). Cheap no-op most calls -
    only schedules a write when the debounce window has actually
    elapsed."""
    global _last_attempt_monotonic
    now = time.monotonic()
    if now - _last_attempt_monotonic < DEBOUNCE_SECONDS:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop (e.g. called from a sync test context) -
        # activity tracking is best-effort, never worth raising over. Not
        # updating _last_attempt_monotonic here, so a real request later
        # in the same process still gets a fair chance to record.
        logger.debug("No running event loop - skipping activity tracking tick")
        return
    _last_attempt_monotonic = now
    loop.create_task(_record_activity())
