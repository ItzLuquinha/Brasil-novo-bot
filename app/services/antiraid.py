from __future__ import annotations
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
import asyncio
import math
import logging
import secrets
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import session_factory
from app.models import RaidEvent, RaidProtection

logger = logging.getLogger("bn_bot.antiraid")

RESPONSE_ACTIONS = {"alert", "lockdown", "quarantine", "block"}
DEFAULT_CONFIG = {
    "enabled": False,
    "join_threshold": 8,
    "join_window_seconds": 20,
    "new_account_seconds": 604800,
    "new_account_ratio": 0.60,
    "risk_threshold": 70,
    "response_action": "alert",
    "lockdown_seconds": 300,
    "quarantine_role_id": None,
    "alert_channel_id": None,
    "lockdown_channels": [],
    "trusted_role_ids": [],
    "bypass_user_ids": [],
}

@dataclass(slots=True)
class JoinContext:
    guild_id: int
    user_id: int
    account_age_seconds: int | None
    role_ids: set[int] = field(default_factory=set)
    is_bot: bool = False
    is_owner: bool = False
    recent_joins: list[datetime] = field(default_factory=list)
    recent_new_accounts: list[datetime] = field(default_factory=list)
    recent_user_ids: list[int] = field(default_factory=list)

@dataclass(slots=True)
class RaidDecision:
    triggered: bool
    risk_score: int
    join_count: int
    new_account_count: int
    action: str
    reasons: list[str]
    metadata: dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def clamp_quarantine_timeout_seconds(value: object, default: int = 900) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 60), 2_419_200)


def _safe_ids(value: object) -> list[int]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: set[int] = set()
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            result.add(parsed)
    return sorted(result)


def merge_lockdown_guild_ids(expired_ids: list[int], pending_ids: list[int]) -> list[int]:
    return list(dict.fromkeys([*expired_ids, *pending_ids]))


def clamp_config(config: dict[str, Any]) -> dict[str, Any]:
    result = dict(DEFAULT_CONFIG)
    result.update(config)
    try:
        result["join_threshold"] = min(max(int(result["join_threshold"]), 2), 1000)
    except (TypeError, ValueError):
        result["join_threshold"] = DEFAULT_CONFIG["join_threshold"]
    try:
        result["join_window_seconds"] = min(max(int(result["join_window_seconds"]), 2), 120)
    except (TypeError, ValueError):
        result["join_window_seconds"] = DEFAULT_CONFIG["join_window_seconds"]
    try:
        result["new_account_seconds"] = min(max(int(result["new_account_seconds"]), 0), 31_536_000)
    except (TypeError, ValueError):
        result["new_account_seconds"] = DEFAULT_CONFIG["new_account_seconds"]
    try:
        ratio = float(result["new_account_ratio"])
        result["new_account_ratio"] = min(max(ratio, 0.0), 1.0) if math.isfinite(ratio) else DEFAULT_CONFIG["new_account_ratio"]
    except (TypeError, ValueError):
        result["new_account_ratio"] = DEFAULT_CONFIG["new_account_ratio"]
    try:
        result["risk_threshold"] = min(max(int(result["risk_threshold"]), 1), 100)
    except (TypeError, ValueError):
        result["risk_threshold"] = DEFAULT_CONFIG["risk_threshold"]
    result["enabled"] = bool(result.get("enabled", False))
    result["response_action"] = result.get("response_action") if result.get("response_action") in RESPONSE_ACTIONS else "alert"
    try:
        result["lockdown_seconds"] = min(max(int(result["lockdown_seconds"]), 30), 86_400)
    except (TypeError, ValueError):
        result["lockdown_seconds"] = DEFAULT_CONFIG["lockdown_seconds"]
    result["lockdown_channels"] = _safe_ids(result.get("lockdown_channels", []))
    result["trusted_role_ids"] = _safe_ids(result.get("trusted_role_ids", []))
    result["bypass_user_ids"] = _safe_ids(result.get("bypass_user_ids", []))
    return result


def calculate_risk(context: JoinContext, config: dict[str, Any], now: datetime | None = None) -> RaidDecision:
    now = now or utc_now()
    config = clamp_config(config)
    window = config["join_window_seconds"]
    threshold = config["join_threshold"]
    cutoff = now - timedelta(seconds=window)
    recent_joins = [item for item in context.recent_joins if item >= cutoff]
    recent_new = [item for item in context.recent_new_accounts if item >= cutoff]
    join_count = len(recent_joins) + 1
    new_count = len(recent_new) + (1 if context.account_age_seconds is not None and context.account_age_seconds <= config["new_account_seconds"] else 0)
    ratio = new_count / join_count if join_count else 0.0
    reasons: list[str] = []
    score = 0
    if join_count >= threshold:
        score += min(70, 45 + int(min(join_count / threshold, 3.0) * 10))
        reasons.append(f"{join_count} entradas em {window}s")
    elif join_count >= max(3, threshold // 2) and ratio >= config["new_account_ratio"]:
        score += 55
        reasons.append(f"pico de {join_count} entradas com contas recentes")
    if ratio >= config["new_account_ratio"] and join_count >= 3:
        score += 20
        reasons.append(f"{new_count} de {join_count} contas recentes")
    if context.account_age_seconds is not None and context.account_age_seconds <= config["new_account_seconds"]:
        score += 10
        reasons.append("conta recém-criada")
    score = min(score, 100)
    triggered = score >= config["risk_threshold"] or join_count >= threshold
    metadata = {
        "window_seconds": window,
        "join_threshold": threshold,
        "new_account_ratio": round(ratio, 4),
        "risk_threshold": config["risk_threshold"],
        "recent_user_ids": context.recent_user_ids[:50],
    }
    return RaidDecision(triggered, score, join_count, new_count, config["response_action"], reasons, metadata)

class RaidWindowStore:
    def __init__(self, redis: Any | None = None, prefix: str = "bn:antiraid") -> None:
        self.redis = redis
        self.prefix = prefix

    def key(self, guild_id: int, kind: str) -> str:
        return f"{self.prefix}:{guild_id}:{kind}"

    async def add_join(self, context: JoinContext, now: datetime, new_account: bool) -> tuple[list[datetime], list[datetime], list[int]]:
        if self.redis is not None:
            return await self._add_redis(context, now, new_account)
        return await self._add_memory(context, now, new_account)

    async def _add_redis(self, context: JoinContext, now: datetime, new_account: bool) -> tuple[list[datetime], list[datetime], list[int]]:
        stamp_key = self.key(context.guild_id, "timestamps")
        new_key = self.key(context.guild_id, "new")
        users_key = self.key(context.guild_id, "users")
        score = now.timestamp()
        token = secrets.token_hex(12)
        member = f"{score:.6f}:{context.user_id}:{token}"
        await self.redis.zadd(stamp_key, {member: score})
        cutoff = (now - timedelta(seconds=120)).timestamp()
        await self.redis.zremrangebyscore(stamp_key, 0, cutoff)
        if new_account:
            await self.redis.zadd(new_key, {member: score})
        await self.redis.zremrangebyscore(new_key, 0, cutoff)
        await self.redis.lpush(users_key, f"{token}\t{context.user_id}")
        await self.redis.ltrim(users_key, 0, 199)
        stamp_rows = await self.redis.zrange(stamp_key, 0, -1, withscores=True)
        new_rows = await self.redis.zrange(new_key, 0, -1, withscores=True)
        raw_users = [str(value) for value in await self.redis.lrange(users_key, 0, 199)]
        timestamps = [datetime.fromtimestamp(float(item[1]), timezone.utc) for item in stamp_rows if str(item[0]) != member]
        new_timestamps = [datetime.fromtimestamp(float(item[1]), timezone.utc) for item in new_rows if str(item[0]) != member]
        users: list[int] = []
        for value in raw_users:
            if "\t" not in value:
                continue
            item_token, item_user_id = value.split("\t", 1)
            if item_token != token:
                users.append(int(item_user_id))
        return timestamps, new_timestamps, users

    async def _add_memory(self, context: JoinContext, now: datetime, new_account: bool) -> tuple[list[datetime], list[datetime], list[int]]:
        guild_id = context.guild_id
        async with _memory_lock:
            timestamps = _memory_timestamps[guild_id]
            new_timestamps = _memory_new_timestamps[guild_id]
            users = _memory_users[guild_id]
            recent_timestamps = list(timestamps)
            recent_new = list(new_timestamps)
            recent_users = list(users)
            timestamps.append(now)
            users.appendleft(context.user_id)
            if new_account:
                new_timestamps.append(now)
            cutoff = now - timedelta(seconds=120)
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()
            while new_timestamps and new_timestamps[0] < cutoff:
                new_timestamps.popleft()
            while len(users) > 200:
                users.pop()
        return recent_timestamps, recent_new, recent_users

_memory_timestamps: dict[int, deque[datetime]] = defaultdict(deque)
_memory_new_timestamps: dict[int, deque[datetime]] = defaultdict(deque)
_memory_users: dict[int, deque[int]] = defaultdict(deque)
_memory_lock = asyncio.Lock()

async def get_store() -> RaidWindowStore:
    try:
        from app.core.redis import redis_client
        await redis_client.ping()
        return RaidWindowStore(redis_client)
    except Exception:
        logger.warning("Redis indisponível para Anti-Raid; usando fallback local")
        return RaidWindowStore(None)

async def load_protection(session: AsyncSession, guild_id: int) -> RaidProtection:
    result = await session.execute(select(RaidProtection).where(RaidProtection.guild_id == guild_id).with_for_update())
    row = result.scalar_one_or_none()
    if row is None:
        now = utc_now()
        row = RaidProtection(guild_id=guild_id, created_at=now, updated_at=now)
        session.add(row)
        await session.flush()
    return row

async def evaluate_join(context: JoinContext) -> RaidDecision | None:
    async with session_factory() as session:
        protection = await load_protection(session, context.guild_id)
        if not protection.enabled or context.is_bot or context.is_owner:
            await session.commit()
            return None
        trusted_roles = set(protection.trusted_role_ids or [])
        bypass_users = set(protection.bypass_user_ids or [])
        if context.user_id in bypass_users or trusted_roles.intersection(context.role_ids):
            await session.commit()
            return None
        now = utc_now()
        new_account = context.account_age_seconds is not None and context.account_age_seconds <= protection.new_account_seconds
        store = await get_store()
        try:
            recent_joins, recent_new, recent_users = await store.add_join(context, now, new_account)
        except Exception:
            if store.redis is None:
                raise
            logger.exception("Redis Anti-Raid indisponível durante registro; usando fallback local")
            fallback_store = RaidWindowStore(None)
            recent_joins, recent_new, recent_users = await fallback_store.add_join(context, now, new_account)
        context.recent_joins = recent_joins
        context.recent_new_accounts = recent_new
        context.recent_user_ids = recent_users
        config = {
            "join_threshold": protection.join_threshold,
            "join_window_seconds": protection.join_window_seconds,
            "new_account_seconds": protection.new_account_seconds,
            "new_account_ratio": float(protection.new_account_ratio if isinstance(protection.new_account_ratio, Decimal) else protection.new_account_ratio),
            "risk_threshold": protection.risk_threshold,
            "response_action": protection.response_action,
        }
        decision = calculate_risk(context, config, now)
        if not decision.triggered:
            await session.commit()
            return None
        if protection.active_until is not None and protection.active_until > now:
            decision.action = "alert"
        elif decision.action == "lockdown":
            protection.active_until = now + timedelta(seconds=protection.lockdown_seconds)
        await record_event(session, context.guild_id, context.user_id, "raid_detected", decision.action, decision.risk_score, decision.join_count, decision.new_account_count, protection.join_window_seconds, decision.metadata | {"reasons": decision.reasons})
        protection.updated_at = now
        await session.commit()
        return decision

async def record_event(session: AsyncSession, guild_id: int, user_id: int | None, event_type: str, action: str, risk_score: int, join_count: int, new_account_count: int, window_seconds: int, details: dict[str, Any]) -> None:
    session.add(RaidEvent(id=secrets.randbits(62), guild_id=guild_id, user_id=user_id, event_type=event_type, action=action, risk_score=risk_score, join_count=join_count, new_account_count=new_account_count, window_seconds=window_seconds, details=details, created_at=utc_now()))

async def clear_expired_state(session: AsyncSession, now: datetime | None = None) -> list[int]:
    now = now or utc_now()
    rows = list((await session.execute(select(RaidProtection).where(RaidProtection.active_until.is_not(None), RaidProtection.active_until <= now).with_for_update(skip_locked=True))).scalars())
    guild_ids: list[int] = []
    for row in rows:
        row.active_until = None
        row.updated_at = now
        guild_ids.append(row.guild_id)
        await record_event(session, row.guild_id, None, "lockdown_expired", "unlock", 0, 0, 0, row.join_window_seconds, {})
    if rows:
        await session.commit()
    return guild_ids
