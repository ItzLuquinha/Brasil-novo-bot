from pathlib import Path

from app.services.antiraid import clamp_quarantine_timeout_seconds


def test_temporary_role_worker_keeps_record_on_transient_discord_errors() -> None:
    source = Path("app/tasks/worker.py").read_text(encoding="utf-8")
    block = source[source.index("async def temporary_roles"):source.index("@temporary_roles.before_loop")]
    assert "except discord.HTTPException:" in block
    assert "continue" in block
    assert "delete_record = False" in block
    assert "cleanup deferred" in block


def test_antiraid_quarantine_timeout_is_safe_for_corrupt_config() -> None:
    assert clamp_quarantine_timeout_seconds(None) == 900
    assert clamp_quarantine_timeout_seconds("bad") == 900
    assert clamp_quarantine_timeout_seconds(-5) == 60
    assert clamp_quarantine_timeout_seconds(2_419_201) == 2_419_200
    assert clamp_quarantine_timeout_seconds(600) == 600


def test_command_sync_is_serialized() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "self._command_sync_lock = asyncio.Lock()" in source
    ready = source[source.index("async def on_ready"):source.index("async def close", source.index("async def on_ready"))]
    join = source[source.index("async def on_guild_join"):source.index("async def on_guild_remove", source.index("async def on_guild_join"))]
    assert "async with self._command_sync_lock:" in ready
    assert "async with self._command_sync_lock:" in join


def test_poll_completion_does_not_count_twice() -> None:
    source = Path("app/services/community.py").read_text(encoding="utf-8")
    block = source[source.index("async def end_poll"):source.index("async def open_items", source.index("async def end_poll"))]
    assert block.count("counts = await poll_counts") == 1


def test_custom_permissions_are_deterministic_and_user_rules_override_roles() -> None:
    source = Path("app/services/permissions.py").read_text(encoding="utf-8")
    assert ".order_by(" in source
    assert "GuildPermission.id.desc()" in source
    assert "if user_rules:" in source
    assert "return user_rules[0].allowed" in source
    assert "relevant[-1]" not in source


def test_dashboard_distinguishes_expired_discord_tokens_from_service_outages() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    start = source.index("async def discord_get")
    end = source.index("async def discord_token", start)
    block = source[start:end]
    assert "if response.status_code == 401:" in block
    assert 'status_code=401' in block
    assert "if response.status_code == 403:" in block
    assert 'status_code=502' in block


def test_automod_skips_invalid_rule_rows_instead_of_aborting_evaluation() -> None:
    source = Path("app/discord/cogs/automod.py").read_text(encoding="utf-8")
    start = source.index("for row in rule_rows:")
    end = source.index("whitelist =", start)
    block = source[start:end]
    assert "config_errors = validate_rule_config" in block
    assert "if config_errors:" in block
    assert "continue" in block


def test_dashboard_redirects_expired_api_sessions_to_oauth_login() -> None:
    source = Path("app/dashboard/static/app.js").read_text(encoding="utf-8")
    assert "response.status===401" in source
    assert "window.location.href='/auth/login'" in source


def test_worker_only_deletes_temporary_role_record_after_confirmed_completion_or_nonexistent_guild() -> None:
    source = Path("app/tasks/worker.py").read_text(encoding="utf-8")
    block = source[source.index("async def temporary_roles"):source.index("@temporary_roles.before_loop")]
    assert "delete_record = False" in block
    assert "cleanup deferred" in block
    assert "except discord.HTTPException:" in block
    assert "continue" in block


def test_on_ready_backfills_existing_guilds_for_dashboard() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "async def _ensure_registered_guilds" in source
    assert "await ensure_guild(session, guild.id, guild.name, guild.owner_id, guild.icon.url if guild.icon else None)" in source
    ready_start = source.index("async def on_ready")
    ready_end = source.index("async def close", ready_start)
    ready = source[ready_start:ready_end]
    assert "asyncio.wait_for(self._ensure_registered_guilds(), timeout=15)" in ready


def test_automod_invalid_rule_is_skipped_before_rule_evaluation() -> None:
    source = Path("app/discord/cogs/automod.py").read_text(encoding="utf-8")
    start = source.index("for row in rule_rows:")
    end = source.index("whitelist =", start)
    block = source[start:end]
    assert "validate_rule_config(row.rule_type, config)" in block
    assert "if config_errors:" in block
    assert "continue" in block
    assert "rules.append(_rule_definition(row))" in block


def test_command_matrix_covers_all_handlers() -> None:
    from app.services.command_matrix import EXPECTED_COMMANDS, audit_summary
    ok, cases, issues = audit_summary()
    assert ok, issues
    assert len(cases) == len(EXPECTED_COMMANDS)






def test_timeout_accepts_seconds_minutes_hours_days_and_rejects_over_28_days() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    assert "def parse_timeout_duration" in source
    assert 'raw = f"{raw}m"' in source
    assert 'seconds = ModerationCog.parse_twarn_duration(raw)' in source
    assert "28 * 86400" in source
    assert 'duration: str' in source

def test_timeout_removal_commands_have_matching_permissions_and_api_calls() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    for name in ("untimeout", "unmute"):
        assert f'@app_commands.command(name="{name}"' in source
        assert f'async def {name}' in source
    assert '@app_commands.checks.has_permissions(moderate_members=True)' in source
    assert 'async def _remove_timeout' in source
    assert 'current = await self._edit_timeout(guild, user, None, clean_reason)' in source

def test_timeout_requests_are_not_retried_outside_discord_py_rate_limit_handling() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    start = source.index("async def _edit_timeout")
    end = source.index("async def _remove_timeout", start)
    block = source[start:end]
    assert "await user.timeout(until, reason=reason)" in block
    assert "asyncio.sleep" not in block
    assert "parse_timeout_duration" in source
    assert '@command_rate_limit("moderation-action", 3)' in source

def test_development_guild_sync_uses_sanitized_copies() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("def _copy_command_for_guild"):source.index("async def _sync_command_scopes", source.index("def _copy_command_for_guild"))]
    assert "command._copy_with(parent=None, binding=binding, bindings=bindings)" in block
    assert "node.allowed_contexts = None" in block
    assert "node.allowed_installs = None" in block
    assert "self.tree.add_command(command, guild=guild_object)" in block
    assert 'self.tree.copy_global_to(guild=guild_object)' not in block
    assert "await self.tree.sync(guild=guild_object)" in block

def test_guild_copy_helper_strips_install_and_context_metadata() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("def _copy_command_for_guild"):source.index("async def _sync_guild_commands", source.index("def _copy_command_for_guild"))]
    assert "binding = getattr(command, \"binding\", None)" in block
    assert "bindings = {binding: binding} if binding is not None else {}" in block
    assert "command._copy_with(parent=None, binding=binding, bindings=bindings)" in block
    assert "node.allowed_contexts = None" in block
    assert "node.allowed_installs = None" in block


def test_guild_copy_helper_preserves_group_binding() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("def _copy_command_for_guild"):source.index("async def _sync_guild_commands", source.index("def _copy_command_for_guild"))]
    assert "isinstance(command, discord.app_commands.Group)" in block
    assert "next((getattr(child, \"binding\", None)" in block


def test_guild_command_sync_verifies_guild_scoped_local_commands() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("async def _sync_guild_commands"):source.index("async def _sync_command_scopes", source.index("async def _sync_guild_commands"))]
    assert 'self.tree.walk_commands(guild=guild_object)' in block

def test_dashboard_is_registered_and_opens_the_web_dashboard() -> None:
    bot = Path("app/discord/bot.py").read_text(encoding="utf-8")
    dashboard = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert "from app.discord.cogs.dashboard import DashboardCog" in bot
    assert "await self.add_cog(DashboardCog(self))" in bot
    assert '@app_commands.command(name="dashboard"' in dashboard
    assert "get_settings().dashboard_url" in dashboard
    assert "discord.ButtonStyle.link" in dashboard


def test_command_matrix_uses_group_qualified_names() -> None:
    from app.services.command_matrix import audit_commands
    names = {case.qualified_name for case in audit_commands()}
    assert "admin credit" in names
    assert "automod rule-add" in names
    assert "giveaway create" in names
    assert "poll create" in names
    assert "dashboard" in names


def test_reminder_channel_delivery_blocks_unintended_everyone_and_role_mentions() -> None:
    source = Path("app/tasks/worker.py").read_text(encoding="utf-8")
    block = source[source.index("async def reminders"):source.index("@reminders.before_loop")]
    assert "allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)" in block
    assert "Reminder.attempt_count < max_attempts" in block
    assert "Reminder.next_attempt_at <= now" in block
    assert "reminder.attempt_count = max_attempts" in block


def test_serial_ids_are_flushed_before_their_values_are_used() -> None:
    checks = {
        "app/discord/cogs/admin.py": [("ShopItem(", "item_id = row.id"), ("Job(", "job_id = row.id")],
        "app/discord/cogs/automod.py": [("AutoModRule(", "rule_id = row.id")],
    }
    for file_name, pairs in checks.items():
        source = Path(file_name).read_text(encoding="utf-8")
        for start_token, id_token in pairs:
            start = source.index(start_token)
            end = source.index(id_token, start) + len(id_token)
            block = source[start:end]
            assert "await session.flush()" in block
            assert block.index("await session.flush()") < block.index(id_token)


def test_command_matrix_contains_each_expected_command_exactly_once() -> None:
    from app.services.command_matrix import EXPECTED_COMMANDS, audit_commands
    names = [case.qualified_name for case in audit_commands()]
    assert len(names) == len(set(names))
    assert set(names) == EXPECTED_COMMANDS


def test_antiraid_has_runtime_redis_fallback() -> None:
    source = Path("app/services/antiraid.py").read_text(encoding="utf-8")
    start = source.index("store = await get_store()")
    end = source.index("context.recent_joins = recent_joins", start)
    block = source[start:end]
    assert "except Exception:" in block
    assert "if store.redis is None:" in block
    assert "RaidWindowStore(None)" in block



def test_ticket_transcripts_are_bounded_and_close_action_is_rate_limited() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    start = source.index("async def ticket_close(self")
    end = source.index('@app_commands.command(name="ticket-reopen"', start)
    block = source[start:end]
    assert 'check_and_set(f"bn:ticket-close:{guild.id}:{interaction.user.id}", 20)' in block
    assert "channel.history(limit=max_transcript_messages, oldest_first=True)" in block
    assert "max_transcript_messages = 1000" in block
    assert "Transcript limitado a" in block

def test_ticket_creation_uses_priority_labels_instead_of_status_labels() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    assert 'priority_labels = {"low": "baixa", "normal": "normal", "high": "alta", "urgent": "urgente"}' in source
    assert 'STATUS_LABELS.get(priority, priority)' not in source


def test_ticket_channel_creation_fetches_uncached_opener() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    block = source[source.index("async def ensure_ticket_channel"):source.index("async def build_ticket_message", source.index("async def ensure_ticket_channel"))]
    assert "guild.get_member(ticket.opener_id)" in block
    assert "await guild.fetch_member(ticket.opener_id)" in block


def test_rewards_falls_back_to_utc_when_saved_timezone_is_invalid() -> None:
    source = Path("app/services/rewards.py").read_text(encoding="utf-8")
    assert "except ZoneInfoNotFoundError:" in source
    assert 'local_now("UTC")' in source


def test_giveaway_result_message_restricts_allowed_mentions() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    block = source[source.index("async def finish_giveaway"):source.index("poll_group =", source.index("async def finish_giveaway"))]
    assert "allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False)" in block


def test_command_matrix_detects_indirect_staff_guard() -> None:
    from app.services.command_matrix import audit_commands
    case = next(case for case in audit_commands() if case.qualified_name == "ticket-claim")
    assert case.permission_guard


def test_command_matrix_enforces_protection_contracts() -> None:
    from app.services.command_matrix import PROTECTED_COMMANDS, audit_commands
    cases = {case.qualified_name: case for case in audit_commands()}
    assert all(cases[name].permission_guard for name in PROTECTED_COMMANDS)


def test_moderation_reversible_actions_are_state_aware() -> None:
    moderation = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    service = Path("app/services/moderation.py").read_text(encoding="utf-8")
    assert "await user.timeout(until, reason=reason)" in moderation
    assert "await guild.fetch_ban(discord.Object(id=target_id))" in moderation
    assert "O usuário `{target_id}` não está banido." in moderation
    assert "if not warning.active:" in service
    assert "return False" in service
    assert "O warn `{target_id}` já está desativado." in moderation


def test_moderation_rate_limit_errors_are_not_generic() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "isinstance(original, discord.RateLimited)" in source
    assert "O Discord está limitando esta ação" in source


def test_diagnostics_covers_all_admin_subcommands() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert 'required = {"credit", "debit", "shop-add", "job-add", "job-remove", "rewards", "timezone"}' in source

def test_command_matrix_ignores_removed_bump_legacy_source() -> None:
    source = Path("app/services/command_matrix.py").read_text(encoding="utf-8")
    assert 'LEGACY_COMMAND_FILES = {"bump.py"}' in source
    assert 'if path.name in LEGACY_COMMAND_FILES:' in source
    assert 'continue' in source



def test_timeout_and_unmute_use_idempotent_member_timeout_api() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    assert 'current = await self._edit_timeout(guild, user, expires_at, clean_reason)' in source
    assert 'current = await self._edit_timeout(guild, user, None, clean_reason)' in source
    assert 'await user.timeout(until, reason=reason)' in source

def test_timeout_uses_the_requested_gif() -> None:
    source = Path("app/discord/theme.py").read_text(encoding="utf-8")
    assert '"timeout": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbmo3ZDM1YTJzMzM4MTU3a21iZW8xMmg2MXpqMDNjcTNyM3l5d3FvNiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/vOVFNit4dmql2N2Gm4/giphy.gif"' in source


def test_economy_logger_is_configured_for_testall() -> None:
    source = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    assert "import logging" in source
    assert 'logger = logging.getLogger("bn_bot.discord.economy")' in source

def test_testall_repairs_stale_discord_command_scopes_once() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "await bot._sync_command_scopes()" in source

def test_timeout_duration_contract_is_not_minutes_only() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    block = source[source.index("def parse_timeout_duration"):source.index('@app_commands.command(name="timeout"')]
    assert 'raw = f"{raw}m"' in block
    assert "parse_twarn_duration(raw)" in block
    assert "28 * 86400" in block
    command = source[source.index('@app_commands.command(name="timeout"'):source.index('async def _edit_timeout')]
    assert 'duration: str' in command
    assert 'Duração: 30s, 15m, 2h ou 7d' in command





def test_production_sync_keeps_user_installable_global_commands_and_syncs_guild_commands() -> None:
    import ast

    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BNBot")
    method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_sync_command_scopes")
    production_if = next(node for node in method.body if isinstance(node, ast.If) and isinstance(node.test, ast.Compare))
    calls = [ast.unparse(node) for node in ast.walk(production_if) if isinstance(node, ast.Await) and isinstance(node.value, ast.Call)]
    assert any("self._sync_guild_commands(guild.id)" in call for call in calls)
    assert any("self._sync_user_installable_global_commands()" in call for call in calls)
    assert not any("self.tree.sync(guild=guild_object)" in call for call in calls)


def test_guild_join_syncs_commands_in_production_too() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    start = source.index("async def on_guild_join")
    end = source.index("async def on_guild_remove", start)
    block = source[start:end]
    assert 'await self._sync_guild_commands(guild.id)' in block
    assert 'if settings.app_env != "production"' not in block


def test_guild_sync_runs_before_optional_user_install_global_sync() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("async def _sync_command_scopes"):source.index("async def _restore_voice_sessions", source.index("async def _sync_command_scopes"))]
    guild_sync = block.index("await self._sync_guild_commands")
    user_sync = block.index("await self._sync_user_installable_global_commands")
    assert guild_sync < user_sync
    assert "except (discord.HTTPException, discord.RateLimited) as exc:" in block
    assert "user-installable global slash commands could not be synchronized" in block


def test_guild_sync_does_not_sync_an_empty_guild_tree_before_real_commands() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("async def _sync_guild_commands"):source.index("async def _ensure_registered_guilds", source.index("async def _sync_guild_commands"))]
    first_sync = block.index("await self.tree.sync(guild=guild_object)")
    add_commands = block.index("for command in guild_copies:")
    add_command = block.index("self.tree.add_command(command, guild=guild_object)", add_commands)
    assert add_command < first_sync
    assert "self.tree.clear_commands(guild=None)" not in block


def test_on_ready_synchronizes_commands_before_database_bootstrap() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("async def on_ready"):source.index("async def close", source.index("async def on_ready"))]
    assert block.index("await self._sync_command_scopes()") < block.index("asyncio.wait_for(self._ensure_registered_guilds(), timeout=15)")
    assert "asyncio.wait_for(self._ensure_registered_guilds(), timeout=15)" in block


def test_main_uses_async_database_head_check_before_sync_alembic() -> None:
    source = Path("main.py").read_text(encoding="utf-8")
    assert "from app.core.migrations import database_at_head, upgrade_to_head" in source
    assert "if await database_at_head():" in source
    assert "asyncio.wait_for(asyncio.to_thread(upgrade_to_head), timeout=35)" in source


def test_alembic_migration_connection_has_timeouts() -> None:
    source = Path("alembic/env.py").read_text(encoding="utf-8")
    assert 'connect_timeout": 15' in source
    assert 'lock_timeout=15000' in source
    assert 'statement_timeout=120000' in source


def test_oauth_state_supports_multiple_tabs_without_overwriting_pending_login() -> None:
    from app.core.security import consume_oauth_state, store_oauth_state

    session = {}
    store_oauth_state(session, "state-one", now=1000)
    store_oauth_state(session, "state-two", now=1001)
    assert consume_oauth_state(session, "state-one", now=1002)
    assert consume_oauth_state(session, "state-two", now=1002)
    assert not consume_oauth_state(session, "state-one", now=1002)


def test_oauth_state_mismatch_does_not_destroy_a_valid_pending_state() -> None:
    from app.core.security import consume_oauth_state, store_oauth_state

    session = {}
    store_oauth_state(session, "valid-state", now=1000)
    assert not consume_oauth_state(session, "wrong-state", now=1001)
    assert consume_oauth_state(session, "valid-state", now=1001)


def test_oauth_state_expires_after_ten_minutes() -> None:
    from app.core.security import consume_oauth_state, store_oauth_state

    session = {}
    store_oauth_state(session, "expired-state", now=1000)
    assert not consume_oauth_state(session, "expired-state", now=1601)


def test_oauth_state_migrates_legacy_single_state_cookie() -> None:
    from app.core.security import consume_oauth_state, store_oauth_state

    session = {"oauth_state": "legacy-state"}
    store_oauth_state(session, "new-state", now=1000)
    assert consume_oauth_state(session, "legacy-state", now=1001)
    assert consume_oauth_state(session, "new-state", now=1001)


def test_dashboard_oauth_uses_session_bound_pending_states_and_actionable_errors() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    assert "store_oauth_state(request.session, state)" in source
    assert "consume_oauth_state(request.session, state)" in source
    assert "OAuth session cookie was not received or has expired" in source
    assert "do not reuse an older callback URL" in source
