from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import SystemRole, decode_access_token, get_system_role
from api.database import get_db
from app.models import ApiAuthSession, Guild

security = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sessão inválida ou expirada. Entre novamente com o Discord.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> dict:
    token = credentials.credentials if credentials and credentials.scheme.casefold() == "bearer" else request.cookies.get("bn_access")
    if not token:
        raise _unauthorized()
    payload = decode_access_token(token)
    if not payload:
        raise _unauthorized()
    session = await db.get(ApiAuthSession, payload["sid"])
    now = datetime.now(timezone.utc)
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise _unauthorized()
    if session.user_id != int(payload["id"]):
        raise _unauthorized()
    payload["username"] = session.username
    payload["avatar"] = session.avatar_hash
    payload["guilds"] = [str(item) for item in session.guild_ids if str(item).isdigit()]
    payload["system_role"] = get_system_role(payload["id"]).value
    return payload


async def require_guild_manager(
    guild_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    guild = await db.get(Guild, guild_id)
    if guild is None or getattr(guild, "active", True) is False:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    if current_user.get("system_role") == SystemRole.ADMIN.value:
        return current_user
    user_id = int(current_user["id"])
    if guild.owner_id == user_id:
        return current_user
    manageable = {str(item) for item in current_user.get("guilds", []) if str(item).isdigit()}
    if str(guild_id) in manageable:
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não tem permissão para gerenciar este servidor.")


async def require_system_moderator(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("system_role") in {SystemRole.MODERATOR.value, SystemRole.ADMIN.value}:
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito à equipe de moderação do sistema.")


async def require_system_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("system_role") == SystemRole.ADMIN.value:
        return current_user
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito aos administradores do sistema.")
