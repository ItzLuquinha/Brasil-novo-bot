import asyncio
import logging
import sys
from importlib import import_module
from pathlib import Path


def runtime_preflight() -> None:
    from app.core.runtime import ensure_project_venv

    ensure_project_venv(Path(__file__).resolve().parent)
    if sys.version_info < (3, 12):
        raise SystemExit(f"Python 3.12+ é obrigatório. Versão atual: {sys.version.split()[0]}")
    try:
        import_module("greenlet")
    except Exception as exc:
        raise SystemExit(
            "Dependência ausente: greenlet. Execute `python -m pip install -r requirements.txt` usando o Python da .venv e tente novamente."
        ) from exc
    command_modules = (
        "app.discord.cogs.utility",
        "app.discord.cogs.economy",
        "app.discord.cogs.progression",
        "app.discord.cogs.moderation",
        "app.discord.cogs.community",
        "app.discord.cogs.automod",
        "app.discord.cogs.admin",
        "app.discord.cogs.antiraid",
    )
    try:
        for module_name in command_modules:
            import_module(module_name)
    except Exception as exc:
        raise SystemExit(
            f"Falha ao carregar definições dos comandos em {module_name}: {type(exc).__name__}: {exc}"
        ) from exc


runtime_preflight()

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings
from app.core.logging import configure_logging
from app.core.migrations import database_at_head, upgrade_to_head
from app.discord.bot import BNBot


async def main() -> None:
    configure_logging()
    logger = logging.getLogger("bn_bot")
    logger.info("checking database migrations")
    if await database_at_head():
        logger.info("database migrations already at head")
    else:
        logger.info("running database migrations")
        try:
            await asyncio.wait_for(asyncio.to_thread(upgrade_to_head), timeout=35)
        except asyncio.TimeoutError as exc:
            raise SystemExit("As migrações excederam 35 segundos. Verifique a conexão com o PostgreSQL e locks ativos antes de iniciar o BN Bot.") from exc
        logger.info("database migrations complete")
    bot = BNBot()
    logger.info("starting %s", get_settings().app_name)
    try:
        await bot.start(get_settings().discord_token)
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
