from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Date, and_, case, cast, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActivityRoleRule,
    AnalyticsConfig,
    ChannelActivity,
    GuildActivity,
    MemberActivity,
    Member,
    StatCounter,
    User,
)

SUPPORTED_METRICS = {
    "messages": "Mensagens",
    "voice_seconds": "Segundos em voz",
    "active_members": "Membros ativos",
    "member_count": "Membros",
    "human_members": "Membros humanos",
    "bot_members": "Bots",
    "voice_members": "Membros em voz",
    "joins": "Entradas",
    "leaves": "Saídas",
    "messages_period": "Mensagens no período",
    "active_members_period": "Membros ativos no período",
}


def floor_hour(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def normalize_id_list(values: list[Any] | None) -> list[int]:
    normalized: set[int] = set()
    for value in values or []:
        if isinstance(value, bool):
            continue
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if number > 0:
            normalized.add(number)
    return sorted(normalized)


def message_is_eligible(config: AnalyticsConfig | None, *, channel_id: int, category_id: int | None,
                        role_ids: list[int], content: str, bot_id: int | None = None,
                        is_bot: bool = False) -> bool:
    exclude_bots = bool(getattr(config, "exclude_bots", True))
    exclude_commands = bool(getattr(config, "exclude_commands", True))
    if is_bot and exclude_bots:
        return False
    if channel_id in normalize_id_list(getattr(config, "excluded_channel_ids", None)):
        return False
    if category_id and category_id in normalize_id_list(getattr(config, "excluded_category_ids", None)):
        return False
    excluded_roles = set(normalize_id_list(getattr(config, "excluded_role_ids", None)))
    if excluded_roles.intersection(normalize_id_list(role_ids)):
        return False
    if exclude_commands and bot_id is not None:
        if content.startswith(f"<@{bot_id}>") or content.startswith(f"<@!{bot_id}>"):
            return False
    return True


def voice_is_eligible(config: AnalyticsConfig | None, *, channel_id: int | None,
                      category_id: int | None, role_ids: list[int], is_bot: bool = False) -> bool:
    if not bool(getattr(config, "track_voice", True)):
        return False
    if is_bot and bool(getattr(config, "exclude_bots", True)):
        return False
    if channel_id is not None and channel_id in normalize_id_list(getattr(config, "excluded_channel_ids", None)):
        return False
    if category_id and category_id in normalize_id_list(getattr(config, "excluded_category_ids", None)):
        return False
    if set(normalize_id_list(getattr(config, "excluded_role_ids", None))).intersection(normalize_id_list(role_ids)):
        return False
    return True


def period_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime, str]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    duration = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}.get(period)
    if duration is None:
        raise ValueError("Período inválido")
    return current - duration, current, period


def percent_change(current: int | float, previous: int | float) -> float | None:
    if previous == 0:
        return None
    return round(((current - previous) / abs(previous)) * 100, 2)


async def activity_series(session: AsyncSession, guild_id: int, metric: str, days: int) -> list[dict[str, int | str]]:
    if metric not in {"messages", "voice_seconds"}:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    result = await session.execute(
        select(MemberActivity.bucket_start, func.sum(MemberActivity.value))
        .where(MemberActivity.guild_id == guild_id, MemberActivity.metric == metric, MemberActivity.bucket_start >= since)
        .group_by(MemberActivity.bucket_start)
        .order_by(MemberActivity.bucket_start.asc())
    )
    return [{"bucket": bucket.isoformat(), "value": int(value)} for bucket, value in result.all()]


async def top_channels(session: AsyncSession, guild_id: int, metric: str, limit: int = 10, days: int | None = None) -> list[dict[str, int | str]]:
    if metric not in {"messages", "voice_seconds"}:
        return []
    filters = [ChannelActivity.guild_id == guild_id, ChannelActivity.metric == metric]
    if days is not None:
        filters.append(ChannelActivity.bucket_start >= datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365))))
    result = await session.execute(
        select(ChannelActivity.channel_id, func.sum(ChannelActivity.value).label("total"))
        .where(*filters)
        .group_by(ChannelActivity.channel_id)
        .order_by(func.sum(ChannelActivity.value).desc(), ChannelActivity.channel_id.asc())
        .limit(max(1, min(limit, 100)))
    )
    return [{"channel_id": int(channel_id), "value": int(total)} for channel_id, total in result.all()]


async def get_or_create_analytics_config(session: AsyncSession, guild_id: int) -> AnalyticsConfig:
    from sqlalchemy.exc import IntegrityError

    config = await session.get(AnalyticsConfig, guild_id)
    if config is not None:
        return config
    now = datetime.now(timezone.utc)
    try:
        async with session.begin_nested():
            config = AnalyticsConfig(guild_id=guild_id, created_at=now, updated_at=now)
            session.add(config)
            await session.flush()
    except IntegrityError:
        config = await session.get(AnalyticsConfig, guild_id)
        if config is None:
            raise
    return config


async def analytics_report(
    session: AsyncSession,
    guild_id: int,
    start: datetime,
    end: datetime,
    excluded_channel_ids: list[int] | None = None,
) -> dict[str, Any]:
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    if start >= end:
        raise ValueError("O início do período deve ser anterior ao fim")
    member_filters = [
        MemberActivity.guild_id == guild_id,
        MemberActivity.bucket_start >= start,
        MemberActivity.bucket_start < end,
        MemberActivity.metric.in_(["messages", "voice_seconds"]),
    ]
    channel_filters = [
        ChannelActivity.guild_id == guild_id,
        ChannelActivity.bucket_start >= start,
        ChannelActivity.bucket_start < end,
        ChannelActivity.metric.in_(["messages", "voice_seconds"]),
    ]
    result = await session.execute(
        select(MemberActivity.bucket_start, MemberActivity.metric, func.sum(MemberActivity.value))
        .where(*member_filters)
        .group_by(MemberActivity.bucket_start, MemberActivity.metric)
        .order_by(MemberActivity.bucket_start.asc())
    )
    by_bucket: dict[str, dict[str, int]] = {}
    for bucket, metric, value in result.all():
        key = bucket.astimezone(timezone.utc).isoformat()
        by_bucket.setdefault(key, {})[metric] = int(value or 0)

    sums = await session.execute(
        select(MemberActivity.metric, func.coalesce(func.sum(MemberActivity.value), 0))
        .where(*member_filters)
        .group_by(MemberActivity.metric)
    )
    totals = {metric: int(value or 0) for metric, value in sums.all()}
    active_members_query = await session.execute(
        select(func.count(distinct(MemberActivity.user_id)))
        .where(
            MemberActivity.guild_id == guild_id,
            MemberActivity.metric.in_(["messages", "voice_seconds"]),
            MemberActivity.value > 0,
            MemberActivity.bucket_start >= start,
            MemberActivity.bucket_start < end,
        )
    )
    active_members = int(active_members_query.scalar_one() or 0)
    join_leave_result = await session.execute(
        select(GuildActivity.bucket_start, GuildActivity.metric, func.sum(GuildActivity.value))
        .where(GuildActivity.guild_id == guild_id, GuildActivity.bucket_start >= start, GuildActivity.bucket_start < end)
        .group_by(GuildActivity.bucket_start, GuildActivity.metric)
        .order_by(GuildActivity.bucket_start.asc())
    )
    guild_series: dict[str, dict[str, int]] = {}
    for bucket, metric, value in join_leave_result.all():
        guild_series.setdefault(bucket.astimezone(timezone.utc).isoformat(), {})[metric] = int(value or 0)
    channel_result = await session.execute(
        select(ChannelActivity.channel_id, ChannelActivity.metric, func.sum(ChannelActivity.value).label("total"))
        .where(*channel_filters)
        .group_by(ChannelActivity.channel_id, ChannelActivity.metric)
        .order_by(func.sum(ChannelActivity.value).desc())
    )
    channel_map: dict[int, dict[str, int]] = {}
    for channel_id, metric, value in channel_result.all():
        channel_map.setdefault(int(channel_id), {})[metric] = int(value or 0)
    top_channel_rows = sorted(
        ({"channel_id": channel_id, **metrics} for channel_id, metrics in channel_map.items()),
        key=lambda item: item.get("messages", 0), reverse=True,
    )[:20]
    member_result = await session.execute(
        select(MemberActivity.user_id, User.username, User.display_name, MemberActivity.metric,
               func.sum(MemberActivity.value).label("total"))
        .join(User, User.id == MemberActivity.user_id, isouter=True)
        .where(*member_filters)
        .group_by(MemberActivity.user_id, User.username, User.display_name, MemberActivity.metric)
    )
    member_map: dict[int, dict[str, Any]] = {}
    for user_id, username, display_name, metric, value in member_result.all():
        row = member_map.setdefault(int(user_id), {"username": username, "display_name": display_name})
        row[metric] = int(value or 0)
    top_member_rows = sorted(
        ({"user_id": user_id, **metrics} for user_id, metrics in member_map.items()),
        key=lambda item: (item.get("messages", 0), item.get("voice_seconds", 0)), reverse=True,
    )[:20]

    hourly: dict[int, int] = {hour: 0 for hour in range(24)}
    daily: dict[str, dict[str, int]] = {}
    for key, metrics in by_bucket.items():
        timestamp = datetime.fromisoformat(key).astimezone(timezone.utc)
        hourly[timestamp.hour] += metrics.get("messages", 0)
        day_key = timestamp.date().isoformat()
        day_values = daily.setdefault(day_key, {"messages": 0, "voice_seconds": 0})
        day_values["messages"] += metrics.get("messages", 0)
        day_values["voice_seconds"] += metrics.get("voice_seconds", 0)
    member_count_result = await session.execute(
        select(GuildActivity.bucket_start, GuildActivity.value)
        .where(GuildActivity.guild_id == guild_id, GuildActivity.metric == "member_count",
               GuildActivity.bucket_start >= start, GuildActivity.bucket_start < end)
        .order_by(GuildActivity.bucket_start.asc())
    )
    member_count_series = [
        {"bucket": bucket.astimezone(timezone.utc).isoformat(), "value": int(value)}
        for bucket, value in member_count_result.all()
    ]
    daily_member_counts_map: dict[str, dict[str, int | str]] = {}
    for item in member_count_series:
        day_key = datetime.fromisoformat(str(item["bucket"])).date().isoformat()
        daily_member_counts_map[day_key] = {"date": day_key, "value": int(item["value"])}
    latest_member_count = await session.scalar(
        select(GuildActivity.value)
        .where(GuildActivity.guild_id == guild_id, GuildActivity.metric == "member_count", GuildActivity.bucket_start < end)
        .order_by(GuildActivity.bucket_start.desc()).limit(1)
    )
    members_current = int(latest_member_count if latest_member_count is not None else (await session.scalar(
        select(func.count(Member.user_id)).where(Member.guild_id == guild_id, Member.left_at.is_(None))
    )) or 0)
    history_start = await session.scalar(
        select(func.min(MemberActivity.bucket_start)).where(MemberActivity.guild_id == guild_id)
    )
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "member_count_snapshot_available": latest_member_count is not None,
        "totals": {
            "messages": totals.get("messages", 0),
            "voice_seconds": totals.get("voice_seconds", 0),
            "active_members": active_members,
            "joins": sum(item.get("joins", 0) for item in guild_series.values()),
            "leaves": sum(item.get("leaves", 0) for item in guild_series.values()),
            "member_count": members_current,
        },
        "hourly_messages": [{"hour": hour, "value": hourly[hour]} for hour in range(24)],
        "daily": [{"date": key, **daily[key]} for key in sorted(daily)],
        "daily_member_counts": [daily_member_counts_map[key] for key in sorted(daily_member_counts_map)],
        "member_count_series": member_count_series,
        "series": [{"bucket": key, **by_bucket[key]} for key in sorted(by_bucket)],
        "guild_series": [{"bucket": key, **guild_series[key]} for key in sorted(guild_series)],
        "top_channels": top_channel_rows,
        "top_members": top_member_rows,
        "history_available_from": history_start.isoformat() if history_start else None,
    }


async def member_activity_report(session: AsyncSession, guild_id: int, user_id: int, days: int) -> dict[str, Any]:
    days = max(1, min(days, 365))
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    result = await session.execute(
        select(MemberActivity.metric, func.coalesce(func.sum(MemberActivity.value), 0))
        .where(MemberActivity.guild_id == guild_id, MemberActivity.user_id == user_id,
               MemberActivity.bucket_start >= start, MemberActivity.bucket_start < now,
               MemberActivity.metric.in_(["messages", "voice_seconds"]))
        .group_by(MemberActivity.metric)
    )
    totals = {metric: int(value or 0) for metric, value in result.all()}
    active_result = await session.execute(
        select(func.count(distinct(cast(MemberActivity.bucket_start, Date))))
        .where(MemberActivity.guild_id == guild_id, MemberActivity.user_id == user_id,
               MemberActivity.metric.in_(["messages", "voice_seconds"]), MemberActivity.value > 0,
               MemberActivity.bucket_start >= start, MemberActivity.bucket_start < now)
    )
    history_start = await session.scalar(
        select(func.min(MemberActivity.bucket_start)).where(
            MemberActivity.guild_id == guild_id, MemberActivity.user_id == user_id,
            MemberActivity.metric.in_(["messages", "voice_seconds"]),
        )
    )
    return {"user_id": str(user_id), "days": days, "messages": totals.get("messages", 0),
            "voice_seconds": totals.get("voice_seconds", 0), "active_days": int(active_result.scalar_one() or 0),
            "history_available_from": history_start.isoformat() if history_start else None}


async def record_guild_metric(session: AsyncSession, guild_id: int, metric: str, value: int, bucket_start: datetime) -> None:
    if metric not in {"joins", "leaves"} or value <= 0:
        return
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(GuildActivity).values(
        guild_id=guild_id, bucket_start=floor_hour(bucket_start), metric=metric, value=value,
    ).on_conflict_do_update(
        index_elements=[GuildActivity.guild_id, GuildActivity.bucket_start, GuildActivity.metric],
        set_={"value": GuildActivity.value + value},
    )
    await session.execute(stmt)


async def record_guild_snapshot(session: AsyncSession, guild_id: int, member_count: int, bucket_start: datetime) -> None:
    """Store the latest known guild member count once per hour without summing snapshots."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(GuildActivity).values(
        guild_id=guild_id, bucket_start=floor_hour(bucket_start), metric="member_count", value=max(0, int(member_count)),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[GuildActivity.guild_id, GuildActivity.bucket_start, GuildActivity.metric],
        set_={"value": stmt.excluded.value},
    )
    await session.execute(stmt)


def validate_counter_template(template: str) -> str:
    template = template.strip()
    if not template or len(template) > 100:
        raise ValueError("O formato deve ter entre 1 e 100 caracteres")
    allowed = {"value", "label", "goal", "percent"}
    import re
    placeholders = re.findall(r"\{([^{}]+)\}", template)
    if any(value not in allowed for value in placeholders) or "{" in re.sub(r"\{(?:value|label|goal|percent)\}", "", template) or "}" in re.sub(r"\{(?:value|label|goal|percent)\}", "", template):
        raise ValueError("Use apenas os marcadores {value}, {label}, {goal} e {percent}")
    if "{value}" not in template:
        raise ValueError("O formato precisa conter {value}")
    return template


def render_counter_name(template: str, metric: str, value: int, goal: int | None) -> str:
    label = SUPPORTED_METRICS.get(metric, metric.replace("_", " ").title())
    percent: int | str = min(100, max(0, round(value / goal * 100))) if goal else "n/a"
    name = template.replace("{value}", str(max(0, int(value))))
    name = name.replace("{label}", label).replace("{goal}", str(goal if goal is not None else "n/a"))
    name = name.replace("{percent}", str(percent))
    return name[:100]


async def counter_value(session: AsyncSession, guild_id: int, metric: str, period_days: int | None, goal_value: int | None = None) -> int:
    if metric == "member_count":
        from app.models import Member
        return int(await session.scalar(select(func.count(Member.user_id)).where(Member.guild_id == guild_id, Member.left_at.is_(None))) or 0)
    if metric == "human_members":
        from app.models import Member, User
        return int(await session.scalar(select(func.count(Member.user_id)).join(User, User.id == Member.user_id).where(Member.guild_id == guild_id, Member.left_at.is_(None), User.bot.is_(False))) or 0)
    if metric == "bot_members":
        from app.models import Member, User
        return int(await session.scalar(select(func.count(Member.user_id)).join(User, User.id == Member.user_id).where(Member.guild_id == guild_id, Member.left_at.is_(None), User.bot.is_(True))) or 0)
    if metric == "voice_members":
        from app.models import Member
        return int(await session.scalar(select(func.count(Member.user_id)).where(Member.guild_id == guild_id, Member.left_at.is_(None), Member.voice_joined_at.is_not(None))) or 0)
    if metric not in {"messages_period", "active_members_period"}:
        raise ValueError("Métrica de contador desconhecida")
    start = datetime.now(timezone.utc) - timedelta(days=max(1, min(period_days or 7, 365)))
    if metric == "messages_period":
        return int(await session.scalar(select(func.coalesce(func.sum(MemberActivity.value), 0)).where(MemberActivity.guild_id == guild_id, MemberActivity.metric == "messages", MemberActivity.bucket_start >= start)) or 0)
    return int(await session.scalar(select(func.count(distinct(MemberActivity.user_id))).where(
        MemberActivity.guild_id == guild_id,
        MemberActivity.metric.in_(["messages", "voice_seconds"]),
        MemberActivity.value > 0,
        MemberActivity.bucket_start >= start,
    )) or 0)


async def evaluate_activity_rule_metrics(session: AsyncSession, guild_id: int, rule: ActivityRoleRule) -> dict[int, dict[str, int]]:
    now = datetime.now(timezone.utc)
    message_since = now - timedelta(days=max(1, min(int(rule.messages_window_days or 7), 365)))
    voice_since = now - timedelta(days=max(1, min(int(rule.voice_window_days or 7), 365)))
    active_since = now - timedelta(days=max(1, min(int(rule.active_days_window_days or 7), 365)))
    query_since = min(message_since, voice_since, active_since)
    messages_condition = and_(
        MemberActivity.metric == "messages",
        MemberActivity.bucket_start >= message_since,
    )
    voice_condition = and_(
        MemberActivity.metric == "voice_seconds",
        MemberActivity.bucket_start >= voice_since,
    )
    active_condition = and_(MemberActivity.bucket_start >= active_since, MemberActivity.value > 0)
    result = await session.execute(
        select(
            MemberActivity.user_id,
            func.coalesce(func.sum(case((messages_condition, MemberActivity.value), else_=0)), 0).label("messages"),
            func.coalesce(func.sum(case((voice_condition, MemberActivity.value), else_=0)), 0).label("voice_seconds"),
            func.count(distinct(case((active_condition, cast(MemberActivity.bucket_start, Date)), else_=None))).label("active_days"),
        )
        .where(
            MemberActivity.guild_id == guild_id,
            MemberActivity.bucket_start >= query_since,
            MemberActivity.bucket_start < now,
            MemberActivity.metric.in_(["messages", "voice_seconds"]),
        )
        .group_by(MemberActivity.user_id)
    )
    metrics: dict[int, dict[str, int]] = {}
    for user_id, messages, voice_seconds, active_days in result.all():
        metrics[int(user_id)] = {
            "messages": int(messages or 0),
            "voice_seconds": int(voice_seconds or 0),
            "active_days": int(active_days or 0),
        }
    return metrics
