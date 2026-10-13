from __future__ import annotations
import asyncio
import json
import logging
import secrets
import time
from datetime import timedelta
from dataclasses import dataclass
from typing import Any
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.core.time import utc_now
from app.core.validation import parse_snowflake
from app.models import AuditLog, AutoModEvent, AutoModListEntry, AutoModRule, GuildSettings
from app.services.automod import ACTIONS, DEFAULT_RULES, ENTRY_TYPES, LIST_TYPES, RULE_TYPES, AttachmentInfo, MessageContext, RuleDefinition, collect_activity, evaluate_rules, validate_rule_config
from app.services.moderation import add_warning, record_punishment
from app.discord.theme import embed, number, status_line, bar

logger = logging.getLogger("bn_bot.automod")
automod_group = app_commands.Group(name="automod", description="Proteção automática do BN Bot.", default_permissions=discord.Permissions(manage_guild=True))

RULE_TYPE_CHOICES = [
    app_commands.Choice(name="Spam", value="spam"),
    app_commands.Choice(name="Flood", value="flood"),
    app_commands.Choice(name="Duplicadas", value="duplicate"),
    app_commands.Choice(name="Similaridade", value="similarity"),
    app_commands.Choice(name="Links", value="link"),
    app_commands.Choice(name="Convites", value="invite"),
    app_commands.Choice(name="Palavras proibidas", value="forbidden_word"),
    app_commands.Choice(name="Caps", value="caps"),
    app_commands.Choice(name="Menções", value="mentions"),
    app_commands.Choice(name="Arquivos", value="attachments"),
    app_commands.Choice(name="Comportamento suspeito", value="suspicious"),
]
ACTION_CHOICES = [
    app_commands.Choice(name="Nenhuma", value="none"),
    app_commands.Choice(name="Apagar", value="delete"),
    app_commands.Choice(name="Warn", value="warn"),
    app_commands.Choice(name="Timeout", value="timeout"),
    app_commands.Choice(name="Expulsar", value="kick"),
    app_commands.Choice(name="Banir", value="ban"),
]
LIST_TYPE_CHOICES = [
    app_commands.Choice(name="Whitelist", value="whitelist"),
    app_commands.Choice(name="Blacklist", value="blacklist"),
]
ENTRY_TYPE_CHOICES = [
    app_commands.Choice(name="Usuário", value="user"),
    app_commands.Choice(name="Canal", value="channel"),
    app_commands.Choice(name="Cargo", value="role"),
    app_commands.Choice(name="Palavra", value="word"),
    app_commands.Choice(name="Domínio", value="domain"),
]
BLACKLIST_ACTION_CHOICES = [choice for choice in ACTION_CHOICES if choice.value != "none"]


def _parse_ids(value: str | None, limit: int = 50) -> set[int]:
    if not value:
        return set()
    result: set[int] = set()
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        result.add(parse_snowflake(part))
        if len(result) > limit:
            raise ValueError(f"informe no máximo {limit} IDs")
    return result


def _rule_definition(row: AutoModRule) -> RuleDefinition:
    return RuleDefinition(id=row.id, name=row.name, rule_type=row.rule_type, action=row.action, enabled=row.enabled, priority=row.priority, channels=set(row.channel_ids or []), roles=set(row.role_ids or []), config=dict(row.config or {}))


def _rule_badge(row: AutoModRule) -> str:
    state = "ATIVA" if row.enabled else "PAUSADA"
    return f"`#{row.id}` · **{row.name[:32]}** · {state} · {row.rule_type} para {row.action}"


AUTOMOD_CACHE_TTL = 15.0
ACTIVITY_RULE_TYPES = {"spam", "flood", "duplicate", "similarity", "suspicious"}


@dataclass(frozen=True, slots=True)
class AutoModRuleSnapshot:
    id: int
    name: str
    rule_type: str
    action: str
    enabled: bool
    priority: int
    channel_ids: tuple[int, ...]
    role_ids: tuple[int, ...]
    config: dict[str, Any]


class AutoModCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._cache: dict[int, tuple[float, bool, str, tuple[RuleDefinition, ...], tuple[dict[str, str], ...], tuple[dict[str, str], ...], tuple[AutoModRuleSnapshot, ...]]] = {}
        self._cache_locks: dict[int, asyncio.Lock] = {}
        self._cache_locks_guard = asyncio.Lock()

    async def audit(self, guild_id: int, executor_id: int, action: str, resource: str, before: dict[str, Any] | None = None, after: dict[str, Any] | None = None) -> None:
        try:
            async with session_factory() as session:
                session.add(AuditLog(id=secrets.randbits(62), guild_id=guild_id, executor_id=executor_id, action=action, resource=resource, before_state=before, after_state=after, created_at=utc_now()))
                await session.commit()
        except Exception:
            logger.exception("audit persistence failed action=%s resource=%s", action, resource)

    async def invalidate_cache(self, guild_id: int) -> None:
        self._cache.pop(guild_id, None)

    async def _guild_cache_lock(self, guild_id: int) -> asyncio.Lock:
        async with self._cache_locks_guard:
            return self._cache_locks.setdefault(guild_id, asyncio.Lock())

    async def _load_cache(self, guild_id: int) -> tuple[bool, str, tuple[RuleDefinition, ...], tuple[dict[str, str], ...], tuple[dict[str, str], ...], tuple[AutoModRuleSnapshot, ...]]:
        cached = self._cache.get(guild_id)
        if cached is not None and time.monotonic() - cached[0] < AUTOMOD_CACHE_TTL:
            return cached[1:]
        cache_lock = await self._guild_cache_lock(guild_id)
        async with cache_lock:
            cached = self._cache.get(guild_id)
            if cached is not None and time.monotonic() - cached[0] < AUTOMOD_CACHE_TTL:
                return cached[1:]
            async with session_factory() as session:
                settings = await session.get(GuildSettings, guild_id)
                if settings is None or not settings.automod_enabled:
                    value = (False, "delete", tuple(), tuple(), tuple(), tuple())
                    self._cache[guild_id] = (time.monotonic(), *value)
                    return value
                rule_rows = list((await session.execute(select(AutoModRule).where(AutoModRule.guild_id == guild_id, AutoModRule.enabled.is_(True)).order_by(AutoModRule.priority.desc(), AutoModRule.id.asc()))).scalars())
                entries_rows = list((await session.execute(select(AutoModListEntry).where(AutoModListEntry.guild_id == guild_id))).scalars())
            rules: list[RuleDefinition] = []
            snapshots: list[AutoModRuleSnapshot] = []
            for row in rule_rows:
                config = dict(row.config or {})
                config_errors = validate_rule_config(row.rule_type, config)
                if config_errors:
                    logger.error("invalid AutoMod rule config skipped guild=%s rule=%s errors=%s", guild_id, row.id, " | ".join(config_errors[:4]))
                    continue
                rules.append(_rule_definition(row))
                snapshots.append(AutoModRuleSnapshot(id=row.id, name=row.name, rule_type=row.rule_type, action=row.action, enabled=row.enabled, priority=row.priority, channel_ids=tuple(row.channel_ids or []), role_ids=tuple(row.role_ids or []), config=config))
            whitelist = tuple(dict(list_type=row.list_type, entry_type=row.entry_type, value=row.value) for row in entries_rows if row.list_type == "whitelist")
            blacklist = tuple(dict(list_type=row.list_type, entry_type=row.entry_type, value=row.value) for row in entries_rows if row.list_type == "blacklist")
            automod_config = dict((settings.config or {}).get("automod", {}))
            blacklist_action = str(automod_config.get("blacklist_action", "delete"))
            value = (True, blacklist_action, tuple(rules), whitelist, blacklist, tuple(snapshots))
            self._cache[guild_id] = (time.monotonic(), *value)
            return value

    async def evaluate(self, message: discord.Message) -> tuple[Any, list[AutoModRuleSnapshot]]:
        enabled, blacklist_action, rules, whitelist, blacklist, snapshots = await self._load_cache(message.guild.id)
        if not enabled or not rules:
            return None, []
        role_ids = {role.id for role in getattr(message.author, "roles", [])}
        created_at = message.author.created_at
        joined_at = message.author.joined_at if isinstance(message.author, discord.Member) else None
        now = utc_now()
        context = MessageContext(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            user_id=message.author.id,
            message_id=message.id,
            role_ids=role_ids,
            content=message.content,
            mention_count=len(message.mentions) + (1 if message.mention_everyone else 0),
            role_mention_count=len(message.role_mentions),
            attachments=[AttachmentInfo(filename=item.filename, size=item.size) for item in message.attachments],
            author_age_seconds=max(int((now - created_at).total_seconds()), 0) if created_at else None,
            member_age_seconds=max(int((now - joined_at).total_seconds()), 0) if joined_at else None,
        )
        if any(rule.rule_type in ACTIVITY_RULE_TYPES for rule in rules):
            context = await collect_activity(context)
        evaluation = evaluate_rules(rules, context, list(whitelist), list(blacklist), blacklist_action)
        return evaluation, list(snapshots)

    async def on_message_event(self, message: discord.Message) -> bool:
        if message.guild is None or message.author.bot:
            return False
        try:
            evaluation, rows = await self.evaluate(message)
        except Exception:
            logger.exception("automod evaluation failed guild=%s channel=%s message=%s", message.guild.id, message.channel.id, message.id)
            return False
        if not evaluation or not evaluation.matched:
            return False
        selected = evaluation.rule
        selected_row = next((row for row in rows if selected and row.id == selected.id), None)
        primary = evaluation.matched[0]
        action = evaluation.action
        data = {"detections": [{"rule_type": item.rule_type, "severity": item.severity, "reason": item.reason, "metadata": item.metadata} for item in evaluation.matched]}
        try:
            await self.execute_action(message, action, primary.reason, selected_row.config if selected_row else {})
        except Exception:
            logger.exception("automod action failed guild=%s channel=%s message=%s action=%s", message.guild.id, message.channel.id, message.id, action)
            return False
        try:
            async with session_factory() as session:
                event_id = secrets.randbits(62)
                session.add(AutoModEvent(id=event_id, guild_id=message.guild.id, channel_id=message.channel.id, user_id=message.author.id, message_id=message.id, rule_id=selected_row.id if selected_row else None, rule_type=primary.rule_type, action=action, reason=primary.reason, data=data, created_at=utc_now()))
                await session.commit()
        except Exception:
            logger.exception("automod event persistence failed guild=%s channel=%s message=%s action=%s", message.guild.id, message.channel.id, message.id, action)
        return action != "none"

    async def execute_action(self, message: discord.Message, action: str, reason: str, config: dict[str, Any]) -> None:
        if action == "none":
            return
        if action == "delete":
            await message.delete()
            return
        if action == "warn":
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            async with session_factory() as session:
                await add_warning(session, message.guild.id, message.author.id, self.bot.user.id if self.bot.user else 0, f"AutoMod: {reason}")
            return
        if action == "timeout":
            duration = max(min(int(config.get("timeout_seconds", 600)), 2_419_200), 1)
            member = message.author if isinstance(message.author, discord.Member) else None
            if member is None:
                raise ValidationFailure("Não foi possível aplicar timeout neste autor.")
            await member.timeout(timedelta(seconds=duration), reason=f"BN Bot AutoMod: {reason}")
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            async with session_factory() as session:
                await record_punishment(session, message.guild.id, member.id, self.bot.user.id if self.bot.user else 0, "timeout", f"AutoMod: {reason}", utc_now() + timedelta(seconds=duration), {"duration_seconds": duration, "source": "automod"})
            return
        if action == "kick":
            member = message.author if isinstance(message.author, discord.Member) else None
            if member:
                await member.kick(reason=f"BN Bot AutoMod: {reason}")
                async with session_factory() as session:
                    await record_punishment(session, message.guild.id, member.id, self.bot.user.id if self.bot.user else 0, "kick", f"AutoMod: {reason}", None, {"source": "automod"})
            return
        if action == "ban":
            member = message.author if isinstance(message.author, discord.Member) else None
            if member:
                await member.ban(reason=f"BN Bot AutoMod: {reason}", delete_message_seconds=0)
                async with session_factory() as session:
                    await record_punishment(session, message.guild.id, member.id, self.bot.user.id if self.bot.user else 0, "ban", f"AutoMod: {reason}", None, {"source": "automod"})

    @automod_group.command(name="enable", description="Ativa o AutoMod no servidor.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def enable(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            settings = await session.get(GuildSettings, interaction.guild.id)
            if settings is None:
                settings = GuildSettings(guild_id=interaction.guild.id, timezone="UTC", locale="pt-BR", economy_enabled=True, levels_enabled=True, analytics_enabled=True, automod_enabled=True, config={}, created_at=utc_now(), updated_at=utc_now())
                session.add(settings)
            else:
                settings.automod_enabled = True
                settings.updated_at = utc_now()
            await session.commit()
        await self.invalidate_cache(interaction.guild.id)
        await self.audit(interaction.guild.id, interaction.user.id, "automod.enable", "settings", None, {"enabled": True})
        page = embed("BN / AUTOMOD", "A proteção automática está em operação.", "security")
        page.add_field(name="Estado", value=status_line("AutoMod", "ativo", "active"), inline=False)
        await respond(interaction, embed=page)

    @automod_group.command(name="disable", description="Desativa o AutoMod no servidor.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            settings = await session.get(GuildSettings, interaction.guild.id)
            if settings is None:
                await respond(interaction, "As configurações do servidor ainda não existem.", ephemeral=True)
                return
            settings.automod_enabled = False
            settings.updated_at = utc_now()
            await session.commit()
        await self.invalidate_cache(interaction.guild.id)
        await self.audit(interaction.guild.id, interaction.user.id, "automod.disable", "settings", {"enabled": True}, {"enabled": False})
        page = embed("BN / AUTOMOD", "A proteção automática foi pausada.", "security")
        page.add_field(name="Estado", value=status_line("AutoMod", "desativado", "closed"), inline=False)
        await respond(interaction, embed=page)

    @automod_group.command(name="setup", description="Cria a configuração inicial completa do AutoMod.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            settings = await session.get(GuildSettings, interaction.guild.id)
            if settings is None:
                settings = GuildSettings(guild_id=interaction.guild.id, timezone="UTC", locale="pt-BR", economy_enabled=True, levels_enabled=True, analytics_enabled=True, automod_enabled=True, config={"automod": {"blacklist_action": "delete"}}, created_at=utc_now(), updated_at=utc_now())
                session.add(settings)
            else:
                settings.automod_enabled = True
                config = dict(settings.config or {})
                automod_config = dict(config.get("automod", {}))
                automod_config.setdefault("blacklist_action", "delete")
                config["automod"] = automod_config
                settings.config = config
                settings.updated_at = utc_now()
            existing_rows = list((await session.execute(select(AutoModRule).where(AutoModRule.guild_id == interaction.guild.id))).scalars())
            existing_names = {row.name.casefold() for row in existing_rows}
            created = 0
            for definition in DEFAULT_RULES:
                if definition["name"].casefold() in existing_names:
                    continue
                session.add(AutoModRule(guild_id=interaction.guild.id, name=definition["name"], rule_type=definition["rule_type"], action=definition["action"], enabled=True, priority=definition["priority"], channel_ids=[], role_ids=[], config=definition["config"], created_at=utc_now(), updated_at=utc_now()))
                created += 1
            await session.commit()
        await self.invalidate_cache(interaction.guild.id)
        await self.audit(interaction.guild.id, interaction.user.id, "automod.setup", "rules", None, {"created": created})
        page = embed("BN / AUTOMOD PRONTO", "O perfil inicial foi aplicado sem apagar regras existentes.", "security")
        page.add_field(name="Regras novas", value=f"`{created}`", inline=True)
        page.add_field(name="Perfil", value="proteção base", inline=True)
        await respond(interaction, embed=page)

    @automod_group.command(name="rule-add", description="Cria uma regra AutoMod com configuração JSON.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(rule_type=RULE_TYPE_CHOICES, action=ACTION_CHOICES)
    @app_commands.describe(name="Nome da regra", rule_type="Tipo de detecção", action="Ação quando detectar", config_json="Objeto JSON da configuração", priority="Prioridade de 0 a 10000", channels="IDs de canais separados por vírgula", roles="IDs de cargos separados por vírgula")
    async def rule_add(self, interaction: discord.Interaction, name: str, rule_type: str, action: str, config_json: str = "{}", priority: int = 0, channels: str | None = None, roles: str | None = None) -> None:
        await defer(interaction, ephemeral=True)
        name = " ".join(name.split())
        if not name or len(name) > 100:
            await respond(interaction, "O nome da regra deve ter entre 1 e 100 caracteres.", ephemeral=True)
            return
        if rule_type not in RULE_TYPES:
            await respond(interaction, "Tipo de regra inválido.", ephemeral=True)
            return
        if action not in ACTIONS:
            await respond(interaction, "Ação inválida.", ephemeral=True)
            return
        if priority < -10000 or priority > 10000:
            await respond(interaction, "A prioridade deve estar entre -10000 e 10000.", ephemeral=True)
            return
        try:
            config = json.loads(config_json)
        except json.JSONDecodeError:
            await respond(interaction, "config_json precisa conter JSON válido.", ephemeral=True)
            return
        if not isinstance(config, dict):
            await respond(interaction, "config_json precisa ser um objeto JSON.", ephemeral=True)
            return
        config_errors = validate_rule_config(rule_type, config)
        if config_errors:
            await respond(interaction, "Configuração inválida: " + "; ".join(config_errors), ephemeral=True)
            return
        try:
            channel_ids = sorted(_parse_ids(channels))
            role_ids = sorted(_parse_ids(roles))
        except ValueError as exc:
            await respond(interaction, str(exc), ephemeral=True)
            return
        async with session_factory() as session:
            existing = await session.scalar(select(AutoModRule.id).where(AutoModRule.guild_id == interaction.guild.id, func.lower(AutoModRule.name) == name.casefold()).limit(1))
            if existing is not None:
                await respond(interaction, "Já existe uma regra com esse nome.", ephemeral=True)
                return
            row = AutoModRule(guild_id=interaction.guild.id, name=name, rule_type=rule_type, action=action, enabled=True, priority=priority, channel_ids=channel_ids, role_ids=role_ids, config=config, created_at=utc_now(), updated_at=utc_now())
            session.add(row)
            try:
                await session.flush()
                rule_id = row.id
                await session.commit()
                await self.invalidate_cache(interaction.guild.id)
            except IntegrityError:
                await session.rollback()
                await respond(interaction, "A regra não pôde ser criada porque já existe uma regra com esse nome.", ephemeral=True)
                return
        await self.audit(interaction.guild.id, interaction.user.id, "automod.rule_create", f"rule:{rule_id}", None, {"name": name, "rule_type": rule_type, "action": action, "priority": priority, "channels": channel_ids, "roles": role_ids, "config": config})
        page = embed("BN / REGRA CRIADA", f"**{name}** entrou no conjunto de proteção.", "security")
        page.add_field(name="ID", value=f"`{rule_id}`", inline=True)
        page.add_field(name="Detecção", value=f"`{rule_type}`", inline=True)
        page.add_field(name="Ação", value=f"`{action}`", inline=True)
        page.add_field(name="Prioridade", value=f"`{priority}`", inline=True)
        await respond(interaction, embed=page)

    @automod_group.command(name="rule-update", description="Atualiza ação, configuração, prioridade e escopo de uma regra.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(action=ACTION_CHOICES)
    async def rule_update(self, interaction: discord.Interaction, rule_id: int, action: str | None = None, config_json: str | None = None, priority: int | None = None, channels: str | None = None, roles: str | None = None, enabled: bool | None = None) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            row = await session.get(AutoModRule, rule_id)
            if row is None or row.guild_id != interaction.guild.id:
                await respond(interaction, "Regra não encontrada.", ephemeral=True)
                return
            if action is not None:
                if action not in ACTIONS:
                    await respond(interaction, "Ação inválida.", ephemeral=True)
                    return
                row.action = action
            if config_json is not None:
                try:
                    config = json.loads(config_json)
                except json.JSONDecodeError:
                    await respond(interaction, "config_json precisa conter JSON válido.", ephemeral=True)
                    return
                if not isinstance(config, dict):
                    await respond(interaction, "config_json precisa ser um objeto JSON.", ephemeral=True)
                    return
                config_errors = validate_rule_config(row.rule_type, config)
                if config_errors:
                    await respond(interaction, "Configuração inválida: " + "; ".join(config_errors), ephemeral=True)
                    return
                row.config = config
            if priority is not None:
                if priority < -10000 or priority > 10000:
                    await respond(interaction, "A prioridade deve estar entre -10000 e 10000.", ephemeral=True)
                    return
                row.priority = priority
            try:
                if channels is not None:
                    row.channel_ids = sorted(_parse_ids(channels))
                if roles is not None:
                    row.role_ids = sorted(_parse_ids(roles))
            except ValueError as exc:
                await respond(interaction, str(exc), ephemeral=True)
                return
            if enabled is not None:
                row.enabled = enabled
            row.updated_at = utc_now()
            await session.commit()
            await self.invalidate_cache(interaction.guild.id)
            snapshot = {"action": row.action, "enabled": row.enabled, "priority": row.priority, "channels": row.channel_ids, "roles": row.role_ids, "config": row.config}
        await self.audit(interaction.guild.id, interaction.user.id, "automod.rule_update", f"rule:{rule_id}", None, snapshot)
        page = embed("BN / REGRA ATUALIZADA", f"A regra `#{rule_id}` foi salva.", "security")
        page.add_field(name="Estado", value=status_line("Regra", "ativa" if snapshot["enabled"] else "pausada", "active" if snapshot["enabled"] else "closed"), inline=True)
        page.add_field(name="Ação", value=f"`{snapshot['action']}`", inline=True)
        page.add_field(name="Prioridade", value=f"`{snapshot['priority']}`", inline=True)
        await respond(interaction, embed=page)

    @automod_group.command(name="rule-delete", description="Remove uma regra AutoMod.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rule_delete(self, interaction: discord.Interaction, rule_id: int) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            row = await session.get(AutoModRule, rule_id)
            if row is None or row.guild_id != interaction.guild.id:
                await respond(interaction, "Regra não encontrada.", ephemeral=True)
                return
            name = row.name
            await session.delete(row)
            await session.commit()
        await self.invalidate_cache(interaction.guild.id)
        await self.audit(interaction.guild.id, interaction.user.id, "automod.rule_delete", f"rule:{rule_id}")
        page = embed("BN / REGRA REMOVIDA", f"**{name}** deixou de fazer parte do AutoMod.", "security")
        page.add_field(name="ID", value=f"`{rule_id}`", inline=False)
        await respond(interaction, embed=page)

    @automod_group.command(name="rules", description="Lista as regras AutoMod do servidor.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def rules(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            rows = list((await session.execute(select(AutoModRule).where(AutoModRule.guild_id == interaction.guild.id).order_by(AutoModRule.priority.desc(), AutoModRule.id.asc()))).scalars())
        page = embed("BN / REGRAS", "Painel resumido do conjunto de regras.", "security")
        if not rows:
            page.add_field(name="Conjunto vazio", value="Use `/automod rule-add` ou `/automod setup` para começar.", inline=False)
        else:
            active = sum(row.enabled for row in rows)
            lines = [_rule_badge(row) for row in rows[:15]]
            page.add_field(name=f"Regras · {number(len(rows))}", value="\n".join(lines)[:1024], inline=False)
            page.add_field(name="Ativas", value=f"`{active}` · {bar(active, len(rows))}", inline=False)
        await respond(interaction, embed=page, ephemeral=True)

    @automod_group.command(name="list-action", description="Define a ação aplicada quando a blacklist corresponder.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(action=BLACKLIST_ACTION_CHOICES)
    async def list_action(self, interaction: discord.Interaction, action: str) -> None:
        await defer(interaction, ephemeral=True)
        if action not in ACTIONS - {"none"}:
            await respond(interaction, "Ação inválida.", ephemeral=True)
            return
        async with session_factory() as session:
            settings = await session.get(GuildSettings, interaction.guild.id)
            if settings is None:
                settings = GuildSettings(guild_id=interaction.guild.id, timezone="UTC", locale="pt-BR", economy_enabled=True, levels_enabled=True, analytics_enabled=True, automod_enabled=True, config={"automod": {"blacklist_action": action}}, created_at=utc_now(), updated_at=utc_now())
                session.add(settings)
            else:
                config = dict(settings.config or {})
                automod_config = dict(config.get("automod", {}))
                automod_config["blacklist_action"] = action
                config["automod"] = automod_config
                settings.config = config
                settings.updated_at = utc_now()
            await session.commit()
        await self.invalidate_cache(interaction.guild.id)
        await self.audit(interaction.guild.id, interaction.user.id, "automod.blacklist_action", "settings", None, {"action": action})
        page = embed("BN / BLACKLIST", "A ação padrão foi alterada.", "security")
        page.add_field(name="Quando corresponder", value=f"`{action}`", inline=True)
        await respond(interaction, embed=page)

    @automod_group.command(name="list-add", description="Adiciona uma entrada à whitelist ou blacklist.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(list_type=LIST_TYPE_CHOICES, entry_type=ENTRY_TYPE_CHOICES)
    async def list_add(self, interaction: discord.Interaction, list_type: str, entry_type: str, value: str, reason: str | None = None) -> None:
        await defer(interaction, ephemeral=True)
        if list_type not in LIST_TYPES or entry_type not in ENTRY_TYPES:
            await respond(interaction, "Lista ou tipo de entrada inválido.", ephemeral=True)
            return
        value = value.strip().casefold() if entry_type in {"domain", "word"} else value.strip()
        if not value or len(value) > 200:
            await respond(interaction, "O valor deve ter entre 1 e 200 caracteres.", ephemeral=True)
            return
        if entry_type in {"user", "channel", "role"}:
            try:
                value = str(parse_snowflake(value))
            except ValueError as exc:
                await respond(interaction, str(exc), ephemeral=True)
                return
        async with session_factory() as session:
            exists = await session.scalar(select(AutoModListEntry.id).where(AutoModListEntry.guild_id == interaction.guild.id, AutoModListEntry.list_type == list_type, AutoModListEntry.entry_type == entry_type, AutoModListEntry.value == value).limit(1))
            if exists is not None:
                await respond(interaction, "Essa entrada já existe.", ephemeral=True)
                return
            session.add(AutoModListEntry(guild_id=interaction.guild.id, list_type=list_type, entry_type=entry_type, value=value, reason=reason[:500] if reason else None, created_at=utc_now(), updated_at=utc_now()))
            try:
                await session.commit()
                await self.invalidate_cache(interaction.guild.id)
            except IntegrityError:
                await session.rollback()
                await respond(interaction, "Essa entrada já existe.", ephemeral=True)
                return
        await self.audit(interaction.guild.id, interaction.user.id, "automod.list_add", f"{list_type}:{entry_type}:{value}", None, {"reason": reason})
        page = embed("BN / LISTA ATUALIZADA", "Nova entrada aplicada ao AutoMod.", "security")
        page.add_field(name="Lista", value=f"`{list_type}`", inline=True)
        page.add_field(name="Tipo", value=f"`{entry_type}`", inline=True)
        page.add_field(name="Valor", value=f"`{value}`", inline=False)
        await respond(interaction, embed=page)

    @automod_group.command(name="lists", description="Lista as entradas de whitelist e blacklist.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def lists(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            rows = list((await session.execute(select(AutoModListEntry).where(AutoModListEntry.guild_id == interaction.guild.id).order_by(AutoModListEntry.list_type.asc(), AutoModListEntry.entry_type.asc(), AutoModListEntry.value.asc()))).scalars())
        page = embed("BN / LISTAS", "Whitelist e blacklist em uma leitura compacta.", "security")
        if not rows:
            page.add_field(name="Listas vazias", value="Nenhuma exceção ou bloqueio cadastrado.", inline=False)
        else:
            whitelist = sum(row.list_type == "whitelist" for row in rows)
            blacklist = len(rows) - whitelist
            lines = [f"`{row.list_type}` · `{row.entry_type}` · `{row.value[:80]}`" for row in rows[:20]]
            page.add_field(name=f"Entradas · {number(len(rows))}", value="\n".join(lines)[:1024], inline=False)
            page.add_field(name="Distribuição", value=f"Whitelist `{whitelist}` · Blacklist `{blacklist}`", inline=False)
        await respond(interaction, embed=page, ephemeral=True)

    @automod_group.command(name="list-remove", description="Remove uma entrada da whitelist ou blacklist.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(list_type=LIST_TYPE_CHOICES, entry_type=ENTRY_TYPE_CHOICES)
    async def list_remove(self, interaction: discord.Interaction, list_type: str, entry_type: str, value: str) -> None:
        await defer(interaction, ephemeral=True)
        if list_type not in LIST_TYPES or entry_type not in ENTRY_TYPES:
            await respond(interaction, "Lista ou tipo de entrada inválido.", ephemeral=True)
            return
        normalized = value.strip().casefold() if entry_type in {"domain", "word"} else value.strip()
        if entry_type in {"user", "channel", "role"}:
            try:
                normalized = str(parse_snowflake(normalized))
            except ValueError as exc:
                await respond(interaction, str(exc), ephemeral=True)
                return
        async with session_factory() as session:
            row = await session.scalar(select(AutoModListEntry).where(AutoModListEntry.guild_id == interaction.guild.id, AutoModListEntry.list_type == list_type, AutoModListEntry.entry_type == entry_type, AutoModListEntry.value == normalized))
            if row is None:
                await respond(interaction, "Entrada não encontrada.", ephemeral=True)
                return
            await session.delete(row)
            await session.commit()
        await self.invalidate_cache(interaction.guild.id)
        await self.audit(interaction.guild.id, interaction.user.id, "automod.list_remove", f"{list_type}:{entry_type}:{normalized}")
        page = embed("BN / LISTA LIMPA", "A entrada foi removida.", "security")
        page.add_field(name="Valor", value=f"`{normalized}`", inline=False)
        await respond(interaction, embed=page)

    @automod_group.command(name="status", description="Mostra o estado do AutoMod.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        await defer(interaction, ephemeral=True)
        async with session_factory() as session:
            settings = await session.get(GuildSettings, interaction.guild.id)
            count = await session.scalar(select(func.count(AutoModRule.id)).where(AutoModRule.guild_id == interaction.guild.id))
            active = await session.scalar(select(func.count(AutoModRule.id)).where(AutoModRule.guild_id == interaction.guild.id, AutoModRule.enabled.is_(True)))
        enabled = settings.automod_enabled if settings else False
        page = embed("BN / AUTOMOD", "Leitura operacional da proteção automática.", "security")
        page.add_field(name="Estado", value=status_line("AutoMod", "ativo" if enabled else "desativado", "active" if enabled else "closed"), inline=True)
        page.add_field(name="Regras", value=f"`{number(int(active or 0))}` / `{number(int(count or 0))}`", inline=True)
        page.add_field(name="Cobertura", value=f"{bar(int(active or 0), int(count or 0))}\n`{int(active or 0)}/{int(count or 0)}` ativas", inline=False)
        await respond(interaction, embed=page, ephemeral=True)


def add_to_tree(bot: commands.Bot, binding: commands.Cog | None = None) -> None:
    if binding is not None:
        for command in list(automod_group.commands):
            if getattr(command, "binding", None) is binding:
                continue
            bound = command._copy_with(parent=automod_group, binding=binding)
            automod_group.remove_command(command.name)
            automod_group.add_command(bound)
    if bot.tree.get_command(automod_group.name) is None:
        bot.tree.add_command(automod_group)
