from alembic import op

revision = "0007_channel_activity_sequence"
down_revision = "0006_autoincrement_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS public.channel_activity_id_seq AS BIGINT")
    op.execute("ALTER TABLE public.channel_activity ALTER COLUMN id SET DEFAULT nextval('public.channel_activity_id_seq'::regclass)")
    op.execute("ALTER SEQUENCE public.channel_activity_id_seq OWNED BY public.channel_activity.id")
    op.execute("SELECT setval('public.channel_activity_id_seq'::regclass, COALESCE((SELECT MAX(id) FROM public.channel_activity), 0) + 1, false)")


def downgrade() -> None:
    op.execute("ALTER TABLE public.channel_activity ALTER COLUMN id DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS public.channel_activity_id_seq")
