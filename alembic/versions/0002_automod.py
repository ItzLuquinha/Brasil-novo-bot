from alembic import op

revision = "0002_automod"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE automod_rules (
        id SERIAL PRIMARY KEY,
        guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
        name VARCHAR(120) NOT NULL,
        rule_type VARCHAR(40) NOT NULL,
        action VARCHAR(20) NOT NULL,
        enabled BOOLEAN NOT NULL,
        priority INTEGER NOT NULL,
        channel_ids JSON NOT NULL,
        role_ids JSON NOT NULL,
        config JSON NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        UNIQUE (guild_id, name)
    );
    CREATE INDEX ix_automod_rules_guild_enabled ON automod_rules (guild_id, enabled, priority);
    CREATE TABLE automod_list_entries (
        id SERIAL PRIMARY KEY,
        guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
        list_type VARCHAR(20) NOT NULL,
        entry_type VARCHAR(20) NOT NULL,
        value VARCHAR(500) NOT NULL,
        reason VARCHAR(500),
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        UNIQUE (guild_id, list_type, entry_type, value)
    );
    CREATE INDEX ix_automod_lists_guild_type ON automod_list_entries (guild_id, list_type, entry_type);
    CREATE TABLE automod_events (
        id BIGINT PRIMARY KEY,
        guild_id BIGINT NOT NULL REFERENCES guilds(id) ON DELETE CASCADE,
        channel_id BIGINT NOT NULL,
        user_id BIGINT NOT NULL,
        message_id BIGINT NOT NULL,
        rule_id INTEGER REFERENCES automod_rules(id) ON DELETE SET NULL,
        rule_type VARCHAR(40) NOT NULL,
        action VARCHAR(20) NOT NULL,
        reason VARCHAR(500) NOT NULL,
        data JSON NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL
    );
    CREATE INDEX ix_automod_events_guild_created ON automod_events (guild_id, created_at);
    CREATE INDEX ix_automod_events_guild_user_created ON automod_events (guild_id, user_id, created_at);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS automod_events; DROP TABLE IF EXISTS automod_list_entries; DROP TABLE IF EXISTS automod_rules;")
