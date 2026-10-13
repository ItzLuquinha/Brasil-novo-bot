from datetime import datetime, timezone
import secrets
from decimal import Decimal
from sqlalchemy import desc, select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import CooldownActive, InsufficientFunds, NotFound
from app.models import EconomyAccount, EconomyTransaction, ShopItem, InventoryItem

def now() -> datetime:
    return datetime.now(timezone.utc)

def tx_id() -> int:
    return secrets.randbits(62)

async def get_or_create_account(session: AsyncSession, guild_id: int, user_id: int, lock: bool = False) -> EconomyAccount:
    stmt = select(EconomyAccount).where(EconomyAccount.guild_id == guild_id, EconomyAccount.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()
    if account is None:
        try:
            async with session.begin_nested():
                account = EconomyAccount(guild_id=guild_id, user_id=user_id)
                session.add(account)
                await session.flush()
        except IntegrityError:
            retry = await session.execute(select(EconomyAccount).where(EconomyAccount.guild_id == guild_id, EconomyAccount.user_id == user_id).with_for_update())
            account = retry.scalar_one()
    return account

async def add_wallet(session: AsyncSession, guild_id: int, user_id: int, amount: Decimal, kind: str, note: str | None = None, counterparty_user_id: int | None = None) -> EconomyAccount:
    if amount <= 0:
        raise ValueError("amount must be positive")
    account = await get_or_create_account(session, guild_id, user_id, lock=True)
    account.wallet += amount
    account.lifetime_earned += amount
    session.add(EconomyTransaction(id=tx_id(), guild_id=guild_id, user_id=user_id, counterparty_user_id=counterparty_user_id, amount=amount, kind=kind, note=note, created_at=now()))
    await session.flush()
    return account

async def remove_wallet(session: AsyncSession, guild_id: int, user_id: int, amount: Decimal, kind: str, note: str | None = None, counterparty_user_id: int | None = None) -> EconomyAccount:
    if amount <= 0:
        raise ValueError("amount must be positive")
    account = await get_or_create_account(session, guild_id, user_id, lock=True)
    if account.wallet < amount:
        raise InsufficientFunds()
    account.wallet -= amount
    account.lifetime_spent += amount
    session.add(EconomyTransaction(id=tx_id(), guild_id=guild_id, user_id=user_id, counterparty_user_id=counterparty_user_id, amount=-amount, kind=kind, note=note, created_at=now()))
    await session.flush()
    return account

async def move_wallet_to_bank(session: AsyncSession, guild_id: int, user_id: int, amount: Decimal) -> EconomyAccount:
    if amount <= 0:
        raise ValueError("amount must be positive")
    account = await get_or_create_account(session, guild_id, user_id, lock=True)
    if account.wallet < amount:
        raise InsufficientFunds()
    account.wallet -= amount
    account.bank += amount
    session.add(EconomyTransaction(id=tx_id(), guild_id=guild_id, user_id=user_id, amount=-amount, kind="deposit", created_at=now()))
    return account

async def move_bank_to_wallet(session: AsyncSession, guild_id: int, user_id: int, amount: Decimal) -> EconomyAccount:
    if amount <= 0:
        raise ValueError("amount must be positive")
    account = await get_or_create_account(session, guild_id, user_id, lock=True)
    if account.bank < amount:
        raise InsufficientFunds()
    account.bank -= amount
    account.wallet += amount
    session.add(EconomyTransaction(id=tx_id(), guild_id=guild_id, user_id=user_id, amount=amount, kind="withdraw", created_at=now()))
    return account

async def transfer(session: AsyncSession, guild_id: int, sender_id: int, receiver_id: int, amount: Decimal) -> None:
    if sender_id == receiver_id or amount <= 0:
        raise ValueError("invalid transfer")
    first, second = sorted((sender_id, receiver_id))
    await get_or_create_account(session, guild_id, first, lock=True)
    await get_or_create_account(session, guild_id, second, lock=True)
    sender = await get_or_create_account(session, guild_id, sender_id, lock=True)
    receiver = await get_or_create_account(session, guild_id, receiver_id, lock=True)
    if sender.wallet < amount:
        raise InsufficientFunds()
    sender.wallet -= amount
    sender.lifetime_spent += amount
    receiver.wallet += amount
    receiver.lifetime_earned += amount
    current = now()
    session.add(EconomyTransaction(id=tx_id(), guild_id=guild_id, user_id=sender_id, counterparty_user_id=receiver_id, amount=-amount, kind="transfer", created_at=current))
    session.add(EconomyTransaction(id=tx_id(), guild_id=guild_id, user_id=receiver_id, counterparty_user_id=sender_id, amount=amount, kind="transfer", created_at=current))

async def get_shop_items(session: AsyncSession, guild_id: int) -> list[ShopItem]:
    result = await session.execute(select(ShopItem).where(ShopItem.guild_id == guild_id).order_by(ShopItem.id.asc()))
    return list(result.scalars())

async def get_shop_item(session: AsyncSession, guild_id: int, item_id: int) -> ShopItem:
    item = await session.get(ShopItem, item_id)
    if item is None or item.guild_id != guild_id:
        raise NotFound()
    return item


def _check_shop_availability(item: ShopItem, current: datetime) -> None:
    if item.available_from is not None and current < item.available_from:
        raise CooldownActive(max(int((item.available_from - current).total_seconds()), 1))
    if item.available_until is not None and current >= item.available_until:
        raise ValueError("item unavailable")


async def buy_item(session: AsyncSession, guild_id: int, user_id: int, item_id: int, quantity: int) -> ShopItem:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    item = await session.get(ShopItem, item_id, with_for_update=True)
    if item is None or item.guild_id != guild_id:
        raise NotFound()
    current = now()
    _check_shop_availability(item, current)
    if item.stock is not None and item.stock < quantity:
        raise ValueError("insufficient stock")
    if item.cooldown_seconds and item.cooldown_seconds > 0:
        previous = await session.scalar(
            select(EconomyTransaction.created_at)
            .where(
                EconomyTransaction.guild_id == guild_id,
                EconomyTransaction.user_id == user_id,
                EconomyTransaction.kind == "purchase",
                EconomyTransaction.note == item.name,
            )
            .order_by(desc(EconomyTransaction.created_at))
            .limit(1)
        )
        if previous is not None:
            elapsed = int((current - previous).total_seconds())
            remaining = item.cooldown_seconds - elapsed
            if remaining > 0:
                raise CooldownActive(remaining)
    total = item.price * quantity
    account = await get_or_create_account(session, guild_id, user_id, lock=True)
    if account.wallet < total:
        raise InsufficientFunds()
    inventory_result = await session.execute(select(InventoryItem).where(InventoryItem.guild_id == guild_id, InventoryItem.user_id == user_id, InventoryItem.shop_item_id == item_id).with_for_update())
    inv = inventory_result.scalar_one_or_none()
    if inv is None:
        inv = InventoryItem(guild_id=guild_id, user_id=user_id, shop_item_id=item_id, quantity=0, acquired_at=current, created_at=current, updated_at=current)
        session.add(inv)
        await session.flush()
    if inv.quantity + quantity > item.stack_limit:
        raise ValueError("stack limit exceeded")
    account.wallet -= total
    account.lifetime_spent += total
    inv.quantity += quantity
    inv.updated_at = current
    if item.stock is not None:
        item.stock -= quantity
        item.updated_at = current
    session.add(EconomyTransaction(id=tx_id(), guild_id=guild_id, user_id=user_id, amount=-total, kind="purchase", note=item.name, created_at=current))
    return item

async def sell_item(session: AsyncSession, guild_id: int, user_id: int, item_id: int, quantity: int) -> Decimal:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    item = await session.get(ShopItem, item_id, with_for_update=True)
    if item is None or item.guild_id != guild_id:
        raise NotFound()
    result = await session.execute(select(InventoryItem).where(InventoryItem.guild_id == guild_id, InventoryItem.user_id == user_id, InventoryItem.shop_item_id == item_id).with_for_update())
    inv = result.scalar_one_or_none()
    if inv is None or inv.quantity < quantity:
        raise ValueError("not enough items")
    value = item.price * Decimal("0.5") * quantity
    current = now()
    inv.quantity -= quantity
    inv.updated_at = current
    if item.stock is not None:
        item.stock += quantity
        item.updated_at = current
    account = await get_or_create_account(session, guild_id, user_id, lock=True)
    account.wallet += value
    session.add(EconomyTransaction(id=tx_id(), guild_id=guild_id, user_id=user_id, amount=value, kind="sale", note=item.name, created_at=current))
    return value
