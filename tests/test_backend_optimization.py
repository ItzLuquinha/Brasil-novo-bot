import asyncio
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from starlette.requests import Request

from api.core import security
from api.middleware import CookieCSRFMiddleware, RedisRateLimitMiddleware, RequestObservabilityMiddleware
from app.core.database_options import engine_options


TEST_KEY = "R4nd0m-Backend-Tests-Only-2026-Secure-Key!"


def configure_key(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", TEST_KEY)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


def test_provider_credentials_are_encrypted_and_tampering_is_rejected(monkeypatch):
    configure_key(monkeypatch)
    raw_token = "discord-access-token-for-test-only"
    encrypted = security.encrypt_provider_token(raw_token)
    assert raw_token not in encrypted
    assert security.decrypt_provider_token(encrypted) == raw_token
    tampered = encrypted[:-2] + ("AA" if encrypted[-2:] != "AA" else "BB")
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        security.decrypt_provider_token(tampered)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "session_state",
    [
        {"revoked_at": datetime.now(timezone.utc), "expires_at": datetime.now(timezone.utc) + timedelta(hours=1)},
        {"revoked_at": None, "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
    ],
)
async def test_current_user_rejects_revoked_or_expired_sessions(monkeypatch, session_state):
    configure_key(monkeypatch)
    from api.dependencies import get_current_user

    token = security.create_access_token({"id": "123456789", "guilds": []})
    claims = security.decode_access_token(token)
    row = SimpleNamespace(
        id=claims["sid"], user_id=123456789, username="test-user", avatar_hash=None,
        guild_ids=[], **session_state,
    )

    class FakeDatabase:
        async def get(self, model, key):
            return row if key == row.id else None

    request = Request({
        "type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": "/api/v1/auth/me", "raw_path": b"/api/v1/auth/me", "query_string": b"",
        "headers": [], "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
    })
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    with pytest.raises(HTTPException) as result:
        await get_current_user(request, HTTPAuthorizationCredentials(scheme="Bearer", credentials=token), FakeDatabase())
    assert result.value.status_code == 401


def test_csrf_middleware_requires_matching_origin_cookie_and_header():
    app = FastAPI()
    app.add_middleware(CookieCSRFMiddleware, allowed_origins=["https://dashboard.example.com"])

    @app.post("/api/v1/guilds/1/settings")
    async def update_settings():
        return {"saved": True}

    with TestClient(app) as client:
        csrf = "random-csrf-value-for-test"
        valid = client.post(
            "/api/v1/guilds/1/settings",
            headers={"Origin": "https://dashboard.example.com", "X-CSRF-Token": csrf, "Cookie": f"bn_access=session; bn_csrf={csrf}"},
        )
        missing = client.post(
            "/api/v1/guilds/1/settings",
            headers={"Origin": "https://dashboard.example.com", "Cookie": f"bn_access=session; bn_csrf={csrf}"},
        )
        mismatched = client.post(
            "/api/v1/guilds/1/settings",
            headers={"Origin": "https://dashboard.example.com", "X-CSRF-Token": "wrong", "Cookie": f"bn_access=session; bn_csrf={csrf}"},
        )
        untrusted_origin = client.post(
            "/api/v1/guilds/1/settings",
            headers={"Origin": "https://attacker.example", "X-CSRF-Token": csrf, "Cookie": f"bn_access=session; bn_csrf={csrf}"},
        )
    assert valid.status_code == 200
    assert missing.status_code == 403
    assert mismatched.status_code == 403
    assert untrusted_origin.status_code == 403


def _install_fake_redis_exceptions(monkeypatch):
    redis_package = ModuleType("redis")
    redis_package.__path__ = []
    exceptions_module = ModuleType("redis.exceptions")
    exceptions_module.RedisError = type("RedisError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "redis", redis_package)
    monkeypatch.setitem(sys.modules, "redis.exceptions", exceptions_module)


def test_rate_limiter_returns_429_after_configured_threshold(monkeypatch):
    import api.middleware as middleware

    _install_fake_redis_exceptions(monkeypatch)

    class FakeRedis:
        def __init__(self):
            self.counts = {}

        async def eval(self, script, key_count, key, window):
            self.counts[key] = self.counts.get(key, 0) + 1
            return [self.counts[key], window]

    monkeypatch.setattr(middleware, "_get_rate_limit_redis", lambda: fake_redis)
    fake_redis = FakeRedis()
    app = FastAPI()
    app.add_middleware(RedisRateLimitMiddleware)

    @app.get("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    with TestClient(app) as client:
        responses = [client.get("/api/v1/auth/login") for _ in range(11)]
    assert all(response.status_code == 200 for response in responses[:10])
    assert responses[10].status_code == 429
    assert int(responses[10].headers["Retry-After"]) >= 1


def test_rate_limiter_fails_closed_when_redis_is_unavailable(monkeypatch):
    import api.middleware as middleware

    monkeypatch.setenv("APP_ENV", "production")
    _install_fake_redis_exceptions(monkeypatch)

    def unavailable():
        raise middleware.RateLimitStoreUnavailable

    monkeypatch.setattr(middleware, "_get_rate_limit_redis", unavailable)
    app = FastAPI()
    app.add_middleware(RedisRateLimitMiddleware)

    @app.get("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/login")
    assert response.status_code == 503


def test_rate_limiter_uses_bounded_memory_fallback_in_development(monkeypatch):
    import api.middleware as middleware

    monkeypatch.setenv("APP_ENV", "development")
    middleware._memory_rate_limit_buckets.clear()
    middleware._memory_rate_limit_operations = 0
    middleware._warned_memory_rate_limit = False
    _install_fake_redis_exceptions(monkeypatch)

    def unavailable():
        raise middleware.RateLimitStoreUnavailable

    monkeypatch.setattr(middleware, "_get_rate_limit_redis", unavailable)
    app = FastAPI()
    app.add_middleware(RedisRateLimitMiddleware)

    @app.get("/api/v1/auth/login")
    async def login():
        return {"ok": True}

    with TestClient(app) as client:
        responses = [client.get("/api/v1/auth/login") for _ in range(11)]
    assert all(response.status_code == 200 for response in responses[:10])
    assert responses[10].status_code == 429
    assert int(responses[10].headers["Retry-After"]) >= 1


def test_request_observability_adds_request_id_without_logging_query_string(caplog):
    app = FastAPI()
    app.add_middleware(RequestObservabilityMiddleware)

    @app.get("/api/v1/health")
    async def health():
        return {"status": "online"}

    with TestClient(app) as client:
        response = client.get("/api/v1/health?code=must-not-appear", headers={"X-Request-ID": "request_123"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request_123"
    assert response.headers["Cache-Control"] == "no-store"
    assert "must-not-appear" not in caplog.text


def test_analytics_overview_executes_one_database_round_trip():
    from app.repositories.analytics import overview

    expected = {
        "members": 12, "messages": 125, "economy": 3400.5,
        "warnings": 2, "tickets": 3, "reports": 1, "pending_suggestions": 4,
    }

    class FakeMappings:
        def one(self):
            return expected

    class FakeResult:
        def mappings(self):
            return FakeMappings()

    class FakeDatabase:
        def __init__(self):
            self.calls = 0

        async def execute(self, statement):
            self.calls += 1
            return FakeResult()

    database = FakeDatabase()
    result = asyncio.run(overview(database, 123))
    assert result == expected
    assert database.calls == 1


def test_postgres_pool_settings_are_bounded_and_validated(monkeypatch):
    url = make_url("postgresql+asyncpg://test-user:test-password@localhost/test_db")
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    monkeypatch.delenv("DB_POOL_TIMEOUT", raising=False)
    monkeypatch.delenv("DB_POOL_RECYCLE", raising=False)
    options = engine_options(url)
    assert options["pool_size"] == 5
    assert options["max_overflow"] == 10
    assert options["pool_timeout"] == 30
    assert options["pool_recycle"] == 1800
    assert options["pool_pre_ping"] is True

    monkeypatch.setenv("DB_POOL_SIZE", "0")
    with pytest.raises(RuntimeError, match="DB_POOL_SIZE"):
        engine_options(url)


def test_refresh_cookie_format_is_validated():
    from api.routers.auth import _refresh_cookie_parts

    assert _refresh_cookie_parts(None) is None
    assert _refresh_cookie_parts("incomplete") is None
    assert _refresh_cookie_parts("bad.session.secret") is None
    session_id = "A" * 40
    secret = "B" * 64
    assert _refresh_cookie_parts(f"{session_id}.{secret}") == (session_id, secret)


def test_auth_logout_has_rate_limit_policy():
    from api.middleware import RedisRateLimitMiddleware
    from starlette.requests import Request

    scope = {
        "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/v1/auth/logout", "raw_path": b"/api/v1/auth/logout", "query_string": b"",
        "headers": [], "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
    }
    request = Request(scope)
    assert RedisRateLimitMiddleware._policy(request) == ("auth-logout", 60, 60)


def test_request_observability_hides_unexpected_exception_details(caplog):
    app = FastAPI()
    app.add_middleware(RequestObservabilityMiddleware)

    @app.get("/health")
    async def failing_health():
        raise RuntimeError("private-database-detail")

    with TestClient(app) as client:
        response = client.get("/health?token=private-query")
    assert response.status_code == 500
    assert response.json()["detail"] == "Ocorreu um erro interno. Tente novamente mais tarde."
    assert "private-database-detail" not in caplog.text
    assert "private-query" not in caplog.text
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


@pytest.mark.asyncio
async def test_refresh_rotates_refresh_cookie_and_replay_revokes_session(monkeypatch):
    configure_key(monkeypatch)
    from api.routers.auth import REFRESH_COOKIE, _refresh_digest, refresh_session
    from http.cookies import SimpleCookie

    now = datetime.now(timezone.utc)
    session_id = "S" * 40
    original_secret = "T" * 64
    session = SimpleNamespace(
        id=session_id,
        user_id=123456789,
        username="test-user",
        avatar_hash=None,
        guild_ids=["100"],
        refresh_token_hash=_refresh_digest(original_secret),
        previous_refresh_token_hash=None,
        previous_refresh_until=None,
        discord_access_token_encrypted=security.encrypt_provider_token("access-test-token"),
        discord_refresh_token_encrypted=security.encrypt_provider_token("refresh-test-token"),
        discord_token_expires_at=now + timedelta(hours=1),
        discord_permissions_checked_at=now,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=24),
        revoked_at=None,
    )

    class FakeResult:
        def scalar_one_or_none(self):
            return session

    class FakeDatabase:
        def __init__(self):
            self.commits = 0

        async def execute(self, statement):
            return FakeResult()

        async def commit(self):
            self.commits += 1

    def make_request(raw_cookie):
        return Request({
            "type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
            "path": "/api/v1/auth/refresh", "raw_path": b"/api/v1/auth/refresh", "query_string": b"",
            "headers": [(b"cookie", f"{REFRESH_COOKIE}={raw_cookie}".encode())],
            "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000), "session": {},
        })

    database = FakeDatabase()
    original_cookie = f"{session_id}.{original_secret}"
    response = await refresh_session(make_request(original_cookie), database)
    assert response.status_code == 200
    assert session.refresh_token_hash != _refresh_digest(original_secret)
    assert database.commits == 1

    cookie = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        cookie.load(header)
    rotated_cookie = cookie[REFRESH_COOKIE].value
    assert rotated_cookie != original_cookie

    concurrent_response = await refresh_session(make_request(original_cookie), database)
    assert concurrent_response.status_code == 409
    assert session.revoked_at is None
    assert database.commits == 1

    session.previous_refresh_until = now - timedelta(seconds=1)
    replay_response = await refresh_session(make_request(original_cookie), database)
    assert replay_response.status_code == 401
    assert session.revoked_at is not None
    assert database.commits == 2


def test_api_authentication_routes_use_only_versioned_prefix(monkeypatch):
    configure_key(monkeypatch)
    import api.main as api_main

    paths = set(api_main.app.openapi()["paths"])
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/auth/login" not in paths
    assert "/auth/refresh" not in paths


def test_jwt_rejects_wrong_issuer_and_audience(monkeypatch):
    configure_key(monkeypatch)
    token = security.create_access_token({"id": "123456789", "guilds": []})
    claims = security.jwt.decode(token, options={"verify_signature": False})
    claims["iss"] = "another-service"
    wrong_issuer = security.jwt.encode(claims, security.get_secret_key(), algorithm=security.ALGORITHM)
    claims["iss"] = security.JWT_ISSUER
    claims["aud"] = "another-application"
    wrong_audience = security.jwt.encode(claims, security.get_secret_key(), algorithm=security.ALGORITHM)
    assert security.decode_access_token(wrong_issuer) is None
    assert security.decode_access_token(wrong_audience) is None


@pytest.mark.asyncio
async def test_automod_mutations_lock_the_guild_row_for_update():
    from sqlalchemy.dialects import postgresql

    from api.routers.guilds import _lock_automod_guild_writes

    class FakeDatabase:
        statement = None

        async def scalar(self, statement):
            self.statement = statement
            return 987654321

    database = FakeDatabase()
    locked_guild = await _lock_automod_guild_writes(database, 987654321)
    sql = str(database.statement.compile(dialect=postgresql.dialect()))

    assert locked_guild == 987654321
    assert "FOR UPDATE" in sql
    assert "guilds.id" in sql


@pytest.mark.asyncio
async def test_automod_write_lock_returns_not_found_for_missing_guild():
    from fastapi import HTTPException

    from api.routers.guilds import _lock_automod_guild_writes

    class FakeDatabase:
        async def scalar(self, statement):
            return None

    with pytest.raises(HTTPException) as result:
        await _lock_automod_guild_writes(FakeDatabase(), 987654321)
    assert result.value.status_code == 404
