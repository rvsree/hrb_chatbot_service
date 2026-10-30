"""Phase 280: local dev and production share the same Redis instance
(confirmed by comparing local .env's REDIS_URL against production's App
Runner REDIS_URL secret - same host), so the cache key must be scoped by
environment or local testing silently poisons what production serves.
No real Redis - _client_or_raise() faked with a minimal in-memory stand-in."""

from src.hrb_chatbot.common.clients.cache_client.admin_dashboard_cache import (
    AdminDashboardCache,
    _resolve_key_prefix,
)


class _FakeRedisClient:
    def __init__(self):
        self.strings: dict[str, str] = {}

    async def get(self, key):
        return self.strings.get(key)

    async def set(self, key, value, ex=None):
        self.strings[key] = value

    async def ping(self):
        return True

    async def scan_iter(self, match):
        for key in list(self.strings):
            if key.startswith(match.rstrip("*")):
                yield key


def _store_with_fake_redis(monkeypatch):
    cache = AdminDashboardCache(url="redis://fake")
    fake_client = _FakeRedisClient()
    monkeypatch.setattr(cache, "_client_or_raise", lambda: fake_client)
    return cache, fake_client


def test_resolve_key_prefix_defaults_to_local(monkeypatch):
    monkeypatch.setenv("HRB_CHATBOT_LOCAL", "true")
    monkeypatch.setenv("HRB_CHATBOT_PROD", "false")
    assert _resolve_key_prefix() == "admin_dashboard_cache_local:"


def test_resolve_key_prefix_switches_to_prod(monkeypatch):
    monkeypatch.setenv("HRB_CHATBOT_LOCAL", "false")
    monkeypatch.setenv("HRB_CHATBOT_PROD", "true")
    assert _resolve_key_prefix() == "admin_dashboard_cache_prod:"


def test_resolve_key_prefix_prod_wins_if_both_true(monkeypatch):
    monkeypatch.setenv("HRB_CHATBOT_LOCAL", "true")
    monkeypatch.setenv("HRB_CHATBOT_PROD", "true")
    assert _resolve_key_prefix() == "admin_dashboard_cache_prod:"


async def test_set_writes_under_this_instance_own_prefix(monkeypatch):
    monkeypatch.setenv("HRB_CHATBOT_LOCAL", "true")
    monkeypatch.setenv("HRB_CHATBOT_PROD", "false")
    cache, fake_client = _store_with_fake_redis(monkeypatch)

    await cache.set("docs", {"count": 1})

    assert "admin_dashboard_cache_local:docs" in fake_client.strings


async def test_get_reads_back_what_set_wrote(monkeypatch):
    cache, _ = _store_with_fake_redis(monkeypatch)

    await cache.set("docs", {"count": 2})
    result = await cache.get("docs")

    assert result == {"count": 2}


async def test_local_and_prod_prefixes_never_collide(monkeypatch):
    monkeypatch.setenv("HRB_CHATBOT_LOCAL", "true")
    monkeypatch.setenv("HRB_CHATBOT_PROD", "false")
    local_cache, shared_redis = _store_with_fake_redis(monkeypatch)
    await local_cache.set("docs", {"source": "local"})

    monkeypatch.setenv("HRB_CHATBOT_LOCAL", "false")
    monkeypatch.setenv("HRB_CHATBOT_PROD", "true")
    prod_cache = AdminDashboardCache(url="redis://fake")
    monkeypatch.setattr(prod_cache, "_client_or_raise", lambda: shared_redis)

    assert await prod_cache.get("docs") is None
