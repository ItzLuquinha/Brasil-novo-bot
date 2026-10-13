from alembic import op
import sqlalchemy as sa

revision = "0012_reminder_delivery_retries"
down_revision = "0011_voice_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reminders", sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("reminders", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reminders", sa.Column("last_error", sa.String(length=500), nullable=True))
    op.create_index("ix_reminders_pending_delivery", "reminders", ["sent_at", "due_at", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_reminders_pending_delivery", table_name="reminders")
    op.drop_column("reminders", "last_error")
    op.drop_column("reminders", "next_attempt_at")
    op.drop_column("reminders", "attempt_count")
