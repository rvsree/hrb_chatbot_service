"""Phase 262 - records "someone with a real identity is using this app
right now", for a future scheduled Lambda's idle-timeout auto-pause check.
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
write per ~60s, not one per request."""

import asyncio
import time
from datetime import UTC, datetime

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("activity_tracker")

ACTIVITY_SETTING_KEY = "active_user_last_seen_at"
DEBOUNCE_SECONDS = 60

_last_attempt_monotonic: float = 0.0


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
