from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Guild, GuildSettings, User, Member

def now() -> datetime:
    return datetime.now(timezone.utc)

async def ensure_guild(session: AsyncSession, guild_id: int, name: str, owner_id: int | None = None, icon_url: str | None = None, reactivate: bool = False) -> Guild:
    guild = await session.get(Guild, guild_id)
    current = now()
    if guild is None:
        try:
            async with session.begin_nested():
                guild = Guild(id=guild_id, name=name, owner_id=owner_id, icon_url=icon_url, created_at=current, updated_at=current)
                session.add(guild)
                await session.flush()
        except IntegrityError:
            guild = await session.get(Guild, guild_id)
            if guild is None:
                raise
    guild.name = name
    guild.owner_id = owner_id
    guild.icon_url = icon_url
    if reactivate:
        guild.active = True
    guild.updated_at = current
    settings = await session.get(GuildSettings, guild_id)
    if settings is None:
        try:
            async with session.begin_nested():
                settings = GuildSettings(guild_id=guild_id, created_at=current, updated_at=current)
                session.add(settings)
                await session.flush()
        except IntegrityError:
            settings = await session.get(GuildSettings, guild_id)
            if settings is None:
                raise
    await session.flush()
    return guild


async def ensure_user(session: AsyncSession, user_id: int, username: str, display_name: str, avatar_url: str | None = None, banner_url: str | None = None, bot: bool = False) -> User:
    user = await session.get(User, user_id)
    current = now()
    if user is None:
        try:
            async with session.begin_nested():
                user = User(id=user_id, username=username, display_name=display_name, avatar_url=avatar_url, banner_url=banner_url, bot=bot, created_at=current, updated_at=current)
                session.add(user)
                await session.flush()
        except IntegrityError:
            user = await session.get(User, user_id)
            if user is None:
                raise
    user.username = username
    user.display_name = display_name
    user.avatar_url = avatar_url
    if banner_url is not None:
        user.banner_url = banner_url
    user.bot = bot
    user.updated_at = current
    await session.flush()
    return user


async def ensure_member(session: AsyncSession, guild_id: int, user_id: int, joined_at: datetime | None) -> Member:
    result = await session.execute(select(Member).where(Member.guild_id == guild_id, Member.user_id == user_id))
    member = result.scalar_one_or_none()
    current = now()
    if member is None:
        try:
            async with session.begin_nested():
                member = Member(guild_id=guild_id, user_id=user_id, joined_at=joined_at, created_at=current, updated_at=current)
                session.add(member)
                await session.flush()
        except IntegrityError:
            result = await session.execute(select(Member).where(Member.guild_id == guild_id, Member.user_id == user_id))
            member = result.scalar_one_or_none()
            if member is None:
                raise
    if joined_at is not None:
        member.joined_at = joined_at
        member.left_at = None
    member.updated_at = current
    await session.flush()
    return member
