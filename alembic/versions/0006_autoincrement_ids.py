from alembic import op

revision = "0006_autoincrement_ids"
down_revision = "0005_suggestion_channel"
branch_labels = None
depends_on = None

TABLES = ("member_activity", "polls", "punishments", "tickets", "warnings")


def upgrade() -> None:
    for table in TABLES:
        sequence = f"{table}_id_seq"
        op.execute(f"CREATE SEQUENCE IF NOT EXISTS public.{sequence} AS BIGINT")
        op.execute(f"ALTER TABLE public.{table} ALTER COLUMN id SET DEFAULT nextval('public.{sequence}'::regclass)")
        op.execute(f"ALTER SEQUENCE public.{sequence} OWNED BY public.{table}.id")
        op.execute(f"SELECT setval('public.{sequence}'::regclass, COALESCE((SELECT MAX(id) FROM public.{table}), 0) + 1, false)")


def downgrade() -> None:
    for table in reversed(TABLES):
        sequence = f"{table}_id_seq"
        op.execute(f"ALTER TABLE public.{table} ALTER COLUMN id DROP DEFAULT")
        op.execute(f"DROP SEQUENCE IF EXISTS public.{sequence}")
