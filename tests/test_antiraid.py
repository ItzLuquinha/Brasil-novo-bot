from datetime import datetime, timedelta, timezone
import pytest
from app.services.antiraid import JoinContext, RaidWindowStore, calculate_risk, clamp_config


def test_config_is_clamped_to_safe_bounds() -> None:
    result = clamp_config({"join_threshold": 1, "join_window_seconds": 999, "risk_threshold": 0, "response_action": "invalid"})
    assert result["join_threshold"] == 2
    assert result["join_window_seconds"] == 120
    assert result["risk_threshold"] == 1
    assert result["response_action"] == "alert"


def test_burst_of_new_accounts_triggers_raid() -> None:
    now = datetime.now(timezone.utc)
    recent = [now - timedelta(seconds=value) for value in range(1, 7)]
    recent_new = [now - timedelta(seconds=value) for value in range(1, 6)]
    context = JoinContext(1, 100, 300, recent_joins=recent, recent_new_accounts=recent_new, recent_user_ids=[10, 11, 12])
    result = calculate_risk(context, {"join_threshold": 8, "join_window_seconds": 20, "new_account_seconds": 604800, "new_account_ratio": 0.6, "risk_threshold": 70, "response_action": "lockdown"}, now)
    assert result.triggered
    assert result.join_count == 7
    assert result.new_account_count == 6
    assert result.risk_score >= 70
    assert result.action == "lockdown"


def test_single_old_account_does_not_trigger() -> None:
    now = datetime.now(timezone.utc)
    context = JoinContext(1, 100, 31_536_000, recent_joins=[], recent_new_accounts=[])
    result = calculate_risk(context, {"join_threshold": 8, "join_window_seconds": 20, "new_account_seconds": 604800, "new_account_ratio": 0.6, "risk_threshold": 70, "response_action": "alert"}, now)
    assert not result.triggered
    assert result.join_count == 1
    assert result.risk_score == 0


@pytest.mark.asyncio
async def test_memory_join_store_excludes_current_join_from_history() -> None:
    store = RaidWindowStore(None, prefix="test-antiraid")
    now = datetime.now(timezone.utc)
    first = JoinContext(123, 1, 100)
    previous, previous_new, previous_users = await store.add_join(first, now, True)
    assert previous == []
    assert previous_new == []
    assert previous_users == []
    second = JoinContext(123, 2, 100)
    previous, previous_new, previous_users = await store.add_join(second, now + timedelta(seconds=1), True)
    assert len(previous) == 1
    assert len(previous_new) == 1
    assert previous_users == [1]


def test_merge_lockdown_guild_ids_includes_pending_retries_without_duplicates() -> None:
    from app.services.antiraid import merge_lockdown_guild_ids

    assert merge_lockdown_guild_ids([123, 456], [456, 789]) == [123, 456, 789]


def test_expiration_worker_does_not_restore_a_lockdown_before_it_expires() -> None:
    from pathlib import Path

    source = Path("app/discord/cogs/antiraid.py").read_text(encoding="utf-8")
    block = source[source.index("async def expire_lockdowns"):source.index("def add_to_tree", source.index("async def expire_lockdowns"))]
    assert "RaidProtection.active_until.is_(None)" in block
    assert "RaidProtection.active_until <= now" in block
    assert "RaidLockdownChannel.next_restore_attempt_at <= now" in block


def test_manual_unlock_marks_pending_restoration_as_requested() -> None:
    from pathlib import Path

    source = Path("app/discord/cogs/antiraid.py").read_text(encoding="utf-8")
    block = source[source.index('async def unlock'):source.index('async def expire_lockdowns', source.index('async def unlock'))]
    assert "row.active_until = None" in block
    assert "pending == 0 else row.active_until" not in block


def test_lockdown_persists_restore_state_before_changing_discord_permissions() -> None:
    from pathlib import Path

    source = Path("app/discord/cogs/antiraid.py").read_text(encoding="utf-8")
    block = source[source.index("async def apply_lockdown"):source.index("@staticmethod", source.index("async def apply_lockdown"))]
    assert block.index("await session.commit()") < block.index("await channel.set_permissions(")
    assert "restore record retained" in block
