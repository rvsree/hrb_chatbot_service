"""Redis-backed read-through cache for Admin Dashboard list views (Phase
276, 2026-10-30, user-directed - "loading data across is not performant
enough"). Separate key namespace/TTL from answer_cache.py's own RAG-answer
cache (Phase 84/78) - a completely different kind of data (dashboard list
reads vs RAG query/answer pairs) - same fail-open discipline: a down Redis
degrades to "no caching", never a broken request. 24h TTL, with a
force_refresh escape hatch each cached route exposes for its own Refresh
button - see api/admin/manage_admin.py's cached_admin_list()."""

import json

import redis.asyncio as redis

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("admin_dashboard_cache")

KEY_PREFIX = "admin_dashboard_cache:"
DEFAULT_TTL_SECONDS = 60 * 60 * 24  # 24h - user-specified


class AdminDashboardCache:
    PROVIDER_NAME = "redis"
    ENV_KEY = "REDIS_URL"

    def __init__(self, url: str | None = None):
        self.url = read_setting(url, "REDIS_URL")
        self.ttl_seconds = int(
            read_setting(None, "REDIS_ADMIN_DASHBOARD_CACHE_TTL_SECONDS", DEFAULT_TTL_SECONDS)
        )

        if not self.url:
            logger.warning("[REDIS] REDIS_URL not set")

        self._client: redis.Redis | None = None

    def get_configuration(self) -> dict:
        # Never echo the URL itself - it carries the password.
        return {"configured": bool(self.url)}

    def _client_or_raise(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(self.url, decode_responses=True)
        return self._client

    async def get(self, cache_key: str) -> dict | None:
        """Returns None on a miss or if Redis is unreachable - never raises,
        so a down cache degrades to "no caching", not a broken request."""
        try:
            with log_backend_call(logger, "redis", "admin_dashboard_cache.get", cache_key=cache_key):
                raw = await self._client_or_raise().get(KEY_PREFIX + cache_key)
                return json.loads(raw) if raw else None
        except Exception as error:
            logger.warning("[admin_dashboard_cache] Redis unreachable on get, treating as a miss: %s", error)
            return None

    async def set(self, cache_key: str, value: dict) -> None:
        """Best-effort - a failed cache write must never break the response that was already computed."""
        try:
            with log_backend_call(logger, "redis", "admin_dashboard_cache.set", cache_key=cache_key):
                await self._client_or_raise().set(KEY_PREFIX + cache_key, json.dumps(value), ex=self.ttl_seconds)
        except Exception as error:
            logger.warning("[admin_dashboard_cache] Redis unreachable on set, skipping cache write: %s", error)

    async def health_check(self) -> dict:
        """Report whether this cache is usable - pings Redis, counts cached keys."""
        result = {"provider": self.PROVIDER_NAME}
        result.update(self.get_configuration())

        if not self.url:
            result["status"] = "unhealthy"
            result["message"] = "REDIS_URL not set"
            return result

        try:
            client = self._client_or_raise()
            await client.ping()
            count = 0
            async for _ in client.scan_iter(match=KEY_PREFIX + "*"):
                count += 1
            result["status"] = "healthy"
            result["entries_cached"] = count
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
