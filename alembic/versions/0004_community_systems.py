from alembic import op
import sqlalchemy as sa

revision = "0004_community_systems"
down_revision = "0003_antiraid"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("tickets", sa.Column("panel_message_id", sa.BigInteger(), nullable=True))
    op.add_column("suggestions", sa.Column("message_id", sa.BigInteger(), nullable=True))
    op.add_column("giveaways", sa.Column("message_id", sa.BigInteger(), nullable=True))
    op.add_column("polls", sa.Column("message_id", sa.BigInteger(), nullable=True))
    op.create_table("suggestion_votes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("suggestion_id", sa.BigInteger(), sa.ForeignKey("suggestions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("suggestion_id", "user_id"))
    op.create_index("ix_suggestion_votes_suggestion", "suggestion_votes", ["suggestion_id"])
    op.create_table("giveaway_entries",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("giveaway_id", sa.BigInteger(), sa.ForeignKey("giveaways.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("giveaway_id", "user_id"))
    op.create_index("ix_giveaway_entries_giveaway", "giveaway_entries", ["giveaway_id"])
    op.create_table("poll_votes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("poll_id", sa.BigInteger(), sa.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("option_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("poll_id", "user_id"))
    op.create_index("ix_poll_votes_poll_option", "poll_votes", ["poll_id", "option_index"])
    op.create_table("ticket_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("ticket_id", sa.BigInteger(), sa.ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_ticket_events_ticket_created", "ticket_events", ["ticket_id", "created_at"])

def downgrade() -> None:
    op.drop_index("ix_ticket_events_ticket_created", table_name="ticket_events")
    op.drop_table("ticket_events")
    op.drop_index("ix_poll_votes_poll_option", table_name="poll_votes")
    op.drop_table("poll_votes")
    op.drop_index("ix_giveaway_entries_giveaway", table_name="giveaway_entries")
    op.drop_table("giveaway_entries")
    op.drop_index("ix_suggestion_votes_suggestion", table_name="suggestion_votes")
    op.drop_table("suggestion_votes")
    op.drop_column("polls", "message_id")
    op.drop_column("giveaways", "message_id")
    op.drop_column("suggestions", "message_id")
    op.drop_column("tickets", "panel_message_id")
