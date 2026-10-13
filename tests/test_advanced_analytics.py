from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.analytics import (
    floor_hour,
    message_is_eligible,
    period_bounds,
    percent_change,
    render_counter_name,
    validate_counter_template,
    voice_is_eligible,
)


def test_floor_hour_normalizes_naive_and_aware_times_to_utc():
    value = datetime(2026, 10, 12, 15, 47, 33, tzinfo=timezone(timedelta(hours=-4)))
    assert floor_hour(value) == datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)
    assert floor_hour(datetime(2026, 10, 12, 19, 47)) == datetime(2026, 10, 12, 19, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("period,duration", [("24h", timedelta(hours=24)), ("7d", timedelta(days=7)), ("30d", timedelta(days=30)), ("90d", timedelta(days=90))])
def test_period_bounds_uses_expected_duration(period, duration):
    now = datetime(2026, 10, 12, 18, tzinfo=timezone.utc)
    start, end, label = period_bounds(period, now)
    assert end == now
    assert end - start == duration
    assert label == period


def test_period_bounds_rejects_unknown_period():
    with pytest.raises(ValueError, match="Período inválido"):
        period_bounds("all-time")


def test_percent_change_has_no_fabricated_percentage_when_previous_is_zero():
    assert percent_change(0, 0) is None
    assert percent_change(25, 0) is None
    assert percent_change(150, 100) == 50.0
    assert percent_change(50, 100) == -50.0


def test_counter_template_only_allows_known_fields_and_requires_value():
    assert validate_counter_template("{label}: {value}/{goal} ({percent}%)") == "{label}: {value}/{goal} ({percent}%)"
    with pytest.raises(ValueError, match="marcadores"):
        validate_counter_template("{label}: {value} {system_secret}")
    with pytest.raises(ValueError, match="precisa conter"):
        validate_counter_template("Estatística do servidor")


def test_counter_name_renders_values_and_stays_within_discord_name_limit():
    assert render_counter_name("{label}: {value}/{goal} ({percent}%)", "member_count", 25, 100) == "Membros: 25/100 (25%)"
    rendered = render_counter_name("x" * 99 + "{value}", "member_count", 1000, None)
    assert len(rendered) == 100


def test_message_eligibility_respects_channel_category_role_and_command_filters():
    config = SimpleNamespace(
        exclude_bots=True,
        excluded_channel_ids=[123],
        excluded_category_ids=[234],
        excluded_role_ids=[345],
        exclude_commands=True,
    )
    common = {"category_id": None, "role_ids": [], "content": "hello", "bot_id": 999, "is_bot": False}
    assert message_is_eligible(config, channel_id=100, **common)
    assert not message_is_eligible(config, channel_id=123, **common)
    assert not message_is_eligible(config, channel_id=100, category_id=234, role_ids=[], content="hello", bot_id=999, is_bot=False)
    assert not message_is_eligible(config, channel_id=100, category_id=None, role_ids=[345], content="hello", bot_id=999, is_bot=False)
    assert not message_is_eligible(config, channel_id=100, category_id=None, role_ids=[], content="<@999> ping", bot_id=999, is_bot=False)
    assert not message_is_eligible(config, channel_id=100, category_id=None, role_ids=[], content="hello", bot_id=999, is_bot=True)


def test_voice_eligibility_respects_voice_toggle_and_filters():
    enabled = SimpleNamespace(track_voice=True, exclude_bots=True, excluded_channel_ids=[1], excluded_category_ids=[2], excluded_role_ids=[3])
    assert voice_is_eligible(enabled, channel_id=4, category_id=5, role_ids=[6])
    assert not voice_is_eligible(enabled, channel_id=1, category_id=5, role_ids=[6])
    assert not voice_is_eligible(enabled, channel_id=4, category_id=2, role_ids=[6])
    assert not voice_is_eligible(enabled, channel_id=4, category_id=5, role_ids=[3])
    assert not voice_is_eligible(enabled, channel_id=4, category_id=5, role_ids=[6], is_bot=True)
    disabled = SimpleNamespace(track_voice=False, exclude_bots=True, excluded_channel_ids=[], excluded_category_ids=[], excluded_role_ids=[])
    assert not voice_is_eligible(disabled, channel_id=4, category_id=5, role_ids=[6])


def test_missing_analytics_config_uses_safe_command_and_bot_defaults():
    assert message_is_eligible(None, channel_id=100, category_id=None, role_ids=[], content="hello", bot_id=999, is_bot=False)
    assert not message_is_eligible(None, channel_id=100, category_id=None, role_ids=[], content="<@999> ping", bot_id=999, is_bot=False)
    assert not message_is_eligible(None, channel_id=100, category_id=None, role_ids=[], content="automated", bot_id=999, is_bot=True)
    assert voice_is_eligible(None, channel_id=100, category_id=None, role_ids=[], is_bot=False)
    assert not voice_is_eligible(None, channel_id=100, category_id=None, role_ids=[], is_bot=True)


def test_counter_percentage_is_not_fabricated_when_no_goal_is_configured():
    assert render_counter_name("{value} ({percent}%)", "member_count", 17, None) == "17 (n/a%)"


@pytest.mark.asyncio
async def test_activity_rule_metrics_count_active_days_from_text_or_voice():
    from app.services.analytics import evaluate_activity_rule_metrics

    now = datetime.now(timezone.utc)
    rows = [
        (101, 3, 180, 2),
        (202, 0, 60, 1),
    ]

    class FakeResult:
        def all(self):
            return rows

    class FakeSession:
        async def execute(self, _statement):
            return FakeResult()

    rule = SimpleNamespace(
        min_messages=1, messages_window_days=7,
        min_voice_seconds=None, voice_window_days=7,
        min_active_days=1, active_days_window_days=7,
    )
    result = await evaluate_activity_rule_metrics(FakeSession(), 55, rule)
    assert result[101]["messages"] == 3
    assert result[101]["voice_seconds"] == 180
    assert result[101]["active_days"] == 2
    assert result[202]["active_days"] == 1


@pytest.mark.parametrize(
    "guild_owner_id,user,expected",
    [
        (123, {"id": "123", "system_role": "user"}, True),
        (123, {"id": "456", "system_role": "admin"}, True),
        (123, {"id": "456", "system_role": "user"}, False),
        (123, {"id": "invalid", "system_role": "user"}, False),
    ],
)
def test_channel_statistics_require_owner_or_system_admin(guild_owner_id, user, expected):
    from api.routers.guilds import _can_view_all_channel_statistics

    guild = SimpleNamespace(owner_id=guild_owner_id)
    assert _can_view_all_channel_statistics(guild, user) is expected
