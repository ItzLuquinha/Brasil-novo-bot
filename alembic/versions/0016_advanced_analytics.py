from alembic import op
import sqlalchemy as sa

revision = "0016_advanced_analytics"
down_revision = "0015_audit_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("members", sa.Column("voice_channel_id", sa.BigInteger(), nullable=True))
    op.add_column("members", sa.Column("voice_analytics_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_message_logs_guild_created", "message_logs", ["guild_id", "created_at"])
    op.create_index("ix_message_logs_guild_channel_created", "message_logs", ["guild_id", "channel_id", "created_at"])
    op.create_table(
        "guild_activity",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(30), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("guild_id", "bucket_start", "metric", name="uq_guild_activity_guild_bucket_metric"),
    )
    op.create_index("ix_guild_activity_guild_bucket", "guild_activity", ["guild_id", "bucket_start"])
    op.create_table(
        "analytics_config",
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("excluded_channel_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("excluded_category_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("excluded_role_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("exclude_commands", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exclude_bots", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("track_voice", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("member_statistics_for_managers", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "stat_counters",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("metric", sa.String(40), nullable=False),
        sa.Column("format_template", sa.String(100), nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=True),
        sa.Column("goal_value", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_value", sa.BigInteger(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stat_counters_guild_enabled", "stat_counters", ["guild_id", "enabled"])
    op.create_table(
        "activity_role_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("guild_id", sa.BigInteger(), sa.ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("min_messages", sa.Integer(), nullable=True),
        sa.Column("messages_window_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("min_voice_seconds", sa.Integer(), nullable=True),
        sa.Column("voice_window_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("min_active_days", sa.Integer(), nullable=True),
        sa.Column("active_days_window_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("remove_when_unqualified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("guild_id", "name", name="uq_activity_role_rules_guild_name"),
    )
    op.create_index("ix_activity_role_rules_guild_enabled", "activity_role_rules", ["guild_id", "enabled"])


def downgrade() -> None:
    op.drop_index("ix_message_logs_guild_channel_created", table_name="message_logs")
    op.drop_index("ix_message_logs_guild_created", table_name="message_logs")
    op.drop_index("ix_activity_role_rules_guild_enabled", table_name="activity_role_rules")
    op.drop_table("activity_role_rules")
    op.drop_index("ix_stat_counters_guild_enabled", table_name="stat_counters")
    op.drop_table("stat_counters")
    op.drop_table("analytics_config")
    op.drop_index("ix_guild_activity_guild_bucket", table_name="guild_activity")
    op.drop_table("guild_activity")
    op.drop_column("members", "voice_analytics_active")
    op.drop_column("members", "voice_channel_id")
