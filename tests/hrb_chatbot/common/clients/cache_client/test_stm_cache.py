"""Phase 247: StmCache's own cache-aside commands (LRANGE/RPUSH/EXPIRE/
DELETE) and its never-raise-on-a-Redis-error contract - no real Redis,
_client_or_raise() faked with a minimal in-memory stand-in, same pattern as
test_answer_cache.py."""

import json

from src.hrb_chatbot.common.clients.cache_client.stm_cache import StmCache


class _FakeRedisClient:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}

    async def lrange(self, key, start, end):
        assert (start, end) == (0, -1)
        return list(self.lists.get(key, []))

    async def rpush(self, key, *values):
        self.lists.setdefault(key, []).extend(values)

    async def expire(self, key, seconds):
        pass

    async def delete(self, key):
        return 1 if self.lists.pop(key, None) is not None else 0


class _RaisingRedisClient:
    async def lrange(self, key, start, end):
        raise ConnectionError("redis unreachable")

    async def rpush(self, key, *values):
        raise ConnectionError("redis unreachable")

    async def expire(self, key, seconds):
        raise ConnectionError("redis unreachable")

    async def delete(self, key):
        raise ConnectionError("redis unreachable")


def _cache_with_fake_redis(monkeypatch):
    cache = StmCache(url="redis://fake")
    fake_client = _FakeRedisClient()
    monkeypatch.setattr(cache, "_client_or_raise", lambda: fake_client)
    return cache, fake_client


def _cache_with_raising_redis(monkeypatch):
    cache = StmCache(url="redis://fake")
    monkeypatch.setattr(cache, "_client_or_raise", lambda: _RaisingRedisClient())
    return cache


async def test_get_turns_on_an_unwritten_conversation_is_a_miss(monkeypatch):
    cache, _ = _cache_with_fake_redis(monkeypatch)

    assert await cache.get_turns("never-seen") is None


async def test_append_turn_then_get_turns_round_trips(monkeypatch):
    cache, _ = _cache_with_fake_redis(monkeypatch)
    await cache.append_turn("conv-1", "human", "what is the pto policy?")
    await cache.append_turn("conv-1", "ai", "15 days a year.")

    turns = await cache.get_turns("conv-1")

    assert turns == [
        {"role": "human", "content": "what is the pto policy?"},
        {"role": "ai", "content": "15 days a year."},
    ]


async def test_backfill_populates_the_cache_from_a_postgres_read(monkeypatch):
    cache, _ = _cache_with_fake_redis(monkeypatch)
    turns = [{"role": "human", "content": "q1"}, {"role": "ai", "content": "a1"}]

    await cache.backfill("conv-1", turns)

    assert await cache.get_turns("conv-1") == turns


async def test_backfill_with_an_empty_list_is_a_no_op(monkeypatch):
    cache, fake_client = _cache_with_fake_redis(monkeypatch)

    await cache.backfill("conv-1", [])

    assert fake_client.lists == {}


async def test_clear_removes_the_cached_conversation(monkeypatch):
    cache, _ = _cache_with_fake_redis(monkeypatch)
    await cache.append_turn("conv-1", "human", "q1")

    await cache.clear("conv-1")

    assert await cache.get_turns("conv-1") is None


async def test_different_conversation_ids_stay_isolated(monkeypatch):
    cache, _ = _cache_with_fake_redis(monkeypatch)
    await cache.append_turn("conv-a", "human", "a question")
    await cache.append_turn("conv-b", "human", "b question")

    assert await cache.get_turns("conv-a") == [{"role": "human", "content": "a question"}]
    assert await cache.get_turns("conv-b") == [{"role": "human", "content": "b question"}]


async def test_a_redis_error_on_get_turns_is_treated_as_a_miss_not_raised(monkeypatch):
    cache = _cache_with_raising_redis(monkeypatch)

    assert await cache.get_turns("conv-1") is None


async def test_a_redis_error_on_append_turn_is_swallowed_not_raised(monkeypatch):
    cache = _cache_with_raising_redis(monkeypatch)

    await cache.append_turn("conv-1", "human", "q1")  # must not raise


async def test_a_redis_error_on_backfill_is_swallowed_not_raised(monkeypatch):
    cache = _cache_with_raising_redis(monkeypatch)

    await cache.backfill("conv-1", [{"role": "human", "content": "q1"}])  # must not raise


async def test_a_redis_error_on_clear_is_swallowed_not_raised(monkeypatch):
    cache = _cache_with_raising_redis(monkeypatch)

    await cache.clear("conv-1")  # must not raise


async def test_json_round_trip_preserves_special_characters(monkeypatch):
    cache, fake_client = _cache_with_fake_redis(monkeypatch)
    await cache.append_turn("conv-1", "human", 'a "quoted" question with \n a newline')

    turns = await cache.get_turns("conv-1")

    assert turns == [{"role": "human", "content": 'a "quoted" question with \n a newline'}]
    # Confirms the value is actually JSON-encoded on the wire, not just round-tripped in Python.
    assert json.loads(fake_client.lists["stm:conv-1"][0])["role"] == "human"
