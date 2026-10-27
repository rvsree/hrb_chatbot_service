"""Phase 259 - a generic, Redis-backed circuit breaker, reusable across any
backend call. Generalizes Phase 185's MCP-only circuit breaker
(ai/rag_pipeline/tools/mcp_tools/__init__.py's _check_circuit_breaker()) -
same real behavior (N consecutive failures within a cooldown window trips
the breaker; it stays open, failing fast, until the cooldown expires, then
allows one retry), reimplemented once here instead of copy-pasted per
backend.

Sync, not async, deliberately - confirmed by reading the actual call path
(openai_client.py/anthropic_client.py's own ask(), and everything that
calls it - generate_answer(), GatewayChatModel, LangChain's chain.invoke())
is synchronous throughout, not async. A sync Redis call inside a sync
method just blocks whatever thread is already running it, same as the real
LLM SDK call already does - no asyncio-in-sync-context problem to solve.
Redis-backed for the same reason rate_limiter.py already is (Phase 84's
own lesson: in-process state doesn't work once App Runner auto-scales to
multiple instances - this needs to be shared state, not per-process).

Phase 260 - failure_threshold/cooldown_seconds are now read fresh from
app_settings on every check()/record_failure() call (via AppSettingsStore's
own sync counterpart, get_setting_sync() - same sync-context reasoning as
above), not just once at construction time - so a Settings UI change takes
effect on the very next call, no restart. Three-level fallback: app_settings
-> the constructor-time value (itself env var -> hardcoded default) if the
Postgres read itself fails. Per-breaker, not shared - each breaker's own
app_settings key is derived from its own name, same pattern the env var
already uses, so "llm:openai" and "llm:anthropic" can be tuned
independently if ever wanted, not forced to share one dial."""

import redis

from src.hrb_chatbot.common.clients.db_client.db_gateway import get_db_gateway
from src.hrb_chatbot.common.config.settings import read_setting
from src.hrb_chatbot.common.logging.logger import get_logger

logger = get_logger("circuit_breaker")

FAIL_PREFIX = "circuitbreaker:fail:"
OPEN_PREFIX = "circuitbreaker:open:"


class CircuitBreaker:
    """One breaker per `name` (e.g. "llm:openai", "llm:anthropic") - each
    tracks its own failure count and open/closed state independently."""

    def __init__(
        self,
        name: str,
        failure_threshold: str | None = None,
        cooldown_seconds: str | None = None,
        redis_url: str | None = None,
    ):
        self.name = name
        self._env_prefix = name.upper().replace(":", "_")
        self._app_settings_key_prefix = name.lower().replace(":", "_")
        # Constructor-time values - the 2nd-level fallback, used only if
        # the Phase 260 dynamic app_settings read itself fails.
        self._fallback_failure_threshold = int(
            read_setting(failure_threshold, f"{self._env_prefix}_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "2")
        )
        self._fallback_cooldown_seconds = int(
            read_setting(cooldown_seconds, f"{self._env_prefix}_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "10")
        )
        self.url = read_setting(redis_url, "REDIS_URL")

        self._client: redis.Redis | None = None

    def _client_or_raise(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(self.url, decode_responses=True)
        return self._client

    def _resolve_failure_threshold(self) -> int:
        """Own try/except, not just relying on record_failure()'s outer one
        - a threshold-read failure must never skip recording the real
        failure in Redis, only fall back to a sensible value and keep
        going. The real AppSettingsStore.get_setting_sync() already never
        raises; this guards against that contract being violated too."""
        try:
            value = get_db_gateway().app_settings_store().get_setting_sync(
                f"{self._app_settings_key_prefix}_circuit_breaker_failure_threshold", self._fallback_failure_threshold
            )
            return int(value)
        except Exception as error:
            logger.warning("[circuit_breaker] %s: could not resolve failure_threshold, using fallback: %s", self.name, error)
            return self._fallback_failure_threshold

    def _resolve_cooldown_seconds(self) -> int:
        try:
            value = get_db_gateway().app_settings_store().get_setting_sync(
                f"{self._app_settings_key_prefix}_circuit_breaker_cooldown_seconds", self._fallback_cooldown_seconds
            )
            return int(value)
        except Exception as error:
            logger.warning("[circuit_breaker] %s: could not resolve cooldown_seconds, using fallback: %s", self.name, error)
            return self._fallback_cooldown_seconds

    def check(self) -> bool:
        """True = proceed with the real call. False = circuit open
        (known, ongoing failure within the cooldown window) - fail fast
        instead of paying a real network timeout first. Fails open on any
        problem reaching Redis itself - a pre-flight check that can itself
        fail must never block a real call, only skip one it's confident
        is pointless (same convention Phase 185's own MCP check uses)."""
        try:
            client = self._client_or_raise()
            is_open = client.exists(OPEN_PREFIX + self.name)
            return not is_open
        except Exception as error:
            logger.warning("[circuit_breaker] %s: could not check state, allowing the call through: %s", self.name, error)
            return True

    def record_failure(self) -> None:
        """Never raises - a circuit breaker that can't reach its own
        backing store must never take the whole app down with it."""
        try:
            cooldown_seconds = self._resolve_cooldown_seconds()
            failure_threshold = self._resolve_failure_threshold()
            client = self._client_or_raise()
            fail_key = FAIL_PREFIX + self.name
            count = client.incr(fail_key)
            if count == 1:
                client.expire(fail_key, cooldown_seconds)
            if count >= failure_threshold:
                client.set(OPEN_PREFIX + self.name, "1", ex=cooldown_seconds)
                logger.warning(
                    "[circuit_breaker] %s: tripped after %d consecutive failures, open for %ds",
                    self.name,
                    count,
                    cooldown_seconds,
                )
        except Exception as error:
            logger.warning("[circuit_breaker] %s: could not record failure: %s", self.name, error)

    def record_success(self) -> None:
        """Resets the breaker fully - a real success clears both the
        failure count and the open state, not just one or the other."""
        try:
            client = self._client_or_raise()
            client.delete(FAIL_PREFIX + self.name, OPEN_PREFIX + self.name)
        except Exception as error:
            logger.warning("[circuit_breaker] %s: could not record success: %s", self.name, error)


class CircuitBreakerOpenError(Exception):
    """Raised instead of attempting the real call when the breaker is open."""
