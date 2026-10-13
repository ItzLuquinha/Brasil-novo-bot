from alembic import op

revision = "0015_audit_query_indexes"
down_revision = "0014_api_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_audit_logs_guild_created", "audit_logs", ["guild_id", "created_at"])
    op.create_index("ix_moderation_logs_guild_created", "moderation_logs", ["guild_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_moderation_logs_guild_created", table_name="moderation_logs")
    op.drop_index("ix_audit_logs_guild_created", table_name="audit_logs")
