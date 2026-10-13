from alembic import op
import sqlalchemy as sa

revision = "0011_voice_tracking"
down_revision = "0010_remove_bump_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("members", sa.Column("voice_joined_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("members", "voice_joined_at")
