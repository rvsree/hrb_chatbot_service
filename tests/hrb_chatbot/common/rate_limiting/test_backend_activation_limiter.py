"""Phase 284: backend_activation_limiter - per-IP-per-day cap on the public
backend-activation resume route. Redis/Postgres are faked, no real call."""

from src.hrb_chatbot.common.rate_limiting import backend_activation_limiter
from tests.conftest import FakeAppSettingsStore, FakeDBGateway


class _FakeRedisClient:
    def __init__(self, raise_on_incr=False):
        self._counts: dict[str, int] = {}
        self.raise_on_incr = raise_on_incr

    async def incr(self, key):
        if self.raise_on_incr:
            raise ConnectionError("redis unreachable")
        self._counts[key] = self._counts.get(key, 0) + 1
        return self._counts[key]

    async def expire(self, key, seconds):
        pass


def _patch_gateway(monkeypatch, app_settings=None):
    gateway = FakeDBGateway(app_settings_store=FakeAppSettingsStore(app_settings or {}))
    monkeypatch.setattr(backend_activation_limiter, "get_db_gateway", lambda: gateway)
    return gateway


def _patch_redis(monkeypatch, client=None):
    monkeypatch.setattr(backend_activation_limiter, "_get_redis_client", lambda: client or _FakeRedisClient())


async def test_missing_ip_address_is_allowed_through(monkeypatch):
    _patch_gateway(monkeypatch, app_settings={"backend_activation_resume_limit_per_ip_per_day": 1})
    _patch_redis(monkeypatch)

    result = await backend_activation_limiter.check_and_record(None)

    assert result is True


async def test_under_the_daily_cap_is_allowed_through(monkeypatch):
    _patch_gateway(monkeypatch, app_settings={"backend_activation_resume_limit_per_ip_per_day": 5})
    _patch_redis(monkeypatch)

    result = await backend_activation_limiter.check_and_record("1.2.3.4")

    assert result is True


async def test_exceeding_the_daily_cap_blocks(monkeypatch):
    _patch_gateway(monkeypatch, app_settings={"backend_activation_resume_limit_per_ip_per_day": 1})
    redis_client = _FakeRedisClient()
    _patch_redis(monkeypatch, redis_client)

    first = await backend_activation_limiter.check_and_record("1.2.3.4")
    second = await backend_activation_limiter.check_and_record("1.2.3.4")

    assert first is True
    assert second is False


async def test_different_ips_have_independent_caps(monkeypatch):
    _patch_gateway(monkeypatch, app_settings={"backend_activation_resume_limit_per_ip_per_day": 1})
    _patch_redis(monkeypatch)

    first = await backend_activation_limiter.check_and_record("1.2.3.4")
    second = await backend_activation_limiter.check_and_record("5.6.7.8")

    assert first is True
    assert second is True


async def test_redis_failure_fails_open(monkeypatch):
    _patch_gateway(monkeypatch, app_settings={"backend_activation_resume_limit_per_ip_per_day": 1})
    _patch_redis(monkeypatch, _FakeRedisClient(raise_on_incr=True))

    result = await backend_activation_limiter.check_and_record("1.2.3.4")

    assert result is True
