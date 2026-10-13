from __future__ import annotations

import base64
import importlib
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request

from api.core import security


VALID_TEST_KEY = "R4nd0m-Test-Key-Used-Only-For-Unit-Tests-2026!"


def test_legacy_discord_oauth_callback_alias_is_registered_and_rate_limited() -> None:
    from api.routers import auth as auth_module
    from api.middleware import RedisRateLimitMiddleware

    assert any(getattr(route, "path", None) == "/auth/callback" for route in auth_module.legacy_callback_router.routes)
    assert RedisRateLimitMiddleware._policy(SimpleNamespace(
        url=SimpleNamespace(path="/auth/callback"), method="GET",
    )) == ("auth-callback", 30, 300)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/guilds/123/analytics",
        "/api/v1/guilds/123/analytics/channels/456",
        "/api/v1/guilds/123/analytics/members/789",
        "/api/v1/guilds/123/analytics/settings",
        "/api/v1/guilds/123/analytics/counters",
        "/api/v1/guilds/123/analytics/role-rules",
    ],
)
def test_advanced_analytics_read_endpoints_are_rate_limited(path: str) -> None:
    from api.middleware import RedisRateLimitMiddleware

    policy = RedisRateLimitMiddleware._policy(SimpleNamespace(
        url=SimpleNamespace(path=path), method="GET",
    ))
    assert policy == ("guild-read", 120, 60)


def configure_test_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", VALID_TEST_KEY)
    monkeypatch.setenv("JWT_ALGORITHM", "HS256")


def test_jwt_configuration_rejects_missing_and_weak_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        security.get_secret_key()

    monkeypatch.setenv("APP_SECRET_KEY", "short")
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        security.get_secret_key()

    monkeypatch.setenv("APP_SECRET_KEY", "a" * 48)
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY"):
        security.get_secret_key()


def test_jwt_configuration_rejects_a_non_allowlisted_algorithm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", VALID_TEST_KEY)
    monkeypatch.setenv("JWT_ALGORITHM", "HS512")
    with pytest.raises(RuntimeError, match="JWT_ALGORITHM"):
        security.get_secret_key()


def test_api_import_fails_closed_without_jwt_secret() -> None:
    environment = os.environ.copy()
    environment.pop("APP_SECRET_KEY", None)
    environment.pop("JWT_ALGORITHM", None)
    environment["PYTHON_DOTENV_DISABLED"] = "true"
    result = subprocess.run(
        [sys.executable, "-c", "import api.main"],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert "APP_SECRET_KEY" in result.stderr
    assert "fallback-secret-key-change-me" not in result.stderr


def test_jwt_expiration_signature_and_tampering_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_test_key(monkeypatch)
    valid = security.create_access_token({"id": "123456789", "guilds": ["111111111"]})
    assert security.decode_access_token(valid)["id"] == "123456789"

    now = datetime.now(timezone.utc)
    expired = security.jwt.encode({
        "id": "123456789", "sub": "123456789", "guilds": [],
        "system_role": "user", "iat": now - timedelta(minutes=5),
        "nbf": now - timedelta(minutes=5), "exp": now - timedelta(minutes=2),
        "iss": security.JWT_ISSUER, "aud": security.JWT_AUDIENCE, "jti": "expired-test-token",
    }, security.get_secret_key(), algorithm=security.ALGORITHM)
    assert security.decode_access_token(expired) is None
    with pytest.raises(ValueError, match="expiry"):
        security.create_access_token({"id": "123456789"}, expires_delta=timedelta(0))

    pieces = valid.split(".")
    signature_bytes = bytearray(base64.urlsafe_b64decode(pieces[2] + "=" * (-len(pieces[2]) % 4)))
    signature_bytes[0] ^= 0x01
    invalid_signature_part = base64.urlsafe_b64encode(bytes(signature_bytes)).decode().rstrip("=")
    invalid_signature = ".".join([pieces[0], pieces[1], invalid_signature_part])
    assert security.decode_access_token(invalid_signature) is None

    payload_replacement = "A" if pieces[1][-1] != "A" else "B"
    adulterated = ".".join([pieces[0], pieces[1][:-1] + payload_replacement, pieces[2]])
    assert security.decode_access_token(adulterated) is None


def test_invalid_user_claims_are_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_test_key(monkeypatch)
    with pytest.raises(ValueError, match="user ID"):
        security.create_access_token({"id": "0"})
    with pytest.raises(ValueError, match="system role"):
        security.create_access_token({"id": "123456789", "system_role": "superadmin"})
    with pytest.raises(ValueError, match="guild access"):
        security.create_access_token({"id": "123456789", "guilds": ["-1"]})


@pytest.mark.asyncio
async def test_signed_admin_claim_does_not_grant_global_privileges(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_test_key(monkeypatch)
    monkeypatch.delenv("SYSTEM_ADMIN_IDS", raising=False)
    monkeypatch.delenv("SYSTEM_MOD_IDS", raising=False)
    signed_token = security.create_access_token({"id": "123456789", "system_role": "admin", "guilds": []})
    from api.dependencies import get_current_user

    claims = security.decode_access_token(signed_token)
    assert claims is not None
    active_session = SimpleNamespace(
        id=claims["sid"], user_id=123456789, username="test-user", avatar_hash=None,
        guild_ids=[], revoked_at=None, expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    class FakeSessionDatabase:
        async def get(self, model, session_id):
            return active_session if session_id == active_session.id else None

    request = Request({
        "type": "http", "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/api/v1/auth/me", "raw_path": b"/api/v1/auth/me",
        "query_string": b"", "headers": [], "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    })
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=signed_token)
    user = await get_current_user(request, credentials, FakeSessionDatabase())
    assert user["system_role"] == "user"


class FakeGuildDatabase:
    def __init__(self, guild):
        self.guild = guild

    async def get(self, model, guild_id):
        return self.guild if getattr(self.guild, "id", None) == guild_id else None


@pytest.mark.asyncio
async def test_guild_access_policy_for_owner_manager_moderator_and_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.dependencies import require_guild_manager

    guild = SimpleNamespace(id=100, owner_id=200)
    database = FakeGuildDatabase(guild)

    owner = {"id": "200", "guilds": [], "system_role": "user"}
    assert await require_guild_manager(100, current_user=owner, db=database) == owner

    delegated = {"id": "201", "guilds": ["100"], "system_role": "user"}
    assert await require_guild_manager(100, current_user=delegated, db=database) == delegated

    moderator_without_guild_access = {"id": "202", "guilds": [], "system_role": "moderator"}
    with pytest.raises(HTTPException) as denied:
        await require_guild_manager(100, current_user=moderator_without_guild_access, db=database)
    assert denied.value.status_code == 403

    admin = {"id": "203", "guilds": [], "system_role": "admin"}
    assert await require_guild_manager(100, current_user=admin, db=database) == admin

    with pytest.raises(HTTPException) as absent:
        await require_guild_manager(999, current_user=admin, db=database)
    assert absent.value.status_code == 404

    inactive_database = FakeGuildDatabase(SimpleNamespace(id=100, owner_id=200, active=False))
    for inactive_user in (owner, delegated, admin):
        with pytest.raises(HTTPException) as inactive:
            await require_guild_manager(100, current_user=inactive_user, db=inactive_database)
        assert inactive.value.status_code == 404


@pytest.mark.asyncio
async def test_oauth_callback_rejects_missing_invalid_and_reused_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.security import new_state, store_oauth_state
    from api.routers.auth import discord_callback

    def make_request(session: dict) -> Request:
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/auth/callback",
            "raw_path": b"/api/v1/auth/callback",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8000),
            "session": session,
        }
        return Request(scope)

    accepted_state = new_state()
    session = {}
    store_oauth_state(session, accepted_state)

    with pytest.raises(HTTPException) as missing:
        await discord_callback(make_request(session.copy()), code="not-used", state=None, error=None)
    assert missing.value.status_code == 400

    with pytest.raises(HTTPException) as invalid:
        await discord_callback(make_request(session.copy()), code="not-used", state="wrong-state", error=None)
    assert invalid.value.status_code == 400

    valid_session = session.copy()
    with pytest.raises(HTTPException) as cancelled:
        await discord_callback(make_request(valid_session), code="not-used", state=accepted_state, error="access_denied")
    assert cancelled.value.status_code == 400
    assert "oauth_states" not in valid_session
    with pytest.raises(HTTPException) as replayed:
        await discord_callback(make_request(valid_session), code="not-used", state=accepted_state, error=None)
    assert replayed.value.status_code == 400


def test_timezone_and_locale_are_validated_by_backend_schema() -> None:
    from pydantic import ValidationError
    from api.routers.guilds import GuildSettingsUpdateSchema

    valid = GuildSettingsUpdateSchema.model_validate({"timezone": "America/New_York", "locale": "pt-BR"})
    assert valid.timezone == "America/New_York"
    assert valid.locale == "pt-BR"

    for payload in ({"timezone": "Not/A_Real_Zone"}, {"timezone": "   "}, {"locale": "pt-br"}, {"locale": ""}, {"unexpected": True}):
        with pytest.raises(ValidationError):
            GuildSettingsUpdateSchema.model_validate(payload)




def test_dashboard_url_and_oauth_callback_match_secure_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_test_key(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DASHBOARD_URL", "https://dashboard.example.com")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://api.example.com/api/v1/auth/callback")
    from api.main import validate_public_urls
    validate_public_urls(["https://dashboard.example.com"])

    monkeypatch.setenv("DASHBOARD_URL", "https://other.example.com")
    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        validate_public_urls(["https://dashboard.example.com"])

    monkeypatch.setenv("DASHBOARD_URL", "http://dashboard.example.com")
    with pytest.raises(RuntimeError, match="HTTPS"):
        validate_public_urls(["http://dashboard.example.com"])

    monkeypatch.setenv("DASHBOARD_URL", "https://dashboard.example.com")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "http://api.example.com/callback")
    with pytest.raises(RuntimeError, match="HTTPS"):
        validate_public_urls(["https://dashboard.example.com"])


def test_cors_configuration_is_explicit_and_disallows_wildcards(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_test_key(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DASHBOARD_URL", "https://dashboard.example.com")
    monkeypatch.setenv("DISCORD_REDIRECT_URI", "https://api.example.com/api/v1/auth/callback")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:5432/unused")
    module = importlib.import_module("api.main")
    assert module._allowed_origins() == ["https://dashboard.example.com"]
    cors_options = next(item.kwargs for item in module.app.user_middleware if item.cls.__name__ == "CORSMiddleware")
    assert cors_options["allow_credentials"] is True
    assert cors_options["allow_origins"] == ["https://dashboard.example.com"]

    from fastapi.testclient import TestClient
    with TestClient(module.app) as client:
        allowed = client.options(
            "/health",
            headers={"Origin": "https://dashboard.example.com", "Access-Control-Request-Method": "GET"},
        )
        denied = client.options(
            "/health",
            headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "GET"},
        )
    assert allowed.headers.get("access-control-allow-origin") == "https://dashboard.example.com"
    assert denied.headers.get("access-control-allow-origin") is None

    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://dashboard.example.com,https://admin.example.com")
    assert module._allowed_origins() == ["https://dashboard.example.com", "https://admin.example.com"]

    for invalid in ("*", "https://dashboard.example.com/path", "https://user:pass@dashboard.example.com", "http://dashboard.example.com"):
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", invalid)
        with pytest.raises(RuntimeError):
            module._allowed_origins()


@pytest.mark.asyncio
async def test_oauth_callback_accepts_valid_state_once_and_creates_authenticated_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from api.routers import auth as auth_module
    from app.core.security import new_state, store_oauth_state

    configure_test_key(monkeypatch)
    monkeypatch.delenv("SYSTEM_ADMIN_IDS", raising=False)
    monkeypatch.delenv("SYSTEM_MOD_IDS", raising=False)
    monkeypatch.setattr(auth_module, "CLIENT_ID", "unit-test-client")
    monkeypatch.setattr(auth_module, "CLIENT_SECRET", "unit-test-client-secret")
    monkeypatch.setattr(auth_module, "REDIRECT_URI", "http://localhost:8000/api/v1/auth/callback")
    monkeypatch.setattr(auth_module, "DASHBOARD_URL", "http://localhost:5173")

    class Response:
        def __init__(self, status_code: int, payload: dict | list):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return Response(200, {
                "access_token": "mock-discord-access-token",
                "refresh_token": "mock-discord-refresh-token",
                "expires_in": 3600,
            })

        async def get(self, path: str, **_kwargs):
            if path == "/users/@me":
                return Response(200, {"id": "123456789", "username": "unit-test-user", "avatar": None})
            if path == "/users/@me/guilds":
                return Response(200, [{"id": "111111111", "owner": True, "permissions": "0"}])
            return Response(404, {})

    monkeypatch.setattr(auth_module, "httpx", SimpleNamespace(
        AsyncClient=FakeAsyncClient,
        TimeoutException=httpx.TimeoutException,
        RequestError=httpx.RequestError,
    ))
    session_created_at = datetime.now(timezone.utc)

    async def fake_create_api_session(db, user_data, guild_ids, provider_access_token, provider_refresh_token, provider_expires_in):
        session_row = SimpleNamespace(
            id="test-session-id", user_id=int(user_data["id"]), username=user_data["username"],
            avatar_hash=user_data.get("avatar"), guild_ids=guild_ids,
            created_at=session_created_at,
            expires_at=session_created_at + timedelta(hours=24),
        )
        return session_row, f"{session_row.id}." + "R" * 64, "csrf-test-token-012345678901234567890123"

    monkeypatch.setattr(auth_module, "_create_api_session", fake_create_api_session)
    state = new_state()
    session = {}
    store_oauth_state(session, state)
    request = Request({
        "type": "http", "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": "/api/v1/auth/callback",
        "raw_path": b"/api/v1/auth/callback", "query_string": b"",
        "headers": [], "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000), "session": session,
    })

    response = await auth_module.discord_callback(request, code="mock-oauth-code", state=state, error=None, db=object())
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173"
    assert "token=" not in response.headers["location"]
    assert "oauth_states" not in session
    from http.cookies import SimpleCookie
    access_header = next(value for value in response.headers.getlist("set-cookie") if value.startswith("bn_access="))
    access_cookie = SimpleCookie()
    access_cookie.load(access_header)
    token = access_cookie["bn_access"].value
    assert access_cookie["bn_access"]["httponly"]
    claims = security.decode_access_token(token)
    assert claims is not None
    assert claims["id"] == "123456789"
    assert claims["guilds"] == ["111111111"]
    assert claims["exp"] - claims["iat"] <= 15 * 60 + 1
    assert any(value.startswith("bn_refresh=") for value in response.headers.getlist("set-cookie"))
    assert any(value.startswith("bn_csrf=") for value in response.headers.getlist("set-cookie"))

    with pytest.raises(HTTPException) as replay:
        await auth_module.discord_callback(request, code="mock-oauth-code", state=state, error=None, db=object())
    assert replay.value.status_code == 400


@pytest.mark.asyncio
async def test_logout_is_not_blocked_when_redis_rate_limiter_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.responses import JSONResponse
    from api import middleware

    app = lambda scope, receive, send: None
    limiter = middleware.RedisRateLimitMiddleware(app)

    async def unavailable(key: str, window: int):
        raise middleware.RateLimitStoreUnavailable

    monkeypatch.setattr(limiter, "_increment", unavailable)
    monkeypatch.setattr(middleware, "_development_rate_limit_fallback_enabled", lambda: False)
    scope = {
        "type": "http", "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/api/v1/auth/logout", "raw_path": b"/api/v1/auth/logout",
        "query_string": b"", "headers": [], "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    request = Request(scope)
    reached_endpoint = False

    async def call_next(_request):
        nonlocal reached_endpoint
        reached_endpoint = True
        return JSONResponse({"status": "logged_out"})

    response = await limiter.dispatch(request, call_next)

    assert reached_endpoint is True
    assert response.status_code == 200
