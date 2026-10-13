from pathlib import Path


def test_transfer_updates_lifetime_accounting() -> None:
    source = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    block = source[source.index("async def transfer"):source.index("async def get_shop_items", source.index("async def transfer"))]
    assert "sender.lifetime_spent += amount" in block
    assert "receiver.lifetime_earned += amount" in block


def test_job_queries_are_guild_scoped_on_both_sides_of_the_join() -> None:
    for path in ("app/discord/cogs/economy.py", "app/discord/cogs/progression.py"):
        source = Path(path).read_text(encoding="utf-8")
        assert "Job.guild_id == guild.id" in source


def test_dashboard_community_mutations_use_transition_services() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    assert "update_suggestion(session, suggestion_id" in source
    assert "update_report(session, report_id" in source
    assert "set_ticket_status(session, ticket_id" in source
    assert "row.status = payload.status" not in source


def test_dashboard_reopens_closed_tickets_through_the_service_contract() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    assert 'service_status = "reopened" if requested_status == "open" and row.status == "closed" else requested_status' in source


def test_missing_ticket_channel_is_persistently_closed_before_cooldown_check() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    block = source[source.index("existing = await session.scalar(select(Ticket)"):source.index("ticket_row = await create_ticket", source.index("existing = await session.scalar(select(Ticket)"))]
    assert 'await set_ticket_status(session, existing.id, interaction.user.id, "closed"' in block
    assert "await session.commit()" in block
    assert block.index("await session.commit()") < block.index("cooldown = await check_and_set")


def test_automod_allowed_extension_policy_is_strict_for_extensionless_files() -> None:
    source = Path("app/services/automod.py").read_text(encoding="utf-8")
    assert 'bool(allowed_extensions and (not extensions or not extensions.issubset(allowed_extensions)))' in source


def test_diagnostics_command_check_uses_command_matrix_as_canonical_inventory() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "EXPECTED_COMMANDS as MATRIX_EXPECTED_COMMANDS" in source
    assert "unexpected = sorted(name for name in command_names if name not in MATRIX_EXPECTED_COMMANDS)" in source


def test_stale_theme_backup_file_is_removed() -> None:
    assert not Path("app/discord/theme.py.new").exists()


def test_removed_gif_is_absent_from_the_project() -> None:
    needle = "L0eLbQSACTr10" + "Voj83"
    for path in Path(".").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        assert needle not in path.read_text(encoding="utf-8")


def test_dashboard_guild_cache_coalesces_concurrent_discord_requests() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    block = source[source.index("async def session_guilds"):source.index("async def authorized_guild")]
    assert "GUILD_CACHE_TTL_SECONDS = 30" in source
    assert "nx=True" in block
    assert "GUILD_CACHE_LOCK_SECONDS" in block
    assert "await redis_client.eval(_CACHE_LOCK_RELEASE" in block
    assert "json.dumps(dashboard_guilds)" in source
    assert 'json.dumps(result), ex=GUILD_CACHE_TTL_SECONDS' in block


def test_command_sync_uses_bounded_retries_and_avoids_re_syncing_successful_guilds() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    block = source[source.index("def _command_sync_retry_delay"):source.index("async def _ensure_registered_guilds")]
    assert "error.retry_after" in block
    assert "for attempt in range(5)" in block
    assert "min(max(retry_after, delay * 2), 900.0)" in block
    sync_scopes = source[source.index("async def _sync_command_scopes"):source.index("async def _restore_voice_sessions")]
    assert "if guild.id in self._synced_guild_command_ids" in sync_scopes
    assert "await asyncio.gather(*retry_tasks, return_exceptions=True)" in source


def test_community_actions_debounce_public_message_edits() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    assert "async def _run_debounced_refresh" in source
    assert "await asyncio.sleep(2)" in source
    assert "channel.get_partial_message" in source
    assert 'check_and_set(f"bn:suggestion-vote:' in source
    assert 'check_and_set(f"bn:giveaway-enter:' in source
    assert 'check_and_set(f"bn:poll-vote:' in source
    assert "def cog_unload(self)" in source


def test_reminder_retry_honors_discord_retry_after_and_has_a_finite_attempt_budget() -> None:
    source = Path("app/tasks/worker.py").read_text(encoding="utf-8")
    block = source[source.index("async def reminders"):source.index("@reminders.before_loop")]
    assert "max_attempts = 5" in block
    assert "except discord.RateLimited as exc" in block
    assert "delay = max(delay, int(discord_retry_after + 0.999))" in block
    assert "reminder.next_attempt_at = utc_now() + timedelta(seconds=delay)" in block
