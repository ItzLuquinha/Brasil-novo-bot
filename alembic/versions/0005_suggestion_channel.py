from alembic import op
import sqlalchemy as sa

revision = "0005_suggestion_channel"
down_revision = "0004_community_systems"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("suggestions", sa.Column("channel_id", sa.BigInteger(), nullable=True))

def downgrade() -> None:
    op.drop_column("suggestions", "channel_id")
