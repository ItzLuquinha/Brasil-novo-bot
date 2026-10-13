from __future__ import annotations
from decimal import Decimal
import logging
import math
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.models import EconomyAccount, EconomyTransaction, GuildSettings, ShopItem, InventoryItem, UserJob, Job, Experience
from app.repositories.economy import get_shop_items, buy_item, sell_item
from app.repositories.guilds import ensure_guild, ensure_user, ensure_member
from app.services.economy import economy_service
from app.services.cooldowns import check_and_set, release
from app.core.time import utc_now
from app.services.rewards import claim_reward, reward_config
from app.core.exceptions import CooldownActive, InsufficientFunds, NotFound, ValidationFailure
from app.discord.theme import embed, money, number, bar, percent, ledger, compact_money, status_line, duration


from app.services.rate_limits import command_rate_limit

logger = logging.getLogger("bn_bot.discord.economy")
MAX_TRANSACTION = 1_000_000_000.0
HIGH_VALUE_CONFIRMATION = Decimal("100000")


class PaginatedEmbedView(discord.ui.View):
    def __init__(self, owner_id: int, pages: list[discord.Embed], timeout: int = 180):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.pages = pages
        self.page = 0
        self.previous_button = discord.ui.Button(label="Anterior", style=discord.ButtonStyle.secondary, row=0)
        self.next_button = discord.ui.Button(label="Próxima", style=discord.ButtonStyle.secondary, row=0)
        self.close_button = discord.ui.Button(label="Fechar", style=discord.ButtonStyle.secondary, row=0)
        self.previous_button.callback = self.previous_callback
        self.next_button.callback = self.next_callback
        self.close_button.callback = self.close_callback
        self.add_item(self.previous_button)
        self.add_item(self.next_button)
        self.add_item(self.close_button)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await respond(interaction, "Este painel pertence a outro membro.", ephemeral=True)
            return False
        return True

    async def previous_callback(self, interaction: discord.Interaction) -> None:
        self.page = max(self.page - 1, 0)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    async def next_callback(self, interaction: discord.Interaction) -> None:
        self.page = min(self.page + 1, len(self.pages) - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.pages[self.page], view=self)

    async def close_callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(view=None)
        self.stop()


class PayConfirmView(discord.ui.View):
    def __init__(self, cog: "EconomyCog", owner_id: int, target: discord.Member, amount: Decimal):
        super().__init__(timeout=90)
        self.cog = cog
        self.owner_id = owner_id
        self.target = target
        self.amount = amount

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await respond(interaction, "Esta confirmação pertence a outro membro.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirmar transferência", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.complete_pay(interaction, self.target, self.amount)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Transferência cancelada.", embed=None, view=None)
        self.stop()


class JobSelectView(discord.ui.View):
    def __init__(self, cog: "EconomyCog", jobs: list[Job], owner_id: int, user_level: int = 0, page_index: int = 0):
        super().__init__(timeout=120)
        self.cog = cog
        self.jobs = jobs
        self.owner_id = owner_id
        self.user_level = user_level
        self.page_index = page_index
        self.page_size = 25
        self.select = discord.ui.Select(placeholder="Escolha seu emprego", min_values=1, max_values=1, options=self._options())
        self.select.callback = self.select_callback
        self.add_item(self.select)
        if self.page_index > 0:
            previous = discord.ui.Button(label="Anterior", style=discord.ButtonStyle.secondary, row=1)
            previous.callback = self.previous_callback
            self.add_item(previous)
        if (self.page_index + 1) * self.page_size < len(self.jobs):
            next_page = discord.ui.Button(label="Próxima", style=discord.ButtonStyle.secondary, row=1)
            next_page.callback = self.next_callback
            self.add_item(next_page)
        cancel = discord.ui.Button(label="Cancelar", style=discord.ButtonStyle.danger, row=1)
        cancel.callback = self.cancel_callback
        self.add_item(cancel)

    def _options(self) -> list[discord.SelectOption]:
        start = self.page_index * self.page_size
        current = self.jobs[start:start + self.page_size]
        options: list[discord.SelectOption] = []
        for row in current:
            requirements = row.requirements if isinstance(row.requirements, dict) else {}
            try:
                required_level = max(int(requirements.get("level", 0)), 0)
            except (TypeError, ValueError):
                required_level = 0
            locked = required_level > self.user_level
            if locked:
                label = f"Nível {required_level} bloqueado · {row.name}"
                description = f"BLOQUEADO · exige nível {required_level} · salário {money(row.salary)} · XP {row.xp_reward}"
            else:
                label = row.name
                description = f"Salário {money(row.salary)} · XP {row.xp_reward}"
                if required_level:
                    description += f" · requer nível {required_level}"
            options.append(discord.SelectOption(label=label[:100], value=row.key[:100], description=description[:100]))
        return options

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await respond(interaction, "Este seletor pertence a outro membro.", ephemeral=True)
            return False
        return True

    async def select_callback(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        await self.cog.equip_job(interaction, self.select.values[0])

    async def previous_callback(self, interaction: discord.Interaction) -> None:
        self.page_index -= 1
        await interaction.response.edit_message(view=JobSelectView(self.cog, self.jobs, self.owner_id, self.user_level, self.page_index))

    async def next_callback(self, interaction: discord.Interaction) -> None:
        self.page_index += 1
        await interaction.response.edit_message(view=JobSelectView(self.cog, self.jobs, self.owner_id, self.user_level, self.page_index))

    async def cancel_callback(self, interaction: discord.Interaction) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @staticmethod
    def guild_and_member(interaction: discord.Interaction) -> tuple[discord.Guild, discord.Member]:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise RuntimeError("guild context required")
        return interaction.guild, interaction.user

    async def ensure_context(self, session, guild: discord.Guild, member: discord.Member) -> None:
        await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
        await ensure_user(session, member.id, member.name, member.display_name, member.display_avatar.url, member.banner.url if member.banner else None, member.bot)
        await ensure_member(session, guild.id, member.id, member.joined_at)

    @staticmethod
    def valid_amount(amount: float) -> bool:
        return math.isfinite(amount) and 0 < amount <= MAX_TRANSACTION

    @app_commands.command(name="balance", description="Mostra carteira e banco.")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        guild, member = self.guild_and_member(interaction)
        target = user or member
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            await self.ensure_context(session, guild, target)
            data = await economy_service.balance(session, guild.id, target.id)
        total = data["total"]
        page = embed("BN / CARTEIRA", f"**{target.display_name}** · leitura financeira do servidor.", "economy")
        page.set_thumbnail(url=target.display_avatar.url)
        page.add_field(name="Patrimônio", value=f"**{money(total)}**", inline=False)
        page.add_field(name="Mapa do saldo", value=ledger([
            ("Carteira", money(data["wallet"])),
            ("Banco", money(data["bank"])),
            ("Total", money(total)),
        ]), inline=False)
        page.add_field(name="Liquidez", value=f"{bar(data['wallet'], total)}\nCarteira `{percent(data['wallet'], total)}` · Banco `{percent(data['bank'], total)}`", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="bank", description="Mostra o saldo do banco.")
    @app_commands.guild_only()
    async def bank(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            data = await economy_service.balance(session, guild.id, member.id)
        page = embed("BN / BANCO", f"**{member.display_name}** · reserva guardada.", "economy")
        page.add_field(name="Saldo bancário", value=money(data["bank"]), inline=True)
        page.add_field(name="Carteira", value=money(data["wallet"]), inline=True)
        page.add_field(name="Total", value=money(data["total"]), inline=True)
        page.add_field(name="Distribuição", value=f"{bar(data['wallet'], data['total'])}\nCarteira {percent(data['wallet'], data['total'])} · Banco {percent(data['bank'], data['total'])}", inline=False)
        await respond(interaction, embed=page)

    @command_rate_limit("deposit", 2)
    @app_commands.command(name="deposit", description="Deposita moedas no banco.")
    @app_commands.guild_only()
    async def deposit(self, interaction: discord.Interaction, amount: app_commands.Range[float, 0.01, MAX_TRANSACTION]) -> None:
        guild, member = self.guild_and_member(interaction)
        if not self.valid_amount(amount):
            await respond(interaction, "O valor precisa estar entre 0,01 e 1.000.000.000,00 moedas.", ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            data = await economy_service.deposit(session, guild.id, member.id, Decimal(str(amount)))
        page = embed("BN / DEPÓSITO", "Movimentação concluída.", "economy")
        page.add_field(name="Movido", value=money(Decimal(str(amount))), inline=True)
        page.add_field(name="Carteira", value=money(data["wallet"]), inline=True)
        page.add_field(name="Banco", value=money(data["bank"]), inline=True)
        await respond(interaction, embed=page)

    @command_rate_limit("withdraw", 2)
    @app_commands.command(name="withdraw", description="Saca moedas do banco.")
    @app_commands.guild_only()
    async def withdraw(self, interaction: discord.Interaction, amount: app_commands.Range[float, 0.01, MAX_TRANSACTION]) -> None:
        guild, member = self.guild_and_member(interaction)
        if not self.valid_amount(amount):
            await respond(interaction, "O valor precisa estar entre 0,01 e 1.000.000.000,00 moedas.", ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            data = await economy_service.withdraw(session, guild.id, member.id, Decimal(str(amount)))
        page = embed("BN / SAQUE", "Movimentação concluída.", "economy")
        page.add_field(name="Movido", value=money(Decimal(str(amount))), inline=True)
        page.add_field(name="Carteira", value=money(data["wallet"]), inline=True)
        page.add_field(name="Banco", value=money(data["bank"]), inline=True)
        await respond(interaction, embed=page)

    async def shop_item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        if interaction.guild is None:
            return []
        query = current.casefold().strip()
        async with session_factory() as session:
            rows = list((await session.execute(select(ShopItem).where(ShopItem.guild_id == interaction.guild.id).order_by(ShopItem.name.asc()).limit(100))).scalars())
        matches = [row for row in rows if not query or query in row.name.casefold() or query in str(row.id)]
        return [app_commands.Choice(name=f"#{row.id} · {row.name} · {compact_money(row.price)}"[:100], value=row.id) for row in matches[:25]]

    async def sell_item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        if interaction.guild is None:
            return []
        query = current.casefold().strip()
        async with session_factory() as session:
            result = await session.execute(
                select(ShopItem, InventoryItem)
                .join(InventoryItem, InventoryItem.shop_item_id == ShopItem.id)
                .where(InventoryItem.guild_id == interaction.guild.id, InventoryItem.user_id == interaction.user.id, InventoryItem.quantity > 0)
                .order_by(ShopItem.name.asc())
                .limit(100)
            )
            rows = result.all()
        matches = [(item, inv) for item, inv in rows if not query or query in item.name.casefold() or query in str(item.id)]
        return [app_commands.Choice(name=f"#{item.id} · {item.name} · {inv.quantity}x"[:100], value=item.id) for item, inv in matches[:25]]

    @command_rate_limit("pay", 5)
    @app_commands.command(name="pay", description="Transfere moedas para outro usuário.")
    @app_commands.guild_only()
    async def pay(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[float, 0.01, MAX_TRANSACTION]) -> None:
        guild, member = self.guild_and_member(interaction)
        target = user
        if target.id == member.id:
            await respond(interaction, "Você não pode transferir moedas para si mesmo.", ephemeral=True)
            return
        if target.bot:
            await respond(interaction, "Contas de bot não podem receber transferências.", ephemeral=True)
            return
        if not self.valid_amount(amount):
            await respond(interaction, "O valor precisa estar entre 0,01 e 1.000.000.000,00 moedas.", ephemeral=True)
            return
        transfer_amount = Decimal(str(amount))
        if transfer_amount >= HIGH_VALUE_CONFIRMATION:
            page = embed("BN / CONFIRMAR TRANSFERÊNCIA", "Esta transferência ultrapassa o limite de confirmação automática.", "economy")
            page.add_field(name="Destino", value=f"{target.mention} · `{target.display_name}`", inline=False)
            page.add_field(name="Valor", value=f"**{money(transfer_amount)}**", inline=True)
            page.add_field(name="Proteção", value="A operação só será concluída após sua confirmação.", inline=True)
            await interaction.response.send_message(embed=page, view=PayConfirmView(self, member.id, target, transfer_amount), ephemeral=True)
            return
        await self.complete_pay(interaction, target, transfer_amount)

    async def complete_pay(self, interaction: discord.Interaction, user: discord.Member, amount: Decimal) -> None:
        guild, member = self.guild_and_member(interaction)
        if user.id == member.id or user.bot or amount <= 0 or amount > Decimal(str(MAX_TRANSACTION)):
            await respond(interaction, "A transferência não é válida.", ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        try:
            async with session_factory() as session:
                await self.ensure_context(session, guild, member)
                await self.ensure_context(session, guild, user)
                await economy_service.transfer(session, guild.id, member.id, user.id, amount)
                sender_account = await session.scalar(select(EconomyAccount).where(EconomyAccount.guild_id == guild.id, EconomyAccount.user_id == member.id))
        except InsufficientFunds:
            await respond(interaction, "Saldo insuficiente para concluir esta transferência.", ephemeral=True)
            return
        except (NotFound, ValueError, ValidationFailure) as exc:
            await respond(interaction, str(exc) or "A transferência não pôde ser concluída.", ephemeral=True)
            return
        except SQLAlchemyError:
            logger.exception("pay persistence failed guild=%s user=%s target=%s", guild.id, member.id, user.id)
            await respond(interaction, "O banco de dados recusou a transferência. Tente novamente.", ephemeral=True)
            return
        page = embed("BN / TRANSFERÊNCIA", "Movimentação concluída entre duas carteiras.", "economy")
        page.add_field(name="Origem", value=member.mention, inline=True)
        page.add_field(name="Destino", value=user.mention, inline=True)
        page.add_field(name="Valor", value=money(amount), inline=True)
        page.add_field(name="Carteira restante", value=money(sender_account.wallet if sender_account else Decimal("0")), inline=False)
        await respond(interaction, embed=page, ephemeral=True)

    @app_commands.command(name="daily", description="Recebe a recompensa diária.")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction, ephemeral=True)
        try:
            async with session_factory() as session:
                await self.ensure_context(session, guild, member)
                settings = await session.get(GuildSettings, guild.id)
                configuration = reward_config(settings)
                amount, streak = await claim_reward(session, guild.id, member.id, "daily")
                await session.commit()
        except CooldownActive as exc:
            await respond(interaction, f"A recompensa diária já foi coletada. Próxima janela em {duration(exc.seconds)}.", ephemeral=True)
            return
        page = embed("BN / DAILY", "Recompensa diária confirmada.", "economy")
        bonus_percent = min(Decimal(max(streak - 1, 0)) * configuration["streak_bonus_percent"], configuration["streak_bonus_cap_percent"])
        page.add_field(name="Recebido", value=money(amount), inline=True)
        page.add_field(name="Base", value=money(configuration["daily_amount"]), inline=True)
        page.add_field(name="Bônus", value=f"+{bonus_percent}%", inline=True)
        page.add_field(name="Streak", value=f"`{streak}` dias", inline=True)
        page.add_field(name="Sequência", value=f"{bar(min(streak, 20), 20)}\n`{min(streak, 20)}/20` dias", inline=False)
        page.add_field(name="Próxima janela", value="Amanhã", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="weekly", description="Recebe a recompensa semanal.")
    @app_commands.guild_only()
    async def weekly(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction, ephemeral=True)
        try:
            async with session_factory() as session:
                await self.ensure_context(session, guild, member)
                settings = await session.get(GuildSettings, guild.id)
                configuration = reward_config(settings)
                amount, streak = await claim_reward(session, guild.id, member.id, "weekly")
                await session.commit()
        except CooldownActive as exc:
            await respond(interaction, f"A recompensa semanal já foi coletada. Próxima janela em {duration(exc.seconds)}.", ephemeral=True)
            return
        page = embed("BN / WEEKLY", "Recompensa semanal confirmada.", "economy")
        bonus_percent = min(Decimal(max(streak - 1, 0)) * configuration["streak_bonus_percent"], configuration["streak_bonus_cap_percent"])
        page.add_field(name="Recebido", value=money(amount), inline=True)
        page.add_field(name="Base", value=money(configuration["weekly_amount"]), inline=True)
        page.add_field(name="Bônus", value=f"+{bonus_percent}%", inline=True)
        page.add_field(name="Streak", value=f"`{streak}` semanas", inline=True)
        page.add_field(name="Sequência", value=f"{bar(min(streak, 12), 12)}\n`{min(streak, 12)}/12` semanas", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="shop", description="Lista os itens da loja.")
    @app_commands.guild_only()
    async def shop(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction)
        async with session_factory() as session:
            items = await get_shop_items(session, guild.id)
        rarity_labels = {"common": "Comum", "uncommon": "Incomum", "rare": "Raro", "epic": "Épico", "legendary": "Lendário"}
        now = utc_now()
        if not items:
            page = embed("BN / LOJA", "Nenhum item foi publicado ainda.", "economy")
            await respond(interaction, embed=page)
            return
        pages: list[discord.Embed] = []
        for page_index in range(0, len(items), 8):
            page_items = items[page_index:page_index + 8]
            page = embed("BN / LOJA", f"Catálogo do servidor · página {page_index // 8 + 1}/{math.ceil(len(items) / 8)}", "economy")
            for item in page_items:
                stock = "ilimitado" if item.stock is None else ("esgotado" if item.stock <= 0 else number(item.stock))
                rarity = rarity_labels.get(str(item.rarity).casefold(), str(item.rarity).capitalize())
                if item.available_from and now < item.available_from:
                    availability = f"abre {discord.utils.format_dt(item.available_from, 'R')}"
                elif item.available_until and now >= item.available_until:
                    availability = "encerrado"
                elif item.available_until:
                    availability = f"até {discord.utils.format_dt(item.available_until, 'R')}"
                else:
                    availability = "disponível"
                details = [f"**{money(item.price)}**", f"Raridade: `{rarity}` · Categoria: `{item.category}`", f"Estoque: `{stock}` · Limite por membro: `{item.stack_limit}`", f"Disponibilidade: {availability}"]
                if item.cooldown_seconds:
                    details.append(f"Cooldown de compra: `{duration(item.cooldown_seconds)}`")
                if item.description:
                    details.append(item.description[:300])
                page.add_field(name=f"#{item.id} · {item.name}", value="\n".join(details)[:1024], inline=False)
            pages.append(page)
        await respond(interaction, embed=pages[0], view=PaginatedEmbedView(member.id, pages))

    @command_rate_limit("buy", 2)
    @app_commands.autocomplete(item_id=shop_item_autocomplete)
    @app_commands.command(name="buy", description="Compra um item da loja.")
    @app_commands.guild_only()
    async def buy(self, interaction: discord.Interaction, item_id: int, quantity: app_commands.Range[int, 1, 99] = 1) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            item = await buy_item(session, guild.id, member.id, item_id, quantity)
            remaining_inventory = await session.scalar(select(func.coalesce(func.sum(InventoryItem.quantity), 0)).where(InventoryItem.guild_id == guild.id, InventoryItem.user_id == member.id, InventoryItem.shop_item_id == item_id))
            account = await session.scalar(select(EconomyAccount).where(EconomyAccount.guild_id == guild.id, EconomyAccount.user_id == member.id))
            await session.commit()
        total = item.price * quantity
        page = embed("BN / COMPRA", "Compra concluída e adicionada ao inventário.", "economy")
        page.add_field(name="Item", value=f"`#{item.id}` · {item.name}", inline=False)
        page.add_field(name="Quantidade", value=f"`{quantity}x`", inline=True)
        page.add_field(name="Total", value=money(total), inline=True)
        page.add_field(name="Em posse", value=f"`{int(remaining_inventory or 0)}x`", inline=True)
        page.add_field(name="Carteira restante", value=money(account.wallet if account else Decimal("0")), inline=False)
        await respond(interaction, embed=page)

    @command_rate_limit("sell", 2)
    @app_commands.autocomplete(item_id=sell_item_autocomplete)
    @app_commands.command(name="sell", description="Vende um item da loja.")
    @app_commands.guild_only()
    async def sell(self, interaction: discord.Interaction, item_id: int, quantity: app_commands.Range[int, 1, 99] = 1) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            value = await sell_item(session, guild.id, member.id, item_id, quantity)
            remaining_inventory = await session.scalar(select(func.coalesce(func.sum(InventoryItem.quantity), 0)).where(InventoryItem.guild_id == guild.id, InventoryItem.user_id == member.id, InventoryItem.shop_item_id == item_id))
            await session.commit()
        page = embed("BN / VENDA", "Item devolvido ao mercado por 50% do preço.", "economy")
        page.add_field(name="Item", value=f"`#{item_id}`", inline=True)
        page.add_field(name="Quantidade", value=f"`{quantity}x`", inline=True)
        page.add_field(name="Recebido", value=money(value), inline=True)
        page.add_field(name="Em posse", value=f"`{int(remaining_inventory or 0)}x`", inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="inventory", description="Mostra o inventário.")
    @app_commands.guild_only()
    async def inventory(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            result = await session.execute(select(InventoryItem, ShopItem).join(ShopItem, InventoryItem.shop_item_id == ShopItem.id).where(InventoryItem.guild_id == guild.id, InventoryItem.user_id == member.id, InventoryItem.quantity > 0).order_by(ShopItem.name.asc()))
            rows = result.all()
        if not rows:
            page = embed("BN / INVENTÁRIO", f"**{member.display_name}** ainda não possui itens.", "economy")
            await respond(interaction, embed=page)
            return
        pages: list[discord.Embed] = []
        for page_index in range(0, len(rows), 10):
            page_rows = rows[page_index:page_index + 10]
            page = embed("BN / INVENTÁRIO", f"Itens de **{member.display_name}** · página {page_index // 10 + 1}/{math.ceil(len(rows) / 10)}", "economy")
            for inv, item in page_rows:
                value = Decimal(item.price) * inv.quantity
                details = ledger([("Quantidade", f"{inv.quantity}x"), ("Preço", money(item.price)), ("Valor", money(value))])
                if item.description:
                    details += f"\n{item.description[:250]}"
                page.add_field(name=f"#{item.id} · {item.name}", value=details[:1024], inline=False)
            pages.append(page)
        await respond(interaction, embed=pages[0], view=PaginatedEmbedView(member.id, pages))

    @app_commands.command(name="transactions", description="Mostra seu histórico financeiro.")
    @app_commands.guild_only()
    @app_commands.choices(kind=[
        app_commands.Choice(name="Todas", value="all"),
        app_commands.Choice(name="Entradas", value="in"),
        app_commands.Choice(name="Saídas", value="out"),
        app_commands.Choice(name="Transferências", value="transfer"),
        app_commands.Choice(name="Compras", value="purchase"),
    ])
    async def transactions(self, interaction: discord.Interaction, kind: str = "all") -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            filters = [EconomyTransaction.guild_id == guild.id, EconomyTransaction.user_id == member.id]
            if kind == "in":
                filters.append(EconomyTransaction.amount > 0)
            elif kind == "out":
                filters.append(EconomyTransaction.amount < 0)
            elif kind in {"transfer", "purchase"}:
                filters.append(EconomyTransaction.kind == kind)
            result = await session.execute(select(EconomyTransaction).where(*filters).order_by(desc(EconomyTransaction.created_at)).limit(100))
            rows = list(result.scalars())
        if not rows:
            page = embed("BN / TRANSAÇÕES", "Nenhuma movimentação encontrada para esse filtro.", "economy")
            await respond(interaction, embed=page)
            return
        pages: list[discord.Embed] = []
        for page_index in range(0, len(rows), 10):
            page_rows = rows[page_index:page_index + 10]
            page = embed("BN / TRANSAÇÕES", f"Histórico financeiro · página {page_index // 10 + 1}/{math.ceil(len(rows) / 10)}", "economy")
            lines = []
            for row in page_rows:
                sign = "+" if row.amount >= 0 else "-"
                counterparty = f" · <@{row.counterparty_user_id}>" if row.counterparty_user_id else ""
                note = f" · {row.note[:80]}" if row.note else ""
                lines.append(f"`{sign}{money(abs(row.amount))}` · `{row.kind}`{counterparty}{note} · {discord.utils.format_dt(row.created_at, 'R')}")
            page.add_field(name="Movimentações", value="\n".join(lines)[:1024], inline=False)
            pages.append(page)
        await respond(interaction, embed=pages[0], view=PaginatedEmbedView(member.id, pages))

    @app_commands.command(name="jobs", description="Mostra o catálogo de empregos do servidor.")
    @app_commands.guild_only()
    async def jobs(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction)
        async with session_factory() as session:
            result = await session.execute(select(Job).where(Job.guild_id == guild.id).order_by(Job.salary.desc(), Job.name.asc()))
            rows = list(result.scalars())
            current_result = await session.execute(select(UserJob, Job).join(Job, UserJob.job_id == Job.id).where(UserJob.guild_id == guild.id, UserJob.user_id == member.id, Job.guild_id == guild.id))
            current = current_result.one_or_none()
            xp_row = await session.scalar(select(Experience).where(Experience.guild_id == guild.id, Experience.user_id == member.id))
            user_level = xp_row.level if xp_row else 0
        if not rows:
            page = embed("BN / EMPREGOS", "Nenhum emprego foi configurado neste servidor.", "economy")
            await respond(interaction, embed=page)
            return
        current_id = current[1].id if current is not None else None
        pages: list[discord.Embed] = []
        for page_index in range(0, len(rows), 10):
            page = embed("BN / EMPREGOS", f"Catálogo de empregos · página {page_index // 10 + 1}/{math.ceil(len(rows) / 10)} · use `/job` para escolher", "economy")
            for row in rows[page_index:page_index + 10]:
                requirements = row.requirements if isinstance(row.requirements, dict) else {}
                try:
                    required_level = max(int(requirements.get("level", 0)), 0)
                except (TypeError, ValueError):
                    required_level = 0
                marker = "ATUAL · " if row.id == current_id else ""
                requirement_text = f"Nível mínimo: `{required_level}`" if required_level else "Sem requisito de nível"
                page.add_field(name=f"{marker}{row.name}", value=f"Salário: **{money(row.salary)}**\nXP por turno: `{row.xp_reward}`\n{requirement_text}", inline=False)
            pages.append(page)
        await respond(interaction, embed=pages[0], view=PaginatedEmbedView(member.id, pages))

    @command_rate_limit("job", 2)
    @app_commands.command(name="job", description="Escolhe ou troca seu emprego.")
    @app_commands.guild_only()
    async def job(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            result = await session.execute(select(Job).where(Job.guild_id == guild.id).order_by(Job.salary.desc(), Job.name.asc()))
            rows = list(result.scalars().all())
            current_result = await session.execute(select(UserJob, Job).join(Job, UserJob.job_id == Job.id).where(UserJob.guild_id == guild.id, UserJob.user_id == member.id, Job.guild_id == guild.id))
            current = current_result.one_or_none()
            xp_row = await session.scalar(select(Experience).where(Experience.guild_id == guild.id, Experience.user_id == member.id))
            user_level = xp_row.level if xp_row else 0
        if not rows:
            await respond(interaction, "Nenhum emprego foi configurado neste servidor.", ephemeral=True)
            return
        page = embed("BN / ESCOLHA SEU EMPREGO", "Selecione um trabalho para equipar. Você pode trocar de emprego a qualquer momento.", "economy")
        current_name = current[1].name if current is not None else None
        page.add_field(name="Atual", value=current_name or "Nenhum", inline=True)
        page.add_field(name="Opções", value=f"`{len(rows)}` empregos disponíveis", inline=True)
        await respond(interaction, embed=page, view=JobSelectView(self, rows, member.id, user_level), ephemeral=True)

    async def equip_job(self, interaction: discord.Interaction, key: str) -> None:
        guild, member = self.guild_and_member(interaction)
        key = key.strip().casefold()
        async with session_factory() as session:
            await self.ensure_context(session, guild, member)
            job = (await session.execute(select(Job).where(Job.guild_id == guild.id, Job.key == key))).scalar_one_or_none()
            if job is None:
                await respond(interaction, "Esse emprego não está mais disponível.", ephemeral=True)
                return
            try:
                required_level = max(int(job.requirements.get("level", 0)), 0) if isinstance(job.requirements, dict) else 0
            except (TypeError, ValueError):
                required_level = 0
            xp = (await session.execute(select(Experience).where(Experience.guild_id == guild.id, Experience.user_id == member.id))).scalar_one_or_none()
            if (xp.level if xp else 0) < required_level:
                await respond(interaction, f"Este emprego exige nível {required_level}.", ephemeral=True)
                return
            user_job = (await session.execute(select(UserJob).where(UserJob.guild_id == guild.id, UserJob.user_id == member.id).with_for_update())).scalar_one_or_none()
            if user_job is None:
                try:
                    async with session.begin_nested():
                        user_job = UserJob(guild_id=guild.id, user_id=member.id, job_id=job.id, level=1, xp=0)
                        session.add(user_job)
                        await session.flush()
                except IntegrityError:
                    user_job = (await session.execute(select(UserJob).where(UserJob.guild_id == guild.id, UserJob.user_id == member.id).with_for_update())).scalar_one()
                    user_job.job_id = job.id
            else:
                user_job.job_id = job.id
            await session.commit()
        page = embed("BN / EMPREGO EQUIPADO", f"**{job.name}** está agora equipado.", "economy")
        page.add_field(name="Salário base", value=money(job.salary), inline=True)
        page.add_field(name="XP por turno", value=f"`{job.xp_reward}`", inline=True)
        page.add_field(name="Próximo passo", value="Use `/work` para trabalhar.", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="work", description="Trabalha no emprego equipado.")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction) -> None:
        guild, member = self.guild_and_member(interaction)
        await defer(interaction, ephemeral=True)
        cooldown_key = f"bn:work:{guild.id}:{member.id}"
        cooldown = None
        try:
            async with session_factory() as session:
                await self.ensure_context(session, guild, member)
                result = await session.execute(select(UserJob, Job).join(Job, UserJob.job_id == Job.id).where(UserJob.guild_id == guild.id, UserJob.user_id == member.id, Job.guild_id == guild.id))
                row = result.one_or_none()
                if row is None:
                    await respond(interaction, "Você ainda não possui um emprego configurado.", ephemeral=True)
                    return
                user_job, job = row
                cooldown = await check_and_set(cooldown_key, 3600)
                if cooldown:
                    await respond(interaction, f"Você já trabalhou recentemente. Aguarde {cooldown}s.", ephemeral=True)
                    return
                reward = job.salary * (Decimal("1") + Decimal(max(user_job.level - 1, 0)) * Decimal("0.05"))
                user_job.xp += job.xp_reward
                threshold = max(user_job.level, 1) * 100
                while user_job.xp >= threshold:
                    user_job.xp -= threshold
                    user_job.level += 1
                    threshold = max(user_job.level, 1) * 100
                user_job.last_work_at = utc_now()
                await economy_service.credit(session, guild.id, member.id, reward, "work", job.name)
                next_xp = max(user_job.level, 1) * 100
                current_xp = user_job.xp
                job_level = user_job.level
        except Exception:
            if cooldown is None:
                await release(cooldown_key)
            raise
        page = embed("BN / TURNO CONCLUÍDO", f"**{job.name}** · trabalho registrado.", "economy")
        page.add_field(name="Recebido", value=money(reward), inline=True)
        page.add_field(name="Nível do emprego", value=f"`{job_level}`", inline=True)
        page.add_field(name="Próximo turno", value=status_line("Cooldown", "1h" , "pending"), inline=True)
        page.add_field(name="Progresso", value=f"{bar(current_xp, next_xp)}\n`{current_xp}/{next_xp}` XP", inline=False)
        await respond(interaction, embed=page)
