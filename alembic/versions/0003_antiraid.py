from alembic import op

revision = "0003_antiraid"
down_revision = "0002_automod"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE raid_protection (
        guild_id BIGINT PRIMARY KEY REFERENCES guilds(id) ON DELETE CASCADE,
        enabled BOOLEAN NOT NULL,
        join_threshold INTEGER NOT NULL,
        join_window_seconds INTEGER NOT NULL,
        new_account_seconds INTEGER NOT NULL,
        new_account_ratio NUMERIC(5,4) NOT NULL,
        risk_threshold INTEGER NOT NULL,
        response_action VARCHAR(20) NOT NULL,
        lockdown_seconds INTEGER NOT NULL,
        quarantine_role_id BIGINT,
        alert_channel_id BIGINT,
        lockdown_channels JSON NOT NULL,
        trusted_role_ids JSON NOT NULL,
        bypass_user_ids JSON NOT NULL,
        config JSON NOT NULL,
        active_until TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL
    );
    CREATE INDEX ix_raid_protection_active_until ON raid_protection (active_until);
    CREATE TABLE raid_events (
        id BIGINT PRIMARY KEY,
        guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
        user_id BIGINT,
        event_type VARCHAR(40) NOT NULL,
        action VARCHAR(20) NOT NULL,
        risk_score INTEGER NOT NULL,
        join_count INTEGER NOT NULL,
        new_account_count INTEGER NOT NULL,
        window_seconds INTEGER NOT NULL,
        details JSON NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL
    );
    CREATE INDEX ix_raid_events_guild_created ON raid_events (guild_id, created_at);
    CREATE INDEX ix_raid_events_guild_user_created ON raid_events (guild_id, user_id, created_at);
    CREATE TABLE raid_lockdown_channels (
        id BIGINT PRIMARY KEY,
        guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
        channel_id BIGINT NOT NULL,
        had_overwrite BOOLEAN NOT NULL,
        allow_bits BIGINT NOT NULL,
        deny_bits BIGINT NOT NULL,
        locked_at TIMESTAMP WITH TIME ZONE NOT NULL,
        UNIQUE (guild_id, channel_id)
    );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS raid_lockdown_channels; DROP TABLE IF EXISTS raid_events; DROP TABLE IF EXISTS raid_protection;")
