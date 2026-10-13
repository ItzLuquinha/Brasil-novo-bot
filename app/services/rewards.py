from decimal import Decimal, InvalidOperation
from datetime import date, datetime, time, timedelta, timezone
import secrets
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfoNotFoundError
import logging
from app.core.exceptions import CooldownActive
from app.core.time import local_now, utc_now
from app.models import GuildSettings, RewardClaim
from app.repositories.economy import add_wallet

DEFAULT_REWARD_CONFIG = {
    "daily_amount": Decimal("250"),
    "weekly_amount": Decimal("1500"),
    "streak_bonus_percent": Decimal("5"),
    "streak_bonus_cap_percent": Decimal("100"),
}


def reward_config(settings: GuildSettings | None) -> dict[str, Decimal]:
    raw = settings.config.get("rewards", {}) if settings and isinstance(settings.config, dict) else {}
    values = dict(DEFAULT_REWARD_CONFIG)
    if not isinstance(raw, dict):
        return values
    for key in values:
        value = raw.get(key)
        if value is None:
            continue
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not parsed.is_finite() or parsed < 0:
            continue
        if key in {"daily_amount", "weekly_amount"} and parsed > Decimal("1000000000"):
            continue
        values[key] = parsed
    values["daily_amount"] = values["daily_amount"].quantize(Decimal("0.01"))
    values["weekly_amount"] = values["weekly_amount"].quantize(Decimal("0.01"))
    values["streak_bonus_percent"] = min(values["streak_bonus_percent"], Decimal("100"))
    values["streak_bonus_cap_percent"] = min(max(values["streak_bonus_cap_percent"], Decimal("0")), Decimal("1000"))
    return values


logger = logging.getLogger("bn_bot.rewards")

def seconds_until_next_reward(kind: str, local: datetime) -> int:
    if kind == "daily":
        next_date = local.date() + timedelta(days=1)
    elif kind == "weekly":
        next_date = local.date() + timedelta(days=7 - local.weekday())
    else:
        raise ValueError("invalid reward kind")
    boundary = datetime.combine(next_date, time.min, tzinfo=local.tzinfo)
    seconds = int((boundary.astimezone(timezone.utc) - local.astimezone(timezone.utc)).total_seconds())
    return max(seconds, 1)

async def claim_reward(session: AsyncSession, guild_id: int, user_id: int, kind: str, base_amount: Decimal | None = None) -> tuple[Decimal, int]:
    if kind not in {"daily", "weekly"}:
        raise ValueError("invalid reward kind")
    settings = await session.get(GuildSettings, guild_id)
    tz_name = settings.timezone if settings else "UTC"
    configuration = reward_config(settings)
    if base_amount is None:
        base_amount = configuration["daily_amount" if kind == "daily" else "weekly_amount"]
    try:
        local = local_now(tz_name)
    except ZoneInfoNotFoundError:
        logger.error("invalid guild timezone; falling back to UTC guild=%s timezone=%s", guild_id, tz_name)
        local = local_now("UTC")
    if kind == "daily":
        claim_key = local.date().isoformat()
        previous_key = (local.date() - timedelta(days=1)).isoformat()
    else:
        iso = local.isocalendar()
        claim_key = f"{iso.year}-W{iso.week:02d}"
        previous = local.date() - timedelta(days=7)
        previous_iso = previous.isocalendar()
        previous_key = f"{previous_iso.year}-W{previous_iso.week:02d}"
    existing = await session.execute(select(RewardClaim).where(RewardClaim.guild_id == guild_id, RewardClaim.user_id == user_id, RewardClaim.kind == kind, RewardClaim.claim_key == claim_key).with_for_update())
    if existing.scalar_one_or_none() is not None:
        raise CooldownActive(seconds_until_next_reward(kind, local))
    last = await session.execute(select(RewardClaim).where(RewardClaim.guild_id == guild_id, RewardClaim.user_id == user_id, RewardClaim.kind == kind).order_by(RewardClaim.claimed_at.desc()).limit(1).with_for_update())
    previous_claim = last.scalar_one_or_none()
    streak = previous_claim.streak + 1 if previous_claim and previous_claim.claim_key == previous_key else 1
    bonus_percent = configuration["streak_bonus_percent"]
    bonus_cap_percent = configuration["streak_bonus_cap_percent"]
    bonus_percent = min(Decimal(max(streak - 1, 0)) * bonus_percent, bonus_cap_percent)
    bonus_multiplier = Decimal("1") + bonus_percent / Decimal("100")
    amount = (base_amount * bonus_multiplier).quantize(Decimal("0.01"))
    try:
        async with session.begin_nested():
            session.add(RewardClaim(id=secrets.randbits(62), guild_id=guild_id, user_id=user_id, kind=kind, claim_key=claim_key, streak=streak, amount=amount, claimed_at=utc_now()))
            await session.flush()
            await add_wallet(session, guild_id, user_id, amount, kind, f"streak:{streak}")
    except IntegrityError as exc:
        raise CooldownActive(seconds_until_next_reward(kind, local)) from exc
    return amount, streak
