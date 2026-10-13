import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import jwt
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from dotenv import load_dotenv

load_dotenv()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
JWT_ISSUER = "bn-bot-api"
JWT_AUDIENCE = "bn-bot-dashboard"


class SystemRole(str, Enum):
    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


def get_secret_key() -> str:
    key = os.getenv("APP_SECRET_KEY", "").strip()
    placeholders = {"change-me", "changeme", "your-secret-here", "secret-key", "password"}
    if len(key) < 32 or key.casefold() in placeholders or len(set(key)) < 8:
        raise RuntimeError("APP_SECRET_KEY must be a strong randomly generated secret of at least 32 characters")
    configured_algorithm = os.getenv("JWT_ALGORITHM", ALGORITHM).strip()
    if configured_algorithm != ALGORITHM:
        raise RuntimeError(f"JWT_ALGORITHM must be {ALGORITHM}")
    return key


def validate_security_configuration() -> None:
    get_secret_key()


def encrypt_provider_token(token: str) -> str:
    if not token:
        raise ValueError("Provider token cannot be empty")
    key = hmac.new(get_secret_key().encode("utf-8"), b"bn-bot-discord-token-encryption-v1", hashlib.sha256).digest()
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(key).encrypt(nonce, token.encode("utf-8"), b"bn-bot-discord")
    return base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")


def decrypt_provider_token(encrypted_token: str) -> str:
    try:
        packed = base64.urlsafe_b64decode(encrypted_token.encode("ascii"))
        if len(packed) < 29:
            raise ValueError
        key = hmac.new(get_secret_key().encode("utf-8"), b"bn-bot-discord-token-encryption-v1", hashlib.sha256).digest()
        return AESGCM(key).decrypt(packed[:12], packed[12:], b"bn-bot-discord").decode("utf-8")
    except (InvalidTag, ValueError, UnicodeError, TypeError):
        raise RuntimeError("Stored Discord credential could not be decrypted") from None


def get_system_role(user_id: int | str) -> SystemRole:
    uid = str(user_id)
    admin_ids = {item.strip() for item in os.getenv("SYSTEM_ADMIN_IDS", "").split(",") if item.strip()}
    moderator_ids = {item.strip() for item in os.getenv("SYSTEM_MOD_IDS", "").split(",") if item.strip()}
    if uid in admin_ids:
        return SystemRole.ADMIN
    if uid in moderator_ids:
        return SystemRole.MODERATOR
    return SystemRole.USER


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    payload = data.copy()
    user_id = payload.get("id", payload.get("sub"))
    if not isinstance(user_id, (str, int)) or not str(user_id).isdigit() or int(user_id) <= 0:
        raise ValueError("A valid Discord user ID is required to issue an access token")
    role = payload.get("system_role", SystemRole.USER.value)
    if role not in {item.value for item in SystemRole}:
        raise ValueError("Invalid system role")
    guilds = payload.get("guilds", [])
    if not isinstance(guilds, list) or any(not str(guild_id).isdigit() or int(guild_id) <= 0 for guild_id in guilds):
        raise ValueError("Invalid guild access claims")
    if expires_delta is not None and expires_delta.total_seconds() <= 0:
        raise ValueError("Token expiry must be in the future")
    session_id = payload.get("sid") or secrets.token_urlsafe(32)
    if not isinstance(session_id, str) or not session_id or len(session_id) > 64:
        raise ValueError("Invalid session identifier")
    now = datetime.now(timezone.utc)
    expiration = now + (expires_delta if expires_delta is not None else timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload.update({
        "id": str(user_id),
        "sub": str(user_id),
        "sid": session_id,
        "iat": now,
        "nbf": now,
        "exp": expiration,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": secrets.token_urlsafe(24),
    })
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(
            token,
            get_secret_key(),
            algorithms=[ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub", "jti", "sid"]},
            leeway=15,
        )
    except (jwt.PyJWTError, TypeError, ValueError):
        return None
    user_id = payload.get("id", payload.get("sub"))
    role = payload.get("system_role", SystemRole.USER.value)
    guilds = payload.get("guilds", [])
    session_id = payload.get("sid")
    if not isinstance(user_id, (str, int)) or not str(user_id).isdigit() or int(user_id) <= 0:
        return None
    if str(payload.get("sub")) != str(user_id):
        return None
    if role not in {item.value for item in SystemRole}:
        return None
    if not isinstance(session_id, str) or not session_id or len(session_id) > 64:
        return None
    if not isinstance(guilds, list) or any(not str(guild_id).isdigit() or int(guild_id) <= 0 for guild_id in guilds):
        return None
    payload["id"] = str(user_id)
    payload["guilds"] = [str(guild_id) for guild_id in guilds]
    return payload
