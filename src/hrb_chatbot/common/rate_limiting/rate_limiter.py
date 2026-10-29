"""Redis-backed rate limiter (Phase 84), fixed window via INCR+EXPIRE -
replaces the Phase-1 in-memory version, whose own docstring already named
this exact fix: the in-memory dict only worked single-process, and App
Runner's real auto-scaling (confirmed up to 25 instances) meant the
configured limit silently multiplied by however many instances were
running."""

import redis.asyncio as redis
from fastapi import HTTPException, Request

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger
from src.hrb_chatbot.common.utils.request_ip import resolve_client_ip

logger = get_logger("rate_limiter")

KEY_PREFIX = "ratelimit:"


def _setting_is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes")


class RateLimiter:
    """Counts requests per client key in Redis, raising HTTPException(429) past the configured limit."""

    def __init__(
        self,
        enabled: str | None = None,
        max_requests: str | None = None,
        window_seconds: str | None = None,
        redis_url: str | None = None,
    ):
        self.enabled = _setting_is_true(read_setting(enabled, "APP_RATE_LIMITING", "false"))
        self.max_requests = int(read_setting(max_requests, "APP_RATE_LIMIT_REQUESTS", "100"))
        self.window_seconds = int(read_setting(window_seconds, "APP_RATE_LIMIT_DURATION", "30"))
        self.url = read_setting(redis_url, "REDIS_URL")

        self._client: redis.Redis | None = None

    def _client_or_raise(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(self.url, decode_responses=True)
        return self._client

    async def check(self, client_key: str) -> None:
        """Record one request from client_key - raises HTTPException(429) if this pushes them over the limit."""
        if not self.enabled:
            return

        key = KEY_PREFIX + client_key

        try:
            client = self._client_or_raise()
            count = await client.incr(key)
            if count == 1:
                # First request in a fresh window - set its expiry once, not on every increment.
                await client.expire(key, self.window_seconds)
        except Exception as error:
            # Fail open, not closed - a rate limiter that can't reach its
            # own backing store must never take the whole app down with it.
            # Found live, 2026-10-05: with no REDIS_URL configured yet, this
            # exact path raised a ValueError on every single request.
            logger.warning("[rate_limit] Redis unreachable, allowing request through: %s", error)
            return

        if count > self.max_requests:
            ttl = await client.ttl(key)
            retry_after_seconds = max(1, ttl)

            logger.warning(
                "[rate_limit] %s exceeded %d requests per %ds window",
                client_key,
                self.max_requests,
                self.window_seconds,
            )
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded: max {self.max_requests} requests per "
                    f"{self.window_seconds} seconds. Try again in {retry_after_seconds}s."
                ),
                headers={"Retry-After": str(retry_after_seconds)},
            )


# Same lazy-singleton pattern as ClientGateway/DBGateway - one shared
# limiter for the whole process.
_shared_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Return the one shared RateLimiter, creating it on the first call."""
    global _shared_rate_limiter
    if _shared_rate_limiter is None:
        _shared_rate_limiter = RateLimiter()
    return _shared_rate_limiter


def reset_rate_limiter() -> None:
    """Throw away the shared limiter so the next call builds a fresh one - only needed in tests."""
    global _shared_rate_limiter
    _shared_rate_limiter = None


async def enforce_rate_limit(request: Request) -> None:
    """Call directly from a route body to rate-limit it - keys on the caller's
    real IP (Phase 266 - resolve_client_ip(), not the bare request.client.host
    this used before: behind a reverse proxy like AWS App Runner, that was the
    proxy's own address, so every real caller behind it would have keyed to
    the same bucket), or "unknown"."""
    client_key = resolve_client_ip(request) or "unknown"
    await get_rate_limiter().check(client_key)
