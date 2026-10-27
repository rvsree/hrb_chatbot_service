"""Tests for CircuitBreaker - common/resiliency/circuit_breaker.py (Phase
259, Redis-backed, sync; Phase 260 adds dynamic app_settings-backed
thresholds). A minimal FakeRedisClient stands in for redis.Redis - only
exists/incr/expire/set/delete, the 5 methods CircuitBreaker actually calls
- same no-real-network-call convention as every other test in this
project, matching test_rate_limiter.py's own pattern."""

from src.hrb_chatbot.common.resiliency import circuit_breaker as circuit_breaker_module
from src.hrb_chatbot.common.resiliency.circuit_breaker import CircuitBreaker
from tests.conftest import FakeAppSettingsStore, FakeDBGateway


class FakeRedisClient:
    def __init__(self):
        self._store: dict[str, str] = {}

    def exists(self, key):
        return key in self._store

    def incr(self, key):
        self._store[key] = str(int(self._store.get(key, "0")) + 1)
        return int(self._store[key])

    def expire(self, key, seconds):
        pass

    def set(self, key, value, ex=None):
        self._store[key] = value

    def delete(self, *keys):
        for key in keys:
            self._store.pop(key, None)


def _breaker(**kwargs) -> CircuitBreaker:
    breaker = CircuitBreaker("llm:test", redis_url="redis://fake", **kwargs)
    breaker._client = FakeRedisClient()
    return breaker


def test_closed_breaker_allows_the_call():
    breaker = _breaker()

    assert breaker.check() is True


def test_stays_closed_below_the_failure_threshold():
    breaker = _breaker(failure_threshold="2")

    breaker.record_failure()  # 1st failure - below threshold of 2

    assert breaker.check() is True


def test_trips_open_at_the_failure_threshold():
    breaker = _breaker(failure_threshold="2")

    breaker.record_failure()
    breaker.record_failure()  # 2nd failure - hits threshold of 2

    assert breaker.check() is False


def test_success_resets_the_failure_count():
    breaker = _breaker(failure_threshold="2")

    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()  # only the 1st failure since the reset

    assert breaker.check() is True


def test_success_closes_an_already_open_breaker():
    breaker = _breaker(failure_threshold="1")

    breaker.record_failure()  # trips immediately (threshold=1)
    assert breaker.check() is False

    breaker.record_success()

    assert breaker.check() is True


def test_two_independent_breakers_do_not_affect_each_other():
    openai_breaker = CircuitBreaker("llm:openai", redis_url="redis://fake", failure_threshold="1")
    anthropic_breaker = CircuitBreaker("llm:anthropic", redis_url="redis://fake", failure_threshold="1")
    shared_redis = FakeRedisClient()
    openai_breaker._client = shared_redis
    anthropic_breaker._client = shared_redis

    openai_breaker.record_failure()

    assert openai_breaker.check() is False
    assert anthropic_breaker.check() is True


def test_check_fails_open_when_redis_is_unreachable():
    class _BoomRedisClient:
        def exists(self, key):
            raise ConnectionError("redis unreachable")

    breaker = _breaker()
    breaker._client = _BoomRedisClient()

    # Must not raise, and must allow the real call through (fail open).
    assert breaker.check() is True


def test_record_failure_never_raises_when_redis_is_unreachable():
    class _BoomRedisClient:
        def incr(self, key):
            raise ConnectionError("redis unreachable")

    breaker = _breaker()
    breaker._client = _BoomRedisClient()

    breaker.record_failure()  # must not raise


def test_record_success_never_raises_when_redis_is_unreachable():
    class _BoomRedisClient:
        def delete(self, *keys):
            raise ConnectionError("redis unreachable")

    breaker = _breaker()
    breaker._client = _BoomRedisClient()

    breaker.record_success()  # must not raise


class TestDynamicAppSettingsOverride:
    """Phase 260 - failure_threshold/cooldown_seconds read fresh from
    app_settings on every record_failure() call, not fixed at construction
    time."""

    def test_app_settings_value_overrides_the_constructor_fallback(self, monkeypatch):
        fake_gateway = FakeDBGateway(
            app_settings_store=FakeAppSettingsStore({"llm_test_circuit_breaker_failure_threshold": 1})
        )
        monkeypatch.setattr(circuit_breaker_module, "get_db_gateway", lambda: fake_gateway)
        # Constructor fallback says 2, but app_settings says 1 - app_settings wins.
        breaker = _breaker(failure_threshold="2")

        breaker.record_failure()  # 1 failure - already at the app_settings threshold of 1

        assert breaker.check() is False

    def test_no_app_settings_value_falls_back_to_the_constructor_value(self, monkeypatch):
        fake_gateway = FakeDBGateway(app_settings_store=FakeAppSettingsStore())  # empty - nothing set
        monkeypatch.setattr(circuit_breaker_module, "get_db_gateway", lambda: fake_gateway)
        breaker = _breaker(failure_threshold="2")

        breaker.record_failure()  # 1 failure - below the constructor fallback of 2

        assert breaker.check() is True

    def test_app_settings_cooldown_override_is_used_for_the_redis_ttl(self, monkeypatch):
        fake_gateway = FakeDBGateway(
            app_settings_store=FakeAppSettingsStore(
                {"llm_test_circuit_breaker_failure_threshold": 1, "llm_test_circuit_breaker_cooldown_seconds": 999}
            )
        )
        monkeypatch.setattr(circuit_breaker_module, "get_db_gateway", lambda: fake_gateway)
        breaker = _breaker(failure_threshold="1", cooldown_seconds="10")

        expire_calls = []
        real_client = breaker._client
        real_client.expire = lambda key, seconds: expire_calls.append(seconds)

        breaker.record_failure()

        assert 999 in expire_calls

    def test_app_settings_read_failure_falls_back_to_the_constructor_value(self, monkeypatch):
        class _BoomAppSettingsStore:
            def get_setting_sync(self, key, default):
                raise ConnectionError("postgres unreachable")

        fake_gateway = FakeDBGateway()
        monkeypatch.setattr(fake_gateway, "app_settings_store", lambda: _BoomAppSettingsStore())
        monkeypatch.setattr(circuit_breaker_module, "get_db_gateway", lambda: fake_gateway)
        breaker = _breaker(failure_threshold="2")

        # Must not raise, and must still correctly use the constructor
        # fallback (2) despite the app_settings read blowing up.
        breaker.record_failure()
        assert breaker.check() is True
        breaker.record_failure()
        assert breaker.check() is False
