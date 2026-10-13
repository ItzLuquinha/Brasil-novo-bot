from decimal import Decimal
from types import SimpleNamespace

from app.services.rewards import DEFAULT_REWARD_CONFIG, reward_config


def test_reward_config_ignores_non_finite_and_out_of_range_amounts():
    settings = SimpleNamespace(
        config={
            "rewards": {
                "daily_amount": "NaN",
                "weekly_amount": "Infinity",
                "streak_bonus_percent": "-Infinity",
                "streak_bonus_cap_percent": "1e999999",
            }
        }
    )

    result = reward_config(settings)

    assert result["daily_amount"] == DEFAULT_REWARD_CONFIG["daily_amount"]
    assert result["weekly_amount"] == DEFAULT_REWARD_CONFIG["weekly_amount"]
    assert result["streak_bonus_percent"] == DEFAULT_REWARD_CONFIG["streak_bonus_percent"]
    assert result["streak_bonus_cap_percent"] == Decimal("1000")


def test_reward_config_keeps_valid_values_and_caps_bonus_percentages():
    settings = SimpleNamespace(
        config={
            "rewards": {
                "daily_amount": "500.25",
                "weekly_amount": "2500",
                "streak_bonus_percent": "250",
                "streak_bonus_cap_percent": "1200",
            }
        }
    )

    result = reward_config(settings)

    assert result["daily_amount"] == Decimal("500.25")
    assert result["weekly_amount"] == Decimal("2500.00")
    assert result["streak_bonus_percent"] == Decimal("100")
    assert result["streak_bonus_cap_percent"] == Decimal("1000")
