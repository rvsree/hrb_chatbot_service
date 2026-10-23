"""Redis-backed STM (short-term memory) cache-aside layer (Phase 247) - a
performance cache in front of conversation_memory.py's Postgres reads, not
a replacement for it. Postgres stays the durable system of record; a down
or expired Redis key just means the next read falls back to Postgres, same
never-raise/best-effort convention as answer_cache.py."""

import json

import redis.asyncio as redis

from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.call_logger import log_backend_call
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("stm_cache")

KEY_PREFIX = "stm:"
DEFAULT_TTL_SECONDS = 60 * 60 * 2  # 2 hours of inactivity


class StmCache:
    """Caches a conversation's turn list by conversation_id."""

    PROVIDER_NAME = "redis"
    ENV_KEY = "REDIS_URL"

    def __init__(self, url: str | None = None):
        self.url = read_setting(url, "REDIS_URL")
        self.ttl_seconds = int(read_setting(None, "REDIS_STM_TTL_SECONDS", DEFAULT_TTL_SECONDS))

        if not self.url:
            logger.warning("[REDIS] REDIS_URL not set")

        self._client: redis.Redis | None = None

    def _client_or_raise(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(self.url, decode_responses=True)
        return self._client

    async def get_turns(self, conversation_id: str) -> list[dict] | None:
        """Returns None on a miss, an empty cached list, or a Redis error -
        an STM key is never legitimately empty once written, so an empty
        read is treated the same as a miss (fall back to Postgres)."""
        try:
            with log_backend_call(logger, "redis", "stm_cache.get_turns", conversation_id=conversation_id):
                client = self._client_or_raise()
                raw_turns = await client.lrange(KEY_PREFIX + conversation_id, 0, -1)
                if not raw_turns:
                    return None
                return [json.loads(raw_turn) for raw_turn in raw_turns]
        except Exception as error:
            logger.warning("[stm_cache] Redis unreachable on get_turns, treating as a miss: %s", error)
            return None

    async def append_turn(self, conversation_id: str, role: str, content: str) -> None:
        """Best-effort - a failed cache write must never break the turn that was already saved to Postgres."""
        try:
            with log_backend_call(logger, "redis", "stm_cache.append_turn", conversation_id=conversation_id):
                client = self._client_or_raise()
                key = KEY_PREFIX + conversation_id
                await client.rpush(key, json.dumps({"role": role, "content": content}))
                await client.expire(key, self.ttl_seconds)
        except Exception as error:
            logger.warning("[stm_cache] Redis unreachable on append_turn, skipping cache write: %s", error)

    async def backfill(self, conversation_id: str, turns: list[dict]) -> None:
        """Populates the cache after a Postgres fallback read, so the next read is a hit. Best-effort, no-op on an empty list."""
        if not turns:
            return
        try:
            with log_backend_call(logger, "redis", "stm_cache.backfill", conversation_id=conversation_id):
                client = self._client_or_raise()
                key = KEY_PREFIX + conversation_id
                raw_turns = [json.dumps({"role": turn["role"], "content": turn["content"]}) for turn in turns]
                await client.rpush(key, *raw_turns)
                await client.expire(key, self.ttl_seconds)
        except Exception as error:
            logger.warning("[stm_cache] Redis unreachable on backfill, skipping cache write: %s", error)

    async def clear(self, conversation_id: str) -> None:
        """Best-effort - called on conversation delete so a stale cached copy never outlives its Postgres rows."""
        try:
            with log_backend_call(logger, "redis", "stm_cache.clear", conversation_id=conversation_id):
                await self._client_or_raise().delete(KEY_PREFIX + conversation_id)
        except Exception as error:
            logger.warning("[stm_cache] Redis unreachable on clear, skipping: %s", error)

    async def health_check(self) -> dict:
        result = {"provider": self.PROVIDER_NAME, "configured": bool(self.url)}

        if not self.url:
            result["status"] = "unhealthy"
            result["message"] = "REDIS_URL not set"
            return result

        try:
            client = self._client_or_raise()
            await client.ping()
            result["status"] = "healthy"
        except Exception as error:
            result["status"] = "unhealthy"
            result["message"] = str(error)

        return result
