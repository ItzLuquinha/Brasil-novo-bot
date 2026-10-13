from alembic import op

revision = "0008_command_usage"
down_revision = "0007_channel_activity_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE command_usage (
        id BIGINT NOT NULL,
        guild_id BIGINT,
        user_id BIGINT NOT NULL,
        channel_id BIGINT,
        command_name VARCHAR(120) NOT NULL,
        category VARCHAR(40) NOT NULL,
        success BOOLEAN NOT NULL,
        error_type VARCHAR(120),
        used_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_command_usage_guild_used ON command_usage (guild_id, used_at)")
    op.execute("CREATE INDEX ix_command_usage_guild_category_used ON command_usage (guild_id, category, used_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS command_usage CASCADE")
