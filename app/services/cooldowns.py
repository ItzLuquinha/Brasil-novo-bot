import asyncio
import logging
from time import monotonic
from app.config import get_settings
from app.core.redis import redis_client

logger = logging.getLogger("bn_bot.cooldowns")
REDIS_WARNING_INTERVAL_SECONDS = 300.0
_memory: dict[str, float] = {}
_memory_lock = asyncio.Lock()
_redis_failure_started_at: float | None = None
_redis_last_warning_at: float | None = None
_redis_suppressed_failures = 0


def _report_redis_failure(error_name: str, *, production: bool, key_prefix: str) -> None:
    """Summarize a Redis outage instead of logging once for every cooldown check."""
    global _redis_failure_started_at, _redis_last_warning_at, _redis_suppressed_failures
    now = monotonic()
    if _redis_failure_started_at is None:
        _redis_failure_started_at = now
    if (
        _redis_last_warning_at is None
        or now - _redis_last_warning_at >= REDIS_WARNING_INTERVAL_SECONDS
    ):
        log = logger.error if production else logger.warning
        message = (
            "Redis cooldown unavailable in production; denying operation key_prefix=%s "
            "error=%s duration_seconds=%.0f suppressed_repeats=%s"
            if production else
            "Redis cooldown unavailable; using process-local development fallback "
            "error=%s duration_seconds=%.0f suppressed_repeats=%s"
        )
        if production:
            log(message, key_prefix, error_name, now - _redis_failure_started_at, _redis_suppressed_failures)
        else:
            log(message, error_name, now - _redis_failure_started_at, _redis_suppressed_failures)
        _redis_last_warning_at = now
        _redis_suppressed_failures = 0
    else:
        _redis_suppressed_failures += 1


def _mark_redis_recovered() -> None:
    global _redis_failure_started_at, _redis_last_warning_at, _redis_suppressed_failures
    if _redis_failure_started_at is not None:
        duration = monotonic() - _redis_failure_started_at
        logger.info(
            "Redis cooldown recovered after_seconds=%.0f suppressed_repeats=%s",
            duration,
            _redis_suppressed_failures,
        )
        _redis_failure_started_at = None
        _redis_last_warning_at = None
        _redis_suppressed_failures = 0


async def check_and_set(key: str, seconds: int) -> int | None:
    if seconds <= 0:
        return None
    try:
        acquired = await redis_client.set(key, "1", ex=seconds, nx=True)
        _mark_redis_recovered()
        if acquired:
            return None
        ttl = await redis_client.ttl(key)
        return max(int(ttl), 1)
    except Exception as exc:
        production = get_settings().app_env == "production"
        _report_redis_failure(
            type(exc).__name__,
            production=production,
            key_prefix=key.split(":", 2)[0],
        )
        if production:
            return max(int(seconds), 1)
        now = monotonic()
        async with _memory_lock:
            expired = [item for item, expires in _memory.items() if expires <= now]
            for item in expired:
                _memory.pop(item, None)
            expires_at = _memory.get(key)
            if expires_at is not None and expires_at > now:
                return max(int(expires_at - now), 1)
            _memory[key] = now + seconds
            return None


async def release(key: str) -> None:
    try:
        await redis_client.delete(key)
        _mark_redis_recovered()
    except Exception:
        if get_settings().app_env != "production":
            async with _memory_lock:
                _memory.pop(key, None)
