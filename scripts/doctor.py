from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    from app.core.runtime import ensure_project_venv

    ensure_project_venv(PROJECT_ROOT)
    print(f"Python: {sys.version.split()[0]}")
    print(f"Executável: {Path(sys.executable).resolve()}")
    in_venv = sys.prefix != sys.base_prefix
    print(f"Virtualenv ativa: {in_venv}")
    print(f"Virtualenv esperada no caminho: {'.venv' in str(Path(sys.executable).resolve()).lower()}")
    try:
        print(f"greenlet: {importlib.metadata.version('greenlet')}")
    except importlib.metadata.PackageNotFoundError:
        print("greenlet: AUSENTE")
        raise SystemExit(1)
    try:
        print(f"SQLAlchemy: {importlib.metadata.version('SQLAlchemy')}")
        print(f"asyncpg: {importlib.metadata.version('asyncpg')}")
        print(f"discord.py: {importlib.metadata.version('discord.py')}")
    except importlib.metadata.PackageNotFoundError as exc:
        print(f"dependência ausente: {exc}")
        raise SystemExit(1)
    if sys.version_info < (3, 12):
        print("Python 3.12+ é obrigatório")
        raise SystemExit(1)
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
            __import__(module_name)
        print(f"Command definitions: OK ({len(command_modules)} módulos)")
    except Exception as exc:
        print(f"Command definitions: ERRO | {module_name}: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc
    print("BN Bot environment check passed")


if __name__ == "__main__":
    main()
