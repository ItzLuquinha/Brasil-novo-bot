from __future__ import annotations
import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
import io
import logging
import secrets
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func
from app.core.db import session_factory
from app.core.time import utc_now
from app.core.interactions import defer, respond
from app.models import Experience, GuildSettings, Member, Report, Suggestion, Ticket, Giveaway, GiveawayEntry, Poll
from app.services.community import add_poll_vote, assign_ticket, cast_suggestion_vote, create_ticket, end_giveaway, end_poll, enter_giveaway, open_items, save_ticket_transcript, set_ticket_status, update_report, update_suggestion, validate_poll_options
from app.services.cooldowns import check_and_set
from app.core.validation import parse_snowflake
from app.discord.theme import embed, number, duration, user_line, bar, ledger, percent, status_line

from app.services.rate_limits import command_rate_limit
logger = logging.getLogger("bn_bot.discord.community")

TICKET_PRIORITY_CHOICES = [
    app_commands.Choice(name="Baixa", value="low"),
    app_commands.Choice(name="Normal", value="normal"),
    app_commands.Choice(name="Alta", value="high"),
    app_commands.Choice(name="Urgente", value="urgent"),
]
SUGGESTION_STATUS_CHOICES = [
    app_commands.Choice(name="Pendente", value="pending"),
    app_commands.Choice(name="Em análise", value="analysis"),
    app_commands.Choice(name="Aprovada", value="approved"),
    app_commands.Choice(name="Rejeitada", value="rejected"),
    app_commands.Choice(name="Implementada", value="implemented"),
]
REPORT_STATUS_CHOICES = [
    app_commands.Choice(name="Aberta", value="open"),
    app_commands.Choice(name="Em investigação", value="investigating"),
    app_commands.Choice(name="Resolvida", value="resolved"),
    app_commands.Choice(name="Rejeitada", value="rejected"),
]
STATUS_LABELS = {
    "open": "aberta",
    "analysis": "em análise",
    "approved": "aprovada",
    "rejected": "rejeitada",
    "implemented": "implementada",
    "investigating": "em investigação",
    "resolved": "resolvida",
    "closed": "fechada",
    "cancelled": "cancelada",
}


def safe_int_list(value: object, limit: int = 50) -> list[int]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[int] = []
    for item in value:
        try:
            parsed = parse_snowflake(str(item))
        except ValueError:
            continue
        if parsed not in result:
            result.append(parsed)
        if len(result) >= limit:
            break
    return result


def setting_config(settings: GuildSettings | None, section: str) -> dict:
    if settings is None:
        return {}
    config = settings.config or {}
    value = config.get(section, {})
    return value if isinstance(value, dict) else {}


async def is_staff(guild: discord.Guild, member: discord.Member) -> bool:
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild or member.guild_permissions.manage_channels:
        return True
    async with session_factory() as session:
        settings = await session.get(GuildSettings, guild.id)
    config = setting_config(settings, "tickets")
    raw_roles = config.get("staff_role_ids", [])
    try:
        role_ids = parse_ids(raw_roles, 20)
    except (TypeError, ValueError):
        role_ids = []
    return any(role.id in role_ids for role in member.roles)


def parse_ids(value: str | list[int] | tuple[int, ...] | None, limit: int = 10) -> list[int]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_values = [str(item).strip() for item in value]
    else:
        raw_values = [item.strip() for item in value.replace(";", ",").split(",")]
    values: list[int] = []
    for item in raw_values:
        if not item:
            continue
        values.append(parse_snowflake(item))
    if len(values) > limit:
        raise ValueError(f"no máximo {limit} IDs podem ser informados")
    return list(dict.fromkeys(values))


def chunk_text(text: str, size: int = 1800) -> list[str]:
    return [text[index:index + size] for index in range(0, len(text), size)] or [""]


def add_line_fields(page: discord.Embed, title: str, lines: list[str], limit: int = 1024) -> None:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        clean = str(line)
        extra = len(clean) + (1 if current else 0)
        if current and length + extra > limit:
            chunks.append("\n".join(current))
            current = [clean]
            length = len(clean)
        else:
            current.append(clean)
            length += extra
    if current:
        chunks.append("\n".join(current))
    if not chunks:
        chunks = ["Sem dados."]
    for index, chunk in enumerate(chunks, start=1):
        suffix = f" · {index}/{len(chunks)}" if len(chunks) > 1 else ""
        page.add_field(name=f"{title}{suffix}", value=chunk[:limit], inline=False)


def compact_mentions(ids: list[int], limit: int = 3000) -> str:
    parts: list[str] = []
    for user_id in ids:
        mention = f"<@{user_id}>"
        candidate = ", ".join(parts + [mention])
        if len(candidate) > limit:
            break
        parts.append(mention)
    omitted = len(ids) - len(parts)
    text = ", ".join(parts) if parts else "nenhum vencedor"
    if omitted:
        text = f"{text} · +{omitted} outros vencedores"
    return text


class BNComponentView(discord.ui.View):
    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[discord.Interaction]) -> None:
        logger.error("component interaction failed custom_id=%s", getattr(item, "custom_id", None), exc_info=(type(error), error, error.__traceback__))
        message = "Não foi possível concluir esta ação. Tente novamente."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.exception("component error response failed")


class TicketView(BNComponentView):
    def __init__(self, cog: "CommunityCog", ticket_id: int, status: str = "open"):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket_id = ticket_id
        if status == "closed":
            reopen = discord.ui.Button(label="Reabrir chamado", style=discord.ButtonStyle.success, custom_id=f"bn:ticket:reopen:{ticket_id}")
            reopen.callback = self.reopen_callback
            self.add_item(reopen)
        else:
            claim = discord.ui.Button(label="Assumir chamado", style=discord.ButtonStyle.secondary, custom_id=f"bn:ticket:claim:{ticket_id}")
            close = discord.ui.Button(label="Fechar chamado", style=discord.ButtonStyle.danger, custom_id=f"bn:ticket:close:{ticket_id}")
            claim.callback = self.claim_callback
            close.callback = self.close_callback
            self.add_item(claim)
            self.add_item(close)

    async def claim_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.ticket_claim(interaction, self.ticket_id)

    async def close_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.ticket_close(interaction, self.ticket_id)

    async def reopen_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.ticket_reopen(interaction, self.ticket_id)


class SuggestionView(BNComponentView):
    def __init__(self, cog: "CommunityCog", suggestion_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.suggestion_id = suggestion_id
        up = discord.ui.Button(label="Apoiar", style=discord.ButtonStyle.success, custom_id=f"bn:suggestion:up:{suggestion_id}")
        down = discord.ui.Button(label="Não apoiar", style=discord.ButtonStyle.danger, custom_id=f"bn:suggestion:down:{suggestion_id}")
        up.callback = self.up_callback
        down.callback = self.down_callback
        self.add_item(up)
        self.add_item(down)

    async def up_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.suggestion_vote(interaction, self.suggestion_id, 1)

    async def down_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.suggestion_vote(interaction, self.suggestion_id, -1)


class GiveawayView(BNComponentView):
    def __init__(self, cog: "CommunityCog", giveaway_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.giveaway_id = giveaway_id
        enter = discord.ui.Button(label="Participar", style=discord.ButtonStyle.success, custom_id=f"bn:giveaway:enter:{giveaway_id}")
        enter.callback = self.enter_callback
        self.add_item(enter)

    async def enter_callback(self, interaction: discord.Interaction) -> None:
        await self.cog.giveaway_enter(interaction, self.giveaway_id)


class PollView(BNComponentView):
    def __init__(self, cog: "CommunityCog", poll_id: int, options: list[str]):
        super().__init__(timeout=None)
        self.cog = cog
        self.poll_id = poll_id
        for index, option in enumerate(options):
            button = discord.ui.Button(label=f"{index + 1}. {option[:70]}", style=discord.ButtonStyle.secondary, custom_id=f"bn:poll:vote:{poll_id}:{index}", row=index // 5)
            button.callback = self.make_callback(index)
            self.add_item(button)

    def make_callback(self, option_index: int):
        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.poll_vote(interaction, self.poll_id, option_index)
        return callback


class CommunityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.registered_views: set[str] = set()
        self._message_refresh_tasks: dict[str, asyncio.Task[None]] = {}
        self._message_refreshing: set[str] = set()
        self._message_refresh_pending: set[str] = set()

    def cog_unload(self) -> None:
        for task in self._message_refresh_tasks.values():
            task.cancel()
        self._message_refresh_tasks.clear()
        self._message_refreshing.clear()
        self._message_refresh_pending.clear()

    def schedule_message_refresh(self, key: str, callback: Callable[[], Awaitable[None]]) -> None:
        task = self._message_refresh_tasks.get(key)
        if task is not None and not task.done():
            if key in self._message_refreshing:
                self._message_refresh_pending.add(key)
            return
        self._message_refresh_tasks[key] = asyncio.create_task(self._run_debounced_refresh(key, callback))

    async def _run_debounced_refresh(self, key: str, callback: Callable[[], Awaitable[None]]) -> None:
        try:
            while True:
                await asyncio.sleep(2)
                self._message_refreshing.add(key)
                try:
                    await callback()
                finally:
                    self._message_refreshing.discard(key)
                if key not in self._message_refresh_pending:
                    break
                self._message_refresh_pending.discard(key)
        except Exception:
            logger.exception("debounced community message refresh failed key=%s", key)
        finally:
            self._message_refreshing.discard(key)
            self._message_refresh_pending.discard(key)
            current = asyncio.current_task()
            if self._message_refresh_tasks.get(key) is current:
                self._message_refresh_tasks.pop(key, None)

    async def get_guild_settings(self, guild_id: int) -> GuildSettings | None:
        async with session_factory() as session:
            return await session.get(GuildSettings, guild_id)

    async def send_channel_message(self, guild: discord.Guild, channel_id: int | None, **kwargs):
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                return await channel.send(**kwargs)
            except discord.HTTPException:
                logger.exception("community channel message failed guild=%s channel=%s", guild.id, channel.id)
        return None

    def resolve_channel(self, guild: discord.Guild, channel_id: int | None):
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        if channel is None and hasattr(guild, "get_thread"):
            channel = guild.get_thread(channel_id)
        return channel

    async def build_suggestion_message(self, suggestion: Suggestion) -> discord.Embed:
        page = embed(f"BN / SUGESTÃO #{suggestion.id}", suggestion.content, "community")
        page.add_field(name="Estado", value=status_line("Status", STATUS_LABELS.get(suggestion.status, suggestion.status), "active" if suggestion.status in {"pending", "analysis"} else "ok" if suggestion.status in {"approved", "implemented"} else "closed"), inline=True)
        page.add_field(name="Apoio", value=f"`{number(suggestion.upvotes)}`", inline=True)
        page.add_field(name="Contrários", value=f"`{number(suggestion.downvotes)}`", inline=True)
        total_votes = suggestion.upvotes + suggestion.downvotes
        page.add_field(name="Balanço", value=f"{bar(suggestion.upvotes, total_votes)}\n{number(total_votes)} votos", inline=False)
        if suggestion.staff_note:
            page.add_field(name="Nota da equipe", value=suggestion.staff_note[:1024], inline=False)
        return page

    async def build_giveaway_message(self, giveaway: Giveaway, entries: int | None = None) -> discord.Embed:
        requirements = giveaway.requirements or {}
        role_ids = safe_int_list(requirements.get("role_ids", []), 20)
        role_text = ", ".join(f"<@&{role_id}>" for role_id in role_ids) if role_ids else "Qualquer membro elegível"
        page = embed(f"BN / SORTEIO #{giveaway.id}", giveaway.prize, "community")
        page.add_field(name="Vencedores", value=f"`{giveaway.winners}`", inline=True)
        page.add_field(name="Termina", value=discord.utils.format_dt(giveaway.ends_at, "R"), inline=True)
        page.add_field(name="Participantes", value=f"`{number(entries or 0)}`", inline=True)
        page.add_field(name="Requisitos", value=role_text[:1024], inline=False)
        requirements_text = []
        try:
            min_level = max(int(requirements.get("min_level", 0)), 0)
        except (TypeError, ValueError):
            min_level = 0
        try:
            min_messages = max(int(requirements.get("min_messages", 0)), 0)
        except (TypeError, ValueError):
            min_messages = 0
        if min_level:
            requirements_text.append(f"nível {min_level}")
        if min_messages:
            requirements_text.append(f"{number(min_messages)} mensagens")
        if requirements_text:
            page.add_field(name="Mínimos", value=" · ".join(requirements_text), inline=False)
        return page

    async def refresh_giveaway_message(self, guild: discord.Guild | None, giveaway_id: int) -> None:
        if guild is None:
            return
        async with session_factory() as session:
            giveaway = await session.get(Giveaway, giveaway_id)
            if giveaway is None or not giveaway.message_id:
                return
            entry_count = int((await session.scalar(select(func.count(GiveawayEntry.id)).where(GiveawayEntry.giveaway_id == giveaway_id))) or 0)
            channel = self.resolve_channel(guild, giveaway.channel_id)
            message_id = giveaway.message_id
            requirements = dict(giveaway.requirements or {})
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            message = channel.get_partial_message(message_id)
            if giveaway.status == "active":
                page = await self.build_giveaway_message(giveaway, entry_count)
                await message.edit(embed=page, view=GiveawayView(self, giveaway.id))
            else:
                winner_ids = safe_int_list(requirements.get("winner_ids", []), 10000)
                page = await self.build_giveaway_message(giveaway, entry_count)
                page.description = f"{giveaway.prize}\n\n**Vencedores:** {compact_mentions(winner_ids)}"
                await message.edit(embed=page, view=None)
        except discord.HTTPException:
            logger.exception("giveaway panel refresh failed giveaway=%s", giveaway_id)

    async def refresh_poll_message(self, guild: discord.Guild | None, poll_id: int) -> None:
        if guild is None:
            return
        async with session_factory() as session:
            poll = await session.get(Poll, poll_id)
            if poll is None or not poll.message_id:
                return
            from app.services.community import poll_counts
            counts = await poll_counts(session, poll_id, len(poll.options))
            message_id = poll.message_id
            channel_id = poll.channel_id
            options = list(poll.options)
            question = poll.question
            active = poll.status == "active" and poll.ends_at > utc_now()
        channel = self.resolve_channel(guild, channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            message = channel.get_partial_message(message_id)
            page = embed("BN / ENQUETE", question, "community")
            total = sum(counts)
            rows = [f"**{index + 1}. {option}** · `{count}` · {percent(count, total)}\n{bar(count, total, 10)}" for index, (option, count) in enumerate(zip(options, counts))]
            add_line_fields(page, f"Votos · {number(total)}", rows)
            leader = max(counts) if counts else 0
            page.add_field(name="Líder", value=f"`{number(leader)}` votos · {percent(leader, total)}" if total else "Sem votos ainda.", inline=False)
            page.set_footer(text=f"BN Bot · votação · termina {discord.utils.format_dt(poll.ends_at, 'R')}")
            await message.edit(embed=page, view=PollView(self, poll.id, options) if active else None)
        except discord.HTTPException:
            logger.exception("poll panel refresh failed poll=%s", poll_id)

    async def ensure_ticket_channel(self, guild: discord.Guild, ticket: Ticket) -> discord.TextChannel:
        settings = await self.get_guild_settings(guild.id)
        config = setting_config(settings, "tickets")
        category_id = config.get("category_id")
        category = guild.get_channel(int(category_id)) if category_id and str(category_id).isdigit() else None
        staff_role_ids = parse_ids(config.get("staff_role_ids"), 20) if isinstance(config.get("staff_role_ids"), str) else safe_int_list(config.get("staff_role_ids", []), 20)
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        opener = guild.get_member(ticket.opener_id)
        if opener is None:
            try:
                opener = await guild.fetch_member(ticket.opener_id)
            except (discord.NotFound, discord.HTTPException):
                opener = None
        if opener:
            overwrites[opener] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
        for role_id in staff_role_ids:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True, attach_files=True)
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True, manage_channels=True)
        kwargs = {"name": f"ticket-{str(ticket.id)[-6:]}", "topic": f"BN Bot Ticket #{ticket.id} | {ticket.reason or 'Suporte'}", "overwrites": overwrites}
        if isinstance(category, discord.CategoryChannel):
            kwargs["category"] = category
        channel = await guild.create_text_channel(**kwargs, reason="BN Bot ticket")
        ticket.channel_id = channel.id
        return channel

    async def build_ticket_message(self, ticket: Ticket) -> discord.Embed:
        priority_labels = {"low": "baixa", "normal": "normal", "high": "alta", "urgent": "urgente"}
        status_labels = {"open": "aberto", "closed": "fechado", "reopened": "reaberto"}
        page = embed(f"BN / TICKET #{ticket.id}", ticket.reason or "Sem motivo informado", "community")
        page.add_field(name="Categoria", value=f"`{ticket.category}`", inline=True)
        page.add_field(name="Prioridade", value=f"`{priority_labels.get(ticket.priority, ticket.priority)}`", inline=True)
        page.add_field(name="Estado", value=f"`{status_labels.get(ticket.status, ticket.status)}`", inline=True)
        page.add_field(name="Responsável", value=f"<@{ticket.assignee_id}>" if ticket.assignee_id else "Ainda não assumido", inline=False)
        page.set_footer(text="BN Bot · painel do chamado")
        return page

    async def restore_views(self) -> None:
        async def load_batches(session, statement):
            rows = []
            offset = 0
            while True:
                batch = list((await session.execute(statement.limit(500).offset(offset))).scalars())
                if not batch:
                    return rows
                rows.extend(batch)
                if len(batch) < 500:
                    return rows
                offset += 500

        try:
            async with session_factory() as session:
                suggestions = await load_batches(session, select(Suggestion).where(Suggestion.status.in_(["pending", "analysis"]), Suggestion.message_id.is_not(None)).order_by(Suggestion.id.asc()))
                giveaways = await load_batches(session, select(Giveaway).where(Giveaway.status == "active", Giveaway.message_id.is_not(None)).order_by(Giveaway.id.asc()))
                polls = await load_batches(session, select(Poll).where(Poll.status == "active", Poll.message_id.is_not(None)).order_by(Poll.id.asc()))
                tickets = await load_batches(session, select(Ticket).where(Ticket.status.in_(["open", "reopened", "closed"]), Ticket.panel_message_id.is_not(None)).order_by(Ticket.id.asc()))
        except Exception:
            logger.exception("community view restoration failed")
            return
        for row in suggestions:
            key = f"suggestion:{row.id}"
            if key not in self.registered_views:
                self.bot.add_view(SuggestionView(self, row.id), message_id=row.message_id)
                self.registered_views.add(key)
        for row in giveaways:
            key = f"giveaway:{row.id}"
            if key not in self.registered_views:
                self.bot.add_view(GiveawayView(self, row.id), message_id=row.message_id)
                self.registered_views.add(key)
        for row in polls:
            key = f"poll:{row.id}"
            if key not in self.registered_views:
                self.bot.add_view(PollView(self, row.id, row.options), message_id=row.message_id)
                self.registered_views.add(key)
        for row in tickets:
            key = f"ticket:{row.id}"
            if key not in self.registered_views:
                self.bot.add_view(TicketView(self, row.id, row.status), message_id=row.panel_message_id)
                self.registered_views.add(key)

    @app_commands.command(name="ticket", description="Abre um ticket de suporte privado.")
    @app_commands.guild_only()
    @app_commands.choices(priority=TICKET_PRIORITY_CHOICES)
    @app_commands.describe(reason="Motivo do atendimento", category="Área do atendimento", priority="Prioridade do chamado")
    async def ticket(self, interaction: discord.Interaction, reason: str, category: str = "general", priority: str = "normal") -> None:
        guild = interaction.guild
        assert guild is not None
        reason = " ".join(reason.split())
        if not reason:
            await interaction.response.send_message("O motivo do ticket não pode estar vazio.", ephemeral=True)
            return
        priority = priority.casefold()
        category = " ".join(category.split()) or "general"
        if len(reason) > 500:
            await interaction.response.send_message("O motivo do ticket deve ter no máximo 500 caracteres.", ephemeral=True)
            return
        if len(category) > 80:
            await interaction.response.send_message("A categoria deve ter no máximo 80 caracteres.", ephemeral=True)
            return
        if priority not in {"low", "normal", "high", "urgent"}:
            await interaction.response.send_message("Prioridade inválida.", ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            existing = await session.scalar(select(Ticket).where(Ticket.guild_id == guild.id, Ticket.opener_id == interaction.user.id, Ticket.status.in_(["open", "reopened"])).order_by(Ticket.created_at.desc()).limit(1))
            if existing:
                existing_channel = guild.get_channel(existing.channel_id) if existing.channel_id else None
                if existing_channel is not None:
                    await respond(interaction, f"Você já possui um ticket aberto: {existing_channel.mention}.", ephemeral=True)
                    return
                await set_ticket_status(session, existing.id, interaction.user.id, "closed", {"reason": "channel_missing"})
                await session.commit()
            cooldown = await check_and_set(f"bn:ticket:{guild.id}:{interaction.user.id}", 30)
            if cooldown is not None:
                await respond(interaction, f"Você já abriu um ticket recentemente. Aguarde {cooldown}s.", ephemeral=True)
                return
            ticket_row = await create_ticket(session, guild.id, interaction.user.id, category, priority, reason)
            ticket_record_id = ticket_row.id
            channel: discord.TextChannel | None = None
            try:
                channel = await self.ensure_ticket_channel(guild, ticket_row)
                message = await channel.send(embed=await self.build_ticket_message(ticket_row), view=TicketView(self, ticket_row.id, ticket_row.status))
                ticket_row.panel_message_id = message.id
                await session.commit()
            except Exception:
                await session.rollback()
                try:
                    from app.services.cooldowns import release
                    await release(f"bn:ticket:{guild.id}:{interaction.user.id}")
                except Exception:
                    logger.exception("ticket cooldown release failed guild=%s user=%s", guild.id, interaction.user.id)
                if channel is not None:
                    try:
                        await channel.delete(reason="BN Bot cleanup após falha ao criar ticket")
                    except discord.HTTPException:
                        logger.exception("ticket cleanup failed ticket=%s", ticket_record_id)
                logger.exception("ticket creation failed guild=%s user=%s", guild.id, interaction.user.id)
                await respond(interaction, "Não foi possível criar o ticket. Verifique se o BN Bot possui Manage Channels.", ephemeral=True)
                return
        self.registered_views.add(f"ticket:{ticket_row.id}")
        page = embed(f"BN / TICKET #{ticket_row.id}", "Chamado aberto e pronto para atendimento.", "community")
        page.add_field(name="Canal", value=f"<#{ticket_row.channel_id}>", inline=True)
        priority_labels = {"low": "baixa", "normal": "normal", "high": "alta", "urgent": "urgente"}
        page.add_field(name="Prioridade", value=f"`{priority_labels.get(priority, priority)}`", inline=True)
        page.add_field(name="Categoria", value=f"`{category}`", inline=True)
        page.add_field(name="Próximo passo", value="Use o painel dentro do ticket para assumir ou encerrar o chamado.", inline=False)
        await respond(interaction, embed=page, ephemeral=True)

    @app_commands.command(name="ticket-close", description="Fecha um ticket e gera o transcript. Informe o ID exibido no painel.")
    @app_commands.guild_only()
    async def ticket_close_command(self, interaction: discord.Interaction, ticket_id: str) -> None:
        try:
            parsed_id = parse_snowflake(ticket_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        await self.ticket_close(interaction, parsed_id)

    async def ticket_close(self, interaction: discord.Interaction, ticket_id: int) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or not await is_staff(guild, member):
            await respond(interaction, "Você não possui permissão para fechar este ticket.", ephemeral=True)
            return
        cooldown = await check_and_set(f"bn:ticket-close:{guild.id}:{interaction.user.id}", 20)
        if cooldown is not None:
            await respond(interaction, f"Você fechou um ticket recentemente. Aguarde {cooldown}s antes de tentar novamente.", ephemeral=True)
            return
        async with session_factory() as lookup_session:
            ticket_row = await lookup_session.get(Ticket, ticket_id)
            if ticket_row is None or ticket_row.guild_id != guild.id:
                await respond(interaction, "Ticket não encontrado.", ephemeral=True)
                return
            if ticket_row.status != "open":
                await respond(interaction, f"O ticket #{ticket_id} já está {ticket_row.status}.", ephemeral=True)
                return
            channel = guild.get_channel(ticket_row.channel_id) if ticket_row.channel_id else None
            opener_id = ticket_row.opener_id
        transcript = ""
        if isinstance(channel, discord.TextChannel):
            lines = []
            max_transcript_messages = 1000
            async for message in channel.history(limit=max_transcript_messages, oldest_first=True):
                content = message.content.replace("\n", " ").strip() or "[sem texto]"
                extras = []
                if message.attachments:
                    extras.extend(f"[anexo] {attachment.url}" for attachment in message.attachments)
                if message.embeds:
                    extras.append(f"[embeds] {len(message.embeds)}")
                suffix = " | " + " | ".join(extras) if extras else ""
                lines.append(f"{message.created_at.isoformat()} | {message.author} ({message.author.id}) | {content}{suffix}")
            if len(lines) >= max_transcript_messages:
                lines.append(f"[Transcript limitado a {max_transcript_messages} mensagens para proteger a estabilidade do Discord.]")
            transcript = "\n".join(lines)
            opener = guild.get_member(opener_id)
            if opener:
                try:
                    await channel.set_permissions(opener, view_channel=True, send_messages=False, read_message_history=True)
                except discord.HTTPException:
                    logger.exception("ticket lock failed ticket=%s", ticket_id)
        async with session_factory() as session:
            await set_ticket_status(session, ticket_id, interaction.user.id, "closed")
            await save_ticket_transcript(session, ticket_id, transcript, interaction.user.id)
            settings = await session.get(GuildSettings, guild.id)
            config = setting_config(settings, "tickets")
            await session.commit()
        transcript_channel_id = config.get("transcript_channel_id") if config else None
        transcript_channel = guild.get_channel(int(transcript_channel_id)) if transcript_channel_id and str(transcript_channel_id).isdigit() else None
        transcript_sent = False
        if isinstance(transcript_channel, discord.TextChannel) and transcript:
            file_data = io.BytesIO(transcript.encode("utf-8"))
            try:
                await transcript_channel.send(content=f"Transcript do ticket #{ticket_id}", file=discord.File(file_data, filename=f"ticket-{ticket_id}.txt"))
                transcript_sent = True
            except discord.HTTPException:
                logger.exception("ticket transcript publication failed ticket=%s", ticket_id)
        if isinstance(channel, discord.TextChannel) and ticket_row.panel_message_id:
            try:
                panel = await channel.fetch_message(ticket_row.panel_message_id)
                closed_view = TicketView(self, ticket_id, "closed")
                closed_page = embed(f"BN / TICKET #{ticket_id}", "Chamado encerrado. O histórico foi preservado.", "community")
                closed_page.add_field(name="Status", value="`fechado`", inline=True)
                closed_page.add_field(name="Transcript", value="Enviado" if transcript_sent else "Não configurado", inline=True)
                closed_page.add_field(name="Mensagens", value=number(len(transcript.splitlines())) if transcript else "0", inline=True)
                await panel.edit(embed=closed_page, view=closed_view)
            except discord.HTTPException:
                logger.exception("ticket panel close refresh failed ticket=%s", ticket_id)
        close_embed = embed("BN / TICKET FECHADO", f"Chamado `#{ticket_id}` foi encerrado.", "community")
        close_embed.add_field(name="Transcript", value="Enviado" if transcript_sent else "Não configurado", inline=True)
        close_embed.add_field(name="Mensagens", value=number(len(transcript.splitlines())) if transcript else "0", inline=True)
        await respond(interaction, embed=close_embed, ephemeral=True)

    @app_commands.command(name="ticket-reopen", description="Reabre um ticket fechado pelo ID do painel.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticket_reopen_command(self, interaction: discord.Interaction, ticket_id: str) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        try:
            ticket_id = parse_snowflake(ticket_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or not await is_staff(guild, member):
            await respond(interaction, "Você não possui permissão para reabrir este ticket.", ephemeral=True)
            return
        async with session_factory() as session:
            ticket_row = await session.get(Ticket, ticket_id)
            if ticket_row is None or ticket_row.guild_id != guild.id:
                await respond(interaction, "Ticket não encontrado.", ephemeral=True)
                return
            if ticket_row.status != "closed":
                await respond(interaction, f"O ticket #{ticket_id} precisa estar fechado para ser reaberto.", ephemeral=True)
                return
            await set_ticket_status(session, ticket_id, interaction.user.id, "reopened")
            created_channel = False
            channel = guild.get_channel(ticket_row.channel_id) if ticket_row.channel_id else None
            try:
                if not isinstance(channel, discord.TextChannel):
                    channel = await self.ensure_ticket_channel(guild, ticket_row)
                    created_channel = True
                    message = await channel.send(embed=await self.build_ticket_message(ticket_row), view=TicketView(self, ticket_row.id, ticket_row.status))
                    ticket_row.panel_message_id = message.id
                else:
                    panel = None
                    if ticket_row.panel_message_id:
                        try:
                            panel = await channel.fetch_message(ticket_row.panel_message_id)
                            await panel.edit(embed=await self.build_ticket_message(ticket_row), view=TicketView(self, ticket_row.id, ticket_row.status))
                        except discord.NotFound:
                            logger.warning("ticket panel missing; recreating ticket=%s", ticket_id)
                        except discord.HTTPException:
                            logger.exception("ticket panel refresh failed ticket=%s", ticket_id)
                    if panel is None:
                        message = await channel.send(embed=await self.build_ticket_message(ticket_row), view=TicketView(self, ticket_row.id, ticket_row.status))
                        ticket_row.panel_message_id = message.id
                opener = guild.get_member(ticket_row.opener_id)
                if opener:
                    await channel.set_permissions(opener, view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
                await session.commit()
            except Exception:
                await session.rollback()
                if created_channel and isinstance(channel, discord.TextChannel):
                    try:
                        await channel.delete(reason="BN Bot cleanup após falha ao reabrir ticket")
                    except discord.HTTPException:
                        logger.exception("ticket reopen cleanup failed ticket=%s", ticket_id)
                logger.exception("ticket reopen failed ticket=%s", ticket_id)
                await respond(interaction, "Não foi possível reabrir o ticket. Verifique as permissões do BN Bot.", ephemeral=True)
                return
        await respond(interaction, f"Ticket #{ticket_id} reaberto.", ephemeral=True)

    @app_commands.command(name="ticket-claim", description="Assume um ticket aberto pelo ID do painel.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def ticket_claim_command(self, interaction: discord.Interaction, ticket_id: str) -> None:
        try:
            parsed_id = parse_snowflake(ticket_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        await self.ticket_claim(interaction, parsed_id)

    async def ticket_claim(self, interaction: discord.Interaction, ticket_id: int) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or not await is_staff(guild, member):
            await respond(interaction, "Você não possui permissão para assumir tickets.", ephemeral=True)
            return
        async with session_factory() as session:
            ticket_row = await session.get(Ticket, ticket_id)
            if ticket_row is None or ticket_row.guild_id != guild.id:
                await respond(interaction, "Ticket não encontrado.", ephemeral=True)
                return
            if ticket_row.status != "open":
                await respond(interaction, "Somente tickets abertos podem ser assumidos.", ephemeral=True)
                return
            await assign_ticket(session, ticket_id, interaction.user.id, interaction.user.id)
            await session.commit()
        await respond(interaction, f"Ticket #{ticket_id} atribuído a {interaction.user.mention}.", ephemeral=True)

    @app_commands.command(name="ticket-config", description="Configura categoria, equipe e transcript dos tickets.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_config(self, interaction: discord.Interaction, category_id: str = "", staff_role_ids: str = "", transcript_channel_id: str = "") -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        if category_id and not category_id.isdigit():
            await respond(interaction, "category_id precisa ser um ID numérico ou ficar vazio.", ephemeral=True)
            return
        if transcript_channel_id and not transcript_channel_id.isdigit():
            await respond(interaction, "transcript_channel_id precisa ser um ID numérico ou ficar vazio.", ephemeral=True)
            return
        try:
            category = int(category_id) if category_id else None
            transcript = int(transcript_channel_id) if transcript_channel_id else None
            role_ids = parse_ids(staff_role_ids, 20)
        except ValueError:
            await respond(interaction, "IDs de tickets inválidos.", ephemeral=True)
            return
        if category is not None and not isinstance(guild.get_channel(category), discord.CategoryChannel):
            await respond(interaction, "A categoria informada não existe neste servidor.", ephemeral=True)
            return
        if transcript is not None and not isinstance(guild.get_channel(transcript), discord.TextChannel):
            await respond(interaction, "O canal de transcript precisa ser um canal de texto deste servidor.", ephemeral=True)
            return
        missing_roles = [str(role_id) for role_id in role_ids if guild.get_role(role_id) is None]
        if missing_roles:
            await respond(interaction, f"Cargos não encontrados: {', '.join(missing_roles[:8])}.", ephemeral=True)
            return
        async with session_factory() as session:
            settings = await session.get(GuildSettings, guild.id)
            if settings is None:
                await respond(interaction, "As configurações do servidor ainda não foram inicializadas.", ephemeral=True)
                return
            config = dict(settings.config or {})
            ticket_config = dict(config.get("tickets", {}))
            ticket_config.update({"category_id": category, "staff_role_ids": role_ids, "transcript_channel_id": transcript})
            config["tickets"] = ticket_config
            settings.config = config
            settings.updated_at = utc_now()
            await session.commit()
        await respond(interaction, "Configuração de tickets salva.", ephemeral=True)

    @command_rate_limit("suggest", 30)
    @app_commands.command(name="suggest", description="Publica uma sugestão para votação da comunidade.")
    @app_commands.guild_only()
    async def suggest(self, interaction: discord.Interaction, content: str) -> None:
        guild = interaction.guild
        assert guild is not None
        if not content.strip():
            await respond(interaction, "A sugestão não pode estar vazia.", ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        settings = await self.get_guild_settings(guild.id)
        config = setting_config(settings, "community")
        channel_id = config.get("suggestion_channel_id")
        target = guild.get_channel(int(channel_id)) if channel_id and str(channel_id).isdigit() else interaction.channel
        if not isinstance(target, (discord.TextChannel, discord.Thread)):
            await respond(interaction, "Canal de sugestões inválido.", ephemeral=True)
            return
        content = " ".join(content.split())
        if len(content) > 4000:
            await respond(interaction, "A sugestão deve ter no máximo 4000 caracteres.", ephemeral=True)
            return
        now = utc_now()
        async with session_factory() as session:
            row = Suggestion(id=secrets.randbits(62), guild_id=guild.id, author_id=interaction.user.id, channel_id=target.id, content=content, status="pending", upvotes=0, downvotes=0, staff_note=None, message_id=None, created_at=now, updated_at=now)
            session.add(row)
            await session.flush()
            suggestion_record_id = row.id
            message = None
            try:
                message = await target.send(embed=await self.build_suggestion_message(row), view=SuggestionView(self, row.id))
                row.message_id = message.id
                await session.commit()
            except Exception:
                await session.rollback()
                if message is not None:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        logger.exception("suggestion cleanup failed suggestion=%s", suggestion_record_id)
                raise
        self.registered_views.add(f"suggestion:{row.id}")
        page = embed(f"BN / SUGESTÃO #{row.id}", "Sugestão publicada para a comunidade.", "community")
        page.add_field(name="Canal", value=target.mention, inline=True)
        page.add_field(name="Estado", value=status_line("Status", "pendente", "pending"), inline=True)
        page.add_field(name="Votação", value="Apoie ou não apoie usando os botões da publicação.", inline=False)
        await respond(interaction, embed=page, ephemeral=True)

    async def suggestion_vote(self, interaction: discord.Interaction, suggestion_id: int, value: int) -> None:
        await defer(interaction, ephemeral=True)
        retry_after = await check_and_set(f"bn:suggestion-vote:{interaction.guild_id or 0}:{interaction.user.id}", 2)
        if retry_after is not None:
            await respond(interaction, f"Aguarde {retry_after}s antes de votar novamente.", ephemeral=True)
            return
        async with session_factory() as session:
            suggestion = await session.get(Suggestion, suggestion_id)
            if suggestion is None or suggestion.guild_id != interaction.guild_id or suggestion.status not in {"pending", "analysis"}:
                await respond(interaction, "Esta sugestão não está disponível para votação.", ephemeral=True)
                return
            before_up = suggestion.upvotes
            before_down = suggestion.downvotes
            upvotes, downvotes = await cast_suggestion_vote(session, suggestion_id, interaction.user.id, value, interaction.guild_id)
            changed = (before_up, before_down) != (upvotes, downvotes)
            await session.commit()
        self.schedule_message_refresh(
            f"suggestion:{interaction.guild_id}:{suggestion_id}",
            lambda: self.refresh_suggestion_message(interaction.guild, suggestion_id),
        )
        if changed:
            label = "apoio" if value == 1 else "não apoio"
            page = embed("BN / VOTO REGISTRADO", "Sua posição foi atualizada.", "community")
            page.add_field(name="Escolha", value=f"`{label}`", inline=True)
            page.add_field(name="Balanço", value=f"A favor `{number(upvotes)}` · contra `{number(downvotes)}`", inline=True)
            page.add_field(name="Termômetro", value=f"{bar(upvotes, upvotes + downvotes)}", inline=False)
            await respond(interaction, embed=page, ephemeral=True)
        else:
            page = embed("BN / VOTO", "Sua posição já era esta.", "community")
            page.add_field(name="Balanço", value=f"A favor `{number(upvotes)}` · contra `{number(downvotes)}`", inline=False)
            await respond(interaction, embed=page, ephemeral=True)

    async def refresh_suggestion_message(self, guild: discord.Guild | None, suggestion_id: int) -> None:
        if guild is None:
            return
        async with session_factory() as session:
            suggestion = await session.get(Suggestion, suggestion_id)
        if suggestion is None or not suggestion.message_id:
            return
        channel = self.resolve_channel(guild, suggestion.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            message = channel.get_partial_message(suggestion.message_id)
            await message.edit(embed=await self.build_suggestion_message(suggestion), view=SuggestionView(self, suggestion.id) if suggestion.status in {"pending", "analysis"} else None)
        except discord.HTTPException:
            logger.exception("suggestion panel refresh failed suggestion=%s", suggestion_id)

    @app_commands.command(name="suggestion-status", description="Atualiza o status de uma sugestão.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.choices(status=SUGGESTION_STATUS_CHOICES)
    @app_commands.describe(suggestion_id="ID da sugestão", status="Novo estado", note="Nota visível para a equipe")
    async def suggestion_status(self, interaction: discord.Interaction, suggestion_id: str, status: str, note: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        try:
            suggestion_id = parse_snowflake(suggestion_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or not await is_staff(guild, member):
            await respond(interaction, "Você não possui permissão para revisar sugestões.", ephemeral=True)
            return
        async with session_factory() as session:
            try:
                row = await update_suggestion(session, suggestion_id, interaction.user.id, status.casefold(), note[:2000] if note else None, guild.id)
            except ValueError as exc:
                await respond(interaction, str(exc), ephemeral=True)
                return
            await session.commit()
        await self.refresh_suggestion_message(guild, row.id)
        await respond(interaction, f"Sugestão #{row.id} atualizada para {row.status}.", ephemeral=True)

    @command_rate_limit("report", 30)
    @app_commands.command(name="report", description="Registra uma denúncia contra um membro.")
    @app_commands.guild_only()
    async def report(self, interaction: discord.Interaction, user: discord.Member, reason: str, evidence: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        reason = " ".join(reason.split())
        if not reason:
            await interaction.response.send_message("O motivo da denúncia não pode estar vazio.", ephemeral=True)
            return
        if len(reason) > 2000:
            await interaction.response.send_message("O motivo da denúncia deve ter no máximo 2000 caracteres.", ephemeral=True)
            return
        if evidence and len(evidence) > 2000:
            await interaction.response.send_message("As evidências devem ter no máximo 2000 caracteres.", ephemeral=True)
            return
        if user.id == interaction.user.id:
            await interaction.response.send_message("Você não pode denunciar a si mesmo.", ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        now = utc_now()
        async with session_factory() as session:
            row = Report(id=secrets.randbits(62), guild_id=guild.id, reporter_id=interaction.user.id, reported_id=user.id, reason=reason, evidence=evidence if evidence else None, channel_id=interaction.channel_id, status="open", resolver_id=None, resolution=None, created_at=now, updated_at=now)
            session.add(row)
            settings = await session.get(GuildSettings, guild.id)
            config = setting_config(settings, "community")
            report_channel_id = config.get("report_channel_id")
            await session.commit()
        report_channel = guild.get_channel(int(report_channel_id)) if report_channel_id and str(report_channel_id).isdigit() else None
        published = False
        if isinstance(report_channel, discord.TextChannel):
            report_page = embed(f"BN / DENÚNCIA #{row.id}", row.reason, "community")
            report_page.add_field(name="Denunciante", value=user_line(interaction.user), inline=False)
            report_page.add_field(name="Denunciado", value=user_line(user), inline=False)
            if row.evidence:
                report_page.add_field(name="Evidências", value=row.evidence[:1024], inline=False)
            report_page.add_field(name="Estado", value=status_line("Denúncia", "aberta", "open"), inline=False)
            try:
                await report_channel.send(embed=report_page, allowed_mentions=discord.AllowedMentions.none())
                published = True
            except discord.HTTPException:
                logger.exception("report publication failed report=%s", row.id)
        page = embed("BN / DENÚNCIA REGISTRADA", f"Denúncia `#{row.id}` foi registrada.", "community")
        page.add_field(name="Denunciado", value=user.mention, inline=True)
        page.add_field(name="Canal", value=report_channel.mention if published and report_channel else "Não configurado", inline=True)
        page.add_field(name="Estado", value=status_line("Status", "aberta", "open"), inline=False)
        await respond(interaction, embed=page, ephemeral=True)

    @app_commands.command(name="report-status", description="Atualiza o status de uma denúncia.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.choices(status=REPORT_STATUS_CHOICES)
    @app_commands.describe(report_id="ID da denúncia", status="Novo estado", resolution="Resumo da resolução")
    async def report_status(self, interaction: discord.Interaction, report_id: str, status: str, resolution: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        try:
            report_id = parse_snowflake(report_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or not await is_staff(guild, member):
            await respond(interaction, "Você não possui permissão para revisar denúncias.", ephemeral=True)
            return
        async with session_factory() as session:
            try:
                row = await update_report(session, report_id, interaction.user.id, status.casefold(), resolution[:2000] if resolution else None, guild.id)
            except ValueError as exc:
                await respond(interaction, str(exc), ephemeral=True)
                return
            await session.commit()
        await respond(interaction, f"Denúncia #{row.id} atualizada para {row.status}.", ephemeral=True)

    giveaway_group = app_commands.Group(name="giveaway", description="Gerencia sorteios de membros.", default_permissions=discord.Permissions(manage_guild=True))

    @command_rate_limit("giveaway", 3)
    @giveaway_group.command(name="create", description="Cria um sorteio.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_create(self, interaction: discord.Interaction, prize: str, duration_minutes: app_commands.Range[int, 1, 525600], winners: app_commands.Range[int, 1, 50] = 1, required_role_ids: str = "", min_level: app_commands.Range[int, 0, 100000] = 0, min_messages: app_commands.Range[int, 0, 1000000] = 0) -> None:
        guild = interaction.guild
        assert guild is not None
        prize = " ".join(prize.split())
        if not prize:
            await interaction.response.send_message("O prêmio não pode estar vazio.", ephemeral=True)
            return
        if len(prize) > 300:
            await interaction.response.send_message("O prêmio deve ter no máximo 300 caracteres.", ephemeral=True)
            return
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("Este comando precisa ser usado em um canal de texto ou thread.", ephemeral=True)
            return
        if duration_minutes < 1 or duration_minutes > 525600 or winners < 1 or winners > 50 or min_level < 0 or min_messages < 0:
            await interaction.response.send_message("Os parâmetros do sorteio são inválidos.", ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        try:
            required_roles = parse_ids(required_role_ids, 20)
        except ValueError:
            await respond(interaction, "Os cargos obrigatórios precisam ser IDs numéricos separados por vírgula.", ephemeral=True)
            return
        missing_roles = [str(role_id) for role_id in required_roles if guild.get_role(role_id) is None]
        if missing_roles:
            await respond(interaction, f"Cargos de requisito não encontrados: {', '.join(missing_roles[:8])}.", ephemeral=True)
            return
        requirements = {"role_ids": required_roles, "min_level": min_level, "min_messages": min_messages, "exclude_bots": True}
        now = utc_now()
        async with session_factory() as session:
            row = Giveaway(id=secrets.randbits(62), guild_id=guild.id, channel_id=channel.id, prize=prize, winners=winners, ends_at=now + timedelta(minutes=duration_minutes), requirements=requirements, status="active", message_id=None, created_at=now, updated_at=now)
            session.add(row)
            await session.flush()
            giveaway_record_id = row.id
            message = None
            try:
                message = await channel.send(embed=await self.build_giveaway_message(row, 0), view=GiveawayView(self, row.id))
                row.message_id = message.id
                await session.commit()
            except Exception:
                await session.rollback()
                if message is not None:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        logger.exception("giveaway cleanup failed giveaway=%s", giveaway_record_id)
                raise
        self.registered_views.add(f"giveaway:{row.id}")
        page = await self.build_giveaway_message(row, 0)
        page.add_field(name="Painel", value="O botão abaixo da publicação controla a participação.", inline=False)
        await respond(interaction, embed=page, ephemeral=True)

    @command_rate_limit("giveaway", 3)
    @giveaway_group.command(name="end", description="Encerra um sorteio imediatamente.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_end_command(self, interaction: discord.Interaction, giveaway_id: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            giveaway_id = parse_snowflake(giveaway_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        winners = await self.finish_giveaway(interaction.guild, giveaway_id)
        if winners is None:
            await interaction.followup.send("Sorteio não encontrado ou já encerrado.", ephemeral=True)
            return
        page = embed(f"BN / SORTEIO #{giveaway_id}", "O sorteio foi encerrado.", "community")
        page.add_field(name="Vencedores", value=", ".join(f"<@{user_id}>" for user_id in winners) or "Nenhum vencedor", inline=False)
        page.add_field(name="Status", value=status_line("Resultado", "encerrado", "closed"), inline=True)
        await interaction.followup.send(embed=page, ephemeral=True)

    @command_rate_limit("giveaway", 3)
    @giveaway_group.command(name="reroll", description="Escolhe um novo vencedor para um sorteio encerrado.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_reroll(self, interaction: discord.Interaction, giveaway_id: str) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        try:
            giveaway_id = parse_snowflake(giveaway_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        async with session_factory() as session:
            giveaway = await session.get(Giveaway, giveaway_id, with_for_update=True)
            if giveaway is None or giveaway.guild_id != guild.id or giveaway.status != "ended":
                await respond(interaction, "Sorteio encerrado não encontrado.", ephemeral=True)
                return
            result = await session.execute(select(GiveawayEntry.user_id).where(GiveawayEntry.giveaway_id == giveaway_id))
            entrants = [int(row[0]) for row in result.all()]
            previous = set(safe_int_list((giveaway.requirements or {}).get("winner_ids", []), 10_000))
            candidates = [user_id for user_id in entrants if user_id not in previous]
            if not candidates:
                await respond(interaction, "Não existem participantes disponíveis para reroll.", ephemeral=True)
                return
            winner = secrets.SystemRandom().choice(candidates)
            requirements = dict(giveaway.requirements or {})
            requirements["winner_ids"] = list(previous | {winner})
            giveaway.requirements = requirements
            giveaway.updated_at = utc_now()
            await session.commit()
        await self.refresh_giveaway_message(guild, giveaway_id)
        page = embed(f"BN / SORTEIO #{giveaway_id}", "Novo vencedor escolhido.", "community")
        page.add_field(name="Vencedor", value=f"<@{winner}>", inline=False)
        page.add_field(name="Método", value="reroll", inline=True)
        await respond(interaction, embed=page)

    @command_rate_limit("giveaway", 3)
    @giveaway_group.command(name="cancel", description="Cancela um sorteio ativo.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def giveaway_cancel(self, interaction: discord.Interaction, giveaway_id: str) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        try:
            giveaway_id = parse_snowflake(giveaway_id)
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        async with session_factory() as session:
            giveaway = await session.get(Giveaway, giveaway_id, with_for_update=True)
            if giveaway is None or giveaway.guild_id != guild.id or giveaway.status != "active":
                await respond(interaction, "Sorteio ativo não encontrado.", ephemeral=True)
                return
            giveaway.status = "cancelled"
            giveaway.updated_at = utc_now()
            channel_id = giveaway.channel_id
            message_id = giveaway.message_id
            await session.commit()
        channel = self.resolve_channel(guild, channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread)) and message_id:
            try:
                message = await channel.fetch_message(message_id)
                page = embed(f"BN / SORTEIO #{giveaway_id}", "Sorteio cancelado pela equipe.", "community")
                page.add_field(name="Status", value="`cancelado`", inline=True)
                page.add_field(name="Participação", value="encerrada", inline=True)
                await message.edit(embed=page, view=None)
            except discord.HTTPException:
                logger.exception("giveaway cancel publication failed giveaway=%s", giveaway_id)
        page = embed(f"BN / SORTEIO #{giveaway_id}", "O sorteio foi cancelado pela equipe.", "community")
        page.add_field(name="Status", value=status_line("Resultado", "cancelado", "closed"), inline=True)
        page.add_field(name="Participação", value="encerrada", inline=True)
        await respond(interaction, embed=page, ephemeral=True)

    async def giveaway_enter(self, interaction: discord.Interaction, giveaway_id: int) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        retry_after = await check_and_set(f"bn:giveaway-enter:{guild.id}:{interaction.user.id}", 3)
        if retry_after is not None:
            await respond(interaction, f"Aguarde {retry_after}s antes de alterar sua participação.", ephemeral=True)
            return
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None:
            await respond(interaction, "Não foi possível validar sua conta neste servidor.", ephemeral=True)
            return
        async with session_factory() as session:
            giveaway = await session.get(Giveaway, giveaway_id)
            if giveaway is None or giveaway.guild_id != guild.id or giveaway.status != "active":
                await respond(interaction, "Sorteio indisponível.", ephemeral=True)
                return
            if giveaway.ends_at <= utc_now():
                await respond(interaction, "Este sorteio já foi encerrado.", ephemeral=True)
                return
            requirements = giveaway.requirements or {}
            if requirements.get("exclude_bots", True) and member.bot:
                await respond(interaction, "Bots não podem participar deste sorteio.", ephemeral=True)
                return
            required_roles = set(safe_int_list(requirements.get("role_ids", []), 20))
            if required_roles and not required_roles.intersection({role.id for role in member.roles}):
                await respond(interaction, "Você não possui um dos cargos exigidos.", ephemeral=True)
                return
            try:
                min_level = max(int(requirements.get("min_level", 0)), 0)
            except (TypeError, ValueError):
                min_level = 0
            try:
                min_messages = max(int(requirements.get("min_messages", 0)), 0)
            except (TypeError, ValueError):
                min_messages = 0
            if min_level or min_messages:
                exp = await session.scalar(select(Experience).where(Experience.guild_id == guild.id, Experience.user_id == member.id))
                member_row = await session.scalar(select(Member).where(Member.guild_id == guild.id, Member.user_id == member.id))
                if (exp.level if exp else 0) < min_level or (member_row.message_count if member_row else 0) < min_messages:
                    await respond(interaction, "Você não atende aos requisitos do sorteio.", ephemeral=True)
                    return
            entered = await enter_giveaway(session, giveaway_id, member.id)
            await session.commit()
        self.schedule_message_refresh(
            f"giveaway:{guild.id}:{giveaway_id}",
            lambda: self.refresh_giveaway_message(guild, giveaway_id),
        )
        page = embed("BN / SORTEIO", "Participação atualizada.", "community")
        page.add_field(name="Estado", value=status_line("Participação", "ativa" if entered else "removida", "active" if entered else "closed"), inline=True)
        page.add_field(name="Sorteio", value=f"`#{giveaway_id}`", inline=True)
        await respond(interaction, embed=page, ephemeral=True)

    async def finish_giveaway(self, guild: discord.Guild | None, giveaway_id: int) -> list[int] | None:
        if guild is None:
            return None
        async with session_factory() as session:
            row = await session.get(Giveaway, giveaway_id)
            if row is None or row.guild_id != guild.id or row.status != "active":
                return None
            try:
                winners = await end_giveaway(session, giveaway_id)
            except ValueError:
                await session.rollback()
                return None
            message_id = row.message_id
            channel_id = row.channel_id
            await session.commit()
        await self.refresh_giveaway_message(guild, giveaway_id)
        channel = self.resolve_channel(guild, channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            try:
                await channel.send(
                    f"Sorteio #{giveaway_id} encerrado. Vencedores: {', '.join(f'<@{user_id}>' for user_id in winners) or 'nenhum vencedor'}",
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except discord.HTTPException:
                logger.exception("giveaway result publication failed giveaway=%s", giveaway_id)
        return winners

    poll_group = app_commands.Group(name="poll", description="Gerencia enquetes.", default_permissions=discord.Permissions(manage_guild=True))

    @command_rate_limit("poll", 3)
    @poll_group.command(name="create", description="Cria uma enquete com 2 a 10 opções.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        question="Pergunta da enquete",
        option1="Opção 1, obrigatória",
        option2="Opção 2, obrigatória",
        option3="Opção 3, opcional",
        option4="Opção 4, opcional",
        option5="Opção 5, opcional",
        option6="Opção 6, opcional",
        option7="Opção 7, opcional",
        option8="Opção 8, opcional",
        option9="Opção 9, opcional",
        option10="Opção 10, opcional",
        duration_minutes="Duração em minutos",
    )
    async def poll_create(
        self,
        interaction: discord.Interaction,
        question: str,
        option1: str,
        option2: str,
        option3: str | None = None,
        option4: str | None = None,
        option5: str | None = None,
        option6: str | None = None,
        option7: str | None = None,
        option8: str | None = None,
        option9: str | None = None,
        option10: str | None = None,
        duration_minutes: app_commands.Range[int, 1, 525600] = 1440,
    ) -> None:
        guild = interaction.guild
        channel = interaction.channel
        assert guild is not None
        question = " ".join(question.split())
        if not question:
            await interaction.response.send_message("A pergunta da enquete não pode estar vazia.", ephemeral=True)
            return
        if len(question) > 2000:
            await interaction.response.send_message("A pergunta da enquete deve ter no máximo 2000 caracteres.", ephemeral=True)
            return
        if duration_minutes < 1 or duration_minutes > 525600:
            await interaction.response.send_message("A duração deve estar entre 1 e 525600 minutos.", ephemeral=True)
            return
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("Este comando precisa ser usado em um canal de texto ou thread.", ephemeral=True)
            return
        try:
            parsed = validate_poll_options([option1, option2, option3, option4, option5, option6, option7, option8, option9, option10])
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        now = utc_now()
        try:
            async with session_factory() as session:
                row = Poll(guild_id=guild.id, channel_id=channel.id, question=question[:2000], options=parsed, ends_at=now + timedelta(minutes=duration_minutes), status="active", message_id=None, created_at=now, updated_at=now)
                session.add(row)
                await session.flush()
                poll_record_id = row.id
                page = embed("BN / ENQUETE", question[:4000], "community")
                rows = [f"**{index + 1}.** {option} · `0`" for index, option in enumerate(parsed)]
                add_line_fields(page, f"Opções · {len(parsed)}", rows)
                page.add_field(name="Votos", value="Nenhum voto ainda.", inline=False)
                page.set_footer(text=f"BN Bot · votação · termina {discord.utils.format_dt(row.ends_at, 'R')}")
                message = None
                try:
                    message = await channel.send(embed=page, view=PollView(self, row.id, parsed))
                    row.message_id = message.id
                    await session.commit()
                except Exception:
                    await session.rollback()
                    if message is not None:
                        try:
                            await message.delete()
                        except discord.HTTPException:
                            logger.exception("poll cleanup failed poll=%s", poll_record_id)
                    raise
        except Exception:
            logger.exception("poll creation failed guild=%s", guild.id)
            await respond(interaction, "Não foi possível criar a enquete. Verifique as permissões do canal.", ephemeral=True)
            return
        self.registered_views.add(f"poll:{row.id}")
        page = embed(f"BN / ENQUETE #{row.id}", "Enquete publicada e pronta para votos.", "community")
        page.add_field(name="Opções", value=f"`{len(parsed)}`", inline=True)
        page.add_field(name="Duração", value=discord.utils.format_dt(row.ends_at, "R"), inline=True)
        page.add_field(name="Votação", value="Escolha uma opção no painel da enquete.", inline=False)
        await respond(interaction, embed=page, ephemeral=True)

    @command_rate_limit("poll", 3)
    @poll_group.command(name="end", description="Encerra uma enquete imediatamente.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def poll_end_command(self, interaction: discord.Interaction, poll_id: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            poll_id = parse_snowflake(poll_id)
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        result = await self.finish_poll(interaction.guild, poll_id)
        if result is None:
            await interaction.followup.send("Enquete não encontrada ou já encerrada.", ephemeral=True)
            return
        counts, options = result
        total = sum(counts)
        summary = "\n".join(
            f"**{index + 1}. {option}** · `{count}` · {percent(count, total)}\n{bar(count, total, 10)}"
            for index, (option, count) in enumerate(zip(options, counts))
        )
        page = embed("BN / ENQUETE ENCERRADA", "A votação foi finalizada.", "community")
        result_rows = summary.split("\n") if summary else ["Sem votos."]
        add_line_fields(page, "Resultado", result_rows)
        page.add_field(name="Total", value=f"`{number(sum(counts))}` votos", inline=True)
        await interaction.followup.send(embed=page, ephemeral=True)

    async def poll_vote(self, interaction: discord.Interaction, poll_id: int, option_index: int) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        retry_after = await check_and_set(f"bn:poll-vote:{interaction.guild_id or 0}:{interaction.user.id}", 2)
        if retry_after is not None:
            await interaction.followup.send(f"Aguarde {retry_after}s antes de votar novamente.", ephemeral=True)
            return
        try:
            async with session_factory() as session:
                poll = await session.get(Poll, poll_id)
                if poll is None or poll.guild_id != interaction.guild_id or poll.status != "active":
                    await interaction.followup.send("Esta enquete não está disponível.", ephemeral=True)
                    return
                _, counts = await add_poll_vote(session, poll_id, interaction.user.id, option_index)
                selected_option = poll.options[option_index]
                options = list(poll.options)
                await session.commit()
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        self.schedule_message_refresh(
            f"poll:{interaction.guild_id}:{poll_id}",
            lambda: self.refresh_poll_message(interaction.guild, poll_id),
        )
        page = embed("BN / VOTO", "Seu voto foi registrado.", "community")
        page.add_field(name="Escolha", value=f"**{selected_option}**", inline=False)
        page.add_field(name="Total", value=f"`{number(sum(counts))}` votos", inline=True)
        distribution_rows = [f"{index + 1}. {option} · `{count}` · {percent(count, sum(counts))}" for index, (option, count) in enumerate(zip(options, counts))]
        add_line_fields(page, "Distribuição", distribution_rows)
        await interaction.followup.send(embed=page, ephemeral=True)

    async def finish_poll(self, guild: discord.Guild | None, poll_id: int):
        if guild is None:
            return None
        async with session_factory() as session:
            row = await session.get(Poll, poll_id)
            if row is None or row.guild_id != guild.id or row.status != "active":
                return None
            try:
                counts = await end_poll(session, poll_id)
            except ValueError:
                await session.rollback()
                return None
            options = list(row.options)
            message_id = row.message_id
            channel_id = row.channel_id
            question = row.question
            await session.commit()
        channel = guild.get_channel(channel_id)
        if channel is None and hasattr(guild, "get_thread"):
            channel = guild.get_thread(channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread)) and message_id:
            try:
                message = await channel.fetch_message(message_id)
                result_text = "\n".join(f"**{index + 1}. {option}** · `{count}`" for index, (option, count) in enumerate(zip(options, counts)))
                page = embed("BN / ENQUETE ENCERRADA", question[:4000], "community")
                add_line_fields(page, "Resultados", result_text.split("\n") if result_text else ["Sem votos."])
                page.add_field(name="Total", value=f"`{number(sum(counts))}` votos", inline=True)
                page.add_field(name="Status", value="`encerrada`", inline=True)
                await message.edit(embed=page, view=None)
            except discord.HTTPException:
                logger.exception("poll result publication failed poll=%s", poll_id)
        return counts, options

    @app_commands.command(name="community-config", description="Configura os canais dos recursos comunitários.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def community_config(self, interaction: discord.Interaction, suggestion_channel_id: str = "", report_channel_id: str = "") -> None:
        guild = interaction.guild
        assert guild is not None
        try:
            suggestion = parse_snowflake(suggestion_channel_id) if suggestion_channel_id.strip() else None
            report = parse_snowflake(report_channel_id) if report_channel_id.strip() else None
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await defer(interaction, ephemeral=True)
        for channel_id, label in ((suggestion, "sugestões"), (report, "denúncias")):
            if channel_id is not None and not isinstance(guild.get_channel(channel_id), discord.TextChannel):
                await respond(interaction, f"O canal de {label} não existe neste servidor.", ephemeral=True)
                return
        async with session_factory() as session:
            settings = await session.get(GuildSettings, guild.id)
            if settings is None:
                await respond(interaction, "As configurações do servidor ainda não foram inicializadas.", ephemeral=True)
                return
            config = dict(settings.config or {})
            community_config = dict(config.get("community", {}))
            community_config.update({"suggestion_channel_id": suggestion, "report_channel_id": report})
            config["community"] = community_config
            settings.config = config
            settings.updated_at = utc_now()
            await session.commit()
        page = embed("BN / COMUNIDADE", "Canais de operação atualizados.", "community")
        page.add_field(name="Sugestões", value=f"<#{suggestion}>" if suggestion else "Canal atual", inline=True)
        page.add_field(name="Denúncias", value=f"<#{report}>" if report else "Não configurado", inline=True)
        await respond(interaction, embed=page, ephemeral=True)

    async def expire_community(self) -> None:
        guilds = list(self.bot.guilds)
        for guild in guilds:
            async with session_factory() as session:
                giveaway_ids = list((await session.execute(select(Giveaway.id).where(Giveaway.guild_id == guild.id, Giveaway.status == "active", Giveaway.ends_at <= utc_now()).limit(20))).scalars())
                poll_ids = list((await session.execute(select(Poll.id).where(Poll.guild_id == guild.id, Poll.status == "active", Poll.ends_at <= utc_now()).limit(20))).scalars())
            for giveaway_id in giveaway_ids:
                await self.finish_giveaway(guild, giveaway_id)
            for poll_id in poll_ids:
                await self.finish_poll(guild, poll_id)
