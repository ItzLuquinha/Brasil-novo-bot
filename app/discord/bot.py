import asyncio
import logging
import discord
from urllib.parse import urlencode
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from discord.ext import commands
from app.config import get_settings
from app.core.db import session_factory
from app.core.time import utc_now
from app.models import AnalyticsConfig, Guild, GuildSettings, Member
from app.repositories.analytics import analytics_message_allowed, record_command_usage, record_message, record_voice_segment
from app.repositories.guilds import ensure_guild, ensure_user, ensure_member
from app.services.cooldowns import check_and_set
from app.services.rate_limits import RateLimitExceeded
from app.services.levels import add_xp
from app.services.analytics import floor_hour, record_guild_metric, voice_is_eligible

logger = logging.getLogger("bn_bot.discord")


class BNBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
        intents.messages = True
        intents.voice_states = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.tree.on_error = self.on_app_command_error
        self.tree.allowed_installs = discord.app_commands.AppInstallationType(guild=True, user=False)
        self.tree.allowed_contexts = discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False)
        self._command_sync_lock = asyncio.Lock()
        self._synced_guild_command_ids: set[int] = set()
        self._command_sync_retry_tasks: dict[str, asyncio.Task[None]] = {}
        self._voice_sessions_restored = False

    async def setup_hook(self) -> None:
        from app.discord.cogs.utility import UtilityCog
        from app.discord.cogs.fun import FunCog
        from app.discord.cogs.economy import EconomyCog
        from app.discord.cogs.progression import ProgressionCog
        from app.discord.cogs.moderation import ModerationCog
        from app.discord.cogs.community import CommunityCog
        from app.discord.cogs.automod import AutoModCog, add_to_tree as add_automod_to_tree
        from app.discord.cogs.admin import AdminCog, add_to_tree
        from app.discord.cogs.antiraid import AntiRaidCog, add_to_tree as add_antiraid_to_tree
        from app.discord.cogs.dashboard import DashboardCog
        from app.tasks.worker import Worker

        await self.add_cog(UtilityCog(self))
        await self.add_cog(FunCog(self))
        await self.add_cog(EconomyCog(self))
        await self.add_cog(ProgressionCog(self))
        await self.add_cog(ModerationCog(self))
        await self.add_cog(CommunityCog(self))
        automod_cog = AutoModCog(self)
        admin_cog = AdminCog(self)
        antiraid_cog = AntiRaidCog(self)
        await self.add_cog(admin_cog)
        await self.add_cog(antiraid_cog)
        await self.add_cog(DashboardCog(self))
        add_to_tree(self, admin_cog)
        add_automod_to_tree(self, automod_cog)
        add_antiraid_to_tree(self, antiraid_cog)
        self.worker = Worker(self)

    @staticmethod
    def _is_user_installable(command: discord.app_commands.Command | discord.app_commands.Group) -> bool:
        installs = getattr(command, "allowed_installs", None)
        return installs is not None and bool(getattr(installs, "user", False))

    async def _sync_user_installable_global_commands(self) -> None:
        global_commands = list(self.tree.get_commands())
        user_commands = [command for command in global_commands if self._is_user_installable(command)]
        remote = await self.tree.fetch_commands()
        from app.services.diagnostics import (
            _local_command_signature,
            _remote_command_signatures,
            _local_top_level_permission_signatures,
            _remote_top_level_permission_signatures,
        )

        self.tree.clear_commands(guild=None)
        try:
            for command in user_commands:
                self.tree.add_command(command)
            local = {
                command.qualified_name: _local_command_signature(command, self.tree)
                for command in self.tree.walk_commands()
                if not getattr(command, "commands", None)
            }
            remote_signatures = _remote_command_signatures(remote)
            local_permissions = _local_top_level_permission_signatures(list(self.tree.get_commands()), self.tree)
            remote_permissions = _remote_top_level_permission_signatures(remote)
            remote_user_installable = all(self._is_user_installable(command) for command in remote)
            unchanged = (
                remote_user_installable
                and set(local) == set(remote_signatures)
                and all(local[name][2] == remote_signatures[name][2] for name in local)
                and local_permissions == remote_permissions
            )
            if unchanged:
                logger.info("user-installable global slash commands unchanged count=%s", len(local))
                return
            synced = await self.tree.sync()
            repaired = await self._reconcile_remote_command_permissions(
                user_commands, synced, scope="global-user-installable"
            )
            if repaired:
                synced = await self.tree.fetch_commands()
            logger.info(
                "user-installable global slash commands synchronized count=%s permissions_repaired=%s",
                len(synced),
                repaired,
            )
        finally:
            self.tree.clear_commands(guild=None)
            for command in global_commands:
                self.tree.add_command(command)

    async def _clear_global_commands(self) -> None:
        global_commands = list(self.tree.get_commands())
        remote = await self.tree.fetch_commands()
        if not remote:
            logger.info("global slash command scope is already empty")
            return
        self.tree.clear_commands(guild=None)
        try:
            await self.tree.sync()
            logger.info("stale global slash commands removed count=%s", len(global_commands))
        finally:
            for command in global_commands:
                self.tree.add_command(command)

    @staticmethod
    def _copy_command_for_guild(command: discord.app_commands.Command | discord.app_commands.Group) -> discord.app_commands.Command | discord.app_commands.Group:
        binding = getattr(command, "binding", None)
        if isinstance(command, discord.app_commands.Group) and binding is None:
            binding = next((getattr(child, "binding", None) for child in command.walk_commands() if getattr(child, "binding", None) is not None), None)
        bindings = {binding: binding} if binding is not None else {}
        clone = command._copy_with(parent=None, binding=binding, bindings=bindings)
        for node in (clone, *clone.walk_commands()) if isinstance(clone, discord.app_commands.Group) else (clone,):
            node.allowed_contexts = None
            node.allowed_installs = None
        return clone

    @staticmethod
    async def _reconcile_remote_command_permissions(
        local_commands: list[discord.app_commands.Command | discord.app_commands.Group],
        remote_commands: list[discord.app_commands.AppCommand],
        *,
        scope: str,
    ) -> int:
        """Explicitly PATCH default permissions when bulk command sync does not persist them.

        Discord.py serializes default_member_permissions during bulk overwrite, but existing
        commands may still come back with a null value from the API. A targeted command edit
        makes the requested default permissions explicit and lets the normal post-sync verifier
        confirm the result. This does not edit per-role/user command permission overwrites.
        """
        local_by_name = {command.name: command for command in local_commands}
        repaired = 0
        for remote in remote_commands:
            local = local_by_name.get(remote.name)
            if local is None:
                continue
            desired = getattr(local, "default_permissions", None)
            remote_permissions = getattr(remote, "default_member_permissions", None)
            desired_value = None if desired is None else int(desired.value)
            remote_value = None if remote_permissions is None else int(remote_permissions.value)
            if desired_value == remote_value:
                continue
            await remote.edit(default_member_permissions=desired)
            repaired += 1
            logger.info(
                "slash command default permissions patched scope=%s command=%s previous=%s desired=%s",
                scope,
                remote.name,
                remote_value,
                desired_value,
            )
        return repaired

    async def _sync_guild_commands(self, guild_id: int) -> list[discord.app_commands.AppCommand]:
        from app.services.diagnostics import (
            _local_command_signature,
            _remote_command_signatures,
            _local_top_level_permission_signatures,
            _remote_top_level_permission_signatures,
        )

        guild_object = discord.Object(id=guild_id)
        global_commands = list(self.tree.get_commands())
        guild_commands = [command for command in global_commands if not self._is_user_installable(command)]
        guild_copies = [self._copy_command_for_guild(command) for command in guild_commands]
        self.tree.clear_commands(guild=guild_object)
        for command in guild_copies:
            self.tree.add_command(command, guild=guild_object)
        try:
            remote = await self.tree.fetch_commands(guild=guild_object)
            local = {
                command.qualified_name: _local_command_signature(command, self.tree)
                for command in self.tree.walk_commands(guild=guild_object)
                if not getattr(command, "commands", None)
            }
            remote_signatures = _remote_command_signatures(remote)
            local_permissions = _local_top_level_permission_signatures(
                list(self.tree.get_commands(guild=guild_object)), self.tree
            )
            remote_permissions = _remote_top_level_permission_signatures(remote)
            permission_stale = sorted(
                name for name in (set(local_permissions) | set(remote_permissions))
                if name not in local_permissions or name not in remote_permissions
                or local_permissions[name] != remote_permissions[name]
            )
            missing = sorted(set(local) - set(remote_signatures))
            unexpected = sorted(set(remote_signatures) - set(local))
            stale = sorted(
                name for name in set(local) & set(remote_signatures)
                if local[name][2] != remote_signatures[name][2]
            )
            if not (missing or unexpected or stale or permission_stale):
                logger.info(
                    "guild slash commands unchanged guild=%s executable=%s",
                    guild_id,
                    len(local),
                )
                return remote

            synced = await self.tree.sync(guild=guild_object)
            repaired = await self._reconcile_remote_command_permissions(
                guild_copies, synced, scope=f"guild:{guild_id}"
            )
            if repaired:
                logger.info(
                    "guild slash command default permissions repaired guild=%s count=%s",
                    guild_id,
                    repaired,
                )
            remote = await self.tree.fetch_commands(guild=guild_object)
            remote_signatures = _remote_command_signatures(remote)
            local_permissions = _local_top_level_permission_signatures(
                list(self.tree.get_commands(guild=guild_object)), self.tree
            )
            remote_permissions = _remote_top_level_permission_signatures(remote)
            permission_stale = sorted(
                name for name in (set(local_permissions) | set(remote_permissions))
                if name not in local_permissions or name not in remote_permissions
                or local_permissions[name] != remote_permissions[name]
            )
            missing = sorted(set(local) - set(remote_signatures))
            unexpected = sorted(set(remote_signatures) - set(local))
            stale = sorted(
                name for name in set(local) & set(remote_signatures)
                if local[name][2] != remote_signatures[name][2]
            )
            if missing or unexpected or stale or permission_stale:
                stale_details = {
                    name: {
                        "local": repr(local.get(name))[:500],
                        "remote": repr(remote_signatures.get(name))[:500],
                    }
                    for name in stale[:3]
                }
                logger.warning(
                    "guild slash command verification mismatch guild=%s missing=%s stale=%s details=%s; retrying when applicable",
                    guild_id,
                    (missing + unexpected)[:8],
                    stale[:8],
                    stale_details,
                )
                if permission_stale:
                    logger.warning(
                        "guild slash command default permissions mismatch guild=%s commands=%s local=%s remote=%s",
                        guild_id,
                        permission_stale[:8],
                        {name: local_permissions.get(name) for name in permission_stale[:8]},
                        {name: remote_permissions.get(name) for name in permission_stale[:8]},
                    )
                raise RuntimeError(
                    f"guild command synchronization mismatch: missing={(missing + unexpected)[:8]} stale={stale[:8]} permissions={permission_stale[:8]}"
                )
            logger.info(
                "guild slash commands synchronized guild=%s top_level=%s executable=%s user_installable_excluded=%s",
                guild_id,
                len(synced),
                len(remote_signatures),
                len(global_commands) - len(guild_commands),
            )
            return synced
        finally:
            self.tree.clear_commands(guild=guild_object)
            for command in global_commands:
                if command not in self.tree.get_commands():
                    self.tree.add_command(command)

    @staticmethod
    def _command_sync_retry_delay(error: Exception) -> float | None:
        if isinstance(error, discord.RateLimited):
            try:
                return min(max(float(error.retry_after), 1.0), 900.0)
            except (TypeError, ValueError):
                return 60.0
        if isinstance(error, RuntimeError) and "command synchronization mismatch" in str(error).lower():
            return 5.0
        if isinstance(error, discord.HTTPException):
            if error.status == 429:
                headers = getattr(getattr(error, "response", None), "headers", {})
                try:
                    return min(max(float(headers.get("Retry-After", 60)), 1.0), 900.0)
                except (AttributeError, TypeError, ValueError):
                    return 60.0
            if error.status >= 500:
                return 30.0
        return None

    def _schedule_command_sync_retry(self, scope: str, initial_delay: float, guild_id: int | None = None) -> None:
        current = self._command_sync_retry_tasks.get(scope)
        if current is not None and not current.done():
            return
        self._command_sync_retry_tasks[scope] = asyncio.create_task(
            self._retry_command_sync(scope, initial_delay, guild_id)
        )

    async def _retry_command_sync(self, scope: str, initial_delay: float, guild_id: int | None) -> None:
        delay = min(max(float(initial_delay), 1.0), 900.0)
        try:
            for attempt in range(5):
                await asyncio.sleep(delay)
                try:
                    async with self._command_sync_lock:
                        if guild_id is None:
                            settings = get_settings()
                            sync_flag = "_production_command_sync_complete" if settings.app_env == "production" else "_development_guild_sync_complete"
                            if getattr(self, sync_flag, False):
                                return
                            await self._sync_command_scopes()
                            setattr(self, sync_flag, True)
                        else:
                            await self._sync_guild_commands(guild_id)
                            self._synced_guild_command_ids.add(guild_id)
                    logger.info("slash command synchronization retry succeeded scope=%s", scope)
                    return
                except Exception as exc:
                    retry_after = self._command_sync_retry_delay(exc)
                    if retry_after is None:
                        logger.exception("slash command synchronization retry stopped scope=%s", scope)
                        return
                    delay = min(max(retry_after, delay * 2), 900.0)
                    logger.warning(
                        "slash command synchronization retry delayed scope=%s attempt=%s/5 retry_seconds=%s error=%s",
                        scope,
                        attempt + 1,
                        delay,
                        type(exc).__name__,
                    )
            logger.error("slash command synchronization retries exhausted scope=%s", scope)
        finally:
            current = asyncio.current_task()
            if self._command_sync_retry_tasks.get(scope) is current:
                self._command_sync_retry_tasks.pop(scope, None)

    async def _ensure_registered_guilds(self) -> None:
        if not self.guilds:
            return
        try:
            async with session_factory() as session:
                for guild in self.guilds:
                    await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
                await session.commit()
        except SQLAlchemyError:
            logger.exception("guild bootstrap persistence failed")

    async def _sync_command_scopes(self) -> None:
        settings = get_settings()
        if settings.app_env == "production":
            guild_errors: list[tuple[int, Exception]] = []
            for guild in self.guilds:
                if guild.id in self._synced_guild_command_ids:
                    continue
                try:
                    await self._sync_guild_commands(guild.id)
                    self._synced_guild_command_ids.add(guild.id)
                except discord.RateLimited as exc:
                    logger.warning("guild command synchronization paused by Discord rate limit guild=%s retry_after=%s", guild.id, getattr(exc, "retry_after", "unknown"))
                    raise
                except Exception as exc:
                    if getattr(exc, "status", None) == 429:
                        logger.warning("guild command synchronization paused by Discord HTTP 429 guild=%s", guild.id)
                        raise
                    guild_errors.append((guild.id, exc))
                    logger.exception("guild slash command synchronization failed guild=%s", guild.id)
            try:
                await self._sync_user_installable_global_commands()
            except (discord.HTTPException, discord.RateLimited) as exc:
                logger.warning("user-installable global slash commands could not be synchronized status=%s detail=%s", getattr(exc, "status", "rate_limited"), str(exc)[:220])
                raise
            if guild_errors:
                retryable_error = next(
                    (error for _, error in guild_errors if self._command_sync_retry_delay(error) is not None),
                    None,
                )
                if retryable_error is not None:
                    raise retryable_error
                raise RuntimeError(f"guild command synchronization failed for {len(guild_errors)} guilds")
            self._production_command_sync_complete = True
            return

        target_ids = [settings.discord_guild_id] if settings.discord_guild_id else [guild.id for guild in self.guilds]
        guild_errors: list[tuple[int, Exception]] = []
        for guild_id in sorted(set(value for value in target_ids if value)):
            if guild_id in self._synced_guild_command_ids:
                continue
            try:
                await self._sync_guild_commands(guild_id)
                self._synced_guild_command_ids.add(guild_id)
            except discord.RateLimited as exc:
                logger.warning("guild command synchronization paused by Discord rate limit guild=%s retry_after=%s", guild_id, getattr(exc, "retry_after", "unknown"))
                raise
            except Exception as exc:
                if getattr(exc, "status", None) == 429:
                    logger.warning("guild command synchronization paused by Discord HTTP 429 guild=%s", guild_id)
                    raise
                guild_errors.append((guild_id, exc))
                logger.exception("guild slash command synchronization failed guild=%s", guild_id)
        try:
            await self._sync_user_installable_global_commands()
        except (discord.HTTPException, discord.RateLimited) as exc:
            logger.warning("user-installable global slash commands could not be synchronized status=%s detail=%s", getattr(exc, "status", "rate_limited"), str(exc)[:220])
            raise
        if guild_errors:
            retryable_error = next(
                (error for _, error in guild_errors if self._command_sync_retry_delay(error) is not None),
                None,
            )
            if retryable_error is not None:
                raise retryable_error
            raise RuntimeError(f"guild command synchronization failed for {len(guild_errors)} guilds")
        self._development_guild_sync_complete = True

    async def _restore_voice_sessions(self) -> None:
        current_voice: dict[int, dict[int, int]] = {}
        for guild in self.guilds:
            channels = [*guild.voice_channels, *getattr(guild, "stage_channels", [])]
            current_voice[guild.id] = {
                member.id: channel.id
                for channel in channels
                for member in channel.members
            }
        try:
            async with session_factory() as session:
                rows = list((await session.execute(select(Member).where(Member.voice_joined_at.is_not(None)))).scalars())
                now = utc_now()
                settings_rows = list((await session.execute(select(GuildSettings))).scalars())
                analytics_rows = list((await session.execute(select(AnalyticsConfig))).scalars())
                guild_settings = {row.guild_id: row for row in settings_rows}
                analytics_configs = {row.guild_id: row for row in analytics_rows}
                for row in rows:
                    channel_id = current_voice.get(row.guild_id, {}).get(row.user_id)
                    row.voice_joined_at = now if channel_id is not None else None
                    row.voice_channel_id = channel_id
                    row.voice_analytics_active = False
                    if channel_id is not None:
                        guild = self.get_guild(row.guild_id)
                        member = guild.get_member(row.user_id) if guild else None
                        channel = guild.get_channel(channel_id) if guild else None
                        settings = guild_settings.get(row.guild_id)
                        config = analytics_configs.get(row.guild_id)
                        row.voice_analytics_active = bool(
                            member and channel and (settings is None or settings.analytics_enabled)
                            and voice_is_eligible(
                                config,
                                channel_id=channel_id,
                                category_id=getattr(channel, "category_id", None),
                                role_ids=[role.id for role in member.roles],
                                is_bot=member.bot,
                            )
                        )
                    row.updated_at = now
                for guild in self.guilds:
                    channels = [*guild.voice_channels, *getattr(guild, "stage_channels", [])]
                    for channel in channels:
                        for member in channel.members:
                            row = await ensure_member(session, guild.id, member.id, member.joined_at)
                            if row.voice_joined_at is None:
                                row.voice_joined_at = now
                                row.voice_channel_id = channel.id
                                config = analytics_configs.get(guild.id)
                                settings = guild_settings.get(guild.id)
                                row.voice_analytics_active = bool(
                                    (settings is None or settings.analytics_enabled)
                                    and voice_is_eligible(
                                        config,
                                        channel_id=channel.id,
                                        category_id=getattr(channel, "category_id", None),
                                        role_ids=[role.id for role in member.roles],
                                        is_bot=member.bot,
                                    )
                                )
                                row.updated_at = now
                await session.commit()
                self._voice_sessions_restored = True
        except SQLAlchemyError:
            logger.exception("voice session restoration failed")

    async def on_ready(self) -> None:
        settings = get_settings()
        sync_flag = "_production_command_sync_complete" if settings.app_env == "production" else "_development_guild_sync_complete"
        retry_task = self._command_sync_retry_tasks.get("all")
        retry_pending = retry_task is not None and not retry_task.done()
        if not getattr(self, sync_flag, False) and not retry_pending:
            sync_error: Exception | None = None
            async with self._command_sync_lock:
                if not getattr(self, sync_flag, False):
                    try:
                        await self._sync_command_scopes()
                        setattr(self, sync_flag, True)
                    except Exception as exc:
                        sync_error = exc
                        logger.exception("slash command synchronization failed environment=%s", settings.app_env)
            if sync_error is not None:
                retry_after = self._command_sync_retry_delay(sync_error)
                if retry_after is not None:
                    self._schedule_command_sync_retry("all", retry_after)
        try:
            await asyncio.wait_for(self._ensure_registered_guilds(), timeout=15)
            await asyncio.wait_for(self._restore_voice_sessions(), timeout=15)
        except asyncio.TimeoutError:
            logger.error("database bootstrap timed out after command synchronization")
        except Exception:
            logger.exception("database bootstrap after ready failed")
        logger.info("logged in as %s", self.user)

    async def close(self) -> None:
        retry_tasks = list(self._command_sync_retry_tasks.values())
        for task in retry_tasks:
            task.cancel()
        if retry_tasks:
            await asyncio.gather(*retry_tasks, return_exceptions=True)
        self._command_sync_retry_tasks.clear()
        if hasattr(self, "worker"):
            self.worker.close()
        await super().close()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            async with session_factory() as session:
                await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None, reactivate=True)
                await session.commit()
        except SQLAlchemyError:
            logger.exception("guild join persistence failed guild=%s; continuing command setup", guild.id)
        async with self._command_sync_lock:
            try:
                await self._sync_guild_commands(guild.id)
                self._synced_guild_command_ids.add(guild.id)
            except Exception as exc:
                logger.exception("guild command sync failed guild=%s", guild.id)
                retry_after = self._command_sync_retry_delay(exc)
                if retry_after is not None:
                    self._schedule_command_sync_retry(f"guild:{guild.id}", retry_after, guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        self._synced_guild_command_ids.discard(guild.id)
        async with session_factory() as session:
            stored = await session.get(Guild, guild.id)
            if stored is not None:
                stored.active = False
                stored.updated_at = utc_now()
                await session.commit()

    async def on_member_join(self, member: discord.Member) -> None:
        try:
            async with session_factory() as session:
                await ensure_guild(session, member.guild.id, member.guild.name, member.guild.owner_id, member.guild.icon.url if member.guild.icon else None)
                await ensure_user(session, member.id, member.name, member.display_name, member.display_avatar.url, member.banner.url if member.banner else None, member.bot)
                previous_member = await session.scalar(
                    select(Member).where(Member.guild_id == member.guild.id, Member.user_id == member.id).with_for_update()
                )
                was_active = previous_member is not None and previous_member.left_at is None
                await ensure_member(session, member.guild.id, member.id, member.joined_at)
                settings = await session.get(GuildSettings, member.guild.id)
                if not was_active and (settings is None or settings.analytics_enabled):
                    await record_guild_metric(session, member.guild.id, "joins", 1, utc_now())
                await session.commit()
        except (SQLAlchemyError, TimeoutError):
            logger.exception("member join persistence failed; Anti-Raid will still run guild=%s user=%s", member.guild.id, member.id)
        antiraid = self.get_cog("AntiRaidCog")
        if antiraid is not None:
            try:
                await antiraid.on_member_join_event(member)
            except Exception:
                logger.exception("antiraid join handling failed guild=%s user=%s", member.guild.id, member.id)

    async def on_member_remove(self, member: discord.Member) -> None:
        try:
            async with session_factory() as session:
                row = await session.scalar(
                    select(Member).where(Member.guild_id == member.guild.id, Member.user_id == member.id).with_for_update()
                )
                if row is not None:
                    current = utc_now()
                    was_active = row.left_at is None
                    if row.voice_joined_at is not None:
                        seconds = max(int((current - row.voice_joined_at).total_seconds()), 0)
                        row.voice_seconds += seconds
                        if row.voice_analytics_active and row.voice_channel_id and seconds > 0:
                            await record_voice_segment(
                                session, member.guild.id, member.id, row.voice_channel_id, row.voice_joined_at, current
                            )
                        row.voice_joined_at = None
                        row.voice_channel_id = None
                        row.voice_analytics_active = False
                    row.left_at = current
                    row.updated_at = current
                    settings = await session.get(GuildSettings, member.guild.id)
                    if was_active and (settings is None or settings.analytics_enabled):
                        await record_guild_metric(session, member.guild.id, "leaves", 1, current)
                    await session.commit()
        except SQLAlchemyError:
            logger.exception("member leave persistence failed guild=%s user=%s", member.guild.id, member.id)

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if member.guild is None or before.channel == after.channel:
            return
        current = utc_now()
        try:
            async with session_factory() as session:
                await ensure_guild(session, member.guild.id, member.guild.name, member.guild.owner_id, member.guild.icon.url if member.guild.icon else None)
                await ensure_user(session, member.id, member.name, member.display_name, member.display_avatar.url, member.banner.url if member.banner else None, member.bot)
                await ensure_member(session, member.guild.id, member.id, member.joined_at)
                row = await session.scalar(
                    select(Member).where(Member.guild_id == member.guild.id, Member.user_id == member.id).with_for_update()
                )
                if row is None:
                    return
                if after.channel is None and row.voice_joined_at is None:
                    return
                if after.channel is not None and row.voice_channel_id == after.channel.id and row.voice_joined_at is not None:
                    if (current - row.voice_joined_at).total_seconds() < 5:
                        return
                if row.voice_joined_at is not None:
                    started_at = row.voice_joined_at
                    seconds = max(int((current - started_at).total_seconds()), 0)
                    row.voice_seconds += seconds
                    if row.voice_analytics_active and row.voice_channel_id and seconds > 0:
                        await record_voice_segment(
                            session, member.guild.id, member.id, row.voice_channel_id, started_at, current
                        )
                    row.voice_joined_at = None
                    row.voice_channel_id = None
                    row.voice_analytics_active = False
                if after.channel is not None:
                    settings = await session.get(GuildSettings, member.guild.id)
                    config = await session.get(AnalyticsConfig, member.guild.id)
                    analytics_enabled = settings is None or settings.analytics_enabled
                    row.voice_joined_at = current
                    row.voice_channel_id = after.channel.id
                    row.voice_analytics_active = bool(
                        analytics_enabled
                        and voice_is_eligible(
                            config,
                            channel_id=after.channel.id,
                            category_id=getattr(after.channel, "category_id", None),
                            role_ids=[role.id for role in member.roles],
                            is_bot=member.bot,
                        )
                    )
                row.updated_at = current
                await session.commit()
        except SQLAlchemyError:
            logger.exception("voice tracking failed guild=%s user=%s", member.guild.id, member.id)

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            if message.author.bot:
                return
            retry_after = await check_and_set(f"bn:dm-install:{message.author.id}", 30)
            if retry_after is not None:
                return
            client_id = self.application_id
            if client_id is None:
                try:
                    client_id = int(get_settings().discord_client_id)
                except (TypeError, ValueError):
                    logger.error("cannot build install link without application id")
                    return
            permissions = discord.Permissions(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                attach_files=True,
                read_message_history=True,
                manage_messages=True,
                moderate_members=True,
                kick_members=True,
                ban_members=True,
                manage_channels=True,
                manage_roles=True,
            )
            server_url = "https://discord.com/oauth2/authorize?" + urlencode({
                "client_id": str(client_id),
                "scope": "bot applications.commands",
                "permissions": str(permissions.value),
                "integration_type": "0",
            })
            app_url = "https://discord.com/oauth2/authorize?" + urlencode({
                "client_id": str(client_id),
                "scope": "applications.commands",
                "integration_type": "1",
            })
            view = discord.ui.View(timeout=180)
            view.add_item(discord.ui.Button(label="Adicionar ao servidor", style=discord.ButtonStyle.link, url=server_url))
            view.add_item(discord.ui.Button(label="Adicionar como App", style=discord.ButtonStyle.link, url=app_url))
            card = discord.Embed(
                title="BN Bot · Instalação",
                description="Quer levar o BN Bot para o seu servidor? Use o botão abaixo.\n\nVocê também pode instalar o BN Bot diretamente na sua conta para usar os comandos compatíveis com App Install.",
                color=0x24272B,
            )
            if self.user is not None:
                card.set_thumbnail(url=self.user.display_avatar.url)
            await message.channel.send(embed=card, view=view, allowed_mentions=discord.AllowedMentions.none())
            return
        if message.author.bot:
            try:
                async with session_factory() as session:
                    guild = message.guild
                    await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
                    await ensure_user(session, message.author.id, message.author.name, message.author.display_name, message.author.display_avatar.url, message.author.banner.url if message.author.banner else None, True)
                    await ensure_member(session, guild.id, message.author.id, message.author.joined_at)
                    settings = await session.get(GuildSettings, guild.id)
                    config = await session.get(AnalyticsConfig, guild.id)
                    if (settings is None or settings.analytics_enabled) and config is not None and not config.exclude_bots:
                        if analytics_message_allowed(config, message, self.user.id if self.user else self.application_id):
                            bucket = floor_hour(message.created_at)
                            await record_message(session, guild.id, message.author.id, message.channel.id, message.id, len(message.content), bucket, message.created_at)
                    await session.commit()
            except SQLAlchemyError:
                logger.exception("bot message analytics persistence failed guild=%s", message.guild.id)
            return
        automod = self.get_cog("AutoModCog")
        if automod is not None:
            handled = await automod.on_message_event(message)
            if handled:
                return
        try:
            async with session_factory() as session:
                guild = message.guild
                await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)
                await ensure_user(session, message.author.id, message.author.name, message.author.display_name, message.author.display_avatar.url, message.author.banner.url if message.author.banner else None, message.author.bot)
                await ensure_member(session, guild.id, message.author.id, message.author.joined_at)
                settings = await session.get(GuildSettings, guild.id)
                analytics_enabled = settings is None or settings.analytics_enabled
                levels_enabled = settings is None or settings.levels_enabled
                config = await session.get(AnalyticsConfig, guild.id)
                if analytics_enabled and analytics_message_allowed(config, message, self.user.id if self.user else self.application_id):
                    bucket = floor_hour(message.created_at)
                    await record_message(session, guild.id, message.author.id, message.channel.id, message.id, len(message.content), bucket, message.created_at)
                if levels_enabled and await check_and_set(f"bn:xp:{guild.id}:{message.author.id}", 60) is None:
                    await add_xp(session, guild.id, message.author.id, 15)
                await session.commit()
        except SQLAlchemyError:
            logger.exception("message persistence failed guild=%s user=%s", message.guild.id, message.author.id)
        await self.process_commands(message)

    async def on_app_command_completion(self, interaction: discord.Interaction, command: discord.app_commands.Command) -> None:
        try:
            async with session_factory() as session:
                await record_command_usage(
                    session,
                    interaction.user.id,
                    interaction.guild.id if interaction.guild else None,
                    interaction.channel_id,
                    command.qualified_name,
                    True,
                )
                await session.commit()
        except SQLAlchemyError:
            logger.exception("command usage persistence failed command=%s user=%s", command.qualified_name, interaction.user.id)

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        original = error.original if isinstance(error, discord.app_commands.CommandInvokeError) else error
        try:
            async with session_factory() as session:
                await record_command_usage(
                    session,
                    interaction.user.id,
                    interaction.guild.id if interaction.guild else None,
                    interaction.channel_id,
                    interaction.command.qualified_name if interaction.command else "unknown",
                    False,
                    type(original).__name__,
                )
                await session.commit()
        except SQLAlchemyError:
            logger.exception("failed command usage persistence command=%s user=%s", interaction.command.qualified_name if interaction.command else "unknown", interaction.user.id)
        if isinstance(original, discord.app_commands.errors.MissingPermissions):
            message = "Você não possui a permissão necessária para executar este comando."
        elif isinstance(original, discord.Forbidden):
            message = "O BN Bot não possui as permissões necessárias neste servidor ou canal."
        elif isinstance(original, discord.NotFound):
            message = "O recurso do Discord não foi encontrado."
        elif isinstance(original, discord.app_commands.errors.TransformerError):
            message = "Um dos parâmetros informados é inválido."
        elif isinstance(original, discord.app_commands.errors.CommandSignatureMismatch):
            message = "A assinatura deste comando estava desatualizada no Discord. O BN Bot está sincronizando os comandos; tente novamente em alguns segundos."
        elif isinstance(original, RateLimitExceeded):
            message = f"Aguarde {original.seconds}s antes de tentar novamente."
        elif isinstance(original, discord.app_commands.errors.CommandOnCooldown):
            wait_seconds = max(1, int(original.retry_after + 0.999))
            message = f"Aguarde {wait_seconds}s antes de tentar novamente."
        elif isinstance(original, discord.app_commands.errors.BotMissingPermissions):
            message = "O BN Bot não possui as permissões necessárias para executar este comando."
        elif isinstance(original, discord.app_commands.errors.MissingRole):
            message = "Você não possui o cargo necessário para executar este comando."
        elif isinstance(original, discord.app_commands.errors.MissingAnyRole):
            message = "Você não possui nenhum dos cargos necessários para executar este comando."
        elif isinstance(original, discord.app_commands.errors.NoPrivateMessage):
            message = "Este comando só pode ser executado em um servidor."
        elif isinstance(original, discord.app_commands.errors.CheckFailure):
            message = "Você não atende aos requisitos para executar este comando."
        elif isinstance(original, discord.RateLimited):
            wait_seconds = max(1, int(original.retry_after + 0.999))
            message = f"O Discord está limitando esta ação. Aguarde {wait_seconds}s e tente novamente."
        elif isinstance(original, discord.HTTPException):
            message = "O Discord recusou esta resposta. Tente o comando novamente."
        elif isinstance(original, SQLAlchemyError):
            message = "Ocorreu um erro ao acessar o banco de dados. Tente novamente."
        else:
            from app.core.exceptions import CooldownActive, InsufficientFunds, NotFound, ValidationFailure
            if isinstance(original, CooldownActive):
                message = f"Aguarde {original.seconds}s antes de tentar novamente."
            elif isinstance(original, InsufficientFunds):
                message = "Saldo insuficiente para concluir a operação."
            elif isinstance(original, NotFound):
                message = "O recurso solicitado não foi encontrado."
            elif isinstance(original, ValidationFailure):
                message = str(original) or "Os dados informados são inválidos."
            elif isinstance(original, ValueError):
                mapping = {
                    "invalid transfer": "A transferência é inválida.",
                    "quantity must be positive": "A quantidade deve ser maior que zero.",
                    "amount must be positive": "O valor deve ser maior que zero.",
                    "not enough items": "Você não possui itens suficientes.",
                    "stack limit exceeded": "A quantidade ultrapassa o limite do item.",
                    "insufficient stock": "O estoque disponível não é suficiente.",
                }
                message = mapping.get(str(original), "Os dados informados não podem ser processados.")
            else:
                message = "Não foi possível concluir este comando."
        if interaction.is_expired():
            logger.warning(
                "application command error could not be surfaced because interaction expired command=%s error=%s",
                interaction.command.qualified_name if interaction.command else "unknown",
                type(original).__name__,
            )
        elif interaction.response.is_done():
            try:
                await interaction.edit_original_response(content=message, embed=None, view=None)
            except (discord.NotFound, discord.HTTPException):
                logger.exception("failed to finalize original command response")
                try:
                    await interaction.followup.send(message, ephemeral=True)
                except discord.HTTPException:
                    logger.exception("failed to send command error followup")
        else:
            try:
                await interaction.response.send_message(message, ephemeral=True)
            except (discord.NotFound, discord.HTTPException):
                logger.exception("failed to send command error response")
        if isinstance(original, RateLimitExceeded):
            logger.warning(
                "application command rate limited command=%s user=%s retry_after=%s",
                interaction.command.qualified_name if interaction.command else "unknown",
                interaction.user.id,
                original.seconds,
            )
        elif isinstance(original, BaseException):
            logger.error("application command failure: %s", type(original).__name__, exc_info=(type(original), original, original.__traceback__))
        else:
            logger.error("application command failure: %r", original)
