from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Any
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class Guild(Base, Timestamped):
    __tablename__ = "guilds"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    icon_url: Mapped[str | None] = mapped_column(String(500))
    owner_id: Mapped[int | None] = mapped_column(BigInteger)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class GuildSettings(Base, Timestamped):
    __tablename__ = "guild_settings"
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default="pt-BR", nullable=False)
    economy_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    levels_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    automod_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

class User(Base, Timestamped):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    banner_url: Mapped[str | None] = mapped_column(String(500))
    bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    locale: Mapped[str] = mapped_column(String(16), default="pt-BR", nullable=False)

class Member(Base, Timestamped):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"), Index("ix_members_guild_activity", "guild_id", "activity_score"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activity_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    voice_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    voice_joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voice_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    voice_analytics_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class EconomyAccount(Base):
    __tablename__ = "economy_accounts"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"), Index("ix_economy_rank", "guild_id", "wallet", "bank"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    wallet: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    bank: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    lifetime_earned: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)
    lifetime_spent: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=0, nullable=False)

class EconomyTransaction(Base):
    __tablename__ = "economy_transactions"
    __table_args__ = (Index("ix_economy_transactions_guild_user_created", "guild_id", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    counterparty_user_id: Mapped[int | None] = mapped_column(BigInteger)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RewardClaim(Base):
    __tablename__ = "reward_claims"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", "kind", "claim_key"), Index("ix_reward_claims_user_kind", "guild_id", "user_id", "kind", "claimed_at"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    claim_key: Mapped[str] = mapped_column(String(40), nullable=False)
    streak: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class ShopItem(Base, Timestamped):
    __tablename__ = "shop_items"
    __table_args__ = (UniqueConstraint("guild_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    rarity: Mapped[str] = mapped_column(String(30), default="common", nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    stock: Mapped[int | None] = mapped_column(Integer)
    stack_limit: Mapped[int] = mapped_column(Integer, default=99, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_seconds: Mapped[int | None] = mapped_column(Integer)

class InventoryItem(Base, Timestamped):
    __tablename__ = "inventory_items"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", "shop_item_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shop_item_id: Mapped[int] = mapped_column(Integer, ForeignKey("shop_items.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class Experience(Base, Timestamped):
    __tablename__ = "experiences"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"), Index("ix_experience_rank", "guild_id", "total_xp"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_xp: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rewarded_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

class Achievement(Base, Timestamped):
    __tablename__ = "achievements"
    __table_args__ = (UniqueConstraint("guild_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class UserAchievement(Base):
    __tablename__ = "user_achievements"
    __table_args__ = (UniqueConstraint("achievement_id", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    achievement_id: Mapped[int] = mapped_column(Integer, ForeignKey("achievements.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class Reputation(Base):
    __tablename__ = "reputations"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"), Index("ix_reputation_rank", "guild_id", "score"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

class ReputationEvent(Base):
    __tablename__ = "reputation_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    giver_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    receiver_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class Job(Base, Timestamped):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("guild_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    salary: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    xp_reward: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

class UserJob(Base):
    __tablename__ = "user_jobs"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_work_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Quest(Base, Timestamped):
    __tablename__ = "quests"
    __table_args__ = (UniqueConstraint("guild_id", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    objective: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    reward: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

class UserQuest(Base, Timestamped):
    __tablename__ = "user_quests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quest_id: Mapped[int] = mapped_column(Integer, ForeignKey("quests.id", ondelete="CASCADE"), nullable=False)
    progress: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class Pet(Base, Timestamped):
    __tablename__ = "pets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    species: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    rarity: Mapped[str] = mapped_column(String(30), default="common", nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hunger: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    energy: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    happiness: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    abilities: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    equipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

class Marriage(Base, Timestamped):
    __tablename__ = "marriages"
    __table_args__ = (UniqueConstraint("guild_id", "user_a_id"), UniqueConstraint("guild_id", "user_b_id"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_a_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_b_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    married_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class Warning(Base):
    __tablename__ = "warnings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    moderator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (Index("ix_warnings_guild_user_active", "guild_id", "user_id", "active"),)

class Punishment(Base):
    __tablename__ = "punishments"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    moderator_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

class ModerationLog(Base):
    __tablename__ = "moderation_logs"
    __table_args__ = (Index("ix_moderation_logs_guild_created", "guild_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class MessageLog(Base):
    __tablename__ = "message_logs"
    __table_args__ = (Index("ix_message_logs_guild_created", "guild_id", "created_at"), Index("ix_message_logs_guild_channel_created", "guild_id", "channel_id", "created_at"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class MemberActivity(Base):
    __tablename__ = "member_activity"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", "bucket_start", "metric"), Index("ix_member_activity_guild_bucket", "guild_id", "bucket_start"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

class ChannelActivity(Base):
    __tablename__ = "channel_activity"
    __table_args__ = (UniqueConstraint("guild_id", "channel_id", "bucket_start", "metric"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

class GuildActivity(Base):
    __tablename__ = "guild_activity"
    __table_args__ = (
        UniqueConstraint("guild_id", "bucket_start", "metric"),
        Index("ix_guild_activity_guild_bucket", "guild_id", "bucket_start"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AnalyticsConfig(Base, Timestamped):
    __tablename__ = "analytics_config"
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)
    excluded_channel_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    excluded_category_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    excluded_role_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    exclude_commands: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    exclude_bots: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    track_voice: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)
    member_statistics_for_managers: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StatCounter(Base, Timestamped):
    __tablename__ = "stat_counters"
    __table_args__ = (Index("ix_stat_counters_guild_enabled", "guild_id", "enabled"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    metric: Mapped[str] = mapped_column(String(40), nullable=False)
    format_template: Mapped[str] = mapped_column(String(100), nullable=False)
    period_days: Mapped[int | None] = mapped_column(Integer)
    goal_value: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_value: Mapped[int | None] = mapped_column(BigInteger)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class ActivityRoleRule(Base, Timestamped):
    __tablename__ = "activity_role_rules"
    __table_args__ = (
        UniqueConstraint("guild_id", "name"),
        Index("ix_activity_role_rules_guild_enabled", "guild_id", "enabled"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    min_messages: Mapped[int | None] = mapped_column(Integer)
    messages_window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    min_voice_seconds: Mapped[int | None] = mapped_column(Integer)
    voice_window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    min_active_days: Mapped[int | None] = mapped_column(Integer)
    active_days_window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    remove_when_unqualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class Ticket(Base, Timestamped):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    opener_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(80), default="general", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    transcript: Mapped[str | None] = mapped_column(Text)
    panel_message_id: Mapped[int | None] = mapped_column(BigInteger)

class Suggestion(Base, Timestamped):
    __tablename__ = "suggestions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    author_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    upvotes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    downvotes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    staff_note: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[int | None] = mapped_column(BigInteger)

class SuggestionVote(Base):
    __tablename__ = "suggestion_votes"
    __table_args__ = (UniqueConstraint("suggestion_id", "user_id"), Index("ix_suggestion_votes_suggestion", "suggestion_id"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    suggestion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("suggestions.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class Report(Base, Timestamped):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    reporter_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reported_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)
    resolver_id: Mapped[int | None] = mapped_column(BigInteger)
    resolution: Mapped[str | None] = mapped_column(Text)

class Giveaway(Base, Timestamped):
    __tablename__ = "giveaways"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    prize: Mapped[str] = mapped_column(String(300), nullable=False)
    winners: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requirements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)

class GiveawayEntry(Base):
    __tablename__ = "giveaway_entries"
    __table_args__ = (UniqueConstraint("giveaway_id", "user_id"), Index("ix_giveaway_entries_giveaway", "giveaway_id"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    giveaway_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class Poll(Base, Timestamped):
    __tablename__ = "polls"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInteger)

class PollVote(Base):
    __tablename__ = "poll_votes"
    __table_args__ = (UniqueConstraint("poll_id", "user_id"), Index("ix_poll_votes_poll_option", "poll_id", "option_index"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    poll_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    option_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class TicketEvent(Base):
    __tablename__ = "ticket_events"
    __table_args__ = (Index("ix_ticket_events_ticket_created", "ticket_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    ticket_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class Automation(Base, Timestamped):
    __tablename__ = "automations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    trigger: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class CustomCommand(Base, Timestamped):
    __tablename__ = "custom_commands"
    __table_args__ = (UniqueConstraint("guild_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class AutoResponse(Base, Timestamped):
    __tablename__ = "auto_responses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    trigger_value: Mapped[str] = mapped_column(String(500), nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class AutoModRule(Base, Timestamped):
    __tablename__ = "automod_rules"
    __table_args__ = (UniqueConstraint("guild_id", "name"), Index("ix_automod_rules_guild_enabled", "guild_id", "enabled", "priority"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(20), default="delete", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    channel_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    role_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

class AutoModListEntry(Base, Timestamped):
    __tablename__ = "automod_list_entries"
    __table_args__ = (UniqueConstraint("guild_id", "list_type", "entry_type", "value"), Index("ix_automod_lists_guild_type", "guild_id", "list_type", "entry_type"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    list_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_type: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))

class AutoModEvent(Base):
    __tablename__ = "automod_events"
    __table_args__ = (Index("ix_automod_events_guild_created", "guild_id", "created_at"), Index("ix_automod_events_guild_user_created", "guild_id", "user_id", "created_at"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rule_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("automod_rules.id", ondelete="SET NULL"))
    rule_type: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RaidProtection(Base, Timestamped):
    __tablename__ = "raid_protection"
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    join_threshold: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    join_window_seconds: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    new_account_seconds: Mapped[int] = mapped_column(Integer, default=604800, nullable=False)
    new_account_ratio: Mapped[float] = mapped_column(Numeric(5, 4), default=0.6, nullable=False)
    risk_threshold: Mapped[int] = mapped_column(Integer, default=70, nullable=False)
    response_action: Mapped[str] = mapped_column(String(20), default="alert", nullable=False)
    lockdown_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    quarantine_role_id: Mapped[int | None] = mapped_column(BigInteger)
    alert_channel_id: Mapped[int | None] = mapped_column(BigInteger)
    lockdown_channels: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    trusted_role_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    bypass_user_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class RaidEvent(Base):
    __tablename__ = "raid_events"
    __table_args__ = (Index("ix_raid_events_guild_created", "guild_id", "created_at"), Index("ix_raid_events_guild_user_created", "guild_id", "user_id", "created_at"))
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    join_count: Mapped[int] = mapped_column(Integer, nullable=False)
    new_account_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class RaidLockdownChannel(Base):
    __tablename__ = "raid_lockdown_channels"
    __table_args__ = (
        Index("ix_raid_lockdown_restore_retry", "guild_id", "next_restore_attempt_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    had_overwrite: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_bits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deny_bits: Mapped[int] = mapped_column(BigInteger, nullable=False)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    restore_attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    next_restore_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restore_last_error: Mapped[str | None] = mapped_column(String(500))

class TemporaryRole(Base):
    __tablename__ = "temporary_roles"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))

class Verification(Base, Timestamped):
    __tablename__ = "verifications"
    __table_args__ = (UniqueConstraint("guild_id", "user_id"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Notification(Base, Timestamped):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Integration(Base, Timestamped):
    __tablename__ = "integrations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (UniqueConstraint("guild_id", "provider"),)


class CommandUsage(Base):
    __tablename__ = "command_usage"
    __table_args__ = (
        Index("ix_command_usage_guild_used", "guild_id", "used_at"),
        Index("ix_command_usage_guild_category_used", "guild_id", "category", "used_at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    command_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(120))
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_guild_created", "guild_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    executor_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource: Mapped[str] = mapped_column(String(120), nullable=False)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

class Backup(Base, Timestamped):
    __tablename__ = "backups"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="valid", nullable=False)

class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (Index("ix_reminders_pending_delivery", "sent_at", "due_at", "next_attempt_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery: Mapped[str] = mapped_column(String(10), default="channel", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))

class ApiAuthSession(Base):
    __tablename__ = "api_auth_sessions"
    __table_args__ = (
        Index("ix_api_auth_sessions_user_expires", "user_id", "expires_at"),
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar_hash: Mapped[str | None] = mapped_column(String(128))
    guild_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    previous_refresh_token_hash: Mapped[str | None] = mapped_column(String(64))
    previous_refresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discord_access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    discord_refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    discord_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    discord_permissions_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GuildPermission(Base):
    __tablename__ = "guild_permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_id: Mapped[int | None] = mapped_column(BigInteger)
    permission: Mapped[str] = mapped_column(String(120), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)

class Cooldown(Base):
    __tablename__ = "cooldowns"
    __table_args__ = (UniqueConstraint("guild_id", "user_id", "key"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    guild_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
