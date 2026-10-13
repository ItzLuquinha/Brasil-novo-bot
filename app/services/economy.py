from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories import economy

class EconomyService:
    async def balance(self, session: AsyncSession, guild_id: int, user_id: int) -> dict[str, Decimal]:
        account = await economy.get_or_create_account(session, guild_id, user_id)
        await session.commit()
        return {"wallet": account.wallet, "bank": account.bank, "total": account.wallet + account.bank}

    async def deposit(self, session: AsyncSession, guild_id: int, user_id: int, amount: Decimal) -> dict[str, Decimal]:
        account = await economy.move_wallet_to_bank(session, guild_id, user_id, amount)
        await session.commit()
        return {"wallet": account.wallet, "bank": account.bank, "total": account.wallet + account.bank}

    async def withdraw(self, session: AsyncSession, guild_id: int, user_id: int, amount: Decimal) -> dict[str, Decimal]:
        account = await economy.move_bank_to_wallet(session, guild_id, user_id, amount)
        await session.commit()
        return {"wallet": account.wallet, "bank": account.bank, "total": account.wallet + account.bank}

    async def transfer(self, session: AsyncSession, guild_id: int, sender_id: int, receiver_id: int, amount: Decimal) -> None:
        await economy.transfer(session, guild_id, sender_id, receiver_id, amount)
        await session.commit()

    async def credit(self, session: AsyncSession, guild_id: int, user_id: int, amount: Decimal, kind: str, note: str | None = None) -> None:
        await economy.add_wallet(session, guild_id, user_id, amount, kind, note)
        await session.commit()

    async def debit(self, session: AsyncSession, guild_id: int, user_id: int, amount: Decimal, kind: str, note: str | None = None) -> None:
        await economy.remove_wallet(session, guild_id, user_id, amount, kind, note)
        await session.commit()

economy_service = EconomyService()
