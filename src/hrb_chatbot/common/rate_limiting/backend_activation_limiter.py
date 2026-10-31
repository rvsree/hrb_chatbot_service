"""Phase 284 - per-IP-per-day cap on the public backend-activation resume
route; a separate counter from demo_query_limiter.py's own IP cap."""

import datetime

import redis.asyncio as redis

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("backend_activation_limiter")

IP_LIMIT_KEY_PREFIX = "backend_activation_ip_limit:"

_redis_client: redis.Redis | None = None


def _get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(read_setting(None, "REDIS_URL"), decode_responses=True)
    return _redis_client


async def _check_ip_daily_cap(ip_address: str | None, per_ip_limit: int) -> bool:
    """Returns True if the IP is still under its daily resume cap (and
    records this attempt). Fails open (returns True) on any Redis error."""
    if not ip_address:
        return True
    key = f"{IP_LIMIT_KEY_PREFIX}{ip_address}:{datetime.date.today().isoformat()}"
    try:
        client = _get_redis_client()
        count = await client.incr(key)
        if count == 1:
            # First hit today for this IP - expire at the end of the day,
            # not a rolling window (simplest correct TTL for a daily cap).
            seconds_until_midnight = 86400 - (
                datetime.datetime.now().hour * 3600
                + datetime.datetime.now().minute * 60
                + datetime.datetime.now().second
            )
            await client.expire(key, max(seconds_until_midnight, 60))
    except Exception as error:
        logger.warning("[backend_activation_limiter] Redis unreachable for IP cap, allowing through: %s", error)
        return True
    return count <= per_ip_limit


async def check_and_record(ip_address: str | None) -> bool:
    """Call only when at least one service needs resuming - a no-op visit
    must never burn a visitor's daily quota."""
    per_ip_limit = await get_db_gateway().app_settings_store().get_setting(
        "backend_activation_resume_limit_per_ip_per_day", 5
    )
    return await _check_ip_daily_cap(ip_address, per_ip_limit)
