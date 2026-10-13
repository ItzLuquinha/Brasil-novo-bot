import pytest
from pathlib import Path
from types import SimpleNamespace

from app.core import db
from app.models import ChannelActivity, EconomyAccount, Experience, InventoryItem, Reputation, UserJob


def test_runtime_database_url_is_normalized_to_asyncpg(monkeypatch) -> None:
    monkeypatch.setattr(db, "get_settings", lambda: SimpleNamespace(database_url="postgresql://user:password@host:5432/db"))
    assert db.async_database_url().drivername == "postgresql+asyncpg"


def test_serial_entities_do_not_request_manual_bigint_ids() -> None:
    source = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    assert "InventoryItem(id=tx_id()" not in source
    assert EconomyAccount.__table__.c.id.autoincrement in (True, "auto")
    assert Experience.__table__.c.id.autoincrement in (True, "auto")
    assert Reputation.__table__.c.id.autoincrement in (True, "auto")
    assert UserJob.__table__.c.id.autoincrement in (True, "auto")
    assert InventoryItem.__table__.c.id.autoincrement in (True, "auto")


def test_new_experience_row_initializes_python_defaults() -> None:
    source = Path("app/services/levels.py").read_text(encoding="utf-8")
    assert "total_xp=0, level=0, rewarded_level=0" in source


def test_buy_item_flushes_new_inventory_before_follow_up_queries() -> None:
    source = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    block_start = source.index("if inv is None:")
    block_end = source.index("if inv.quantity + quantity", block_start)
    assert "await session.flush()" in source[block_start:block_end]


def test_purge_filters_by_author_and_audits_only_confirmed_deletions() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    helper_start = source.index("async def _delete_purge_candidates")
    helper_end = source.index("async def _record_purge_action", helper_start)
    helper = source[helper_start:helper_end]
    assert "message.author.id == user.id" in helper
    assert "channel.history(limit=amount" in helper
    assert "deleted.extend(batch)" in helper
    assert "await message.delete()" in helper
    assert "await message.delete(reason=reason)" not in helper
    assert "await delete_many(batch, reason=reason)" in helper
    audit_start = source.index("async def _record_purge_action")
    audit_end = source.index("async def _send_purge_log", audit_start)
    audit = source[audit_start:audit_end]
    assert '"deleted_message_ids": [message.id for message in deleted]' in audit
    assert '"amount_deleted": len(deleted)' in audit


def test_message_deletions_do_not_pass_unsupported_reason_keyword() -> None:
    moderation = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    automod = Path("app/discord/cogs/automod.py").read_text(encoding="utf-8")
    assert "message.delete(reason=" not in moderation
    assert "message.delete(reason=" not in automod
    assert "await message.delete()" in moderation
    assert "await message.delete()" in automod


def test_purge_supports_1000_messages_and_handles_discord_failures() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    start = source.index("async def purge(")
    block = source[start:]
    assert "app_commands.Range[int, 1, 1000]" in block
    assert "bot_permissions.read_message_history" in block
    assert "bot_permissions.view_channel" in block
    assert "try:" in block and "_delete_purge_candidates" in block
    assert "_record_purge_action" in block and "_send_purge_log" in block
    assert "except discord.RateLimited" in block
    assert "except discord.Forbidden" in block
    assert "except discord.HTTPException" in block


def test_poll_create_exposes_two_required_options() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    assert "option1: str" in source
    assert "option2: str" in source
    assert "options: str" not in source
    assert 'option1="Opção 1, obrigatória"' in source
    assert 'option2="Opção 2, obrigatória"' in source


def test_poll_create_supports_optional_options_three_to_ten() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    for index in range(3, 11):
        assert f"option{index}: str | None = None" in source


def test_testall_checks_actual_economy_result() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "expected_wallet = 40" in source
    assert "expected_bank = 30" in source
    assert "inventory_quantity == 1" in source
    assert "loaded_stock_value == 4" in source


def test_testall_includes_interaction_safety_and_poll_validation() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "_interaction_safety_check()" in source
    assert "_poll_validation_smoke()" in source
    assert "_security_surface_check()" in source
    assert "_code_hygiene_check()" in source


def test_command_handlers_defer_before_io() -> None:
    import ast

    root = Path("app/discord/cogs")
    issues = []
    io_names = {"ban", "create_role", "create_text_channel", "edit", "execute", "fetch_channel", "fetch_message", "history", "kick", "purge", "scalar", "send", "set_permissions", "timeout", "unban"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            decorators = [ast.unparse(value) for value in node.decorator_list]
            if not any(value.endswith(".command") or ".command(" in value or value.startswith("app_commands.command") for value in decorators):
                continue
            calls = sorted((value for value in ast.walk(node) if isinstance(value, ast.Call)), key=lambda value: value.lineno)
            defer_lines = [value.lineno for value in calls if ast.unparse(value.func) in {"defer", "interaction.response.defer"}]
            first_defer = min(defer_lines) if defer_lines else None
            for call in calls:
                name = ast.unparse(call.func)
                final = name.rsplit(".", 1)[-1]
                io = name == "session_factory" or name.startswith("redis_client.") or name.endswith("check_and_set") or (name.startswith("session.") and final in {"execute", "get", "scalar", "flush", "commit", "rollback", "delete"}) or (not name.startswith("interaction.response.") and not name.startswith("interaction.followup.") and final in io_names)
                if io and (first_defer is None or call.lineno < first_defer):
                    issues.append(f"{path.name}:{node.name}:{call.lineno}")
                if name == "interaction.response.send_message" and first_defer is not None and call.lineno > first_defer:
                    issues.append(f"{path.name}:{node.name}:{call.lineno}:response")
    assert issues == []


def test_requirements_include_greenlet_for_sqlalchemy_asyncio() -> None:
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    assert '"greenlet>=3.1,<4"' in pyproject
    assert "greenlet>=3.1,<4" in requirements


def test_windows_setup_uses_project_python() -> None:
    root = Path(__file__).parents[1]
    setup = (root / "docs" / "SETUP_WINDOWS.md").read_text(encoding="utf-8")
    assert r'`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`' in setup


def test_suggestion_vote_flushes_for_same_transaction_reads() -> None:
    source = Path("app/services/community.py").read_text(encoding="utf-8")
    start = source.index("async def cast_suggestion_vote")
    end = source.index("async def update_suggestion", start)
    block = source[start:end]
    assert "await session.flush()" in block


def test_giveaway_toggle_flushes_new_entry() -> None:
    source = Path("app/services/community.py").read_text(encoding="utf-8")
    start = source.index("async def enter_giveaway")
    end = source.index("async def end_giveaway", start)
    block = source[start:end]
    assert "await session.flush()" in block


def test_xp_flushes_after_progression_update() -> None:
    source = Path("app/services/levels.py").read_text(encoding="utf-8")
    assert "row.updated_at = now\n    await session.flush()" in source


def test_sequences_diagnostics_targets_sequence_backed_tables() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    start = source.index("SERIAL_TABLES = {")
    end = source.index("\n}\nREQUIRED_COMMANDS", start) + 2
    block = source[start:end]
    for table in ("member_activity", "polls", "punishments", "tickets", "warnings"):
        assert f'"{table}"' in block


def test_security_scan_does_not_search_for_its_own_source_pattern() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "DISCORD_TOKEN = \"" not in source
    assert "ast.parse(path.read_text(encoding=\"utf-8\"))" in source


def test_interaction_scanner_does_not_classify_dict_get_as_io() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert '    "get",\n' not in source
    assert '"get_guild_settings"' in source


def test_testall_includes_transaction_error_and_orm_checks() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "_transaction_safety_check()" in source
    assert "_error_handling_check()" in source
    assert "_model_sequence_alignment_check()" in source
    transaction_source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "async def cast_suggestion_vote" in transaction_source
    assert "async def enter_giveaway" in transaction_source


def test_main_reexecutes_with_project_venv_when_available() -> None:
    source = Path("main.py").read_text(encoding="utf-8")
    assert "ensure_project_venv(Path(__file__).resolve().parent)" in source
    assert "from app.core.runtime import ensure_project_venv" in source
    assert "A .venv do projeto não está em uso" not in source


def test_doctor_uses_the_same_project_venv_guard_as_main() -> None:
    source = Path("scripts/doctor.py").read_text(encoding="utf-8")
    assert "ensure_project_venv(PROJECT_ROOT)" in source
    assert "from app.core.runtime import ensure_project_venv" in source


def test_community_entity_models_use_autoincrement() -> None:
    from app.models import MemberActivity, Poll, Punishment, Ticket, Warning

    models = (MemberActivity, Poll, Punishment, Ticket, Warning)
    assert all(model.__table__.c.id.autoincrement in (True, "auto") for model in models)


def test_sequence_migration_exists() -> None:
    migration = Path("alembic/versions/0006_autoincrement_ids.py").read_text(encoding="utf-8")
    assert 'TABLES = ("member_activity", "polls", "punishments", "tickets", "warnings")' in migration
    assert 'CREATE SEQUENCE IF NOT EXISTS public.{sequence} AS BIGINT' in migration
    assert 'SET DEFAULT nextval' in migration
    assert 'ALTER SEQUENCE public.{sequence} OWNED BY' in migration


def test_analytics_diagnostic_is_registered() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "async def _analytics_smoke" in source
    assert "results.append(await _analytics_smoke" in source


def test_alembic_can_import_project_from_source_tree() -> None:
    config = Path("alembic.ini").read_text(encoding="utf-8")
    env = Path("alembic/env.py").read_text(encoding="utf-8")
    assert "prepend_sys_path = ." in config
    assert "PROJECT_ROOT = Path(__file__).resolve().parents[1]" in env
    assert "sys.path.insert(0, str(PROJECT_ROOT))" in env


def test_windows_setup_uses_current_python_for_alembic() -> None:
    root = Path(__file__).parents[1]
    setup = (root / "docs" / "SETUP_WINDOWS.md").read_text(encoding="utf-8")
    assert r"`.\.venv\Scripts\python.exe -m alembic upgrade head`" in setup


def test_channel_activity_uses_autoincrement() -> None:
    assert ChannelActivity.__table__.c.id.autoincrement in (True, "auto")


def test_channel_activity_sequence_migration_exists() -> None:
    migration = Path("alembic/versions/0007_channel_activity_sequence.py").read_text(encoding="utf-8")
    assert 'revision = "0007_channel_activity_sequence"' in migration
    assert "channel_activity_id_seq" in migration
    assert "SET DEFAULT nextval" in migration


def test_testall_includes_remote_command_sync() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "async def _remote_command_sync_check" in source
    assert "results.append(await _remote_command_sync_check(bot, guild_id))" in source

def test_external_command_groups_are_replaced_with_current_definitions() -> None:
    admin_source = Path("app/discord/cogs/admin.py").read_text(encoding="utf-8")
    raid_source = Path("app/discord/cogs/antiraid.py").read_text(encoding="utf-8")
    assert "if bot.tree.get_command(admin_group.name) is None:" in admin_source
    assert "bot.tree.add_command(admin_group)" in admin_source
    assert "if bot.tree.get_command(raid_group.name) is None:" in raid_source
    assert "bot.tree.add_command(raid_group)" in raid_source


def test_development_command_sync_is_guild_scoped() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "self.tree.copy_global_to(guild=guild_object)" not in source
    assert "self.tree.add_command(command, guild=guild_object)" in source
    assert "await self.tree.sync(guild=guild_object)" in source

def test_discord_guild_id_is_configurable() -> None:
    source = Path("app/config.py").read_text(encoding="utf-8")
    assert "discord_guild_id: int | None = None" in source


def test_remote_command_sync_ignores_group_nodes() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert 'if not getattr(command, "commands", None)' in source

def test_channel_activity_is_in_sequence_alignment() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert '"channel_activity": ChannelActivity' in source
    serial_start = source.index("SERIAL_TABLES = {")
    assert '"channel_activity"' in source[serial_start:]


def test_admin_audit_has_logger() -> None:
    source = Path("app/discord/cogs/admin.py").read_text(encoding="utf-8")
    assert 'import logging' in source
    assert 'logger = logging.getLogger("bn_bot.discord.admin")' in source


def test_diagnostics_imports_channel_activity() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "ChannelActivity" in source.split("from app.models import ", 1)[1].split("\n", 1)[0]


def test_ticket_reopen_repairs_missing_or_deleted_panel() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    start = source.index('async def ticket_reopen_command')
    end = source.index('async def ticket_claim_command', start)
    block = source[start:end]
    assert 'except discord.NotFound:' in block
    assert 'ticket_row.panel_message_id = message.id' in block


def test_giveaway_enter_rejects_expired_giveaway() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    start = source.index('async def giveaway_enter')
    end = source.index('async def finish_giveaway', start)
    block = source[start:end]
    assert 'giveaway.ends_at <= utc_now()' in block
    assert 'Este sorteio já foi encerrado.' in block


def test_testall_audit_failure_is_best_effort() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    start = source.index('async def testall')
    block = source[start:]
    assert 'testall audit persistence failed' in block
    assert 'except Exception:' in block


def test_interaction_scan_catches_response_edit_and_duplicate_defer() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert 'interaction.response.edit_message' in source
    assert 'múltiplos defer' in source


def test_utility_imports_visual_helpers_it_uses() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    imports = source.split('from app.discord.theme import ', 1)[1].split('\n', 1)[0]
    assert 'status_line' in imports
    assert 'bar(' not in source




def test_project_audit_skips_secret_environment_files() -> None:
    source = Path("scripts/audit.py").read_text(encoding="utf-8")
    assert '".env"' in source
    assert 'path.name in SKIP_FILES' in source

def test_command_source_safety_diagnostic_is_registered() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "def _command_source_safety_check" in source
    assert "_command_source_safety_check()," in source


def test_float_command_ranges_use_float_bounds() -> None:
    economy = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    admin = Path("app/discord/cogs/admin.py").read_text(encoding="utf-8")
    assert "MAX_TRANSACTION = 1_000_000_000.0" in economy
    assert "MAX_ADMIN_AMOUNT = 1_000_000_000.0" in admin
    assert "Range[float, 0.01, MAX_TRANSACTION]" in economy
    assert "Range[float, 0.01, MAX_ADMIN_AMOUNT]" in admin


def test_command_import_preflight_covers_all_cogs() -> None:
    main = Path("main.py").read_text(encoding="utf-8")
    doctor = Path("scripts/doctor.py").read_text(encoding="utf-8")
    for module_name in (
        "app.discord.cogs.utility",
        "app.discord.cogs.economy",
        "app.discord.cogs.progression",
        "app.discord.cogs.moderation",
        "app.discord.cogs.community",
        "app.discord.cogs.automod",
        "app.discord.cogs.admin",
        "app.discord.cogs.antiraid",
    ):
        assert module_name in main
        assert module_name in doctor


def test_all_float_range_constants_are_float_typed() -> None:
    import ast

    for relative_path, constant_name in (
        ("app/discord/cogs/economy.py", "MAX_TRANSACTION"),
        ("app/discord/cogs/admin.py", "MAX_ADMIN_AMOUNT"),
    ):
        tree = ast.parse(Path(relative_path).read_text(encoding="utf-8"))
        assignments = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == constant_name for target in node.targets)
        ]
        assert assignments
        assert isinstance(assignments[0].value, ast.Constant)
        assert type(assignments[0].value.value) is float


def test_doctor_checks_command_definitions_before_runtime() -> None:
    source = Path("scripts/doctor.py").read_text(encoding="utf-8")
    assert "Command definitions: OK" in source
    assert "Command definitions: ERRO" in source


def test_script_entrypoints_bootstrap_project_root() -> None:
    doctor = Path("scripts/doctor.py").read_text(encoding="utf-8")
    seed = Path("scripts/seed.py").read_text(encoding="utf-8")
    for source in (doctor, seed):
        assert "PROJECT_ROOT = Path(__file__).resolve().parents[1]" in source
        assert "sys.path.insert(0, str(PROJECT_ROOT))" in source


def test_doctor_can_load_commands_when_invoked_as_script() -> None:
    source = Path("scripts/doctor.py").read_text(encoding="utf-8")
    root_bootstrap = source.index("PROJECT_ROOT =")
    import_block = source.index("command_modules =")
    assert root_bootstrap < import_block


def test_message_log_insert_is_idempotent_and_persists_message_id() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "repositories" / "analytics.py").read_text(encoding="utf-8")
    assert "pg_insert(MessageLog).values(" in source
    assert "message_id=message_id" in source
    assert ".on_conflict_do_nothing(index_elements=[MessageLog.id])" in source
    assert ".returning(MessageLog.id)" in source


def test_admin_credit_is_nested_under_admin_group() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "discord" / "cogs" / "admin.py").read_text(encoding="utf-8")
    assert '@admin_group.command(name="credit"' in source
    assert '@app_commands.command(name="credit"' not in source


def test_persistent_component_views_define_error_handler() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "discord" / "cogs" / "community.py").read_text(encoding="utf-8")
    assert "class BNComponentView" in source
    assert "async def on_error" in source
    assert "class PollView(BNComponentView)" in source


def test_tutorial_select_does_not_use_decorative_geometry() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "discord" / "cogs" / "utility.py").read_text(encoding="utf-8")
    assert "◆" not in source
    assert "◇" not in source
    assert "✓" not in source
    assert "×" not in source


def test_tree_error_handler_is_installed() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "discord" / "bot.py").read_text(encoding="utf-8")
    assert "self.tree.on_error = self.on_app_command_error" in source


def test_message_logging_call_supplies_message_id() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "repositories" / "analytics.py").read_text(encoding="utf-8")
    assert "message_id=message_id" in source



def test_app_command_group_registration_replaces_stale_definitions() -> None:
    for relative, group_name in (
        ("app/discord/cogs/admin.py", "admin_group"),
        ("app/discord/cogs/automod.py", "automod_group"),
        ("app/discord/cogs/antiraid.py", "raid_group"),
    ):
        source = Path(relative).read_text(encoding="utf-8")
        assert f"if bot.tree.get_command({group_name}.name) is None:" in source
        assert f"bot.tree.add_command({group_name})" in source


def test_reward_claim_insert_and_wallet_credit_share_savepoint() -> None:
    source = Path("app/services/rewards.py").read_text(encoding="utf-8")
    start = source.index("    try:\n        async with session.begin_nested():", source.index("async def claim_reward"))
    end = source.index("    except IntegrityError", start)
    block = source[start:end]
    assert "session.add(RewardClaim(" in block
    assert "await session.flush()" in block
    assert "await add_wallet(" in block


def test_dashboard_rejects_invalid_timezone_locale_and_updates_timestamp() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    assert "ZoneInfo(normalized)" in source
    assert 'raise ValueError("Timezone must be a valid IANA timezone")' in source
    assert 'raise ValueError("Locale must be pt-BR or en-US")' in source
    assert "settings_row.updated_at = datetime.now(timezone.utc)" in source
    assert '"guild.settings_update"' in source


def test_activity_endpoint_scopes_top_channels_to_requested_period() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    assert 'top_channels(session, guild_id, "messages", days=days)' in source


@pytest.mark.asyncio
async def test_claim_reward_maps_unique_race_to_cooldown(monkeypatch) -> None:
    from decimal import Decimal
    from sqlalchemy.exc import IntegrityError
    from app.core.exceptions import CooldownActive
    from app.services import rewards

    class Result:
        def scalar_one_or_none(self):
            return None

    class Nested:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class Session:
        def __init__(self):
            self.added = []
            self.flushes = 0
        async def get(self, *_args, **_kwargs):
            return None
        async def execute(self, *_args, **_kwargs):
            return Result()
        def add(self, value):
            self.added.append(value)
        def begin_nested(self):
            return Nested()
        async def flush(self):
            self.flushes += 1
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))

    credited = False
    async def fake_add_wallet(*_args, **_kwargs):
        nonlocal credited
        credited = True

    monkeypatch.setattr(rewards, "add_wallet", fake_add_wallet)
    session = Session()
    with pytest.raises(CooldownActive):
        await rewards.claim_reward(session, 1, 2, "daily", Decimal("50.00"))
    assert session.flushes == 1
    assert credited is False



def test_dashboard_automod_errors_are_escaped() -> None:
    source = Path("app/dashboard/static/app.js").read_text(encoding="utf-8")
    assert "automodRules.innerHTML=`<p>${esc(error.message)}</p>`" in source
    assert "automodRules.innerHTML=`<p>${error.message}</p>`" not in source


def test_giveaway_reroll_keeps_full_winner_history() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    start = source.index("async def giveaway_reroll")
    end = source.index('async def giveaway_cancel', start)
    block = source[start:end]
    assert 'safe_int_list((giveaway.requirements or {}).get("winner_ids", []), 10_000)' in block


def test_antiraid_disable_retries_pending_lockdown_cleanup() -> None:
    source = Path("app/discord/cogs/antiraid.py").read_text(encoding="utf-8")
    start = source.index('async def disable')
    end = source.index('async def configure', start)
    block = source[start:end]
    assert 'pending = await self.lockdown_pending_count(interaction.guild.id)' in block
    assert 'row.active_until = None' in block
    assert 'if pending:' not in block


def test_dashboard_rejects_corrupt_redis_session_payload() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    start = source.index('async def get_dashboard_token')
    end = source.index('async def session_guilds', start)
    block = source[start:end]
    assert 'except (TypeError, ValueError):' in block
    assert 'request.session.clear()' in block
    assert 'isinstance(data, dict)' in block


def test_dashboard_imports_guild_model_used_by_session_guilds() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    import_line = next(line for line in source.splitlines() if line.startswith("from app.models import "))
    assert "Guild" in import_line
    assert "select(Guild.id)" in source


def test_community_imports_status_line_used_by_commands() -> None:
    source = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    import_line = next(line for line in source.splitlines() if line.startswith("from app.discord.theme import "))
    assert "status_line" in import_line
    assert source.count("status_line(") >= 5


def test_automod_rejects_non_finite_numeric_config() -> None:
    source = Path("app/services/automod.py").read_text(encoding="utf-8")
    assert "math.isfinite(float(value))" in source
    assert "número finito" in source


def test_automod_role_allowlists_ignore_malformed_ids() -> None:
    source = Path("app/services/automod.py").read_text(encoding="utf-8")
    assert "except (TypeError, ValueError):" in source
    assert source.count("int(value) in context.role_ids") >= 2


def test_community_end_operations_require_active_state() -> None:
    source = Path("app/services/community.py").read_text(encoding="utf-8")
    giveaway = source[source.index("async def end_giveaway"):source.index("async def add_poll_vote", source.index("async def end_giveaway"))]
    poll = source[source.index("async def end_poll"):source.index("async def open_items", source.index("async def end_poll"))]
    assert 'if giveaway.status != "active":' in giveaway
    assert 'if poll.status != "active":' in poll


def test_bot_member_sync_preserves_banner_and_identity_fields() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "member.banner.url if member.banner else None, member.bot" in source
    assert "message.author.banner.url if message.author.banner else None, message.author.bot" in source


def test_automod_validates_suspicious_weights_and_similarity_min_length() -> None:
    source = Path("app/services/automod.py").read_text(encoding="utf-8")
    assert '"new_account_weight", "new_member_weight", "invite_weight", "link_weight", "mention_weight", "activity_weight"' in source
    assert '"min_length"' in source
    assert "math.isfinite(float(value))" in source


def test_dashboard_automod_create_normalizes_name_and_handles_race_conflicts() -> None:
    source = Path("app/dashboard/main.py").read_text(encoding="utf-8")
    start = source.index("async def create_automod_rule")
    end = source.index("async def patch_automod_rule", start)
    block = source[start:end]
    assert 'name = " ".join(payload.name.split())' in block
    assert 'if not name:' in block
    assert 'func.lower(AutoModRule.name) == name.casefold()' in block
    assert 'except IntegrityError:' in block


def test_automod_kick_and_ban_are_persisted_in_moderation_history() -> None:
    source = Path("app/discord/cogs/automod.py").read_text(encoding="utf-8")
    start = source.index("    async def execute_action")
    end = source.index('    @automod_group.command(name="enable"', start)
    block = source[start:end]
    assert 'record_punishment(session, message.guild.id, member.id' in block
    assert '"kick"' in block and '"ban"' in block


def test_embed_theme_uses_minimal_branding_and_no_default_gif() -> None:
    source = Path("app/discord/theme.py").read_text(encoding="utf-8")
    start = source.index("def embed(")
    end = source.index("def money(", start)
    block = source[start:end]
    assert "def _clean_title(title: str) -> str:" in source
    assert 'if cleaned.upper().startswith("BN /"):' in source
    assert 'show_gif: bool = False' in block
    assert 'result.set_author(' not in block
    assert 'result.set_footer(' not in block
    assert 'timestamp=discord.utils.utcnow()' not in block


def test_tutorial_panel_does_not_show_a_fake_full_progress_bar() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert 'name="Carga do módulo"' not in source
    assert 'name="Primeiro contato"' in source
    assert 'name="Para a equipe"' in source


def test_development_does_not_sync_commands_globally_from_setup_hook() -> None:
    import ast

    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    setup = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BNBot")
    setup_hook = next(node for node in setup.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "setup_hook")
    calls = [
        ast.unparse(node)
        for node in ast.walk(setup_hook)
        if isinstance(node, ast.Call)
    ]
    assert not any(call == "self.tree.sync()" for call in calls)
    ready = next(node for node in setup.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "on_ready")
    assert "await self._sync_command_scopes()" in ast.unparse(ready)


def test_development_command_sync_clears_stale_global_commands() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    start = source.index("async def _clear_global_commands")
    end = source.index("async def _sync_guild_commands", start)
    block = source[start:end]
    assert "self.tree.clear_commands(guild=None)" in block
    assert "await self.tree.sync()" in block
    assert "for command in global_commands:" in block





def test_remote_command_signatures_flattens_all_group_children_from_payload() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    start = source.index("def _remote_command_signatures")
    end = source.index("async def _remote_command_sync_check", start)
    block = source[start:end]
    assert "data = command.to_dict()" in block
    assert "has_subcommands = any(_enum_int(option.get(\"type\", 0)) in {1, 2} for option in options)" in block
    assert "if has_subcommands:" in block
    assert "walk_options(options, top_name)" in block
    assert 'result[qualified] = ("1", option_name, _remote_option_signature(nested))' in block

def test_remote_command_parser_flattens_group_subcommands_from_exact_payload() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    start = source.index("def _remote_option_signature")
    end = source.index("async def _remote_command_sync_check", start)
    block = source[start:end]
    assert "data = command.to_dict()" in block
    assert "has_subcommands = any(_enum_int(option.get(\"type\", 0)) in {1, 2} for option in options)" in block
    assert "if has_subcommands:" in block
    assert "walk_options(options, top_name)" in block
    assert 'result[qualified] = ("1", option_name, _remote_option_signature(nested))' in block


def test_remote_command_signatures_recognizes_slash_groups_with_root_type_one() -> None:
    import ast
    from pathlib import Path
    from typing import Any

    source = ast.parse(Path("app/services/diagnostics.py").read_text(encoding="utf-8"))
    names = {"_enum_int", "_remote_option_signature", "_remote_command_signatures"}
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"Any": Any}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "diagnostics_helpers.py", "exec"), namespace)
    _remote_command_signatures = namespace["_remote_command_signatures"]

    class RemoteCommand:
        def __init__(self, payload):
            self.payload = payload

        def to_dict(self):
            return self.payload

    commands = [
        RemoteCommand({
            "name": "admin", "type": 1, "options": [
                {"name": "credit", "type": 1, "options": [
                    {"name": "member", "type": 6, "required": True},
                    {"name": "amount", "type": 4, "required": True},
                ]},
                {"name": "shop", "type": 2, "options": [
                    {"name": "add", "type": 1, "options": [
                        {"name": "name", "type": 3, "required": True},
                    ]},
                ]},
            ],
        }),
        RemoteCommand({"name": "ping", "type": 1, "options": []}),
        RemoteCommand({"name": "User Info", "type": 2, "options": []}),
    ]

    signatures = _remote_command_signatures(commands)
    assert set(signatures) == {"admin credit", "admin shop add", "ping", "User Info"}
    assert signatures["admin credit"][0:2] == ("1", "credit")
    assert signatures["admin shop add"][0:2] == ("1", "add")
    assert signatures["ping"][0:2] == ("1", "ping")
    assert signatures["User Info"][0:2] == ("2", "User Info")


def test_module_level_group_commands_are_bound_to_their_cog_before_tree_registration() -> None:
    for filename in ("admin.py", "automod.py", "antiraid.py"):
        source = Path("app/discord/cogs") / filename
        block = source.read_text(encoding="utf-8")
        start = block.index("def add_to_tree")
        section = block[start:]
        assert "binding: commands.Cog | None = None" in section
        assert "command._copy_with(parent=" in section
        assert "binding=binding" in section
        assert "bot.tree.add_command(" in section


def test_setup_hook_passes_cog_bindings_to_module_level_groups() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "add_to_tree(self, admin_cog)" in source
    assert "add_automod_to_tree(self, automod_cog)" in source
    assert "add_antiraid_to_tree(self, antiraid_cog)" in source

def test_command_serialization_passes_command_tree() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "payload = command.to_dict(bot.tree)" in source
    assert "data = command.to_dict(tree)" in source


def test_command_source_safety_unparses_ast_callable_nodes() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "def _called_name(node: ast.AST) -> str:" in source
    assert "return ast.unparse(node)" in source
    assert "name = _called_name(call.func)" in source


def test_xp_diagnostic_snapshots_first_row_before_second_add() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "first_row_total = row.total_xp if row is not None else None" in source
    assert "first_row_level = row.level if row is not None else None" in source
    assert "first_row_total == 101 and first_row_level == 1" in source


def test_analytics_diagnostic_counts_message_logs_with_sqlalchemy_in_clause() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "MessageLog.id.in_([first_message, second_message])" in source
    assert "from app.models import ChannelActivity, EconomyAccount, Experience, Giveaway, GuildSettings, Member, MessageLog" in source


def test_discord_command_diagnostic_checks_global_and_guild_scopes() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "return await bot.tree.fetch_commands(guild=guild_object), await bot.tree.fetch_commands()" in source
    assert "mesmo comando em guilda e global" in source
    assert "user-install ausentes globais" in source
    assert "ausentes na guilda" in source


def test_tutorial_select_does_not_use_static_custom_id() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert 'custom_id="bn:help:category"' not in source


def test_remote_command_type_supports_discord_enum_values() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "def _enum_int(value: Any, default: int = 0) -> int:" in source
    assert 'raw = getattr(value, "value", value)' in source


def test_analytics_smoke_flushes_and_uses_unique_probe_ids() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "probe_user_id = secrets.randbits(50)" in source
    assert "probe_channel_id = secrets.randbits(50)" in source
    assert "await session.flush()" in source[source.index('async def _analytics_smoke'):source.index('def _automod_smoke')]


def test_ping_only_shows_pong_and_latency() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    start = source.index('async def ping(self, interaction: discord.Interaction)')
    end = source.index('    @user_installable', start)
    block = source[start:end]
    assert 'await interaction.response.send_message(f"Pong! `{latency} ms`")' in block
    assert 'page.add_field' not in block
    assert 'Escala de resposta' not in block


def test_embed_theme_defaults_to_no_gif_and_keeps_optional_custom_color() -> None:
    source = Path("app/discord/theme.py").read_text(encoding="utf-8")
    assert "show_gif: bool = False" in source
    assert "color_override: int | None = None" in source
    assert "timestamp=discord.utils.utcnow()" not in source
    assert "if show_gif:" in source


def test_requirements_install_discord_voice_extras_for_optional_voice_support() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "discord.py[voice]==2.7.1" in requirements
    assert '"discord.py[voice]==2.7.1"' in pyproject


def test_gifs_are_opt_in_for_command_embeds() -> None:
    theme = Path("app/discord/theme.py").read_text(encoding="utf-8")
    utility = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert '"progression": "https://' in theme
    assert '"levelup": "https://' in theme
    assert 'show_gif: bool = False' in theme
    ping_start = utility.index('async def ping(self, interaction: discord.Interaction)')
    ping_end = utility.index('    @user_installable', ping_start)
    assert 'Pong! `{latency} ms`' in utility[ping_start:ping_end]


def test_command_embeds_use_gifs_only_when_explicitly_requested() -> None:
    source = Path("app/discord/theme.py").read_text(encoding="utf-8")
    assert 'def gif_for_title(title: str, section: str = "system") -> str | None:' in source
    assert "gif_url = gif_for_title(title, section)" in source
    assert "show_gif: bool = False" in source
    assert "if show_gif:" in source
    for key in ("system", "economy", "moderation", "community", "security", "admin", "fun", "work", "money", "shopping", "purchase", "reward", "warning", "timeout", "kick", "ban", "unban", "purge", "support", "idea", "report", "giveaway", "poll", "lockdown", "respect", "coinflip", "dice", "rps", "eightball", "reminder", "robot", "celebrate"):
        assert f'"{key}": "https://' in source


def test_critical_admin_commands_defer_before_any_work() -> None:
    import ast
    for name in ("credit", "debit", "shop_add", "job_add", "timezone"):
        source = Path("app/discord/cogs/admin.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(item for item in ast.walk(tree) if isinstance(item, ast.AsyncFunctionDef) and item.name == name)
        calls = sorted((item for stmt in node.body for item in ast.walk(stmt) if isinstance(item, ast.Call)), key=lambda item: item.lineno)
        defer_line = next(item.lineno for item in calls if ast.unparse(item.func).split(".")[-1] == "defer")
        assert defer_line == calls[0].lineno


def test_antiraid_critical_commands_start_with_defer() -> None:
    import ast
    source = Path("app/discord/cogs/antiraid.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for name in ("setup", "enable", "disable"):
        node = next(item for item in ast.walk(tree) if isinstance(item, ast.AsyncFunctionDef) and item.name == name)
        calls = sorted((item for stmt in node.body for item in ast.walk(stmt) if isinstance(item, ast.Call)), key=lambda item: item.lineno)
        defer_line = next(item.lineno for item in calls if ast.unparse(item.func).split(".")[-1] == "defer")
        assert defer_line == calls[0].lineno


def test_tutorial_categorizes_ticket_leaf_commands_as_community() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    start = source.index('async def tutorial')
    block = source[start:source.index('page = embed("BN / TUTORIAL"', start)]
    community_start = block.index('"comunidade":')
    community_end = block.index('"seguranca":', community_start)
    community = block[community_start:community_end]
    for name in ("ticket-close", "ticket-reopen", "ticket-claim", "ticket-config"):
        assert name in community


def test_automod_timeout_does_not_persist_when_author_is_not_a_member() -> None:
    source = Path("app/discord/cogs/automod.py").read_text(encoding="utf-8")
    start = source.index('if action == "timeout":')
    end = source.index('if action == "kick":', start)
    block = source[start:end]
    assert 'if member is None:' in block
    assert 'raise ValidationFailure("Não foi possível aplicar timeout neste autor.")' in block
    assert 'record_punishment(session, message.guild.id, member.id' in block


def test_remind_rejects_oversized_messages_instead_of_truncating() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    start = source.index("async def remind")
    end = source.index('@app_commands.command(name="history"', start)
    block = source[start:end]
    assert "if len(text) > 2000:" in block
    assert "O lembrete pode ter no máximo 2000 caracteres." in block


def test_command_matrix_has_an_exact_expected_command_inventory() -> None:
    from app.services.command_matrix import EXPECTED_COMMANDS, audit_commands
    actual = {case.qualified_name for case in audit_commands()}
    assert actual == EXPECTED_COMMANDS
    assert len(actual) == len(EXPECTED_COMMANDS)



def test_user_install_support_is_explicit_and_scoped_to_safe_commands() -> None:
    bot_source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "self.tree.allowed_installs = discord.app_commands.AppInstallationType(guild=True, user=False)" in bot_source
    assert "self.tree.allowed_contexts = discord.app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False)" in bot_source
    assert "async def _sync_user_installable_global_commands" in bot_source
    assert "await self._sync_user_installable_global_commands()" in bot_source

    safe_files = {
        "app/discord/cogs/utility.py": ("ping", "uptime", "botinfo", "avatar", "tutorial"),
        "app/discord/cogs/fun.py": ("coinflip", "dice", "rps", "eightball"),
    }
    for filename, names in safe_files.items():
        source = Path(filename).read_text(encoding="utf-8")
        for name in names:
            start = source.find(f'@app_commands.command(name="{name}"')
            assert start >= 0
            block_start = source.rfind("@user_installable", 0, start)
            assert block_start >= 0
            assert start - block_start < 200


def test_dm_install_message_has_rate_limit_and_server_and_user_install_links() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    start = source.index("    async def on_message")
    end = source.index("    async def on_app_command_completion", start)
    block = source[start:end]
    assert 'bn:dm-install:{message.author.id}' in block
    assert 'integration_type": "0"' in block
    assert 'integration_type": "1"' in block
    assert 'scope": "bot applications.commands"' in block
    assert "client_id = self.application_id" in block
    assert 'scope": "applications.commands"' in block
    assert 'label="Adicionar ao servidor"' in block
    assert 'label="Adicionar como App"' in block
    assert 'allowed_mentions=discord.AllowedMentions.none()' in block


def test_user_installable_commands_are_not_guild_install_only() -> None:
    for filename in ("utility.py", "fun.py"):
        source = Path("app/discord/cogs") / filename
        text = source.read_text(encoding="utf-8")
        assert "from app.discord.app_contexts import user_installable" in text


def test_testall_uses_one_ephemeral_message_with_embed_pages() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    start = source.index('async def testall')
    block = source[start:]
    assert "class TestallView(discord.ui.View):" in source
    assert "await interaction.edit_original_response(embed=pages[0], view=view)" in block
    assert "interaction.followup.send" not in block
    assert "self.page_button.label = f\"{self.page_index + 1} / {total}\"" in source
    assert 'label="Anterior"' in source
    assert 'label="Próxima"' in source
    assert 'label="Primeira"' in source
    assert 'label="Última"' in source


def test_project_python_source_has_no_comments() -> None:
    import io
    import tokenize
    root = Path(".")
    comments = []
    generated_dirs = {".venv", "venv", "site-packages", "node_modules", "dist", "dist-ssr", "build", ".git", "__pycache__", ".pytest_cache"}
    for path in root.rglob("*.py"):
        if any(part in generated_dirs for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                comments.append(f"{path}:{token.start[0]}")
    assert comments == []

def test_project_frontend_source_has_no_comment_blocks() -> None:
    root = Path("app")
    comments = []
    for pattern, markers in (("*.js", ("//", "/*", "*/")), ("*.css", ("/*", "*/")), ("*.html", ("<!--", "-->"))):
        for path in root.rglob(pattern):
            text = path.read_text(encoding="utf-8")
            for marker in markers:
                if marker in text:
                    comments.append(f"{path}:{marker}")
    assert comments == []


def test_rate_limit_uses_a_discord_app_command_check_error() -> None:
    source = (Path("app") / "services" / "rate_limits.py").read_text(encoding="utf-8")
    assert "class RateLimitExceeded(app_commands.CheckFailure)" in source
    assert "raise RateLimitExceeded(retry_after)" in source


def test_global_command_error_handler_covers_expected_check_failures() -> None:
    source = (Path("app") / "discord" / "bot.py").read_text(encoding="utf-8")
    required = (
        "RateLimitExceeded",
        "CommandOnCooldown",
        "BotMissingPermissions",
        "MissingRole",
        "MissingAnyRole",
        "NoPrivateMessage",
        "CheckFailure",
    )
    assert all(item in source for item in required)


def test_command_sync_signature_detects_changed_numeric_limits() -> None:
    import ast
    from pathlib import Path
    from typing import Any

    source = ast.parse(Path("app/services/diagnostics.py").read_text(encoding="utf-8"))
    names = {"_enum_int", "_command_option_signature", "_remote_option_signature"}
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {"Any": Any}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "diagnostic_signature_helpers.py", "exec"), namespace)
    local_signature = namespace["_command_option_signature"]([{
        "name": "amount", "type": 4, "required": True, "description": "Quantidade",
        "min_value": 1, "max_value": 1000,
    }])
    remote_signature = namespace["_remote_option_signature"]([{
        "name": "amount", "type": 4, "required": True, "description": "Quantidade",
        "min_value": 1, "max_value": 100,
    }])
    assert local_signature != remote_signature
