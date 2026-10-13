from __future__ import annotations
from datetime import datetime, timedelta
import io
import logging
import secrets
import discord
from discord import app_commands
from discord.ext import commands
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.services.moderation import add_warning, list_warnings, deactivate_warning, record_punishment, count_active_warnings
from app.models import GuildSettings, ModerationLog
from app.core.time import utc_now
from app.core.validation import parse_snowflake
from app.discord.theme import embed, number, status_line
from app.services.purge_audit import build_purge_archive_parts
from app.services.rate_limits import command_rate_limit


logger = logging.getLogger("bn_bot.discord.moderation")


class ModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def persist_punishment(self, guild_id: int, user_id: int, moderator_id: int, kind: str, reason: str | None, expires_at=None, data: dict | None = None) -> bool:
        try:
            async with session_factory() as session:
                await record_punishment(session, guild_id, user_id, moderator_id, kind, reason, expires_at, data)
            return True
        except Exception:
            logger.exception("punishment persistence failed guild=%s user=%s kind=%s", guild_id, user_id, kind)
            return False

    @staticmethod
    def target_error(interaction: discord.Interaction, user: discord.Member) -> str | None:
        guild = interaction.guild
        actor = interaction.user if isinstance(interaction.user, discord.Member) else None
        if guild is None or actor is None:
            return "Contexto de servidor inválido."
        if user.id == actor.id:
            return "Você não pode aplicar esta ação em si mesmo."
        if user.id == guild.owner_id:
            return "O dono do servidor não pode ser alvo desta ação."
        if actor.id != guild.owner_id and user.top_role >= actor.top_role:
            return "Você não pode moderar alguém com cargo igual ou superior ao seu."
        me = guild.me
        if me is None or user.top_role >= me.top_role:
            return "O maior cargo do BN Bot precisa estar acima do cargo do alvo."
        return None

    async def send_action(self, interaction: discord.Interaction, title: str, description: str, target: discord.Member, kind: str, expires_at=None, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        page = embed(title, description, "moderation")
        page.set_thumbnail(url=target.display_avatar.url)
        page.add_field(name="Usuário", value=target.mention, inline=True)
        page.add_field(name="ID", value=f"`{target.id}`", inline=True)
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        if expires_at is not None:
            page.add_field(name="Expira", value=discord.utils.format_dt(expires_at, "R"), inline=True)
        await respond(interaction, embed=page)

    async def _create_warning(self, interaction: discord.Interaction, user: discord.Member, reason: str, expires_at=None, timed=False) -> None:
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        reason = " ".join(reason.split())
        if not reason:
            await respond(interaction, "Informe um motivo para o warn.", ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            warning_id = await add_warning(session, guild.id, user.id, interaction.user.id, reason[:500], expires_at=expires_at)
            total = await count_active_warnings(session, guild.id, user.id)
        title = "BN / T-WARN" if timed else "BN / WARN"
        description = f"{user.mention} recebeu um T-Warn com expiração automática." if timed else f"{user.mention} recebeu um warn permanente."
        page = embed(title, description, "moderation")
        page.set_thumbnail(url=user.display_avatar.url)
        page.add_field(name="ID", value=f"`{warning_id}`", inline=True)
        page.add_field(name="Warns ativos", value=f"`{number(total)}`", inline=True)
        if expires_at is not None:
            page.add_field(name="Expira", value=discord.utils.format_dt(expires_at, "R"), inline=True)
        page.add_field(name="Motivo", value=reason[:1024], inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="warn", description="Aplica um warn permanente.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(user="Usuário que receberá o warn", reason="Motivo do warn")
    async def warn(self, interaction: discord.Interaction, user: discord.Member, reason: str) -> None:
        await self._create_warning(interaction, user, reason)

    @staticmethod
    def parse_twarn_duration(value: str) -> int:
        import re
        match = re.fullmatch(r"([0-9]{1,9})([smhdSMHD])", value.strip())
        if match is None:
            raise ValueError("A duração deve seguir o formato `30s`, `15m`, `2h` ou `7d`.")
        amount = int(match.group(1))
        unit = match.group(2).lower()
        multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        seconds = amount * multiplier
        if seconds < 1 or seconds > 365 * 86400:
            raise ValueError("A duração do T-Warn deve ficar entre 1 segundo e 365 dias.")
        return seconds

    @app_commands.command(name="t-warn", description="Aplica um warn temporário com duração no formato 30s, 15m, 2h ou 7d.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(user="Usuário que receberá o T-Warn", reason="Motivo do T-Warn", duration="Duração: S segundos, M minutos, H horas ou D dias")
    async def t_warn(self, interaction: discord.Interaction, user: discord.Member, reason: str, duration: str) -> None:
        try:
            seconds = self.parse_twarn_duration(duration)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        expires_at = utc_now() + timedelta(seconds=seconds)
        await self._create_warning(interaction, user, reason, expires_at=expires_at, timed=True)

    @app_commands.command(name="warns", description="Lista warns de um usuário.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warns(self, interaction: discord.Interaction, user: discord.Member) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            rows = await list_warnings(session, guild.id, user.id)
        page = embed("BN / WARNS", f"Histórico de **{user.display_name}**.", "moderation")
        if not rows:
            page.add_field(name="Histórico vazio", value="Este usuário não possui warns registrados.", inline=False)
        else:
            lines = []
            for row in rows[:15]:
                state = "ativo" if row.active else "inativo"
                lines.append(f"`{row.id}` · **{state}** · {row.reason[:90]}")
            page.add_field(name=f"Registros · {len(rows)}", value="\n".join(lines)[:1024], inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="unwarn", description="Desativa um warn pelo ID.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def unwarn(self, interaction: discord.Interaction, warning_id: str) -> None:
        await defer(interaction, ephemeral=True)
        try:
            target_id = parse_snowflake(warning_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        async with session_factory() as session:
            changed = await deactivate_warning(session, guild.id, target_id, interaction.user.id)
        if not changed:
            await respond(interaction, f"O warn `{target_id}` já está desativado.", ephemeral=True)
            return
        page = embed("BN / WARN DESATIVADO", f"Warn `{target_id}` foi desativado.", "moderation")
        await respond(interaction, embed=page)

    @app_commands.command(name="clearwarns", description="Desativa todos os warns de um usuário.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clearwarns(self, interaction: discord.Interaction, user: discord.Member) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            rows = await list_warnings(session, guild.id, user.id)
            active = [row for row in rows if row.active]
            for row in active:
                row.active = False
            if active:
                session.add(ModerationLog(id=secrets.randbits(62), guild_id=guild.id, actor_id=interaction.user.id, target_id=user.id, kind="clearwarns", reason=f"{len(active)} warns desativados", data={"warning_ids": [row.id for row in active]}, created_at=utc_now()))
            await session.commit()
        page = embed("BN / WARNS LIMPOS", f"Histórico ativo de {user.mention} foi limpo.", "moderation")
        page.add_field(name="Desativados", value=f"`{len(active)}`", inline=False)
        await respond(interaction, embed=page)

    @staticmethod
    def parse_timeout_duration(value: str) -> int:
        raw = value.strip()
        if raw.isdigit():
            raw = f"{raw}m"
        seconds = ModerationCog.parse_twarn_duration(raw)
        if seconds > 28 * 86400:
            raise ValueError("A duração do timeout deve ficar entre 1 segundo e 28 dias.")
        return seconds

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="timeout", description="Coloca um usuário em timeout por até 28 dias.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="Usuário que receberá o timeout", duration="Duração: 30s, 15m, 2h ou 7d", reason="Motivo do timeout")
    async def timeout(self, interaction: discord.Interaction, user: discord.Member, duration: str, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        try:
            seconds = self.parse_timeout_duration(duration)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        clean_reason = " ".join(reason.split())[:500] if reason else None
        now = discord.utils.utcnow()
        expires_at = min(now + timedelta(seconds=seconds), now + timedelta(days=28) - timedelta(seconds=2))
        current = await self._edit_timeout(guild, user, expires_at, clean_reason)
        persisted = await self.persist_punishment(guild.id, current.id, interaction.user.id, "timeout", clean_reason, expires_at)
        page = embed("BN / TIMEOUT", f"{current.mention} recebeu um timeout.", "moderation")
        page.set_thumbnail(url=current.display_avatar.url)
        page.add_field(name="Usuário", value=current.mention, inline=True)
        page.add_field(name="Duração", value=f"`{duration.strip()}`", inline=True)
        page.add_field(name="Expira", value=discord.utils.format_dt(expires_at, "R"), inline=True)
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        page.add_field(name="Motivo", value=clean_reason[:1024] if clean_reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    async def _edit_timeout(self, guild: discord.Guild, user: discord.Member, until: datetime | None, reason: str | None) -> discord.Member:
        await user.timeout(until, reason=reason)
        if until is None:
            user.timed_out_until = None
        else:
            user.timed_out_until = until
        return user

    async def _remove_timeout(self, interaction: discord.Interaction, user: discord.Member, kind: str, title: str, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        clean_reason = " ".join(reason.split())[:500] if reason else None
        current = await self._edit_timeout(guild, user, None, clean_reason)
        persisted = await self.persist_punishment(guild.id, current.id, interaction.user.id, kind, clean_reason)
        page = embed(title, f"O timeout de {current.mention} foi removido.", "moderation")
        page.set_thumbnail(url=current.display_avatar.url)
        page.add_field(name="Usuário", value=current.mention, inline=True)
        page.add_field(name="Estado", value="sem timeout", inline=True)
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        await respond(interaction, embed=page)

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="untimeout", description="Remove o timeout de um usuário.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="Usuário que terá o timeout removido", reason="Motivo da remoção do timeout")
    async def untimeout(self, interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        await self._remove_timeout(interaction, user, "untimeout", "BN / UNTIMEOUT", reason)

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="unmute", description="Remove o timeout de um usuário usando o comando unmute.")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.describe(user="Usuário que terá o timeout removido", reason="Motivo da remoção do timeout")
    async def unmute(self, interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        await self._remove_timeout(interaction, user, "unmute", "BN / UNMUTE", reason)

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="kick", description="Expulsa um usuário.")
    @app_commands.default_permissions(kick_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        target_error = self.target_error(interaction, user)
        if target_error:
            await respond(interaction, target_error, ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        await user.kick(reason=reason[:500] if reason else None)
        persisted = await self.persist_punishment(guild.id, user.id, interaction.user.id, "kick", reason[:500] if reason else None)
        page = embed("BN / KICK", f"**{user.display_name}** foi expulso do servidor.", "moderation")
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="ban", description="Bane um usuário do servidor.")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, user: discord.User, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        member = guild.get_member(user.id)
        if member is None:
            try:
                member = await guild.fetch_member(user.id)
            except discord.NotFound:
                member = None
            except discord.RateLimited as exc:
                wait = max(1, int(float(exc.retry_after) + 0.999))
                await respond(interaction, f"O Discord está limitando esta ação. Aguarde {wait}s e tente novamente.", ephemeral=True)
                return
            except discord.HTTPException:
                logger.exception("ban aborted because target hierarchy could not be verified guild=%s target=%s", guild.id, user.id)
                await respond(interaction, "Não foi possível verificar os cargos do alvo. Nenhum ban foi aplicado; tente novamente.", ephemeral=True)
                return
        if member is not None:
            target_error = self.target_error(interaction, member)
            if target_error:
                await respond(interaction, target_error, ephemeral=True)
                return
        if user.id == interaction.user.id or user.id == guild.owner_id:
            await respond(interaction, "Este usuário não pode ser alvo de ban.", ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        await guild.ban(user, reason=reason[:500] if reason else None)
        persisted = await self.persist_punishment(guild.id, user.id, interaction.user.id, "ban", reason[:500] if reason else None)
        page = embed("BN / BAN", f"**BANIMENTO EXECUTADO**\n{user.mention} não pode mais entrar neste servidor.", "moderation")
        page.set_thumbnail(url=user.display_avatar.url)
        page.add_field(name="Alvo", value=f"{user.mention}\n`{user.id}`", inline=True)
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        page.add_field(name="Decisão", value="`BAN`", inline=True)
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    @command_rate_limit("moderation-action", 3)
    @app_commands.command(name="unban", description="Remove o ban de um usuário pelo ID.")
    @app_commands.default_permissions(ban_members=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str) -> None:
        await defer(interaction, ephemeral=True)
        try:
            target_id = parse_snowflake(user_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        guild = interaction.guild
        assert guild is not None
        try:
            await guild.fetch_ban(discord.Object(id=target_id))
        except discord.NotFound:
            await respond(interaction, f"O usuário `{target_id}` não está banido.", ephemeral=True)
            return
        except discord.RateLimited as exc:
            wait = max(1, int(float(exc.retry_after) + 0.999))
            await respond(interaction, f"O Discord está limitando esta ação. Aguarde {wait}s e tente novamente.", ephemeral=True)
            return
        except discord.HTTPException:
            logger.exception("unban aborted because ban status could not be verified guild=%s target=%s", guild.id, target_id)
            await respond(interaction, "Não foi possível confirmar o estado do ban. Nenhuma alteração foi feita; tente novamente.", ephemeral=True)
            return
        await guild.unban(discord.Object(id=target_id))
        persisted = await self.persist_punishment(guild.id, target_id, interaction.user.id, "unban", None)
        page = embed("BN / UNBAN", f"Ban removido de `{target_id}`.", "moderation")
        page.add_field(name="Registro", value=status_line("Auditoria", "salva" if persisted else "indisponível", "ok" if persisted else "warning"), inline=True)
        await respond(interaction, embed=page)

    async def _delete_purge_candidates(
        self,
        channel: discord.TextChannel | discord.Thread,
        amount: int,
        user: discord.Member | None,
        reason: str,
        deleted: list[discord.Message],
    ) -> None:
        candidates: list[discord.Message] = []
        async for message in channel.history(limit=amount, oldest_first=False):
            if user is None or message.author.id == user.id:
                candidates.append(message)

        cutoff = utc_now() - timedelta(days=14)
        bulk_candidates: list[discord.Message] = []
        old_candidates: list[discord.Message] = []
        for message in candidates:
            created_at = message.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=cutoff.tzinfo)
            if created_at >= cutoff:
                bulk_candidates.append(message)
            else:
                old_candidates.append(message)

        delete_many = getattr(channel, "delete_messages", None)
        for start in range(0, len(bulk_candidates), 100):
            batch = bulk_candidates[start:start + 100]
            if len(batch) > 1 and delete_many is not None:
                await delete_many(batch, reason=reason)
                deleted.extend(batch)
            else:
                for message in batch:
                    await message.delete()
                    deleted.append(message)
        for message in old_candidates:
            await message.delete()
            deleted.append(message)

    async def _record_purge_action(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | discord.Thread,
        amount_requested: int,
        user: discord.Member | None,
        deleted: list[discord.Message],
        executed_at: datetime,
        partial: bool,
    ) -> bool:
        guild = interaction.guild
        assert guild is not None
        audit_saved = True
        try:
            async with session_factory() as session:
                session.add(ModerationLog(
                    id=secrets.randbits(62),
                    guild_id=guild.id,
                    actor_id=interaction.user.id,
                    target_id=user.id if user else None,
                    kind="purge",
                    reason=f"{len(deleted)} mensagens removidas" + (" (parcial)" if partial else ""),
                    data={
                        "channel_id": channel.id,
                        "amount_requested": amount_requested,
                        "amount_deleted": len(deleted),
                        "filter_user_id": user.id if user else None,
                        "deleted_message_ids": [message.id for message in deleted],
                        "partial": partial,
                        "executed_at": executed_at.isoformat(),
                    },
                    created_at=executed_at,
                ))
                await session.commit()
        except Exception:
            audit_saved = False
            logger.exception(
                "purge audit persistence failed guild=%s channel=%s deleted=%s",
                guild.id,
                channel.id,
                len(deleted),
            )

        return audit_saved

    async def _send_purge_log(
        self,
        interaction: discord.Interaction,
        source_channel: discord.TextChannel | discord.Thread,
        amount_requested: int,
        user: discord.Member | None,
        deleted: list[discord.Message],
        executed_at: datetime,
        partial: bool,
    ) -> str:
        guild = interaction.guild
        assert guild is not None
        try:
            async with session_factory() as session:
                settings = await session.get(GuildSettings, guild.id)
                raw_channel_id = (settings.config or {}).get("purge_log_channel_id") if settings else None
        except Exception:
            logger.exception("purge log configuration lookup failed guild=%s", guild.id)
            return "erro"

        try:
            log_channel_id = int(raw_channel_id) if raw_channel_id is not None else 0
        except (TypeError, ValueError):
            log_channel_id = 0
        if log_channel_id <= 0:
            logger.debug("purge log channel is not configured guild=%s", guild.id)
            return "desativado"

        log_channel = guild.get_channel(log_channel_id)
        if log_channel is None:
            try:
                fetched = await self.bot.fetch_channel(log_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                logger.warning("purge log channel is missing or inaccessible guild=%s channel=%s", guild.id, log_channel_id)
                return "indisponível"
            log_channel = fetched
        if not isinstance(log_channel, discord.TextChannel):
            logger.warning("purge log destination is not a text channel guild=%s channel=%s", guild.id, log_channel_id)
            return "indisponível"
        if log_channel.guild.id != guild.id:
            logger.warning(
                "purge log destination belongs to another guild guild=%s channel=%s destination_guild=%s",
                guild.id,
                log_channel_id,
                log_channel.guild.id,
            )
            return "indisponível"

        bot_member = guild.me
        if bot_member is None:
            logger.warning("purge log permissions could not be checked guild=%s channel=%s", guild.id, log_channel_id)
            return "indisponível"
        permissions = log_channel.permissions_for(bot_member)
        if not permissions.view_channel or not permissions.send_messages:
            logger.warning("purge log destination lacks view/send permission guild=%s channel=%s", guild.id, log_channel_id)
            return "sem_permissão"

        state_text = "PARCIAL" if partial else "CONCLUÍDA"
        summary = (
            "**Registro de /purge**\n"
            f"Servidor: {guild.name} (`{guild.id}`)\n"
            f"Canal original: {source_channel.mention} (`{source_channel.id}`)\n"
            f"Responsável pela exclusão: {interaction.user.mention} (`{interaction.user.id}`)\n"
            f"Mensagens efetivamente removidas: **{len(deleted)}** de {amount_requested} solicitadas\n"
            f"Filtro de autor: {user.mention if user else 'nenhum'}\n"
            f"Data/hora (UTC): {executed_at.isoformat()}\n"
            f"Estado: **{state_text}**"
        )
        files: list[discord.File] = []
        if deleted and permissions.attach_files:
            try:
                parts = build_purge_archive_parts(
                    deleted,
                    guild_name=guild.name,
                    guild_id=guild.id,
                    channel_name=source_channel.name,
                    channel_id=source_channel.id,
                    moderator_name=str(interaction.user),
                    moderator_id=interaction.user.id,
                    executed_at=executed_at,
                    partial=partial,
                )
                total = len(parts)
                for index, content in enumerate(parts, start=1):
                    filename = f"purge-{guild.id}-{source_channel.id}-{int(executed_at.timestamp())}-part-{index}-of-{total}.txt"
                    files.append(discord.File(io.BytesIO(content), filename=filename))
            except Exception:
                logger.exception("purge archive generation failed guild=%s channel=%s", guild.id, source_channel.id)
        elif deleted:
            summary += "\nO canal de logs precisa da permissão `Attach Files` para receber o arquivo com o conteúdo das mensagens."
            logger.warning("purge log destination lacks attach_files guild=%s channel=%s", guild.id, log_channel_id)

        try:
            if not files:
                await log_channel.send(summary, allowed_mentions=discord.AllowedMentions.none())
            else:
                for start in range(0, len(files), 2):
                    batch = files[start:start + 2]
                    content = summary if start == 0 else f"Continuação do arquivo de auditoria /purge ({start + 1}-{start + len(batch)} de {len(files)} partes)."
                    await log_channel.send(content, files=batch, allowed_mentions=discord.AllowedMentions.none())
            return "enviado"
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.exception("purge log delivery failed guild=%s channel=%s deleted=%s", guild.id, log_channel_id, len(deleted))
            return "falha_no_envio"

    @command_rate_limit("moderation-purge", 10)
    @app_commands.command(name="purge", description="Remove mensagens recentes do canal.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.describe(amount="Quantidade máxima de mensagens a analisar/remover (1 a 1000)", user="Remover somente mensagens deste usuário")
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 1000], user: discord.Member | None = None) -> None:
        channel = interaction.channel
        guild = interaction.guild
        assert guild is not None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await respond(interaction, "Este comando só pode ser usado em canais de texto.", ephemeral=True)
            return
        me = guild.me
        if me is None:
            await respond(interaction, "Não consegui confirmar as permissões do BN Bot neste canal.", ephemeral=True)
            return
        bot_permissions = channel.permissions_for(me)
        if not bot_permissions.view_channel or not bot_permissions.read_message_history:
            await respond(interaction, "O BN Bot precisa das permissões View Channel e Read Message History neste canal.", ephemeral=True)
            return
        if not bot_permissions.manage_messages:
            await respond(interaction, "O BN Bot precisa da permissão Manage Messages neste canal.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted: list[discord.Message] = []
        executed_at = utc_now()
        reason = f"BN Bot purge por {interaction.user}"
        partial = False
        failure_message: str | None = None
        try:
            await self._delete_purge_candidates(channel, int(amount), user, reason, deleted)
        except discord.RateLimited as exc:
            partial = True
            wait = max(1, int(float(exc.retry_after) + 0.999))
            logger.warning("purge rate limited guild=%s channel=%s amount=%s deleted=%s", guild.id, channel.id, amount, len(deleted))
            failure_message = f"O Discord limitou a limpeza. Aguarde {wait}s antes de tentar novamente."
        except discord.Forbidden:
            partial = True
            logger.exception("purge forbidden guild=%s channel=%s amount=%s deleted=%s", guild.id, channel.id, amount, len(deleted))
            failure_message = "O Discord recusou a limpeza. Confira as permissões do bot."
        except discord.NotFound:
            partial = True
            logger.exception("purge resource missing guild=%s channel=%s amount=%s deleted=%s", guild.id, channel.id, amount, len(deleted))
            failure_message = "Um dos recursos desapareceu durante a limpeza."
        except discord.HTTPException:
            partial = True
            logger.exception("purge failed guild=%s channel=%s amount=%s deleted=%s", guild.id, channel.id, amount, len(deleted))
            failure_message = "O Discord não conseguiu concluir toda a limpeza."

        audit_saved = True
        log_delivery = "desativado"
        if failure_message is None or deleted:
            audit_saved = await self._record_purge_action(
                interaction, channel, int(amount), user, deleted, executed_at, partial
            )
            log_delivery = await self._send_purge_log(
                interaction, channel, int(amount), user, deleted, executed_at, partial
            )
        if failure_message is not None:
            detail = f" {len(deleted)} mensagem(ns) foram removidas antes da falha; o registro inclui apenas exclusões confirmadas." if deleted else " Nenhuma exclusão foi confirmada pelo bot."
            await interaction.edit_original_response(content=f"{failure_message}{detail}", embed=None, view=None)
            return
        page = embed("BN / PURGE", f"Limpeza concluída em {channel.mention}.", "moderation")
        page.add_field(name="Removidas", value=f"`{len(deleted)}`", inline=True)
        page.add_field(name="Solicitadas", value=f"`{int(amount)}`", inline=True)
        page.add_field(name="Filtro", value=user.mention if user else "Todas as mensagens", inline=True)
        page.add_field(name="Auditoria", value=status_line("Banco", "salvo" if audit_saved else "não salvo", "ok" if audit_saved else "warning"), inline=True)
        log_label = "enviado" if log_delivery == "enviado" else "não configurado" if log_delivery == "desativado" else "indisponível"
        page.add_field(name="Canal de logs", value=log_label, inline=True)
        await interaction.edit_original_response(content=None, embed=page, view=None)
