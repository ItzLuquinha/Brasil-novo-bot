from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models import Guild, GuildSettings
from app.repositories.guilds import ensure_guild


class FakeSession:
    def __init__(self, guild, settings):
        self.rows = {Guild: guild, GuildSettings: settings}

    async def get(self, model, key):
        return self.rows.get(model)

    async def flush(self):
        return None

    def add(self, instance):
        return None


@pytest.mark.asyncio
async def test_ensure_guild_preserves_admin_disabled_status():
    guild = SimpleNamespace(
        id=123,
        name="Existing",
        owner_id=456,
        icon_url=None,
        active=False,
        updated_at=datetime.now(timezone.utc),
    )
    settings = SimpleNamespace(guild_id=123)
    session = FakeSession(guild, settings)

    result = await ensure_guild(session, 123, "Updated", 456, None)

    assert result is guild
    assert guild.name == "Updated"
    assert guild.active is False


@pytest.mark.asyncio
async def test_ensure_guild_reactivates_only_when_explicitly_requested():
    guild = SimpleNamespace(
        id=123,
        name="Existing",
        owner_id=456,
        icon_url=None,
        active=False,
        updated_at=datetime.now(timezone.utc),
    )
    settings = SimpleNamespace(guild_id=123)
    session = FakeSession(guild, settings)

    result = await ensure_guild(session, 123, "Existing", 456, None, reactivate=True)

    assert result.active is True
