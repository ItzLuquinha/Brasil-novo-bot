from pathlib import Path


def test_job_command_uses_a_real_select_view_and_no_text_key() -> None:
    source = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    block = source[source.index('@app_commands.command(name="job"'):source.index('async def equip_job', source.index('@app_commands.command(name="job"'))]
    assert 'async def job(self, interaction: discord.Interaction)' in block
    assert 'JobSelectView(self, rows, member.id, user_level)' in block
    assert 'key: str' not in block


def test_job_selector_supports_pagination_and_owner_lock() -> None:
    source = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    assert 'self.page_size = 25' in source
    assert 'def interaction_check' in source
    assert 'await self.cog.equip_job' in source
    assert '@app_commands.command(name="work"' in source


def test_public_fun_commands_are_registered() -> None:
    source = Path("app/discord/cogs/fun.py").read_text(encoding="utf-8")
    for name in ("coinflip", "dice", "rps", "eightball"):
        assert f'name="{name}"' in source
        assert 'await respond(interaction, embed=page)' in source


def test_decorative_geometry_is_not_used_in_user_facing_sources() -> None:
    forbidden = "◆◇✦■○§▰▱△✓×●✧"
    paths = [*Path("app/discord").rglob("*.py"), *Path("app/dashboard").rglob("*.js")]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert not any(char in text for char in forbidden), path


def test_fun_commands_use_theme_gif_selection() -> None:
    source = Path("app/discord/cogs/fun.py").read_text(encoding="utf-8")
    assert "GIFS =" not in source
    assert 'page = embed("BN / CARA OU COROA"' in source
    assert 'page = embed("BN / DADO"' in source
    assert 'page = embed("BN / PEDRA, PAPEL E TESOURA"' in source
    assert 'page = embed("BN / BOLA 8"' in source


def test_warn_and_twarn_are_separate_commands_with_compact_duration() -> None:
    source = Path("app/discord/cogs/moderation.py").read_text(encoding="utf-8")
    assert 'name="warn"' in source
    assert 'name="t-warn"' in source
    assert 'duration: str' in source
    assert 'name="unit"' not in source
    assert "parse_twarn_duration" in source
    assert "expires_at = utc_now() + timedelta" in source


def test_admin_job_add_no_longer_requests_a_manual_key_and_job_remove_exists() -> None:
    source = Path("app/discord/cogs/admin.py").read_text(encoding="utf-8")
    block = source[source.index('@admin_group.command(name="job-add"'):source.index('@admin_group.command(name="job-remove"')]
    assert "key: str" not in block
    assert "key_base" in block
    assert '@admin_group.command(name="job-remove"' in source
    assert "job_autocomplete" in source

def test_rps_is_button_driven() -> None:
    source = Path("app/discord/cogs/fun.py").read_text(encoding="utf-8")
    assert "class RPSView(discord.ui.View)" in source
    assert '@discord.ui.button(label="Pedra"' in source
    assert '@discord.ui.button(label="Papel"' in source
    assert '@discord.ui.button(label="Tesoura"' in source
    rps = source[source.index('@app_commands.command(name="rps"'):source.index('@app_commands.command(name="eightball"')]
    assert "RPSView" in rps

def test_command_history_is_server_scoped_and_compact() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert '@app_commands.command(name="history"' in source
    assert "@app_commands.checks.has_permissions(manage_guild=True)" in source
    assert "CommandUsage.guild_id == guild.id" in source
    block = source[source.index("async def history("):source.index('    @command_rate_limit("testall", 30)')]
    assert "CATEGORY_LABELS" not in block
    assert "Não foi possível carregar o histórico agora." in block



def test_job_select_options_are_compatible_and_server_validates_level() -> None:
    source = Path("app/discord/cogs/economy.py").read_text(encoding="utf-8")
    options_start = source.index("def _options(", source.index("class JobSelectView"))
    options_end = source.index("async def interaction_check", options_start)
    block = source[options_start:options_end]
    assert "disabled=" not in block
    assert "BLOQUEADO" in block
    equip_start = source.index("async def equip_job")
    equip_end = source.index('@app_commands.command(name="work"', equip_start)
    equip = source[equip_start:equip_end]
    assert "required_level" in equip and "Este emprego exige nível" in equip
