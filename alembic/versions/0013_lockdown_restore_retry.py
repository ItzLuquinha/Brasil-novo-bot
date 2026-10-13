from alembic import op
import sqlalchemy as sa

revision = "0013_lockdown_restore_retry"
down_revision = "0012_reminder_delivery_retries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raid_lockdown_channels", sa.Column("restore_attempt_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("raid_lockdown_channels", sa.Column("next_restore_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("raid_lockdown_channels", sa.Column("restore_last_error", sa.String(length=500), nullable=True))
    op.create_index("ix_raid_lockdown_restore_retry", "raid_lockdown_channels", ["guild_id", "next_restore_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_raid_lockdown_restore_retry", table_name="raid_lockdown_channels")
    op.drop_column("raid_lockdown_channels", "restore_last_error")
    op.drop_column("raid_lockdown_channels", "next_restore_attempt_at")
    op.drop_column("raid_lockdown_channels", "restore_attempt_count")
