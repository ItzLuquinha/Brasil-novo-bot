import logging
import time
import secrets
from datetime import timedelta
import discord
from discord.ext import tasks
from sqlalchemy import delete, or_, select
from app.core.db import session_factory
from app.core.time import utc_now
from app.services.analytics import counter_value, evaluate_activity_rule_metrics, record_guild_snapshot, render_counter_name, validate_counter_template
from app.repositories.guilds import ensure_guild
from app.models import ActivityRoleRule, AnalyticsConfig, AuditLog, ChannelActivity, Guild, GuildActivity, GuildSettings, Member, MemberActivity, MessageLog, Reminder, StatCounter, TemporaryRole, Warning

logger = logging.getLogger("bn_bot.tasks")


class Worker:
    HEARTBEAT_WARNING_INTERVAL_SECONDS = 300.0

    def __init__(self, bot) -> None:
        self.bot = bot
        self._heartbeat_failure_started_at: float | None = None
        self._heartbeat_last_warning_at: float = 0.0
        self._heartbeat_suppressed_failures: int = 0
        self.reminders.start()
        self.temporary_roles.start()
        self.antiraid.start()
        self.community.start()
        self.warnings.start()
        self.bot_status.start()
        self.analytics_counters.start()
        self.activity_roles.start()
        self.voice_activity_flush.start()
        self.guild_member_snapshots.start()
        self.analytics_retention.start()

    def close(self) -> None:
        self.reminders.cancel()
        self.temporary_roles.cancel()
        self.antiraid.cancel()
        self.community.cancel()
        self.warnings.cancel()
        self.bot_status.cancel()
        self.analytics_counters.cancel()
        self.activity_roles.cancel()
        self.voice_activity_flush.cancel()
        self.guild_member_snapshots.cancel()
        self.analytics_retention.cancel()

    def _report_heartbeat_failure(self, error_name: str) -> None:
        """Report a continuous Redis outage without emitting one warning per loop.

        The task still retries every 30 seconds; only the log emission is throttled.
        A success resets the outage state and is reported by ``bot_status`` below.
        """
        now = time.monotonic()
        if self._heartbeat_failure_started_at is None:
            self._heartbeat_failure_started_at = now
        if (
            self._heartbeat_last_warning_at == 0.0
            or now - self._heartbeat_last_warning_at >= self.HEARTBEAT_WARNING_INTERVAL_SECONDS
        ):
            logger.warning(
                "bot health heartbeat unavailable in Redis error=%s duration_seconds=%.0f suppressed_repeats=%s",
                error_name,
                now - self._heartbeat_failure_started_at,
                self._heartbeat_suppressed_failures,
            )
            self._heartbeat_last_warning_at = now
            self._heartbeat_suppressed_failures = 0
        else:
            self._heartbeat_suppressed_failures += 1

    @tasks.loop(seconds=30)
    async def bot_status(self) -> None:
        if not self.bot.is_ready():
            return
        try:
            from redis.exceptions import RedisError
            from app.core.redis import redis_client
            await redis_client.set("bn:health:discord_bot", "online", ex=90)
        except ImportError:
            self._report_heartbeat_failure("DependencyUnavailable")
        except RedisError as exc:
            self._report_heartbeat_failure(type(exc).__name__)
        else:
            if self._heartbeat_failure_started_at is not None:
                duration = time.monotonic() - self._heartbeat_failure_started_at
                logger.info(
                    "bot health heartbeat recovered after_seconds=%.0f suppressed_repeats=%s",
                    duration,
                    self._heartbeat_suppressed_failures,
                )
                self._heartbeat_failure_started_at = None
                self._heartbeat_last_warning_at = 0.0
                self._heartbeat_suppressed_failures = 0

    @bot_status.before_loop
    async def before_bot_status(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=15)
    async def reminders(self) -> None:
        now = utc_now()
        max_attempts = 5
        retry_delays = (60, 300, 900, 3600)
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(Reminder)
                    .where(
                        Reminder.sent_at.is_(None),
                        Reminder.due_at <= now,
                        Reminder.attempt_count < max_attempts,
                        or_(Reminder.next_attempt_at.is_(None), Reminder.next_attempt_at <= now),
                    )
                    .order_by(Reminder.due_at)
                    .limit(50)
                    .with_for_update(skip_locked=True)
                )
                rows = list(result.scalars())
                for reminder in rows:
                    delivered = False
                    permanent_failure = False
                    error_text: str | None = None
                    discord_retry_after: float | None = None

                    try:
                        if reminder.delivery == "dm":
                            user = self.bot.get_user(reminder.user_id)
                            if user is None:
                                user = await self.bot.fetch_user(reminder.user_id)
                            await user.send(reminder.message)
                            delivered = True
                        elif reminder.channel_id:
                            channel = self.bot.get_channel(reminder.channel_id)
                            if channel is None and reminder.guild_id:
                                guild = self.bot.get_guild(reminder.guild_id)
                                if guild is not None:
                                    channel = guild.get_thread(reminder.channel_id)
                                    if channel is None:
                                        channel = await guild.fetch_channel(reminder.channel_id)
                            if channel is None:
                                raise RuntimeError("reminder destination is not currently available")
                            await channel.send(
                                f"<@{reminder.user_id}> {reminder.message}",
                                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                            )
                            delivered = True
                        else:
                            raise ValueError("reminder has no valid delivery destination")
                    except discord.RateLimited as exc:
                        discord_retry_after = max(float(getattr(exc, "retry_after", 1.0)), 1.0)
                        error_text = f"RateLimited: retry_after={discord_retry_after:.2f}s"[:500]
                    except (discord.NotFound, discord.Forbidden, ValueError) as exc:
                        permanent_failure = True
                        error_text = f"{type(exc).__name__}: {exc}"[:500]
                    except Exception as exc:
                        error_text = f"{type(exc).__name__}: {exc}"[:500]

                    if delivered:
                        reminder.sent_at = utc_now()
                        reminder.next_attempt_at = None
                        reminder.last_error = None
                        logger.info("reminder delivered id=%s delivery=%s", reminder.id, reminder.delivery)
                        continue

                    reminder.attempt_count += 1
                    if permanent_failure:
                        reminder.attempt_count = max_attempts
                    reminder.last_error = error_text or "Delivery failed"
                    if reminder.attempt_count < max_attempts:
                        delay = retry_delays[min(reminder.attempt_count - 1, len(retry_delays) - 1)]
                        if discord_retry_after is not None:
                            delay = max(delay, int(discord_retry_after + 0.999))
                        reminder.next_attempt_at = utc_now() + timedelta(seconds=delay)
                        logger.warning(
                            "reminder delivery deferred id=%s attempt=%s/%s retry_seconds=%s error=%s",
                            reminder.id,
                            reminder.attempt_count,
                            max_attempts,
                            delay,
                            reminder.last_error,
                        )
                    else:
                        reminder.next_attempt_at = None
                        logger.error(
                            "reminder delivery abandoned id=%s attempts=%s error=%s",
                            reminder.id,
                            reminder.attempt_count,
                            reminder.last_error,
                        )
                await session.commit()
        except Exception:
            logger.exception("reminders worker iteration failed")

    @reminders.before_loop
    async def before_reminders(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def temporary_roles(self) -> None:
        try:
            async with session_factory() as session:
                result = await session.execute(select(TemporaryRole).where(TemporaryRole.expires_at <= utc_now()).limit(100).with_for_update(skip_locked=True))
                rows = list(result.scalars())
                for record in rows:
                    guild = self.bot.get_guild(record.guild_id)
                    delete_record = False
                    if guild is None:
                        logger.warning("temporary role cleanup deferred; guild unavailable guild=%s user=%s role=%s", record.guild_id, record.user_id, record.role_id)
                        continue
                    else:
                        member = guild.get_member(record.user_id)
                        if member is None:
                            try:
                                member = await guild.fetch_member(record.user_id)
                            except discord.NotFound:
                                member = None
                                delete_record = True
                            except discord.HTTPException:
                                logger.exception("temporary role member fetch failed guild=%s user=%s", record.guild_id, record.user_id)
                                continue
                        role = guild.get_role(record.role_id)
                        if member is None or role is None or role not in member.roles:
                            delete_record = True
                        else:
                            try:
                                await member.remove_roles(role, reason=record.reason)
                                delete_record = True
                            except discord.NotFound:
                                delete_record = True
                            except discord.HTTPException:
                                logger.exception("temporary role cleanup failed guild=%s user=%s", record.guild_id, record.user_id)
                    if delete_record:
                        await session.delete(record)
                await session.commit()
        except Exception:
            logger.exception("temporary roles worker iteration failed")

    @temporary_roles.before_loop
    async def before_temporary_roles(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def antiraid(self) -> None:
        try:
            cog = self.bot.get_cog("AntiRaidCog")
            if cog is not None:
                await cog.expire_lockdowns()
        except Exception:
            logger.exception("antiraid worker iteration failed")

    @antiraid.before_loop
    async def before_antiraid(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def community(self) -> None:
        try:
            cog = self.bot.get_cog("CommunityCog")
            if cog is not None:
                await cog.restore_views()
                await cog.expire_community()
        except Exception:
            logger.exception("community worker iteration failed")

    @community.before_loop
    async def before_community(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=30)
    async def warnings(self) -> None:
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(Warning)
                    .where(
                        Warning.active.is_(True),
                        Warning.expires_at.is_not(None),
                        Warning.expires_at <= utc_now(),
                    )
                    .limit(200)
                    .with_for_update(skip_locked=True)
                )
                rows = list(result.scalars())
                for warning in rows:
                    warning.active = False
                await session.commit()
        except Exception:
            logger.exception("timed warning cleanup iteration failed")

    @warnings.before_loop
    async def before_warnings(self) -> None:
        await self.bot.wait_until_ready()


    @tasks.loop(seconds=60)
    async def analytics_counters(self) -> None:
        now = utc_now()
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(StatCounter).where(StatCounter.enabled.is_(True))
                    .order_by(StatCounter.last_attempt_at.asc().nullsfirst(), StatCounter.id.asc())
                    .limit(100).with_for_update(skip_locked=True)
                )
                counters = list(result.scalars())
                chunked_guilds: set[int] = set()
                for counter in counters:
                    if counter.last_attempt_at and counter.last_attempt_at > now - timedelta(minutes=2):
                        continue
                    counter.last_attempt_at = now
                    guild = self.bot.get_guild(counter.guild_id)
                    if guild is None:
                        counter.last_error = "Servidor não está disponível para o bot."
                        continue
                    try:
                        channel = guild.get_channel(counter.channel_id)
                        if channel is None:
                            try:
                                channel = await guild.fetch_channel(counter.channel_id)
                            except discord.NotFound:
                                counter.last_error = "Canal não encontrado; confira o ID configurado."
                                continue
                        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
                            counter.last_error = "O destino do contador precisa ser um canal de voz ou palco."
                            continue
                        me = guild.me
                        if me is None or not channel.permissions_for(me).manage_channels:
                            counter.last_error = "O bot precisa da permissão Gerenciar Canais no canal do contador."
                            continue
                        if counter.metric in {"human_members", "bot_members", "voice_members"} and not guild.chunked and guild.id not in chunked_guilds:
                            await guild.chunk(cache=True)
                            chunked_guilds.add(guild.id)
                        if counter.metric == "member_count":
                            value = int(guild.member_count if guild.member_count is not None else len(guild.members))
                        elif counter.metric == "human_members":
                            value = sum(1 for member in guild.members if not member.bot)
                        elif counter.metric == "bot_members":
                            value = sum(1 for member in guild.members if member.bot)
                        elif counter.metric == "voice_members":
                            value = sum(1 for member in guild.members if member.voice and member.voice.channel)
                        else:
                            value = await counter_value(session, counter.guild_id, counter.metric, counter.period_days, counter.goal_value)
                        template = validate_counter_template(counter.format_template)
                        name = render_counter_name(template, counter.metric, value, counter.goal_value)
                        if channel.name != name:
                            await channel.edit(name=name, reason="Atualização automática de contador BN Bot")
                        counter.last_value = value
                        counter.last_updated_at = now
                        counter.last_error = None
                        counter.updated_at = now
                    except discord.Forbidden:
                        counter.last_error = "Discord negou a atualização; verifique permissões e hierarquia."
                    except discord.NotFound:
                        counter.last_error = "Canal não encontrado; confira o ID configurado."
                    except discord.HTTPException as exc:
                        counter.last_error = f"Falha HTTP do Discord (status {getattr(exc, 'status', 'desconhecido')})."
                    except (ValueError, TypeError) as exc:
                        counter.last_error = str(exc)[:500]
                    except Exception as exc:
                        counter.last_error = f"Falha inesperada ({type(exc).__name__})."
                        logger.exception("analytics counter failed id=%s guild=%s", counter.id, counter.guild_id)
                await session.commit()
        except Exception:
            logger.exception("analytics counters worker iteration failed")

    @analytics_counters.before_loop
    async def before_analytics_counters(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=5)
    async def activity_roles(self) -> None:
        now = utc_now()
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(ActivityRoleRule).where(ActivityRoleRule.enabled.is_(True))
                    .order_by(ActivityRoleRule.last_evaluated_at.asc().nullsfirst(), ActivityRoleRule.guild_id.asc(), ActivityRoleRule.id.asc())
                    .limit(100).with_for_update(skip_locked=True)
                )
                rules = list(result.scalars())
                chunked_guilds: set[int] = set()
                for rule in rules:
                    guild = self.bot.get_guild(rule.guild_id)
                    if guild is None:
                        rule.last_error = "Servidor não está disponível para o bot."
                        rule.last_evaluated_at = now
                        continue
                    try:
                        me = guild.me
                        role = guild.get_role(rule.role_id)
                        if role is None:
                            rule.last_error = "Cargo não encontrado no servidor."
                            rule.last_evaluated_at = now
                            continue
                        if me is None or not me.guild_permissions.manage_roles:
                            rule.last_error = "O bot precisa da permissão Gerenciar Cargos."
                            rule.last_evaluated_at = now
                            continue
                        privileged_permissions = (
                            "administrator", "manage_guild", "manage_roles", "manage_channels",
                            "manage_messages", "manage_webhooks", "manage_events", "kick_members",
                            "ban_members", "moderate_members", "manage_nicknames", "manage_permissions",
                        )
                        if role.managed or role.is_default() or role >= me.top_role or any(
                            bool(getattr(role.permissions, permission, False)) for permission in privileged_permissions
                        ):
                            rule.last_error = "Cargo gerenciado, acima do bot ou com permissões privilegiadas não pode ser automatizado."
                            rule.last_evaluated_at = now
                            continue
                        if not guild.chunked and guild.id not in chunked_guilds:
                            await guild.chunk(cache=True)
                            chunked_guilds.add(guild.id)
                        metrics = await evaluate_activity_rule_metrics(session, rule.guild_id, rule)
                        candidates = {user_id for user_id, values in metrics.items() if any(values.values())}
                        candidates.update(member.id for member in guild.members if role in member.roles)
                        failure_count = 0
                        for user_id in candidates:
                            member = guild.get_member(user_id)
                            if member is None or member.bot:
                                continue
                            values = metrics.get(user_id, {"messages": 0, "voice_seconds": 0, "active_days": 0})
                            qualifies = True
                            if rule.min_messages is not None and values.get("messages", 0) < rule.min_messages:
                                qualifies = False
                            if rule.min_voice_seconds is not None and values.get("voice_seconds", 0) < rule.min_voice_seconds:
                                qualifies = False
                            if rule.min_active_days is not None and values.get("active_days", 0) < rule.min_active_days:
                                qualifies = False
                            has_role = role in member.roles
                            action = None
                            try:
                                if qualifies and not has_role:
                                    await member.add_roles(role, reason=f"BN Bot: regra de atividade {rule.id}")
                                    action = "activity_role.grant"
                                elif not qualifies and has_role and rule.remove_when_unqualified:
                                    await member.remove_roles(role, reason=f"BN Bot: regra de atividade {rule.id}")
                                    action = "activity_role.revoke"
                            except discord.HTTPException as exc:
                                failure_count += 1
                                logger.warning("activity role mutation failed guild=%s rule=%s user=%s status=%s", guild.id, rule.id, user_id, getattr(exc, "status", "unknown"))
                                continue
                            if action:
                                session.add(AuditLog(
                                    id=secrets.randbits(62), guild_id=rule.guild_id,
                                    executor_id=int(self.bot.user.id if self.bot.user else 0), action=action,
                                    resource=f"rule:{rule.id};role:{rule.role_id};user:{user_id}",
                                    before_state={"has_role": has_role},
                                    after_state={"has_role": action == "activity_role.grant", "rule_id": rule.id,
                                                 "messages": int(values.get("messages", 0)),
                                                 "voice_seconds": int(values.get("voice_seconds", 0)),
                                                 "active_days": int(values.get("active_days", 0))},
                                    created_at=now,
                                ))
                        rule.last_error = f"{failure_count} operação(ões) falharam no Discord." if failure_count else None
                        rule.last_evaluated_at = now
                        rule.updated_at = now
                    except discord.Forbidden:
                        rule.last_error = "Discord negou a operação; verifique as permissões e a hierarquia do cargo."
                        rule.last_evaluated_at = now
                    except discord.HTTPException as exc:
                        rule.last_error = f"Falha HTTP do Discord (status {getattr(exc, 'status', 'desconhecido')})."
                        rule.last_evaluated_at = now
                    except Exception as exc:
                        rule.last_error = f"Falha inesperada ({type(exc).__name__})."
                        rule.last_evaluated_at = now
                        logger.exception("activity role rule failed id=%s guild=%s", rule.id, rule.guild_id)
                await session.commit()
        except Exception:
            logger.exception("activity role worker iteration failed")

    @activity_roles.before_loop
    async def before_activity_roles(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=60)
    async def voice_activity_flush(self) -> None:
        if not getattr(self.bot, "_voice_sessions_restored", False):
            return
        now = utc_now()
        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(Member).where(Member.voice_joined_at.is_not(None))
                    .order_by(Member.guild_id.asc(), Member.user_id.asc())
                    .with_for_update(skip_locked=True)
                )
                rows = list(result.scalars())
                for row in rows:
                    started_at = row.voice_joined_at
                    if started_at is None:
                        continue
                    seconds = max(int((now - started_at).total_seconds()), 0)
                    if seconds <= 0:
                        continue
                    row.voice_seconds += seconds
                    if row.voice_analytics_active and row.voice_channel_id:
                        await record_voice_segment(session, row.guild_id, row.user_id, row.voice_channel_id, started_at, now)
                    row.voice_joined_at = now
                    row.updated_at = now
                await session.commit()
        except Exception:
            logger.exception("voice activity flush failed")

    @voice_activity_flush.before_loop
    async def before_voice_activity_flush(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=1)
    async def guild_member_snapshots(self) -> None:
        now = utc_now()
        for guild in self.bot.guilds:
            try:
                async with session_factory() as session:
                    stored_guild = await session.get(Guild, guild.id)
                    settings = await session.get(GuildSettings, guild.id)
                    if stored_guild is None or settings is None:
                        await ensure_guild(
                            session,
                            guild.id,
                            guild.name,
                            guild.owner_id,
                            guild.icon.url if guild.icon else None,
                        )
                        settings = await session.get(GuildSettings, guild.id)
                    if settings is not None and not settings.analytics_enabled:
                        await session.commit()
                        continue
                    count = guild.member_count
                    if count is None:
                        if not guild.chunked:
                            await guild.chunk(cache=True)
                        count = len(guild.members)
                    await record_guild_snapshot(session, guild.id, int(count), now)
                    await session.commit()
            except Exception:
                logger.exception("guild member snapshot failed guild=%s", guild.id)

    @guild_member_snapshots.before_loop
    async def before_guild_member_snapshots(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def analytics_retention(self) -> None:
        now = utc_now()
        try:
            async with session_factory() as session:
                config_rows = list((await session.execute(select(AnalyticsConfig))).scalars())
                retention_by_guild = {row.guild_id: max(30, min(int(row.retention_days), 3650)) for row in config_rows}
                guild_rows = list((await session.execute(select(GuildSettings.guild_id))).scalars())
                guild_ids = set(guild_rows) | set(retention_by_guild)
                from sqlalchemy import select as sql_select
                for guild_id in guild_ids:
                    retention_days = retention_by_guild.get(guild_id, 365)
                    cutoff = now - timedelta(days=retention_days)
                    await session.execute(delete(MemberActivity).where(MemberActivity.guild_id == guild_id, MemberActivity.bucket_start < cutoff))
                    await session.execute(delete(ChannelActivity).where(ChannelActivity.guild_id == guild_id, ChannelActivity.bucket_start < cutoff))
                    await session.execute(delete(GuildActivity).where(GuildActivity.guild_id == guild_id, GuildActivity.bucket_start < cutoff))
                    old_message_ids = sql_select(MessageLog.id).where(MessageLog.guild_id == guild_id, MessageLog.created_at < cutoff).limit(5000)
                    await session.execute(delete(MessageLog).where(MessageLog.id.in_(old_message_ids)))
                await session.commit()
        except Exception:
            logger.exception("analytics retention worker iteration failed")

    @analytics_retention.before_loop
    async def before_analytics_retention(self) -> None:
        await self.bot.wait_until_ready()
