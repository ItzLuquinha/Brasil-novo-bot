from datetime import datetime, timezone
import secrets
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import CommandUsage, Member, MessageLog, MemberActivity, ChannelActivity, EconomyAccount, Warning, Ticket, Report, Suggestion, AnalyticsConfig

async def overview(session: AsyncSession, guild_id: int) -> dict[str, int | float]:
    statement = select(
        select(func.count(Member.id)).where(
            Member.guild_id == guild_id, Member.left_at.is_(None)
        ).scalar_subquery().label("members"),
        select(func.count(MessageLog.id)).where(
            MessageLog.guild_id == guild_id
        ).scalar_subquery().label("messages"),
        select(func.coalesce(func.sum(EconomyAccount.wallet + EconomyAccount.bank), 0)).where(
            EconomyAccount.guild_id == guild_id
        ).scalar_subquery().label("economy"),
        select(func.count(Warning.id)).where(
            Warning.guild_id == guild_id, Warning.active.is_(True)
        ).scalar_subquery().label("warnings"),
        select(func.count(Ticket.id)).where(
            Ticket.guild_id == guild_id, Ticket.status == "open"
        ).scalar_subquery().label("tickets"),
        select(func.count(Report.id)).where(
            Report.guild_id == guild_id, Report.status == "open"
        ).scalar_subquery().label("reports"),
        select(func.count(Suggestion.id)).where(
            Suggestion.guild_id == guild_id, Suggestion.status == "pending"
        ).scalar_subquery().label("pending_suggestions"),
    )
    result = await session.execute(statement)
    row = result.mappings().one()
    return {
        "members": int(row["members"] or 0),
        "messages": int(row["messages"] or 0),
        "economy": float(row["economy"] or 0),
        "warnings": int(row["warnings"] or 0),
        "tickets": int(row["tickets"] or 0),
        "reports": int(row["reports"] or 0),
        "pending_suggestions": int(row["pending_suggestions"] or 0),
    }


COMMAND_CATEGORIES = {
    "normal": {"ping", "uptime", "botinfo", "serverinfo", "userinfo", "avatar", "remind", "tutorial", "dashboard", "history"},
    "economia": {"balance", "bank", "deposit", "withdraw", "pay", "daily", "weekly", "shop", "buy", "sell", "inventory", "transactions", "jobs", "job", "work"},
    "progressao": {"profile", "rep", "reps", "leaderboard"},
    "moderacao": {"warn", "t-warn", "warns", "unwarn", "clearwarns", "timeout", "untimeout", "unmute", "kick", "ban", "unban", "purge"},
    "comunidade": {"ticket", "ticket-close", "ticket-reopen", "ticket-claim", "ticket-config", "suggest", "suggestion-status", "report", "report-status", "giveaway", "poll", "community-config"},
    "seguranca": {"automod", "antiraid"},
    "administracao": {"msg", "admin", "admin credit", "admin debit", "admin shop-add", "admin job-add", "admin job-remove", "admin rewards", "admin timezone"},
    "diversao": {"coinflip", "dice", "rps", "eightball"},
}

CATEGORY_LABELS = {
    "normal": "Normais",
    "economia": "Economia",
    "progressao": "Progressão",
    "moderacao": "Moderação",
    "comunidade": "Comunidade",
    "seguranca": "Segurança",
    "administracao": "Administração",
    "diversao": "Diversão",
}


def command_category(command_name: str) -> str:
    normalized = command_name.strip().casefold()
    root = normalized.split(" ", 1)[0]
    for category, names in COMMAND_CATEGORIES.items():
        if normalized in names or root in names:
            return category
    return "normal"


async def record_command_usage(
    session: AsyncSession,
    user_id: int,
    guild_id: int | None,
    channel_id: int | None,
    command_name: str,
    success: bool,
    error_type: str | None = None,
) -> None:
    session.add(CommandUsage(
        id=secrets.randbits(62),
        guild_id=guild_id,
        user_id=user_id,
        channel_id=channel_id,
        command_name=command_name,
        category=command_category(command_name),
        success=success,
        error_type=error_type[:120] if error_type else None,
        used_at=datetime.now(timezone.utc),
    ))


async def record_message(
    session: AsyncSession, guild_id: int, user_id: int, channel_id: int, message_id: int,
    content_length: int, bucket_start: datetime, created_at: datetime | None = None,
) -> bool:
    current = datetime.now(timezone.utc)
    event_time = created_at or current
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    event_time = event_time.astimezone(timezone.utc)
    message_stmt = pg_insert(MessageLog).values(
        id=message_id, guild_id=guild_id, channel_id=channel_id, user_id=user_id,
        message_id=message_id, event="create", content_length=max(0, content_length), created_at=event_time,
    ).on_conflict_do_nothing(index_elements=[MessageLog.id]).returning(MessageLog.id)
    inserted_id = (await session.execute(message_stmt)).scalar_one_or_none()
    if inserted_id is None:
        return False
    member = (await session.execute(
        select(Member).where(Member.guild_id == guild_id, Member.user_id == user_id).with_for_update()
    )).scalar_one_or_none()
    if member:
        member.message_count += 1
        member.activity_score += 1
        member.updated_at = current
    member_activity_stmt = pg_insert(MemberActivity).values(
        guild_id=guild_id, user_id=user_id, bucket_start=bucket_start,
        metric="messages", value=1,
    ).on_conflict_do_update(
        index_elements=[MemberActivity.guild_id, MemberActivity.user_id, MemberActivity.bucket_start, MemberActivity.metric],
        set_={"value": MemberActivity.value + 1},
    )
    await session.execute(member_activity_stmt)
    channel_activity_stmt = pg_insert(ChannelActivity).values(
        guild_id=guild_id, channel_id=channel_id, bucket_start=bucket_start,
        metric="messages", value=1,
    ).on_conflict_do_update(
        index_elements=[ChannelActivity.guild_id, ChannelActivity.channel_id, ChannelActivity.bucket_start, ChannelActivity.metric],
        set_={"value": ChannelActivity.value + 1},
    )
    await session.execute(channel_activity_stmt)
    return True


async def record_voice_segment(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    channel_id: int,
    started_at: datetime,
    ended_at: datetime,
) -> int:
    from datetime import timedelta
    from app.services.analytics import floor_hour

    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    start = started_at.astimezone(timezone.utc)
    end = ended_at.astimezone(timezone.utc)
    if end <= start:
        return 0
    total_seconds = max(0, int((end - start).total_seconds()))
    cursor = start
    remaining = total_seconds
    while cursor < end and remaining > 0:
        bucket = floor_hour(cursor)
        next_bucket = bucket + timedelta(hours=1)
        segment_seconds = min(remaining, max(1, int((min(end, next_bucket) - cursor).total_seconds())))
        if segment_seconds <= 0:
            break
        member_activity_stmt = pg_insert(MemberActivity).values(
            guild_id=guild_id, user_id=user_id, bucket_start=bucket,
            metric="voice_seconds", value=segment_seconds,
        ).on_conflict_do_update(
            index_elements=[MemberActivity.guild_id, MemberActivity.user_id, MemberActivity.bucket_start, MemberActivity.metric],
            set_={"value": MemberActivity.value + segment_seconds},
        )
        await session.execute(member_activity_stmt)
        channel_activity_stmt = pg_insert(ChannelActivity).values(
            guild_id=guild_id, channel_id=channel_id, bucket_start=bucket,
            metric="voice_seconds", value=segment_seconds,
        ).on_conflict_do_update(
            index_elements=[ChannelActivity.guild_id, ChannelActivity.channel_id, ChannelActivity.bucket_start, ChannelActivity.metric],
            set_={"value": ChannelActivity.value + segment_seconds},
        )
        await session.execute(channel_activity_stmt)
        remaining -= segment_seconds
        cursor = min(end, cursor + timedelta(seconds=segment_seconds))
    return total_seconds


def analytics_message_allowed(config: AnalyticsConfig | None, message, bot_id: int | None = None) -> bool:
    from app.services.analytics import message_is_eligible
    channel = getattr(message, "channel", None)
    category = getattr(channel, "category_id", None)
    author = getattr(message, "author", None)
    roles = [getattr(role, "id", 0) for role in getattr(author, "roles", [])]
    return message_is_eligible(
        config,
        channel_id=int(getattr(channel, "id", 0)),
        category_id=int(category) if category else None,
        role_ids=roles,
        content=str(getattr(message, "content", "")),
        bot_id=bot_id,
        is_bot=bool(getattr(author, "bot", False)),
    )
