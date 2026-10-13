import hashlib
import hmac
import logging
import math
import os
import re
import secrets
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from api.core.security import decode_access_token
from app.config import normalize_redis_url_for_runtime

logger = logging.getLogger(__name__)
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_WINDOW_SCRIPT = "local count = redis.call('INCR', KEYS[1]); if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]); end; return {count, redis.call('TTL', KEYS[1])}"
_GUILD_HEAVY_PATH = re.compile(r"^/api/v1/guilds/\d+/(overview|members|audit|economy|levels|moderation|analytics(?:/(?:channels/\d+|members/\d+|settings|counters|role-rules))?)$")
class RateLimitStoreUnavailable(Exception):
    pass


_rate_limit_redis = None
_memory_rate_limit_buckets: dict[str, tuple[int, float]] = {}
_memory_rate_limit_operations = 0
_warned_memory_rate_limit = False


def _rate_limit_redis_url(*, platform_name: str | None = None) -> str:
    configured_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0").strip()
    return normalize_redis_url_for_runtime(configured_url, platform_name=platform_name)


def _get_rate_limit_redis():
    global _rate_limit_redis
    if _rate_limit_redis is None:
        try:
            from redis.asyncio import Redis
        except ImportError:
            raise RateLimitStoreUnavailable from None
        redis_url = _rate_limit_redis_url()
        _rate_limit_redis = Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1, health_check_interval=30)
    return _rate_limit_redis


def _development_rate_limit_fallback_enabled() -> bool:
    """Only use a per-process fallback in local development/test environments."""
    return os.getenv("APP_ENV", "development").strip().casefold() in {"development", "dev", "test"}


def _increment_in_memory(key: str, window: int) -> tuple[int, int]:
    """Fixed-window fallback used only when Redis is unavailable in development."""
    global _memory_rate_limit_operations
    now = time.monotonic()
    entry = _memory_rate_limit_buckets.get(key)
    if entry is None or entry[1] <= now:
        count, expires_at = 1, now + window
    else:
        count, expires_at = entry[0] + 1, entry[1]
    _memory_rate_limit_buckets[key] = (count, expires_at)
    _memory_rate_limit_operations += 1

    if _memory_rate_limit_operations % 256 == 0 or len(_memory_rate_limit_buckets) > 4096:
        for bucket_key, (_, bucket_expiry) in list(_memory_rate_limit_buckets.items()):
            if bucket_expiry <= now:
                _memory_rate_limit_buckets.pop(bucket_key, None)
    return count, max(math.ceil(expires_at - now), 1)


async def close_rate_limit_redis() -> None:
    global _rate_limit_redis
    if _rate_limit_redis is not None:
        await _rate_limit_redis.aclose()
        _rate_limit_redis = None


async def redis_dependency_state() -> tuple[str, str]:
    try:
        from redis.exceptions import RedisError
        redis = _get_rate_limit_redis()
    except (ImportError, RateLimitStoreUnavailable):
        return "unavailable", "unknown"
    try:
        await redis.ping()
        heartbeat = await redis.get("bn:health:discord_bot")
    except RedisError:
        return "unavailable", "unknown"
    return "connected", "online" if heartbeat == "online" else "offline"


class CookieCSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_origins: list[str]):
        super().__init__(app)
        self.allowed_origins = frozenset(allowed_origins)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method.upper() in _SAFE_METHODS or not request.url.path.startswith("/api/v1/"):
            return await call_next(request)
        if not (request.cookies.get("bn_access") or request.cookies.get("bn_refresh")):
            return await call_next(request)
        origin = request.headers.get("origin", "")
        csrf_cookie = request.cookies.get("bn_csrf", "")
        csrf_header = request.headers.get("x-csrf-token", "")
        if origin not in self.allowed_origins or not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
            return JSONResponse({"detail": "Validação de segurança da sessão falhou. Atualize a página e tente novamente."}, status_code=403)
        return await call_next(request)


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:24]

    @staticmethod
    def _policy(request: Request) -> tuple[str, int, int] | None:
        path = request.url.path
        method = request.method.upper()
        if path == "/api/v1/auth/login" and method == "GET":
            return "auth-login", 10, 300
        if path in {"/api/v1/auth/callback", "/auth/callback"} and method == "GET":
            return "auth-callback", 30, 300
        if path == "/api/v1/auth/refresh" and method == "POST":
            return "auth-refresh", 20, 60
        if path == "/api/v1/auth/logout" and method == "POST":
            return "auth-logout", 60, 60
        if path == "/api/v1/guilds" and method == "GET":
            return "guild-list", 60, 60
        if path.startswith("/api/v1/guilds/") and method in {"POST", "PATCH", "PUT", "DELETE"}:
            return "guild-write", 60, 60
        if _GUILD_HEAVY_PATH.fullmatch(path) and method == "GET":
            return "guild-read", 120, 60
        return None

    async def _increment(self, key: str, window: int) -> tuple[int, int]:
        try:
            from redis.exceptions import RedisError
        except ImportError:
            raise RateLimitStoreUnavailable from None
        try:
            result = await _get_rate_limit_redis().eval(_WINDOW_SCRIPT, 1, key, window)
        except RedisError:
            raise RateLimitStoreUnavailable from None
        return int(result[0]), max(int(result[1]), 1)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        policy = self._policy(request)
        if policy is None:
            return await call_next(request)
        category, limit, window = policy
        client_ip = request.client.host if request.client else "unknown"
        actor = client_ip
        access_cookie = request.cookies.get("bn_access", "")
        if access_cookie:
            claims = decode_access_token(access_cookie)
            if claims and claims.get("sid"):
                actor = f"{client_ip}:{claims['sid']}"
        buckets = [(f"bn:api-rl:{category}:actor:{self._digest(actor)}", limit, window)]
        if actor != client_ip:
            buckets.append((f"bn:api-rl:{category}:ip:{self._digest(client_ip)}", max(limit * 5, 300), window))
        for key, bucket_limit, bucket_window in buckets:
            try:
                count, retry_after = await self._increment(key, bucket_window)
            except RateLimitStoreUnavailable:
                if category == "auth-logout":
                    logger.warning("API logout proceeding without Redis rate limiting so sessions can be revoked")
                    return await call_next(request)
                if not _development_rate_limit_fallback_enabled():
                    logger.warning("API rate limiter unavailable for category %s", category)
                    return JSONResponse({"detail": "Proteção contra excesso de requisições indisponível. Tente novamente mais tarde."}, status_code=503)
                global _warned_memory_rate_limit
                if not _warned_memory_rate_limit:
                    logger.warning("Redis indisponível: usando limitador local apenas para desenvolvimento; use Redis em produção")
                    _warned_memory_rate_limit = True
                count, retry_after = _increment_in_memory(key, bucket_window)
                if count > bucket_limit:
                    return JSONResponse(
                        {"detail": "Muitas requisições. Aguarde antes de tentar novamente."},
                        status_code=429,
                        headers={"Retry-After": str(retry_after)},
                    )
            if count > bucket_limit:
                return JSONResponse(
                    {"detail": "Muitas requisições. Aguarde antes de tentar novamente."},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)



class RequestObservabilityMiddleware(BaseHTTPMiddleware):
    _request_id_pattern = re.compile(r"^[A-Za-z0-9._-]{1,80}$")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_id = request.headers.get("x-request-id", "")
        request_id = supplied_id if self._request_id_pattern.fullmatch(supplied_id) else secrets.token_hex(16)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as error:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.error(
                "API request failed request_id=%s method=%s path=%s exception_type=%s duration_ms=%s",
                request_id, request.method, request.url.path, type(error).__name__, elapsed_ms,
            )
            response = JSONResponse(
                {"detail": "Ocorreu um erro interno. Tente novamente mais tarde.", "request_id": request_id},
                status_code=500,
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/api/v1/") or request.url.path == "/auth/callback":
            response.headers.setdefault("Cache-Control", "no-store")
        logger.info(
            "API request request_id=%s method=%s path=%s status=%s duration_ms=%s",
            request_id, request.method, request.url.path, response.status_code, elapsed_ms,
        )
        return response
