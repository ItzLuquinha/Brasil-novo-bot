from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.core.db import get_engine


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _migration_heads() -> set[str]:
    config = Config(str(_project_root() / "alembic.ini"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def database_at_head() -> bool:
    try:
        async with get_engine().connect() as connection:
            result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            versions = {str(row[0]) for row in result.all()}
        return bool(versions) and versions == _migration_heads()
    except Exception:
        return False


def upgrade_to_head() -> None:
    project_root = _project_root()
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    command.upgrade(config, "head")
