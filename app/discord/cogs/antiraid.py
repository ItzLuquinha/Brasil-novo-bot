from __future__ import annotations
from datetime import timedelta
import logging
import secrets
from typing import Any
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func, or_
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.core.time import utc_now
from app.core.validation import parse_snowflake
from app.models import AuditLog, GuildSettings, RaidEvent, RaidProtection, RaidLockdownChannel
from app.services.antiraid import RESPONSE_ACTIONS, JoinContext, clamp_quarantine_timeout_seconds, clear_expired_state, evaluate_join, load_protection, merge_lockdown_guild_ids
from app.discord.theme import embed, number, bar, status_line

logger = logging.getLogger("bn_bot.antiraid")
raid_group = app_commands.Group(name="antiraid", description="Proteção contra raids e entradas suspeitas.", default_permissions=discord.Permissions(manage_guild=True))
RESPONSE_CHOICES = [
    app_commands.Choice(name="Alertar", value="alert"),
    app_commands.Choice(name="Lockdown", value="lockdown"),
    app_commands.Choice(name="Quarentena", value="quarantine"),
    app_commands.Choice(name="Bloquear", value="block"),
]


class AntiRaidCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def audit(self, guild_id: int, executor_id: int, action: str, resource: str, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> None:
        try:
            async with session_factory() as session:
                session.add(AuditLog(id=secrets.randbits(62), guild_id=guild_id, executor_id=executor_id, action=action, resource=resource, before_state=before, after_state=after, created_at=utc_now()))
                await session.commit()
        except Exception:
            logger.exception("audit persistence failed action=%s resource=%s", action, resource)

    async def apply_lockdown(self, guild: discord.Guild, seconds: int, configured_channels: list[int]) -> list[int]:
        async with session_factory() as session:
            existing = list((await session.execute(select(RaidLockdownChannel).where(RaidLockdownChannel.guild_id == guild.id))).scalars())
            existing_ids = {row.channel_id for row in existing}
            target_ids = set(configured_channels)
            channels = [guild.get_channel(channel_id) for channel_id in target_ids] if target_ids else [channel for channel in guild.channels if isinstance(channel, (discord.TextChannel, discord.ForumChannel))]
            changed: list[int] = []
            for channel in channels:
                if channel is None or channel.id in existing_ids or not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                    continue
                overwrite = channel.overwrites_for(guild.default_role)
                allow, deny = overwrite.pair()
                row = RaidLockdownChannel(
                    id=secrets.randbits(62),
                    guild_id=guild.id,
                    channel_id=channel.id,
                    had_overwrite=not overwrite.is_empty(),
                    allow_bits=allow.value,
                    deny_bits=deny.value,
                    locked_at=utc_now(),
                )
                session.add(row)
                await session.commit()
                try:
                    locked = discord.PermissionOverwrite.from_pair(allow, deny)
                    locked.send_messages = False
                    locked.create_public_threads = False
                    locked.create_private_threads = False
                    locked.send_messages_in_threads = False
                    await channel.set_permissions(guild.default_role, overwrite=locked, reason="BN Bot Anti-Raid lockdown")
                    changed.append(channel.id)
                    existing_ids.add(channel.id)
                except discord.Forbidden:
                    await session.delete(row)
                    await session.commit()
                    logger.warning("antiraid lockdown forbidden channel=%s guild=%s", getattr(channel, "id", None), guild.id)
                except discord.RateLimited as exc:
                    await session.delete(row)
                    await session.commit()
                    logger.warning(
                        "antiraid lockdown paused by Discord rate limit guild=%s channel=%s retry_after=%s",
                        guild.id,
                        getattr(channel, "id", None),
                        getattr(exc, "retry_after", "unknown"),
                    )
                    break
                except discord.HTTPException as exc:
                    if exc.status == 429:
                        await session.delete(row)
                        await session.commit()
                        logger.warning("antiraid lockdown paused by Discord HTTP 429 guild=%s channel=%s", guild.id, getattr(channel, "id", None))
                    else:
                        logger.exception("antiraid lockdown failed channel=%s guild=%s status=%s; restore record retained", getattr(channel, "id", None), guild.id, exc.status)
                    if exc.status == 429:
                        break
            return changed

    @staticmethod
    def _defer_restore(row: RaidLockdownChannel, error: Exception, retry_after: float | None = None) -> None:
        now = utc_now()
        row.restore_attempt_count = int(row.restore_attempt_count or 0) + 1
        if isinstance(error, discord.Forbidden):
            delay_seconds = 6 * 3600
        else:
            exponential_delay = min(30 * (2 ** min(row.restore_attempt_count - 1, 10)), 86400)
            delay_seconds = max(exponential_delay, int((retry_after or 0) + 0.999))
        row.next_restore_attempt_at = now + timedelta(seconds=delay_seconds)
        row.restore_last_error = f"{type(error).__name__}: {error}"[:500]

    async def remove_lockdown(self, guild: discord.Guild) -> list[int]:
        now = utc_now()
        async with session_factory() as session:
            rows = list((await session.execute(
                select(RaidLockdownChannel)
                .where(
                    RaidLockdownChannel.guild_id == guild.id,
                    or_(RaidLockdownChannel.next_restore_attempt_at.is_(None), RaidLockdownChannel.next_restore_attempt_at <= now),
                )
                .order_by(RaidLockdownChannel.locked_at.asc())
            )).scalars())
            restored: list[int] = []
            for index, row in enumerate(rows):
                channel = guild.get_channel(row.channel_id)
                if channel is None:
                    await session.delete(row)
                    continue
                try:
                    if row.had_overwrite:
                        allow = discord.Permissions(row.allow_bits)
                        deny = discord.Permissions(row.deny_bits)
                        await channel.set_permissions(guild.default_role, overwrite=discord.PermissionOverwrite.from_pair(allow, deny), reason="BN Bot Anti-Raid lockdown expired")
                    else:
                        await channel.set_permissions(guild.default_role, overwrite=None, reason="BN Bot Anti-Raid lockdown expired")
                    restored.append(channel.id)
                    await session.delete(row)
                except discord.NotFound:
                    await session.delete(row)
                except discord.Forbidden as exc:
                    self._defer_restore(row, exc)
                    logger.warning("antiraid restore deferred due to permissions channel=%s guild=%s", channel.id, guild.id)
                except discord.RateLimited as exc:
                    retry_after = max(float(getattr(exc, "retry_after", 1.0)), 1.0)
                    self._defer_restore(row, exc, retry_after)
                    for pending in rows[index + 1:]:
                        pending.next_restore_attempt_at = utc_now() + timedelta(seconds=int(retry_after + 0.999))
                        pending.restore_last_error = "Deferred after Discord rate limit"[:500]
                    logger.warning("antiraid restore stopped on Discord rate limit guild=%s retry_after=%s", guild.id, retry_after)
                    break
                except discord.HTTPException as exc:
                    if exc.status == 429:
                        try:
                            retry_after = max(float(getattr(getattr(exc, "response", None), "headers", {}).get("Retry-After", 60)), 1.0)
                        except (AttributeError, TypeError, ValueError):
                            retry_after = 60.0
                        self._defer_restore(row, exc, retry_after)
                        for pending in rows[index + 1:]:
                            pending.next_restore_attempt_at = utc_now() + timedelta(seconds=int(retry_after + 0.999))
                            pending.restore_last_error = "Deferred after Discord HTTP 429"[:500]
                        logger.warning("antiraid restore stopped on Discord HTTP 429 guild=%s retry_after=%s", guild.id, retry_after)
                        break
                    self._defer_restore(row, exc)
                    logger.exception("antiraid restore deferred channel=%s guild=%s", channel.id, guild.id)
            await session.commit()
            return restored

    async def lockdown_pending_count(self, guild_id: int) -> int:
        async with session_factory() as session:
            return int(await session.scalar(select(func.count(RaidLockdownChannel.id)).where(RaidLockdownChannel.guild_id == guild_id)) or 0)

    async def quarantine(self, member: discord.Member, role_id: int | None) -> bool:
        if role_id is None or member.guild.me is None:
            return False
        role = member.guild.get_role(role_id)
        if role is None or role in member.roles or role >= member.guild.me.top_role:
            return False
        try:
            await member.add_roles(role, reason="BN Bot Anti-Raid quarantine")
            return True
        except discord.HTTPException:
            logger.exception("antiraid quarantine role failed guild=%s user=%s", member.guild.id, member.id)
            return False

    async def announce(self, guild: discord.Guild, decision: Any, member: discord.Member) -> None:
        async with session_factory() as session:
            protection = await session.get(RaidProtection, guild.id)
            channel_id = protection.alert_channel_id if protection else None
            reasons = ", ".join(decision.reasons) if decision.reasons else "sinais combinados de risco"
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
            try:
                page = embed("BN / ANTI-RAID", f"Entrada suspeita envolvendo {member.mention}.", "security")
                page.add_field(name="Risco", value=f"`{decision.risk_score}/100` · {bar(decision.risk_score, 100)}", inline=False)
                page.add_field(name="Janela", value=f"`{decision.join_count}` entradas", inline=True)
                page.add_field(name="Contas recentes", value=f"`{decision.new_account_count}`", inline=True)
                page.add_field(name="Ação", value=f"`{decision.action}`", inline=True)
                page.add_field(name="Sinais", value=reasons[:1024], inline=False)
                await channel.send(embed=page)
            except discord.HTTPException:
                logger.exception("antiraid alert publication failed guild=%s", guild.id)

    async def on_member_join_event(self, member: discord.Member) -> None:
        now = utc_now()
        account_age = max(int((now - member.created_at).total_seconds()), 0)
        context = JoinContext(guild_id=member.guild.id, user_id=member.id, account_age_seconds=account_age, role_ids={role.id for role in member.roles}, is_bot=member.bot, is_owner=member.id == member.guild.owner_id)
        decision = await evaluate_join(context)
        if decision is None:
            return
        action = decision.action
        if action == "block":
            try:
                await member.kick(reason=f"BN Bot Anti-Raid: {', '.join(decision.reasons)}")
            except discord.HTTPException:
                logger.exception("antiraid block failed guild=%s user=%s", member.guild.id, member.id)
        elif action == "quarantine":
            async with session_factory() as session:
                protection = await session.get(RaidProtection, member.guild.id)
                role_id = protection.quarantine_role_id if protection else None
                quarantine_timeout = clamp_quarantine_timeout_seconds((protection.config or {}).get("quarantine_timeout_seconds", 900) if protection else 900)
            applied = await self.quarantine(member, role_id)
            try:
                await member.timeout(timedelta(seconds=quarantine_timeout), reason=f"BN Bot Anti-Raid: {', '.join(decision.reasons)}")
                applied = True
            except discord.HTTPException:
                logger.exception("antiraid quarantine timeout failed guild=%s user=%s", member.guild.id, member.id)
            if not applied:
                await self.announce(member.guild, decision, member)
        elif action == "lockdown":
            async with session_factory() as session:
                protection = await session.get(RaidProtection, member.guild.id)
                channels = list(protection.lockdown_channels or []) if protection else []
                seconds = protection.lockdown_seconds if protection else 300
            await self.apply_lockdown(member.guild, seconds, channels)
            await self.announce(member.guild, decision, member)
        else:
            await self.announce(member.guild, decision, member)

    @raid_group.command(name="setup", description="Cria a configuração inicial do Anti-Raid.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        guild = interaction.guild
        assert guild is not None
        role = discord.utils.get(guild.roles, name="BN Quarantine")
        if role is None:
            try:
                role = await guild.create_role(name="BN Quarantine", reason="BN Bot Anti-Raid")
            except discord.HTTPException:
                logger.exception("antiraid quarantine role creation failed guild=%s", guild.id)
                role = None
        async with session_factory() as session:
            protection = await load_protection(session, guild.id)
            protection.enabled = False
            protection.quarantine_role_id = role.id if role else None
            protection.updated_at = utc_now()
            settings = await session.get(GuildSettings, guild.id)
            if settings is None:
                now = utc_now()
                session.add(GuildSettings(guild_id=guild.id, timezone="UTC", locale="pt-BR", economy_enabled=True, levels_enabled=True, analytics_enabled=True, automod_enabled=False, config={}, created_at=now, updated_at=now))
            await session.commit()
        await self.audit(guild.id, interaction.user.id, "antiraid.setup", "settings", None, {"quarantine_role_id": role.id if role else None})
        page = embed("BN / ANTI-RAID", "A configuração inicial foi criada.", "security")
        page.add_field(name="Quarentena", value=role.mention if role else "não criada", inline=True)
        page.add_field(name="Estado", value="pronto para ativação", inline=True)
        await respond(interaction, embed=page)

    @raid_group.command(name="enable", description="Ativa a proteção Anti-Raid.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def enable(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            row = await load_protection(session, interaction.guild.id)
            row.enabled = True
            row.updated_at = utc_now()
            await session.commit()
        await self.audit(interaction.guild.id, interaction.user.id, "antiraid.enable", "settings", None, {"enabled": True})
        page = embed("BN / ANTI-RAID", "A proteção de entrada está ativa.", "security")
        page.add_field(name="Estado", value=status_line("Proteção", "ativa", "active"), inline=False)
        await respond(interaction, embed=page)

    @raid_group.command(name="disable", description="Desativa a proteção Anti-Raid.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            row = await load_protection(session, interaction.guild.id)
            row.enabled = False
            row.active_until = None
            row.updated_at = utc_now()
            await session.commit()
        restored = await self.remove_lockdown(interaction.guild)
        pending = await self.lockdown_pending_count(interaction.guild.id)
        await self.audit(interaction.guild.id, interaction.user.id, "antiraid.disable", "settings", None, {"enabled": False, "restored_channels": restored, "pending_channels": pending})
        page = embed("BN / ANTI-RAID", "A proteção foi desativada e o lockdown foi revisado.", "security")
        page.add_field(name="Canais restaurados", value=f"`{number(len(restored))}`", inline=True)
        page.add_field(name="Pendentes", value=f"`{number(pending)}`", inline=True)
        page.add_field(name="Estado", value=status_line("Proteção", "desativada", "closed"), inline=True)
        await respond(interaction, embed=page)

    @raid_group.command(name="configure", description="Configura limites, ação e canais do Anti-Raid.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(action=RESPONSE_CHOICES)
    @app_commands.describe(join_threshold="Entradas para disparar a proteção", join_window_seconds="Janela de detecção", risk_threshold="Score mínimo de risco", action="Resposta automática", lockdown_seconds="Duração do lockdown", alert_channel="Canal para alertas", quarantine_role="Cargo de quarentena", lockdown_channels="IDs de canais separados por vírgula")
    async def configure(self, interaction: discord.Interaction, join_threshold: int | None = None, join_window_seconds: int | None = None, risk_threshold: int | None = None, action: str | None = None, lockdown_seconds: int | None = None, alert_channel: discord.TextChannel | None = None, quarantine_role: discord.Role | None = None, lockdown_channels: str | None = None) -> None:
        await defer(interaction, ephemeral=True)
        guild = interaction.guild
        assert guild is not None
        try:
            channel_ids = None if lockdown_channels is None else sorted({parse_snowflake(value.strip()) for value in lockdown_channels.replace(";", ",").split(",") if value.strip()})
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        if channel_ids is not None and len(channel_ids) > 50:
            await respond(interaction, "Configure no máximo 50 canais de lockdown.", ephemeral=True)
            return
        if channel_ids is not None:
            invalid = [str(channel_id) for channel_id in channel_ids if not isinstance(guild.get_channel(channel_id), (discord.TextChannel, discord.ForumChannel))]
            if invalid:
                await respond(interaction, f"Canais inválidos neste servidor: {', '.join(invalid[:8])}.", ephemeral=True)
                return
        if join_threshold is not None and not 2 <= join_threshold <= 1000:
            await respond(interaction, "join_threshold deve estar entre 2 e 1000.", ephemeral=True)
            return
        if join_window_seconds is not None and not 2 <= join_window_seconds <= 120:
            await respond(interaction, "join_window_seconds deve estar entre 2 e 120.", ephemeral=True)
            return
        if risk_threshold is not None and not 1 <= risk_threshold <= 100:
            await respond(interaction, "risk_threshold deve estar entre 1 e 100.", ephemeral=True)
            return
        if action is not None and action not in RESPONSE_ACTIONS:
            await respond(interaction, "Ação Anti-Raid inválida.", ephemeral=True)
            return
        if lockdown_seconds is not None and not 30 <= lockdown_seconds <= 86_400:
            await respond(interaction, "lockdown_seconds deve estar entre 30 e 86400.", ephemeral=True)
            return
        if quarantine_role is not None:
            if guild.me is None or quarantine_role >= guild.me.top_role:
                await respond(interaction, "O cargo de quarentena precisa ficar abaixo do maior cargo do BN Bot.", ephemeral=True)
                return
        async with session_factory() as session:
            row = await load_protection(session, guild.id)
            if join_threshold is not None:
                row.join_threshold = join_threshold
            if join_window_seconds is not None:
                row.join_window_seconds = join_window_seconds
            if risk_threshold is not None:
                row.risk_threshold = risk_threshold
            if action is not None:
                row.response_action = action
            if lockdown_seconds is not None:
                row.lockdown_seconds = lockdown_seconds
            if alert_channel is not None:
                row.alert_channel_id = alert_channel.id
            if quarantine_role is not None:
                row.quarantine_role_id = quarantine_role.id
            if channel_ids is not None:
                row.lockdown_channels = channel_ids
            row.updated_at = utc_now()
            await session.commit()
            snapshot = {"join_threshold": row.join_threshold, "join_window_seconds": row.join_window_seconds, "risk_threshold": row.risk_threshold, "response_action": row.response_action, "lockdown_seconds": row.lockdown_seconds, "alert_channel_id": row.alert_channel_id, "quarantine_role_id": row.quarantine_role_id, "lockdown_channels": row.lockdown_channels}
        await self.audit(guild.id, interaction.user.id, "antiraid.configure", "settings", None, snapshot)
        page = embed("BN / ANTI-RAID CONFIGURADO", "Parâmetros de proteção atualizados.", "security")
        page.add_field(name="Disparo", value=f"`{snapshot['join_threshold']}` entradas / `{snapshot['join_window_seconds']}s`", inline=True)
        page.add_field(name="Risco", value=f"`{snapshot['risk_threshold']}/100`", inline=True)
        page.add_field(name="Ação", value=f"`{snapshot['response_action']}`", inline=True)
        page.add_field(name="Lockdown", value=f"`{snapshot['lockdown_seconds']}s`", inline=True)
        page.add_field(name="Canais", value=f"`{len(snapshot['lockdown_channels'] or [])}` configurados", inline=True)
        await respond(interaction, embed=page)

    @raid_group.command(name="status", description="Mostra o estado atual da proteção Anti-Raid.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            row = await load_protection(session, interaction.guild.id)
            events = await session.scalar(select(func.count(RaidEvent.id)).where(RaidEvent.guild_id == interaction.guild.id))
            active_until = row.active_until
            await session.commit()
        active = bool(active_until and active_until > utc_now())
        page = embed("BN / ANTI-RAID", "Estado atual da proteção contra entradas suspeitas.", "security")
        page.add_field(name="Proteção", value=status_line("Estado", "ativa" if row.enabled else "desativada", "active" if row.enabled else "closed"), inline=True)
        page.add_field(name="Ação", value=f"`{row.response_action}`", inline=True)
        page.add_field(name="Risco mínimo", value=f"`{row.risk_threshold}/100`", inline=True)
        page.add_field(name="Janela", value=f"`{row.join_threshold}` em `{row.join_window_seconds}s`", inline=True)
        page.add_field(name="Lockdown", value=discord.utils.format_dt(active_until, "R") if active else "inativo", inline=True)
        page.add_field(name="Eventos", value=f"`{number(int(events or 0))}`", inline=True)
        await respond(interaction, embed=page, ephemeral=True)

    @raid_group.command(name="unlock", description="Encerra manualmente o lockdown Anti-Raid.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def unlock(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        guild = interaction.guild
        assert guild is not None
        restored = await self.remove_lockdown(guild)
        pending = await self.lockdown_pending_count(guild.id)
        async with session_factory() as session:
            row = await load_protection(session, guild.id)
            row.active_until = None
            row.updated_at = utc_now()
            await session.commit()
        await self.audit(guild.id, interaction.user.id, "antiraid.unlock", "lockdown", None, {"restored_channels": restored, "pending_channels": pending})
        page = embed("BN / LOCKDOWN ENCERRADO", "O estado manual do lockdown foi revisado.", "security")
        page.add_field(name="Restaurados", value=f"`{number(len(restored))}`", inline=True)
        page.add_field(name="Pendentes", value=f"`{number(pending)}`", inline=True)
        await respond(interaction, embed=page)

    async def expire_lockdowns(self) -> None:
        now = utc_now()
        async with session_factory() as session:
            guild_ids = await clear_expired_state(session, now)
            pending_ids = list((await session.execute(
                select(RaidLockdownChannel.guild_id)
                .outerjoin(RaidProtection, RaidProtection.guild_id == RaidLockdownChannel.guild_id)
                .where(
                    or_(
                        RaidProtection.guild_id.is_(None),
                        RaidProtection.active_until.is_(None),
                        RaidProtection.active_until <= now,
                    ),
                    or_(
                        RaidLockdownChannel.next_restore_attempt_at.is_(None),
                        RaidLockdownChannel.next_restore_attempt_at <= now,
                    ),
                )
                .distinct()
            )).scalars())
        for guild_id in merge_lockdown_guild_ids(guild_ids, pending_ids):
            guild = self.bot.get_guild(guild_id)
            if guild is not None:
                try:
                    await self.remove_lockdown(guild)
                except Exception:
                    logger.exception("antiraid lockdown expiration failed guild=%s", guild_id)


def add_to_tree(bot: commands.Bot, binding: commands.Cog | None = None) -> None:
    if binding is not None:
        for command in list(raid_group.commands):
            if getattr(command, "binding", None) is binding:
                continue
            bound = command._copy_with(parent=raid_group, binding=binding)
            raid_group.remove_command(command.name)
            raid_group.add_command(bound)
    if bot.tree.get_command(raid_group.name) is None:
        bot.tree.add_command(raid_group)
