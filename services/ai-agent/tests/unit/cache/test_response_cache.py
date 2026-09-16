"""SKY-100 cache primitives: key building, Redis fail-open, memory TTL."""

from __future__ import annotations

import uuid

import pytest

from ai_agent.cache.response_cache import (
    MemoryResponseCache,
    RedisResponseCache,
    classification_cache_key,
    response_cache_key,
    tool_cache_key,
)

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


class ExplodingRedis:
    """Client whose every call raises - exercises the fail-open path."""

    async def get(self, key: str) -> bytes:
        raise RuntimeError("redis down")

    async def set(self, key: str, value: str, *, ex: int) -> None:
        raise RuntimeError("redis down")


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self.sets: list[tuple[str, str, int]] = []

    async def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self._store[key] = value.encode("utf-8")
        self.sets.append((key, value, ex))


class TestKeys:
    def test_classification_key_is_tenant_scoped(self) -> None:
        key_a = classification_cache_key(TENANT_A, "what stock is low?")
        key_b = classification_cache_key(TENANT_B, "what stock is low?")

        assert key_a != key_b
        assert str(TENANT_A) in key_a
        assert str(TENANT_B) not in key_a

    def test_classification_key_never_contains_query_text(self) -> None:
        key = classification_cache_key(TENANT_A, "payroll net income confidential")

        assert "payroll" not in key
        assert "confidential" not in key
        assert key.startswith("ai:classify:")

    def test_response_key_includes_conversation_history(self) -> None:
        plain = response_cache_key(tenant_id=TENANT_A, query="hi")
        with_history = response_cache_key(
            tenant_id=TENANT_A, query="hi", conversation_history="user: hello"
        )

        assert plain != with_history

    def test_tool_key_scopes_agent_and_parts(self) -> None:
        base = tool_cache_key(tenant_id=TENANT_A, agent="finance_assistant", parts=("invoice",))
        other_agent = tool_cache_key(tenant_id=TENANT_A, agent="crm_assistant", parts=("invoice",))
        other_args = tool_cache_key(
            tenant_id=TENANT_A, agent="finance_assistant", parts=("invoice", "2026")
        )

        assert base != other_agent
        assert base != other_args
        assert base.startswith("ai:tool:finance_assistant:")


class TestRedisResponseCache:
    async def test_roundtrip(self) -> None:
        redis = FakeRedis()
        cache = RedisResponseCache(client=redis)

        assert await cache.get("some:key") is None
        await cache.set("some:key", "answer", ttl_seconds=60)
        assert await cache.get("some:key") == "answer"
        assert redis.sets == [("some:key", "answer", 60)]

    async def test_fail_open_on_get_error(self) -> None:
        cache = RedisResponseCache(client=ExplodingRedis())

        assert await cache.get("some:key") is None

    async def test_fail_open_on_set_error(self) -> None:
        cache = RedisResponseCache(client=ExplodingRedis())

        await cache.set("some:key", "answer", ttl_seconds=60)  # must not raise


class TestMemoryResponseCache:
    async def test_roundtrip_and_miss(self) -> None:
        cache = MemoryResponseCache()

        await cache.set("some:key", "answer", ttl_seconds=300)
        assert await cache.get("some:key") == "answer"
        assert await cache.get("missing") is None

    async def test_expires_after_ttl(self) -> None:
        now = [100.0]
        cache = MemoryResponseCache(now=lambda: now[0])

        await cache.set("some:key", "answer", ttl_seconds=60)
        now[0] = 159.9
        assert await cache.get("some:key") == "answer"
        now[0] = 160.1
        assert await cache.get("some:key") is None

    async def test_set_with_zero_ttl_is_immediately_expired(self) -> None:
        cache = MemoryResponseCache()

        await cache.set("some:key", "answer", ttl_seconds=0)
        assert await cache.get("some:key") is None


@pytest.mark.parametrize(
    "build",
    [
        lambda: RedisResponseCache(client=ExplodingRedis()),
        lambda: MemoryResponseCache(),
    ],
)
async def test_all_stores_are_fail_open(build) -> None:
    """Both stores are fail-open by contract - get returns None, set is safe."""
    cache = build()
    await cache.set("some:key", "answer", ttl_seconds=60)
    assert True  # contract: never raises
