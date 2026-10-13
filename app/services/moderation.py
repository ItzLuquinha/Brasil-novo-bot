from datetime import datetime, timezone
import secrets
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Warning, Punishment, ModerationLog

def now() -> datetime:
    return datetime.now(timezone.utc)

def log_id() -> int:
    return secrets.randbits(62)

async def add_warning(session: AsyncSession, guild_id: int, user_id: int, moderator_id: int, reason: str, expires_at: datetime | None = None) -> int:
    warning = Warning(guild_id=guild_id, user_id=user_id, moderator_id=moderator_id, reason=reason, created_at=now(), expires_at=expires_at, active=True)
    session.add(warning)
    session.add(ModerationLog(id=log_id(), guild_id=guild_id, actor_id=moderator_id, target_id=user_id, kind="warn", reason=reason, created_at=now()))
    await session.commit()
    return warning.id

async def count_active_warnings(session: AsyncSession, guild_id: int, user_id: int) -> int:
    result = await session.execute(select(func.count(Warning.id)).where(Warning.guild_id == guild_id, Warning.user_id == user_id, Warning.active.is_(True)))
    return int(result.scalar_one() or 0)

async def list_warnings(session: AsyncSession, guild_id: int, user_id: int) -> list[Warning]:
    result = await session.execute(select(Warning).where(Warning.guild_id == guild_id, Warning.user_id == user_id).order_by(Warning.created_at.desc()))
    return list(result.scalars())

async def deactivate_warning(session: AsyncSession, guild_id: int, warning_id: int, moderator_id: int) -> bool:
    warning = await session.get(Warning, warning_id, with_for_update=True)
    if warning is None or warning.guild_id != guild_id:
        raise ValueError("warning not found")
    if not warning.active:
        return False
    warning.active = False
    session.add(ModerationLog(id=log_id(), guild_id=guild_id, actor_id=moderator_id, target_id=warning.user_id, kind="unwarn", data={"warning_id": warning_id}, created_at=now()))
    await session.commit()
    return True

async def record_punishment(session: AsyncSession, guild_id: int, user_id: int, moderator_id: int, kind: str, reason: str | None, expires_at: datetime | None = None, data: dict | None = None) -> None:
    current = now()
    session.add(Punishment(guild_id=guild_id, user_id=user_id, moderator_id=moderator_id, kind=kind, reason=reason, created_at=current, expires_at=expires_at, metadata_json=data or {}))
    session.add(ModerationLog(id=log_id(), guild_id=guild_id, actor_id=moderator_id, target_id=user_id, kind=kind, reason=reason, data=data or {}, created_at=current))
    await session.commit()
