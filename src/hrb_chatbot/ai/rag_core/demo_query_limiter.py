"""Phase 265 - caps how many queries an anonymous demo visitor can make,
with a harder per-IP-per-day backstop (identity is self-asserted and free
to change per conversation; IP isn't) and an admin-grantable waiver on top.
Fails open on any storage error - a cost-control gap on a rare infra
hiccup is acceptable; silently blocking a legitimate visitor (or the
user's own live interview demo) over an unrelated Redis/Postgres blip is
not, same principle rate_limiter.py already applies to itself."""

import datetime

import redis.asyncio as redis

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.enums import Role
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("demo_query_limiter")

IP_LIMIT_KEY_PREFIX = "demo_ip_limit:"
EXEMPT_ROLES = {Role.ADMIN, Role.EMPLOYEE_ADMIN, Role.HR_SUPPORT}


def _is_enabled() -> bool:
    """Same off-by-default-in-tests pattern as rate_limiter.py's own
    APP_RATE_LIMITING - without this, every route test that passes
    through run_guarded_pipeline() would try a real Redis/Postgres
    connection (no REDIS_URL/POSTGRES_DB_HOST in a test environment) and
    hang on connect-timeout instead of failing fast. conftest.py forces
    this to "false" the same way it already does for rate limiting."""
    return str(read_setting(None, "APP_DEMO_QUERY_LIMIT_ENABLED", "false")).strip().lower() in ("1", "true", "yes")

_redis_client: redis.Redis | None = None


def _get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(read_setting(None, "REDIS_URL"), decode_responses=True)
    return _redis_client


async def _check_ip_daily_cap(ip_address: str | None, per_ip_limit: int) -> bool:
    """Returns True if the IP is still under its daily cap (and records
    this attempt against it). Fails open (returns True) on any Redis
    error - this is a backstop, not the primary control."""
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
        logger.warning("[demo_query_limiter] Redis unreachable for IP cap, allowing through: %s", error)
        return True
    return count <= per_ip_limit


class DemoLimitResult:
    def __init__(self, blocked: bool, query_count: int | None, effective_limit: int | None, remaining: int | None):
        self.blocked = blocked
        self.query_count = query_count
        self.effective_limit = effective_limit
        self.remaining = remaining

    def to_response_dict(self) -> dict | None:
        if self.effective_limit is None:
            return None
        return {
            "query_count": self.query_count,
            "effective_limit": self.effective_limit,
            "remaining": max(0, self.remaining),
        }


async def check_and_record(
    conversation_id: str | None,
    employee_id: str | None,
    full_name: str | None,
    role: str | None,
    ip_address: str | None,
    timezone: str | None = None,
) -> DemoLimitResult:
    """Call once per query, after the input guardrail has already passed
    (a blocked query never reaches here, so it never counts against the
    limit) and before generation starts (so an over-limit visitor never
    triggers a wasted LLM call). ADMIN/EMPLOYEE_ADMIN/HR_SUPPORT are
    exempt entirely - self-asserted role, same caveat as the rest of this
    project's RBAC, not a cryptographic guarantee, but a casual anonymous
    visitor won't think to claim it."""
    if not _is_enabled() or role in EXEMPT_ROLES or not conversation_id:
        return DemoLimitResult(blocked=False, query_count=None, effective_limit=None, remaining=None)

    gateway = get_db_gateway()
    per_conversation_limit = await gateway.app_settings_store().get_setting("demo_query_limit", 15)
    per_ip_limit = await gateway.app_settings_store().get_setting("demo_query_limit_per_ip_per_day", 50)

    under_ip_cap = await _check_ip_daily_cap(ip_address, per_ip_limit)

    try:
        result = await gateway.demo_visitor_store().record_query(
            conversation_id=conversation_id,
            employee_id=employee_id,
            full_name=full_name,
            role=role,
            ip_address=ip_address,
            timezone=timezone,
        )
    except Exception as error:
        logger.warning("[demo_query_limiter] Could not record demo query, allowing through: %s", error)
        return DemoLimitResult(blocked=False, query_count=None, effective_limit=None, remaining=None)

    query_count = result["query_count"]
    waiver_count = result["waiver_count"]
    effective_limit = per_conversation_limit + waiver_count
    remaining = effective_limit - query_count

    blocked = (not under_ip_cap) or (query_count > effective_limit)
    return DemoLimitResult(blocked=blocked, query_count=query_count, effective_limit=effective_limit, remaining=remaining)


class DemoQueryLimitExceededError(Exception):
    """Raised when a visitor has exhausted their demo query limit - the
    route turns this into a 429 with code DEMO_QUERY_LIMIT_REACHED, a
    distinct error from any guardrail block (this is a cost cap, not a
    safety check, and conflating the two would mislead a legitimate
    visitor)."""
