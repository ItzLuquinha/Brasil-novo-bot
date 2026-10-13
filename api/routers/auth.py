import hashlib
import hmac
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    decrypt_provider_token,
    encrypt_provider_token,
    get_system_role,
)
from api.database import get_db
from api.dependencies import get_current_user
from app.core.security import consume_oauth_state, new_state, store_oauth_state
from app.models import ApiAuthSession

router = APIRouter()
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/api/v1/auth/callback").strip()
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:5173").strip().rstrip("/")
DISCORD_API_URL = "https://discord.com/api/v10"
ACCESS_COOKIE = "bn_access"
REFRESH_COOKIE = "bn_refresh"
CSRF_COOKIE = "bn_csrf"
ACCESS_COOKIE_PATH = "/"
REFRESH_COOKIE_PATH = "/api/v1/auth"
SESSION_IDLE_MINUTES = 24 * 60
SESSION_MAX_DAYS = 30
DISCORD_PERMISSION_CHECK_MINUTES = 5


@asynccontextmanager
async def _discord_client(request: Request):
    application = request.scope.get("app")
    shared_client = getattr(getattr(application, "state", None), "discord_http_client", None)
    if shared_client is not None:
        yield shared_client
        return
    async with httpx.AsyncClient(base_url=DISCORD_API_URL, timeout=10) as client:
        yield client


def _cookie_options() -> dict[str, object]:
    return {
        "secure": os.getenv("APP_ENV", "development").strip().lower() == "production",
        "samesite": os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower(),
    }


def _set_auth_cookies(response, access_token: str, refresh_cookie: str, csrf_token: str, refresh_max_age: int) -> None:
    options = _cookie_options()
    response.set_cookie(
        ACCESS_COOKIE,
        access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path=ACCESS_COOKIE_PATH,
        httponly=True,
        **options,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_cookie,
        max_age=max(refresh_max_age, 0),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        **options,
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max(refresh_max_age, 0),
        path="/",
        httponly=False,
        **options,
    )


def _clear_auth_cookies(response) -> None:
    options = _cookie_options()
    response.delete_cookie(ACCESS_COOKIE, path=ACCESS_COOKIE_PATH, httponly=True, **options)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, httponly=True, **options)
    response.delete_cookie(CSRF_COOKIE, path="/", httponly=False, **options)


def _refresh_cookie_parts(raw: str | None) -> tuple[str, str] | None:
    if not isinstance(raw, str) or "." not in raw:
        return None
    session_id, secret = raw.split(".", 1)
    if not session_id or len(session_id) > 64 or len(secret) < 32 or len(secret) > 128:
        return None
    if not all(character.isalnum() or character in "_-" for character in session_id + secret):
        return None
    return session_id, secret


def _refresh_digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _manageable_guild_ids(response_guilds: list[dict]) -> list[str]:
    guild_ids = set()
    for guild in response_guilds:
        if not isinstance(guild, dict) or not str(guild.get("id", "")).isdigit():
            continue
        try:
            permissions = int(guild.get("permissions", 0))
        except (TypeError, ValueError):
            permissions = 0
        if guild.get("owner") or permissions & 8 or permissions & 32:
            guild_ids.add(str(guild["id"]))
    return sorted(guild_ids)


def _session_access_token(session: ApiAuthSession) -> str:
    return create_access_token({
        "id": str(session.user_id),
        "username": session.username,
        "avatar": session.avatar_hash,
        "system_role": get_system_role(session.user_id).value,
        "guilds": list(session.guild_ids or []),
        "sid": session.id,
    })


def _session_refresh_max_age(session: ApiAuthSession, now: datetime) -> int:
    absolute_expiration = session.created_at + timedelta(days=SESSION_MAX_DAYS)
    expires_at = min(session.expires_at, absolute_expiration)
    return max(int((expires_at - now).total_seconds()), 0)


async def _create_api_session(
    db: AsyncSession,
    user_data: dict,
    guild_ids: list[str],
    provider_access_token: str,
    provider_refresh_token: str,
    provider_expires_in: int,
) -> tuple[ApiAuthSession, str, str]:
    if not provider_access_token or not provider_refresh_token or provider_expires_in < 60:
        raise HTTPException(status_code=502, detail="Resposta OAuth do Discord incompleta")
    now = datetime.now(timezone.utc)
    session_id = secrets.token_urlsafe(32)
    refresh_secret = secrets.token_urlsafe(48)
    avatar_hash = user_data.get("avatar")
    if avatar_hash is not None:
        avatar_hash = str(avatar_hash)[:128]
    session = ApiAuthSession(
        id=session_id,
        user_id=int(user_data["id"]),
        username=str(user_data.get("username", "Discord User"))[:200],
        avatar_hash=avatar_hash,
        guild_ids=list(guild_ids),
        refresh_token_hash=_refresh_digest(refresh_secret),
        discord_access_token_encrypted=encrypt_provider_token(provider_access_token),
        discord_refresh_token_encrypted=encrypt_provider_token(provider_refresh_token),
        discord_token_expires_at=now + timedelta(seconds=provider_expires_in),
        discord_permissions_checked_at=now,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(minutes=SESSION_IDLE_MINUTES),
        revoked_at=None,
    )
    await db.execute(delete(ApiAuthSession).where(
        (ApiAuthSession.expires_at < now - timedelta(days=SESSION_MAX_DAYS))
        | (ApiAuthSession.revoked_at.is_not(None) & (ApiAuthSession.revoked_at < now - timedelta(days=90)))
    ))
    db.add(session)
    await db.commit()
    return session, f"{session_id}.{refresh_secret}", secrets.token_urlsafe(32)


async def discord_login(request: Request):
    if not CLIENT_ID or not REDIRECT_URI:
        raise HTTPException(status_code=503, detail="Login com Discord não está configurado")
    state = new_state()
    store_oauth_state(request.session, state)
    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "identify guilds",
        "state": state,
    }
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{urlencode(params)}", status_code=302)


@router.get("/login", summary="Login com Discord")
async def login(request: Request):
    return await discord_login(request)


@router.get("/callback", summary="Callback OAuth2 do Discord")
async def discord_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if not consume_oauth_state(request.session, state or ""):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Estado OAuth inválido ou expirado. Reinicie o login.")
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="O login com Discord foi cancelado ou recusado")
    if not code or not CLIENT_ID or not CLIENT_SECRET:
        code_status = status.HTTP_400_BAD_REQUEST if not code else status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=code_status, detail="Callback OAuth incompleto ou login não configurado")
    try:
        async with _discord_client(request) as client:
            token_response = await client.post(
                "/oauth2/token",
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_response.status_code != 200:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Falha na autorização com Discord")
            token_payload = token_response.json()
            provider_access_token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
            provider_refresh_token = token_payload.get("refresh_token") if isinstance(token_payload, dict) else None
            try:
                provider_expires_in = int(token_payload.get("expires_in", 0)) if isinstance(token_payload, dict) else 0
            except (TypeError, ValueError):
                provider_expires_in = 0
            if not isinstance(provider_access_token, str) or not provider_access_token or not isinstance(provider_refresh_token, str) or not provider_refresh_token or provider_expires_in < 60:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Resposta OAuth incompleta do Discord")
            authorization = {"Authorization": f"Bearer {provider_access_token}"}
            user_response = await client.get("/users/@me", headers=authorization)
            if user_response.status_code != 200:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível confirmar a conta Discord")
            user_data = user_response.json()
            if not isinstance(user_data, dict) or not str(user_data.get("id", "")).isdigit():
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Perfil inválido retornado pelo Discord")
            guilds_response = await client.get("/users/@me/guilds", headers=authorization)
            if guilds_response.status_code != 200:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Não foi possível verificar as permissões nos servidores")
            response_guilds = guilds_response.json()
            if not isinstance(response_guilds, list):
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Lista de servidores inválida retornada pelo Discord")
    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="O serviço de autenticação do Discord excedeu o tempo limite") from None
    except httpx.RequestError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Serviço de autenticação do Discord indisponível") from None

    user_id = str(user_data["id"])
    session, refresh_cookie, csrf_token = await _create_api_session(
        db,
        user_data,
        _manageable_guild_ids(response_guilds),
        provider_access_token,
        provider_refresh_token,
        provider_expires_in,
    )
    access_token = _session_access_token(session)
    request.session.clear()
    response = RedirectResponse(DASHBOARD_URL, status_code=303)
    _set_auth_cookies(response, access_token, refresh_cookie, csrf_token, _session_refresh_max_age(session, datetime.now(timezone.utc)))
    response.headers["Cache-Control"] = "no-store"
    return response


legacy_callback_router = APIRouter()
legacy_callback_router.add_api_route(
    "/auth/callback",
    discord_callback,
    methods=["GET"],
    name="discord_callback_legacy",
    include_in_schema=False,
)


@router.post("/refresh", summary="Renovar sessão do dashboard")
async def refresh_session(request: Request, db: AsyncSession = Depends(get_db)):
    parts = _refresh_cookie_parts(request.cookies.get(REFRESH_COOKIE))
    if parts is None:
        response = JSONResponse({"detail": "Sessão inválida. Entre novamente com o Discord."}, status_code=401)
        _clear_auth_cookies(response)
        return response
    session_id, supplied_secret = parts
    session = (await db.execute(
        select(ApiAuthSession).where(ApiAuthSession.id == session_id).with_for_update()
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if session is None:
        response = JSONResponse({"detail": "Sessão inválida. Entre novamente com o Discord."}, status_code=401)
        _clear_auth_cookies(response)
        return response
    supplied_digest = _refresh_digest(supplied_secret)
    if not hmac.compare_digest(session.refresh_token_hash, supplied_digest):
        previous_digest = getattr(session, "previous_refresh_token_hash", None)
        previous_until = getattr(session, "previous_refresh_until", None)
        if (
            session.revoked_at is None
            and isinstance(previous_digest, str)
            and hmac.compare_digest(previous_digest, supplied_digest)
            and isinstance(previous_until, datetime)
            and now <= previous_until
        ):
            return JSONResponse(
                {"detail": "A renovação desta sessão já foi processada. Reutilize o cookie atualizado."},
                status_code=409,
                headers={"Cache-Control": "no-store"},
            )
        if session.revoked_at is None:
            session.revoked_at = now
            session.updated_at = now
            await db.commit()
        response = JSONResponse({"detail": "Sessão revogada. Entre novamente com o Discord."}, status_code=401)
        _clear_auth_cookies(response)
        return response
    absolute_expiration = session.created_at + timedelta(days=SESSION_MAX_DAYS)
    if session.revoked_at is not None or session.expires_at <= now or absolute_expiration <= now:
        if session.revoked_at is None:
            session.revoked_at = now
            session.updated_at = now
            await db.commit()
        response = JSONResponse({"detail": "Sessão expirada. Entre novamente com o Discord."}, status_code=401)
        _clear_auth_cookies(response)
        return response

    provider_access_token = decrypt_provider_token(session.discord_access_token_encrypted)
    provider_token_expired = session.discord_token_expires_at <= now + timedelta(seconds=60)
    try:
        async with _discord_client(request) as client:
            if provider_token_expired:
                refresh_token = decrypt_provider_token(session.discord_refresh_token_encrypted)
                provider_response = await client.post(
                    "/oauth2/token",
                    data={
                        "client_id": CLIENT_ID,
                        "client_secret": CLIENT_SECRET,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if provider_response.status_code == 400:
                    session.revoked_at = now
                    session.updated_at = now
                    await db.commit()
                    response = JSONResponse({"detail": "A autorização do Discord expirou. Entre novamente."}, status_code=401)
                    _clear_auth_cookies(response)
                    return response
                if provider_response.status_code != 200:
                    raise HTTPException(status_code=503, detail="Não foi possível renovar a autorização com Discord")
                refreshed = provider_response.json()
                new_access = refreshed.get("access_token") if isinstance(refreshed, dict) else None
                new_refresh = refreshed.get("refresh_token") if isinstance(refreshed, dict) else None
                try:
                    provider_expires_in = int(refreshed.get("expires_in", 0)) if isinstance(refreshed, dict) else 0
                except (TypeError, ValueError):
                    provider_expires_in = 0
                if not isinstance(new_access, str) or not new_access or provider_expires_in < 60:
                    raise HTTPException(status_code=502, detail="Resposta de renovação inválida do Discord")
                provider_access_token = new_access
                session.discord_access_token_encrypted = encrypt_provider_token(new_access)
                if isinstance(new_refresh, str) and new_refresh:
                    session.discord_refresh_token_encrypted = encrypt_provider_token(new_refresh)
                session.discord_token_expires_at = now + timedelta(seconds=provider_expires_in)

            permissions_are_stale = (
                session.discord_permissions_checked_at is None
                or now - session.discord_permissions_checked_at >= timedelta(minutes=DISCORD_PERMISSION_CHECK_MINUTES)
                or provider_token_expired
            )
            if permissions_are_stale:
                authorization = {"Authorization": f"Bearer {provider_access_token}"}
                user_response = await client.get("/users/@me", headers=authorization)
                if user_response.status_code != 200:
                    raise HTTPException(status_code=502, detail="Não foi possível atualizar a conta Discord")
                user_data = user_response.json()
                if not isinstance(user_data, dict) or str(user_data.get("id", "")) != str(session.user_id):
                    session.revoked_at = now
                    session.updated_at = now
                    await db.commit()
                    response = JSONResponse({"detail": "A conta Discord da sessão foi alterada. Entre novamente."}, status_code=401)
                    _clear_auth_cookies(response)
                    return response
                guilds_response = await client.get("/users/@me/guilds", headers=authorization)
                if guilds_response.status_code != 200:
                    raise HTTPException(status_code=502, detail="Não foi possível atualizar as permissões dos servidores")
                response_guilds = guilds_response.json()
                if not isinstance(response_guilds, list):
                    raise HTTPException(status_code=502, detail="Lista de servidores inválida retornada pelo Discord")
                session.guild_ids = _manageable_guild_ids(response_guilds)
                session.username = str(user_data.get("username", session.username))[:200]
                avatar_hash = user_data.get("avatar")
                session.avatar_hash = str(avatar_hash)[:128] if avatar_hash is not None else None
                session.discord_permissions_checked_at = now

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="O serviço de autenticação do Discord excedeu o tempo limite") from None
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Serviço de autenticação do Discord indisponível") from None

    new_refresh_secret = secrets.token_urlsafe(48)
    session.previous_refresh_token_hash = session.refresh_token_hash
    session.previous_refresh_until = now + timedelta(seconds=5)
    session.refresh_token_hash = _refresh_digest(new_refresh_secret)
    session.updated_at = now
    session.expires_at = min(now + timedelta(minutes=SESSION_IDLE_MINUTES), absolute_expiration)
    access_token = _session_access_token(session)
    await db.commit()
    refresh_cookie = f"{session.id}.{new_refresh_secret}"
    csrf_token = secrets.token_urlsafe(32)
    response = JSONResponse({"status": "refreshed"})
    _set_auth_cookies(response, access_token, refresh_cookie, csrf_token, _session_refresh_max_age(session, now))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/me", summary="Obter dados do usuário autenticado")
async def get_me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "username": user["username"],
        "avatar": user.get("avatar"),
        "system_role": user["system_role"],
        "guilds": user["guilds"],
        "expires_at": user.get("exp"),
    }


@router.post("/logout", summary="Encerrar autenticação do dashboard")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    refresh_parts = _refresh_cookie_parts(request.cookies.get(REFRESH_COOKIE))
    session_id = refresh_parts[0] if refresh_parts else None
    if session_id is None:
        from api.core.security import decode_access_token
        access_payload = decode_access_token(request.cookies.get(ACCESS_COOKIE, ""))
        if access_payload:
            session_id = access_payload.get("sid")
    if session_id:
        session = await db.get(ApiAuthSession, session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = datetime.now(timezone.utc)
            session.updated_at = datetime.now(timezone.utc)
            await db.commit()
    request.session.clear()
    response = JSONResponse({"status": "logged_out"})
    _clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return response
