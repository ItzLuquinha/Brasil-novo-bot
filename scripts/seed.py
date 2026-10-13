import asyncio
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.core.db import session_factory
from app.core.time import utc_now
from app.repositories.guilds import ensure_guild
from app.models import Achievement, Job, ShopItem


async def seed() -> None:
    guild_id = int(input("Guild ID to seed: ").strip())
    async with session_factory() as session:
        await ensure_guild(session, guild_id, f"Guild {guild_id}")
        current = utc_now()
        rows = [
            ShopItem(guild_id=guild_id, name="Caixa de Recompensa", description="Consumível básico.", category="consumable", rarity="common", price=Decimal("500"), stock=None, stack_limit=10, created_at=current, updated_at=current),
            ShopItem(guild_id=guild_id, name="Passe VIP", description="Item especial para uso em regras do servidor.", category="special", rarity="rare", price=Decimal("5000"), stock=25, stack_limit=1, created_at=current, updated_at=current),
            Job(guild_id=guild_id, key="pescador", name="Pescador", salary=Decimal("180"), xp_reward=25, requirements={}, created_at=current, updated_at=current),
            Job(guild_id=guild_id, key="programador", name="Programador", salary=Decimal("240"), xp_reward=30, requirements={"level": 3}, created_at=current, updated_at=current),
            Achievement(guild_id=guild_id, key="first_wallet", name="Primeiro Saldo", description="Realize sua primeira entrada de moedas.", category="economy", secret=False, created_at=current, updated_at=current),
            Achievement(guild_id=guild_id, key="active_member", name="Membro Ativo", description="Participe ativamente do servidor.", category="activity", secret=False, created_at=current, updated_at=current),
        ]
        for row in rows:
            session.add(row)
        await session.commit()
    print("Seed concluído")


if __name__ == "__main__":
    asyncio.run(seed())
