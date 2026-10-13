from pathlib import Path


def test_sell_item_restocks_finite_shop_inventory() -> None:
    source = Path("app/repositories/economy.py").read_text(encoding="utf-8")
    start = source.index("async def sell_item")
    end = source.index("return value", start) + len("return value")
    block = source[start:end]
    assert "if item.stock is not None:" in block
    assert "item.stock += quantity" in block


def test_dashboard_command_links_to_configured_web_dashboard() -> None:
    source = Path("app/discord/cogs/dashboard.py").read_text(encoding="utf-8")
    assert "get_settings().dashboard_url" in source
    assert "discord.ButtonStyle.link" in source
    assert "url=dashboard_url" in source
    assert "allowed_mentions=discord.AllowedMentions.none()" in source
    assert 'description="Abre o dashboard web oficial do BN Bot."' in source


def test_dashboard_uses_web_frontend_as_local_default() -> None:
    source = Path("app/config.py").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")
    assert 'dashboard_url: str = "http://localhost:5173"' in source
    assert "DASHBOARD_URL=http://localhost:5173" in env_example


def test_reward_cooldown_uses_next_calendar_boundary() -> None:
    from datetime import datetime
    source = Path("app/services/rewards.py").read_text(encoding="utf-8")
    assert "def seconds_until_next_reward" in source
    assert "datetime.combine(next_date, time.min, tzinfo=local.tzinfo)" in source


def test_every_expected_command_has_a_passing_individual_behavior_contract() -> None:
    from app.services.command_matrix import EXPECTED_COMMANDS, audit_commands, case_issues
    cases = {case.qualified_name: case for case in audit_commands()}
    assert set(cases) == EXPECTED_COMMANDS
    assert len(cases) == len(EXPECTED_COMMANDS)
    failures = {name: case_issues(case) for name, case in cases.items() if case_issues(case)}
    assert failures == {}
