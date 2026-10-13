from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.models import Experience
from app.core.time import utc_now

def required_xp(level: int) -> int:
    return 100 * (level + 1) ** 2

def level_from_xp(total_xp: int) -> int:
    level = 0
    while total_xp >= required_xp(level):
        total_xp -= required_xp(level)
        level += 1
    return level

async def add_xp(session: AsyncSession, guild_id: int, user_id: int, amount: int) -> tuple[int, int, bool]:
    if amount <= 0:
        raise ValueError("amount must be positive")
    result = await session.execute(select(Experience).where(Experience.guild_id == guild_id, Experience.user_id == user_id).with_for_update())
    row = result.scalar_one_or_none()
    now = utc_now()
    if row is None:
        try:
            async with session.begin_nested():
                row = Experience(guild_id=guild_id, user_id=user_id, total_xp=0, level=0, rewarded_level=0, created_at=now, updated_at=now)
                session.add(row)
                await session.flush()
        except IntegrityError:
            result = await session.execute(select(Experience).where(Experience.guild_id == guild_id, Experience.user_id == user_id).with_for_update())
            row = result.scalar_one_or_none()
            if row is None:
                raise
    old_level = row.level
    row.total_xp += amount
    row.level = level_from_xp(row.total_xp)
    row.updated_at = now
    await session.flush()
    return row.total_xp, row.level, row.level > old_level
