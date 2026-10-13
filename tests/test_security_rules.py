from pathlib import Path

ROOT = Path(__file__).parents[1]
CODE_SUFFIXES = {".py", ".html", ".css", ".js", ".ts", ".sql", ".toml", ".yml", ".yaml"}
GENERATED_DIRS = {".venv", "venv", "site-packages", "node_modules", "dist", "build", ".git", "__pycache__", ".pytest_cache"}


def _is_generated(path: Path) -> bool:
    return any(part in GENERATED_DIRS for part in path.parts)


def test_project_has_no_em_dash() -> None:
    offenders = []
    for path in ROOT.rglob("*"):
        if _is_generated(path):
            continue
        if path.is_file() and path.suffix in CODE_SUFFIXES:
            if chr(0x2014) in path.read_text(encoding="utf-8"):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_project_has_no_css_gradients() -> None:
    offenders = []
    for path in ROOT.rglob("*.css"):
        if _is_generated(path):
            continue
        text = path.read_text(encoding="utf-8").lower()
        if "gradient(" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_source_has_no_comments() -> None:
    offenders = []
    for path in ROOT.rglob("*.py"):
        if _is_generated(path):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith("#"):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []



def test_abusable_commands_have_distributed_rate_limits() -> None:
    import ast

    expected = {
        "economy.py": ("deposit", "withdraw", "pay", "buy", "sell", "job"),
        "community.py": ("suggest", "report"),
        "fun.py": ("coinflip", "dice", "rps", "eightball"),
        "utility.py": ("msg", "remind", "history", "testall"),
        "utility.py": ("remind", "history", "testall"),
        "dashboard.py": ("dashboard",),
    }
    for filename, names in expected.items():
        source = (ROOT / "app" / "discord" / "cogs" / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for name in names:
            found = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                decorators = [ast.unparse(value) for value in node.decorator_list]
                if any((f'name="{name}"' in value or f"name='{name}'" in value) and "command" in value for value in decorators):
                    found.append(decorators)
            assert found, f"{filename}:{name} command not found"
            assert any("command_rate_limit(" in "\n".join(decorators) for decorators in found), f"{filename}:{name} lacks command rate limit"


def test_ban_fetches_uncached_members_before_hierarchy_check() -> None:
    source = (ROOT / "app" / "discord" / "cogs" / "moderation.py").read_text(encoding="utf-8")
    block_start = source.index('async def ban(')
    block_end = source.index('@app_commands.command(name="unban"', block_start)
    block = source[block_start:block_end]
    assert "await guild.fetch_member(user.id)" in block
    assert "self.target_error(interaction, member)" in block


def test_rate_limit_falls_back_to_existing_distributed_cooldown_service() -> None:
    source = (ROOT / "app" / "services" / "rate_limits.py").read_text(encoding="utf-8")
    assert "check_and_set" in source
    assert "RateLimitExceeded" in source
    assert "app_commands.CheckFailure" in source
    assert "guild_id = interaction.guild_id or 0" in source


def test_security_audit_covers_all_sensitive_command_groups() -> None:
    source = (ROOT / "scripts" / "security_audit.py").read_text(encoding="utf-8")
    for token in ("automod enable", "automod rule-delete", "automod list-add", "antiraid configure", "antiraid unlock"):
        assert f'"{token}"' in source


def test_admin_job_autocomplete_does_not_expose_options_to_regular_members() -> None:
    source = (ROOT / "app" / "discord" / "cogs" / "admin.py").read_text(encoding="utf-8")
    start = source.index("async def job_autocomplete")
    end = source.index('@admin_group.command(name="job-remove"', start)
    block = source[start:end]
    assert "guild_permissions.administrator" in block
    assert "guild_permissions.manage_guild" in block
    assert "return []" in block
