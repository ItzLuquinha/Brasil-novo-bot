from alembic import op
import sqlalchemy as sa

revision = "0014_api_auth_sessions"
down_revision = "0013_lockdown_restore_retry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "api_auth_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=200), nullable=False),
        sa.Column("avatar_hash", sa.String(length=128), nullable=True),
        sa.Column("guild_ids", sa.JSON(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("previous_refresh_token_hash", sa.String(length=64), nullable=True),
        sa.Column("previous_refresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discord_access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("discord_refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("discord_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("discord_permissions_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_auth_sessions_user_expires", "api_auth_sessions", ["user_id", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_api_auth_sessions_user_expires", table_name="api_auth_sessions")
    op.drop_table("api_auth_sessions")
