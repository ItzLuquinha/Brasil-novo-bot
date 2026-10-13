from types import SimpleNamespace

import os
import sys
import types

import pytest

os.environ.setdefault("APP_SECRET_KEY", "test-only-secret-key-0123456789abcdef")
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("DISCORD_CLIENT_ID", "123456789")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

if "redis.asyncio" not in sys.modules:
    redis_module = types.ModuleType("redis")
    redis_asyncio = types.ModuleType("redis.asyncio")
    class _RedisStub:
        @classmethod
        def from_url(cls, *args, **kwargs):
            return cls()
    redis_asyncio.Redis = _RedisStub
    redis_module.asyncio = redis_asyncio
    sys.modules.setdefault("redis", redis_module)
    sys.modules.setdefault("redis.asyncio", redis_asyncio)

from app.services import cooldowns


@pytest.mark.asyncio
async def test_production_redis_failure_fails_closed(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(cooldowns, "get_settings", lambda: SimpleNamespace(app_env="production"))
    monkeypatch.setattr(cooldowns.redis_client, "set", unavailable, raising=False)
    assert await cooldowns.check_and_set("bn:test:security", 30) == 30


@pytest.mark.asyncio
async def test_development_redis_failure_uses_bounded_process_fallback(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(cooldowns, "get_settings", lambda: SimpleNamespace(app_env="development"))
    monkeypatch.setattr(cooldowns.redis_client, "set", unavailable, raising=False)
    key = "bn:test:development-fallback"
    assert await cooldowns.check_and_set(key, 30) is None
    assert await cooldowns.check_and_set(key, 30) >= 1
    await cooldowns.release(key)


@pytest.mark.asyncio
async def test_development_redis_failure_logs_are_throttled(monkeypatch, caplog):
    import logging

    clock = {"now": 10.0}
    monkeypatch.setattr(cooldowns, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(cooldowns, "get_settings", lambda: SimpleNamespace(app_env="development"))

    async def unavailable(*args, **kwargs):
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr(cooldowns.redis_client, "set", unavailable, raising=False)
    cooldowns._redis_failure_started_at = None
    cooldowns._redis_last_warning_at = None
    cooldowns._redis_suppressed_failures = 0

    with caplog.at_level(logging.WARNING, logger="bn_bot.cooldowns"):
        await cooldowns.check_and_set("bn:warn:first", 30)
        clock["now"] = 20.0
        await cooldowns.check_and_set("bn:warn:second", 30)
        clock["now"] = 40.0
        await cooldowns.check_and_set("bn:warn:third", 30)
        assert len([r for r in caplog.records if r.name == "bn_bot.cooldowns"]) == 1
        clock["now"] = 311.0
        await cooldowns.check_and_set("bn:warn:fourth", 30)

    records = [r for r in caplog.records if r.name == "bn_bot.cooldowns"]
    assert len(records) == 2
    assert "suppressed_repeats=2" in records[-1].getMessage()
    cooldowns._redis_failure_started_at = None
    cooldowns._redis_last_warning_at = None
    cooldowns._redis_suppressed_failures = 0
