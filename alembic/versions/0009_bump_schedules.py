from alembic import op

revision = "0009_bump_schedules"
down_revision = "0008_command_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE bump_schedules (
        guild_id BIGINT NOT NULL,
        channel_id BIGINT NOT NULL,
        interval_seconds INTEGER NOT NULL,
        enabled BOOLEAN NOT NULL,
        next_run_at TIMESTAMP WITH TIME ZONE NOT NULL,
        last_sent_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (guild_id),
        FOREIGN KEY(guild_id) REFERENCES guilds (id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_bump_schedules_next_run ON bump_schedules (enabled, next_run_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bump_schedules CASCADE")
