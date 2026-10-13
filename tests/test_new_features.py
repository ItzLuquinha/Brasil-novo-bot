from pathlib import Path


def test_testall_has_direct_error_button():
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert "class TestallErrorsView" in source
    assert "self.errors_button.label" in source
    assert "Ver erros (" in source
    assert "ephemeral=True" in source


def test_tutorial_admin_uses_stable_thumbnail():
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert 'if value == "administracao":' in source
    assert "page.remove_image()" in source
    assert "page.set_thumbnail" in source


def test_dice_uses_user_selected_gif():
    source = Path("app/discord/theme.py").read_text(encoding="utf-8")
    assert "I38qmkMXsMOFKsuer9" in source



def test_database_migrations_are_checked_before_bot_start():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "upgrade_to_head" in source
    assert "database_at_head" in source
    assert "asyncio.wait_for(asyncio.to_thread(upgrade_to_head), timeout=35)" in source


def test_group_registration_is_idempotent():
    for path, group in [
        ("app/discord/cogs/admin.py", "admin_group"),
        ("app/discord/cogs/automod.py", "automod_group"),
        ("app/discord/cogs/antiraid.py", "raid_group"),
    ]:
        source = Path(path).read_text(encoding="utf-8")
        assert f"if bot.tree.get_command({group}.name) is None:" in source



def test_tutorial_uses_the_central_permission_map() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    permissions = Path("app/services/permissions.py").read_text(encoding="utf-8")
    assert "required_permission_text" in source
    assert "COMMAND_PERMISSIONS" in permissions
    assert "`/admin ...` · Gerenciar Servidor" in source
    assert "`/automod ...` e `/antiraid ...` · Gerenciar Servidor" in source


def test_bump_legacy_source_is_gone():
    assert not Path("app/discord/cogs/bump.py").exists()
    assert not Path("app/services/bump.py").exists()


def test_voice_tracking_handles_voice_and_stage_channels():
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert "guild.voice_channels" in source
    assert "stage_channels" in source
    assert "on_voice_state_update" in source
    assert "voice_joined_at" in source


def test_economy_commands_use_shop_metadata_and_pagination():
    source = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    repository = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    assert "available_from" in source
    assert "available_until" in source
    assert "cooldown_seconds" in source
    assert "stack_limit" in source
    assert "PaginatedEmbedView" in source
    assert "get_shop_item" in repository
    assert "insufficient stock" in repository


def test_jobs_do_not_reference_a_nonexistent_active_column():
    source = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    assert "UserJob.active" not in source


def test_ticket_permissions_are_consistent_with_staff_gate():
    permissions = Path("app/services/permissions.py").read_text(encoding="utf-8")
    community = Path("app/discord/cogs/community.py").read_text(encoding="utf-8")
    assert '"ticket-close": "staff_role"' in permissions
    assert 'not await is_staff(guild, member)' in community


def test_transactions_and_rewards_are_exposed():
    economy = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    admin = Path("app/discord/cogs/admin.py").read_text(encoding="utf-8")
    matrix = Path("app/services/command_matrix.py").read_text(encoding="utf-8")
    assert '@app_commands.command(name="transactions"' in economy
    assert '@admin_group.command(name="rewards"' in admin
    assert '"transactions"' in matrix
    assert '"admin rewards"' in matrix


def test_suggestion_and_report_workflows_validate_transitions():
    source = Path("app/services/community.py").read_text(encoding="utf-8")
    assert "suggestion cannot move" in source
    assert "report cannot move" in source
    assert "this status requires a staff note" in source
    assert "this status requires a resolution note" in source


def test_dashboard_executor_is_replaced_by_a_web_dashboard_link():
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert "get_settings().dashboard_url" in source
    assert "discord.ButtonStyle.link" in source
    assert 'label="Abrir dashboard web"' in source


def test_testall_reports_severity_without_redundant_summary_fields():
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert "diagnostic_severity" in source
    assert "CRÍTICO" in source
    assert "ATENÇÃO" in source
    assert "Críticos:" not in source
    assert 'page.add_field(name="Saúde"' not in source


def test_user_installable_commands_are_excluded_from_guild_sync() -> None:
    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert 'guild_commands = [command for command in global_commands if not self._is_user_installable(command)]' in source
    assert 'self.tree.copy_global_to(guild=guild_object)' not in source
    assert 'self.tree.add_command(command, guild=guild_object)' in source
    assert 'user_installable_excluded=' in source

def test_diagnostics_flags_global_and_guild_command_overlap() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert 'overlap = sorted(set(primary_signatures) & set(global_signatures))' in source
    assert 'mesmo comando em guilda e global' in source

    source = Path("app/discord/bot.py").read_text(encoding="utf-8")
    assert 'guild_commands = [command for command in global_commands if not self._is_user_installable(command)]' in source
    assert 'guild_copies = [self._copy_command_for_guild(command) for command in guild_commands]' in source
    assert 'user_installable_excluded=' in source

def test_twarn_uses_the_requested_gif() -> None:
    source = Path("app/discord/theme.py").read_text(encoding="utf-8")
    assert '"timed_warning": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExcW9wbTlsdTNwOWh0dzh0aXB2ODAzNnFlOTZic2ZlNW83b2p0b2J6NiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/ioa0Au2SQOO9LKv9Fz/giphy.gif"' in source


def test_testall_purge_limit_matches_slash_command_range():
    diagnostics = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    moderation = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    assert '"purge": {"amount": "app_commands.Range[int, 1, 1000]"}' in diagnostics
    assert 'amount: app_commands.Range[int, 1, 1000]' in moderation
    assert "1 a 1000" in moderation


def test_embed_defaults_to_minimal_output():
    theme = Path("app/discord/theme.py").read_text(encoding="utf-8")
    start = theme.index("def embed(")
    end = theme.index("def money(", start)
    block = theme[start:end]
    assert 'show_gif: bool = False' in block
    assert 'result.set_author(' not in block
    assert 'result.set_footer(' not in block
    assert 'timestamp=' not in block


def test_msg_command_is_limited_to_manage_server_users():
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    start = source.index('@command_rate_limit("msg", 15)')
    end = source.index('    @command_rate_limit("history", 5)', start)
    block = source[start:end]
    assert "@app_commands.default_permissions(manage_guild=True)" in block
    assert "@app_commands.checks.has_permissions(manage_guild=True)" in block
    assert '@command_rate_limit("msg", 15)' in block
    assert "canal: discord.TextChannel | discord.Thread" in block
    assert "mensagem: str" in block
    assert "len(mensagem) > 2000" in block
    assert "discord.AllowedMentions(" in block
    assert "users=membros_mencionados" in block
    assert "everyone=False" in block
    assert "roles=False" in block
    assert "resolve_msg_mentions(" in block


def test_msg_checks_destination_permissions_and_reports_errors_safely():
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    start = source.index('@command_rate_limit("msg", 15)')
    end = source.index('    @command_rate_limit("history", 5)', start)
    block = source[start:end]
    for expected in (
        "canal.guild.id != guild.id",
        "canal.archived or canal.locked",
        "sender_permissions.view_channel",
        "channel_permissions.view_channel",
        "channel_permissions.send_messages_in_threads",
        "channel_permissions.send_messages",
        "except discord.Forbidden",
        "except discord.NotFound",
        "except discord.HTTPException",
        "Mensagem enviada para",
    ):
        assert expected in block


def test_msg_is_listed_as_an_administrative_command():
    permissions = Path("app/services/permissions.py").read_text(encoding="utf-8")
    analytics = Path("app/repositories/analytics.py").read_text(encoding="utf-8")
    matrix = Path("app/services/command_matrix.py").read_text(encoding="utf-8")
    assert '"msg": "manage_guild"' in permissions
    assert '"administracao": {"msg"' in analytics
    assert '"msg": ("send_messages_in_threads"' in matrix


def test_tutorial_covers_current_dashboard_analytics_and_safety_tools() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert '"painel": {' in source
    assert '"label": "Dashboard e estatísticas"' in source
    assert "24 horas, 7 dias, 30 dias e 90 dias" in source
    assert "atividade anterior que não foi registrada não pode ser reconstruída" in source
    assert "`/admin purge-log canal:#canal`" in source
    assert "`/automod rule-add`" in source
    assert "`/giveaway reroll`" in source
    assert "`/testall`" in source
    assert "Um guia de verdade" not in source


def test_tutorial_command_chunks_keep_every_permission_line_within_embed_limit() -> None:
    import ast

    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "tutorial_command_chunks")
    module = ast.Module(body=[function], type_ignores=[])
    namespace: dict[str, object] = {}
    exec(compile(module, "tutorial_command_chunks.py", "exec"), namespace)
    chunk_lines = namespace["tutorial_command_chunks"]
    lines = [f"`/{index:02}` · Gerenciar Servidor" + (" detalhe" * 7) for index in range(30)]
    chunks = chunk_lines(lines)
    assert chunks
    assert all(len(chunk) <= 950 for chunk in chunks)
    assert "\n".join(chunks).split("\n") == lines
