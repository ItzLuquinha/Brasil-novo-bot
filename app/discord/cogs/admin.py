from __future__ import annotations
import logging
from datetime import datetime, timezone
from decimal import Decimal
import math
import re
import unicodedata
import secrets
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.core.db import session_factory
from app.core.time import utc_now
from app.core.interactions import defer, respond
from app.models import AuditLog, GuildSettings, ShopItem, Job, UserJob
from app.repositories.guilds import ensure_guild, ensure_user, ensure_member
from app.services.economy import economy_service
from app.discord.theme import embed, money, ledger

logger = logging.getLogger("bn_bot.discord.admin")

admin_group = app_commands.Group(name="admin", description="Administração do BN Bot.", default_permissions=discord.Permissions(manage_guild=True))
MAX_ADMIN_AMOUNT = 1_000_000_000.0
SHOP_RARITY_CHOICES = [
    app_commands.Choice(name="Comum", value="common"),
    app_commands.Choice(name="Incomum", value="uncommon"),
    app_commands.Choice(name="Raro", value="rare"),
    app_commands.Choice(name="Épico", value="epic"),
    app_commands.Choice(name="Lendário", value="legendary"),
]


def parse_shop_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Data/hora inválida. Use ISO 8601, por exemplo 2026-12-31T23:59:00+00:00.") from exc
    if parsed.tzinfo is None:
        raise ValueError("A data/hora precisa informar o timezone, por exemplo +00:00.")
    return parsed.astimezone(timezone.utc)


class JobRemoveConfirmView(discord.ui.View):
    def __init__(self, cog: "AdminCog", owner_id: int, job_id: int, job_name: str) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.owner_id = owner_id
        self.job_id = job_id
        self.job_name = job_name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Esta confirmação pertence a outro administrador.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Remover emprego", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await defer(interaction, ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return
        async with session_factory() as session:
            row = await session.scalar(select(Job).where(Job.guild_id == guild.id, Job.id == self.job_id).with_for_update())
            if row is None:
                await respond(interaction, "Esse emprego já foi removido.", ephemeral=True)
                self.stop()
                return
            name = row.name
            key = row.key
            result = await session.execute(select(UserJob.id).where(UserJob.guild_id == guild.id, UserJob.job_id == row.id))
            affected = len(result.scalars().all())
            await session.delete(row)
            await session.commit()
        await self.cog.audit(guild.id, interaction.user.id, "job.delete", f"job:{self.job_id}", {"key": key, "name": name}, {"affected_members": affected})
        page = embed("BN / EMPREGO REMOVIDO", f"**{name}** foi removido da economia do servidor.", "admin")
        page.add_field(name="Membros afetados", value=f"`{affected}`", inline=False)
        await interaction.message.edit(embed=page, view=None)
        for item in self.children:
            item.disabled = True
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def audit(self, guild_id: int, executor_id: int, action: str, resource: str, before: dict | None, after: dict | None) -> None:
        try:
            async with session_factory() as session:
                session.add(AuditLog(id=secrets.randbits(62), guild_id=guild_id, executor_id=executor_id, action=action, resource=resource, before_state=before, after_state=after, created_at=utc_now()))
                await session.commit()
        except Exception:
            logger.exception("audit persistence failed action=%s resource=%s", action, resource)

    @staticmethod
    def valid_amount(amount: float) -> bool:
        return math.isfinite(amount) and 0 < amount <= MAX_ADMIN_AMOUNT

    @admin_group.command(name="purge-log", description="Consulta, configura ou desativa o canal de auditoria do /purge.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(canal="Canal de texto para os registros", desativar="Desativa o registro de mensagens apagadas")
    async def purge_log(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | None = None,
        desativar: bool = False,
    ) -> None:
        await defer(interaction, ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await respond(interaction, "Este comando só pode ser usado em um servidor.", ephemeral=True)
            return
        if canal is not None and desativar:
            await respond(interaction, "Selecione um canal ou ative `desativar`, mas não os dois.", ephemeral=True)
            return
        if canal is not None and canal.guild.id != guild.id:
            await respond(interaction, "O canal precisa pertencer a este servidor.", ephemeral=True)
            return

        async with session_factory() as session:
            settings_row = await session.get(GuildSettings, guild.id)
            current_config = dict(settings_row.config or {}) if settings_row is not None else {}
            previous_channel_id = current_config.get("purge_log_channel_id")

            if canal is None and not desativar:
                if previous_channel_id is None:
                    message = "O registro de /purge está desativado. Informe `canal` para configurar."
                else:
                    try:
                        current_id = int(previous_channel_id)
                    except (TypeError, ValueError):
                        current_id = 0
                    current_channel = guild.get_channel(current_id) if current_id else None
                    if isinstance(current_channel, discord.TextChannel):
                        message = f"Canal de auditoria atual: {current_channel.mention} (`{current_channel.id}`)."
                    else:
                        message = f"O canal configurado (`{previous_channel_id}`) não está mais disponível. Escolha outro canal ou use `desativar`."
                await respond(interaction, message, ephemeral=True)
                return

            if canal is not None:
                bot_member = guild.me
                if bot_member is None:
                    await respond(interaction, "Não consegui verificar as permissões do bot no servidor.", ephemeral=True)
                    return
                permissions = canal.permissions_for(bot_member)
                if not (permissions.view_channel and permissions.send_messages and permissions.attach_files):
                    await respond(interaction, "No canal escolhido, o bot precisa de View Channel, Send Messages e Attach Files.", ephemeral=True)
                    return

            await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
            settings_row = await session.get(GuildSettings, guild.id)
            if settings_row is None:
                await respond(interaction, "Não foi possível inicializar as configurações deste servidor.", ephemeral=True)
                return
            config = dict(settings_row.config or {})
            before = config.get("purge_log_channel_id")
            if desativar:
                config.pop("purge_log_channel_id", None)
                action = "desativado"
                after = None
            else:
                config["purge_log_channel_id"] = canal.id
                action = f"configurado para {canal.mention}"
                after = canal.id
            settings_row.config = config
            settings_row.updated_at = utc_now()
            await session.commit()

        await self.audit(
            guild.id,
            interaction.user.id,
            "moderation.purge_log_config",
            "guild_settings:purge_log_channel_id",
            {"purge_log_channel_id": before},
            {"purge_log_channel_id": after},
        )
        await respond(interaction, f"Canal de auditoria do /purge {action}.", ephemeral=True)

    @admin_group.command(name="credit", description="Adiciona moedas a um usuário.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def credit(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT], note: str | None = None) -> None:
        await defer(interaction, ephemeral=True)
        if not self.valid_amount(amount):
            await respond(interaction, "O valor deve estar entre 0,01 e 1.000.000.000,00.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        async with session_factory() as session:
            await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
            await ensure_user(session, user.id, user.name, user.display_name, user.display_avatar.url, user.banner.url if user.banner else None, user.bot)
            await ensure_member(session, guild.id, user.id, user.joined_at)
            await economy_service.credit(session, guild.id, user.id, Decimal(str(amount)), "admin_credit", note[:500] if note else None)
        await self.audit(guild.id, interaction.user.id, "economy.credit", f"user:{user.id}", None, {"amount": str(amount), "note": note})
        page = embed("BN / CRÉDITO", f"{user.mention} recebeu moedas administrativas.", "admin")
        page.add_field(name="Operação", value=ledger([("Usuário", str(user.id)), ("Valor", money(amount))]), inline=False)
        page.add_field(name="Nota", value=note[:1024] if note else "Não informada", inline=False)
        await respond(interaction, embed=page)

    @admin_group.command(name="debit", description="Remove moedas de um usuário.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def debit(self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT], note: str | None = None) -> None:
        await defer(interaction, ephemeral=True)
        if not self.valid_amount(amount):
            await respond(interaction, "O valor deve estar entre 0,01 e 1.000.000.000,00.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        async with session_factory() as session:
            await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
            await ensure_user(session, user.id, user.name, user.display_name, user.display_avatar.url, user.banner.url if user.banner else None, user.bot)
            await ensure_member(session, guild.id, user.id, user.joined_at)
            await economy_service.debit(session, guild.id, user.id, Decimal(str(amount)), "admin_debit", note[:500] if note else None)
        await self.audit(guild.id, interaction.user.id, "economy.debit", f"user:{user.id}", None, {"amount": str(amount), "note": note})
        page = embed("BN / DÉBITO", f"{user.mention} teve moedas removidas.", "admin")
        page.add_field(name="Operação", value=ledger([("Usuário", str(user.id)), ("Valor", money(amount))]), inline=False)
        page.add_field(name="Nota", value=note[:1024] if note else "Não informada", inline=False)
        await respond(interaction, embed=page)

    @admin_group.command(name="shop-add", description="Cria um item completo na loja.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(rarity=SHOP_RARITY_CHOICES)
    @app_commands.describe(
        name="Nome do item",
        price="Preço de compra",
        category="Categoria do item",
        stock="Estoque; vazio = ilimitado",
        description="Descrição do item",
        rarity="Raridade",
        stack_limit="Máximo que um usuário pode acumular",
        cooldown_seconds="Cooldown individual de compra em segundos",
        available_from="Início da disponibilidade em ISO 8601",
        available_until="Fim da disponibilidade em ISO 8601",
    )
    async def shop_add(
        self,
        interaction: discord.Interaction,
        name: str,
        price: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT],
        category: str,
        stock: app_commands.Range[int, 0, 1_000_000] | None = None,
        description: str | None = None,
        rarity: str = "common",
        stack_limit: app_commands.Range[int, 1, 1_000_000] = 99,
        cooldown_seconds: app_commands.Range[int, 0, 604800] | None = None,
        available_from: str | None = None,
        available_until: str | None = None,
    ) -> None:
        await defer(interaction, ephemeral=True)
        name = " ".join(name.split())
        category = " ".join(category.split())
        description = " ".join((description or "").split())
        if not name or len(name) > 100 or not category or len(category) > 50 or len(description) > 500 or not self.valid_amount(price):
            await respond(interaction, "Nome, categoria, descrição e preço não atendem aos limites da loja.", ephemeral=True)
            return
        if rarity not in {choice.value for choice in SHOP_RARITY_CHOICES}:
            await respond(interaction, "Raridade inválida.", ephemeral=True)
            return
        try:
            starts_at = parse_shop_datetime(available_from)
            ends_at = parse_shop_datetime(available_until)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        if starts_at and ends_at and starts_at >= ends_at:
            await respond(interaction, "A disponibilidade inicial precisa ser anterior à final.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        async with session_factory() as session:
            duplicate = await session.scalar(select(ShopItem.id).where(ShopItem.guild_id == guild.id, func.lower(ShopItem.name) == name.casefold()).limit(1))
            if duplicate is not None:
                await respond(interaction, "Já existe um item com esse nome nesta loja.", ephemeral=True)
                return
            row = ShopItem(
                guild_id=guild.id,
                name=name,
                description=description,
                category=category,
                rarity=rarity,
                price=Decimal(str(price)),
                stock=stock,
                stack_limit=stack_limit,
                metadata_json={},
                available_from=starts_at,
                available_until=ends_at,
                cooldown_seconds=cooldown_seconds,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(row)
            try:
                await session.flush()
                item_id = row.id
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await respond(interaction, "O item não pôde ser criado porque o nome já existe.", ephemeral=True)
                return
        await self.audit(guild.id, interaction.user.id, "shop.create", f"item:{item_id}", None, {"name": name, "price": str(price), "category": category, "stock": stock, "rarity": rarity, "stack_limit": stack_limit, "cooldown_seconds": cooldown_seconds, "available_from": starts_at.isoformat() if starts_at else None, "available_until": ends_at.isoformat() if ends_at else None})
        page = embed("BN / ITEM PUBLICADO", f"**{name}** entrou na loja.", "admin")
        page.add_field(name="ID", value=f"`{item_id}`", inline=True)
        page.add_field(name="Preço", value=money(price), inline=True)
        page.add_field(name="Estoque", value="∞" if stock is None else f"`{stock}`", inline=True)
        page.add_field(name="Raridade", value=f"`{rarity}`", inline=True)
        page.add_field(name="Stack", value=f"`{stack_limit}`", inline=True)
        page.add_field(name="Cooldown", value=f"`{cooldown_seconds}s`" if cooldown_seconds else "Nenhum", inline=True)
        await respond(interaction, embed=page)

    @admin_group.command(name="job-add", description="Cria um emprego sem exigir uma chave manual.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(name="Nome do emprego", salary="Salário base por turno", xp_reward="XP recebido por turno")
    async def job_add(self, interaction: discord.Interaction, name: str, salary: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT], xp_reward: app_commands.Range[int, 1, 100000] = 25) -> None:
        await defer(interaction, ephemeral=True)
        name = " ".join(name.split())
        if not name or len(name) > 100 or not self.valid_amount(salary):
            await respond(interaction, "Nome e salário precisam respeitar os limites do emprego.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").casefold()
        key_base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:26] or "job"
        async with session_factory() as session:
            existing_keys = {str(value) for value in (await session.execute(select(Job.key).where(Job.guild_id == guild.id))).scalars().all()}
            key = key_base
            suffix = 2
            while key in existing_keys:
                suffix_text = f"-{suffix}"
                key = f"{key_base[:32 - len(suffix_text)]}{suffix_text}"
                suffix += 1
                if suffix > 10000:
                    await respond(interaction, "Não foi possível gerar um identificador interno disponível.", ephemeral=True)
                    return
            row = Job(guild_id=guild.id, key=key, name=name, salary=Decimal(str(salary)), xp_reward=xp_reward, requirements={}, created_at=utc_now(), updated_at=utc_now())
            session.add(row)
            try:
                await session.flush()
                job_id = row.id
                await session.commit()
            except IntegrityError:
                await session.rollback()
                await respond(interaction, "O emprego não pôde ser criado. Tente novamente.", ephemeral=True)
                return
        await self.audit(guild.id, interaction.user.id, "job.create", f"job:{job_id}", None, {"key": key, "salary": str(salary), "xp_reward": xp_reward})
        page = embed("BN / EMPREGO CRIADO", f"**{name}** está disponível para os membros.", "admin")
        page.add_field(name="Salário", value=money(salary), inline=True)
        page.add_field(name="XP por turno", value=f"`{xp_reward}`", inline=True)
        page.add_field(name="Próximo passo", value="Os membros podem escolher pelo `/job`.", inline=False)
        await respond(interaction, embed=page)

    async def job_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        guild = interaction.guild
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if guild is None or member is None or not (member.guild_permissions.administrator or member.guild_permissions.manage_guild):
            return []
        async with session_factory() as session:
            rows = list((await session.execute(select(Job).where(Job.guild_id == guild.id).order_by(Job.name.asc()).limit(100))).scalars().all())
        query = current.casefold().strip()
        matches = [row for row in rows if not query or query in row.name.casefold() or query in row.key.casefold()]
        return [app_commands.Choice(name=f"{row.name} · {money(row.salary)}"[:100], value=str(row.id)) for row in matches[:25]]

    @admin_group.command(name="job-remove", description="Remove um emprego da economia.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(job="Escolha o emprego que será removido")
    @app_commands.autocomplete(job=job_autocomplete)
    async def job_remove(self, interaction: discord.Interaction, job: str) -> None:
        await defer(interaction, ephemeral=True)
        guild = interaction.guild
        assert guild is not None
        try:
            job_id = int(job)
        except ValueError:
            await respond(interaction, "Escolha um emprego pela lista de sugestões.", ephemeral=True)
            return
        async with session_factory() as session:
            row = await session.scalar(select(Job).where(Job.guild_id == guild.id, Job.id == job_id))
            if row is None:
                await respond(interaction, "Esse emprego não existe neste servidor.", ephemeral=True)
                return
            assigned = int(await session.scalar(select(func.count(UserJob.id)).where(UserJob.guild_id == guild.id, UserJob.job_id == job_id)) or 0)
        page = embed("BN / REMOVER EMPREGO", f"Você está prestes a remover **{row.name}**.", "admin")
        page.add_field(name="Salário", value=money(row.salary), inline=True)
        page.add_field(name="Membros com este emprego", value=f"`{assigned}`", inline=True)
        page.add_field(name="Consequência", value="Os membros atualmente equipados perderão esse emprego.", inline=False)
        await respond(interaction, embed=page, view=JobRemoveConfirmView(self, interaction.user.id, row.id, row.name))

    @admin_group.command(name="rewards", description="Configura as recompensas diária e semanal.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(daily_amount="Valor base do daily", weekly_amount="Valor base do weekly", streak_bonus_percent="Bônus percentual por dia/semana de streak", streak_bonus_cap_percent="Limite máximo do bônus de streak")
    async def rewards(
        self,
        interaction: discord.Interaction,
        daily_amount: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT],
        weekly_amount: app_commands.Range[float, 0.01, MAX_ADMIN_AMOUNT],
        streak_bonus_percent: app_commands.Range[float, 0, 100],
        streak_bonus_cap_percent: app_commands.Range[float, 0, 1000],
    ) -> None:
        await defer(interaction, ephemeral=True)
        guild = interaction.guild
        assert guild is not None
        values = {
            "daily_amount": str(Decimal(str(daily_amount)).quantize(Decimal("0.01"))),
            "weekly_amount": str(Decimal(str(weekly_amount)).quantize(Decimal("0.01"))),
            "streak_bonus_percent": str(Decimal(str(streak_bonus_percent)).quantize(Decimal("0.01"))),
            "streak_bonus_cap_percent": str(Decimal(str(streak_bonus_cap_percent)).quantize(Decimal("0.01"))),
        }
        async with session_factory() as session:
            settings = await session.get(GuildSettings, guild.id)
            if settings is None:
                now = utc_now()
                settings = GuildSettings(guild_id=guild.id, timezone="UTC", locale="pt-BR", economy_enabled=True, levels_enabled=True, analytics_enabled=True, automod_enabled=False, config={}, created_at=now, updated_at=now)
                session.add(settings)
            config = dict(settings.config or {})
            config["rewards"] = values
            settings.config = config
            settings.updated_at = utc_now()
            await session.commit()
        await self.audit(guild.id, interaction.user.id, "economy.rewards_config", "settings", None, values)
        page = embed("BN / RECOMPENSAS", "Os valores de daily, weekly e streak foram atualizados.", "admin")
        page.add_field(name="Daily", value=money(daily_amount), inline=True)
        page.add_field(name="Weekly", value=money(weekly_amount), inline=True)
        page.add_field(name="Bônus", value=f"+{streak_bonus_percent}% por sequência · máximo +{streak_bonus_cap_percent}%", inline=False)
        await respond(interaction, embed=page)

    @admin_group.command(name="timezone", description="Configura o timezone do servidor.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def timezone(self, interaction: discord.Interaction, timezone_name: str) -> None:
        await defer(interaction, ephemeral=True)
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        timezone_name = timezone_name.strip()
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            await respond(interaction, "Timezone IANA inválido.", ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        async with session_factory() as session:
            settings = await session.get(GuildSettings, guild.id)
            if settings is None:
                now = utc_now()
                settings = GuildSettings(guild_id=guild.id, timezone=timezone_name, locale="pt-BR", created_at=now, updated_at=now)
                session.add(settings)
            else:
                settings.timezone = timezone_name
                settings.updated_at = utc_now()
            await session.commit()
        await self.audit(guild.id, interaction.user.id, "guild.timezone", "settings", None, {"timezone": timezone_name})
        page = embed("BN / TIMEZONE", f"O servidor agora usa `{timezone_name}`.", "admin")
        page.add_field(name="Timezone", value=f"`{timezone_name}`", inline=False)
        await respond(interaction, embed=page)


def add_to_tree(bot: commands.Bot, binding: commands.Cog | None = None) -> None:
    if binding is not None:
        for command in list(admin_group.commands):
            if getattr(command, "binding", None) is binding:
                continue
            bound = command._copy_with(parent=admin_group, binding=binding)
            admin_group.remove_command(command.name)
            admin_group.add_command(bound)
    if bot.tree.get_command(admin_group.name) is None:
        bot.tree.add_command(admin_group)
