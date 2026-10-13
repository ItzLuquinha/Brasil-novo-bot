from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from api.routers.guilds import list_pending_suggestions


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class FakeSession:
    def __init__(self, items):
        self.items = items
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return FakeResult(self.items)


@pytest.mark.asyncio
async def test_pending_suggestions_endpoint_returns_real_detail_fields_and_safe_ids():
    row = SimpleNamespace(
        id=1542032965759017038,
        guild_id=77,
        author_id=123456789012345678,
        channel_id=None,
        message_id=123456789012345679,
        content="Adicionar um canal de novidades",
        status="pending",
        upvotes=8,
        downvotes=2,
        staff_note=None,
        created_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
    )
    session = FakeSession([row])

    payload = await list_pending_suggestions(guild_id=77, limit=100, db=session, user={"id": "1"})

    assert payload["items"] == [
        {
            "id": "1542032965759017038",
            "author_id": "123456789012345678",
            "channel_id": None,
            "message_id": "123456789012345679",
            "content": "Adicionar um canal de novidades",
            "status": "pending",
            "upvotes": 8,
            "downvotes": 2,
            "staff_note": None,
            "created_at": "2026-10-11T00:00:00+00:00",
        }
    ]
    assert session.statement is not None


class FakeDeleteSession:
    def __init__(self, row):
        self.row = row
        self.deleted = []
        self.added = []
        self.committed = False

    async def get(self, model, object_id):
        return self.row if self.row.id == object_id else None

    async def scalar(self, statement):
        self.statement = statement
        return self.row

    def add(self, item):
        self.added.append(item)

    async def delete(self, item):
        self.deleted.append(item)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_delete_suggestion_is_guild_scoped_and_audited():
    from api.routers.guilds import delete_suggestion
    from app.models import AuditLog

    row = SimpleNamespace(
        id=54, guild_id=77, author_id=5, channel_id=6, message_id=7,
        content="Remover spam", status="pending", upvotes=3, downvotes=1,
    )
    session = FakeDeleteSession(row)
    result = await delete_suggestion(guild_id=77, suggestion_id=54, db=session, user={"id": "33"})

    assert result == {"deleted": "54"}
    assert session.deleted == [row]
    assert session.committed
    assert len(session.added) == 1
    assert isinstance(session.added[0], AuditLog)
    assert session.added[0].executor_id == 33
    assert session.added[0].action == "suggestion.delete"
    assert session.added[0].before_state["content"] == "Remover spam"
    assert session.statement._for_update_arg is not None


@pytest.mark.asyncio
async def test_delete_suggestion_does_not_delete_another_guilds_record():
    from fastapi import HTTPException
    from api.routers.guilds import delete_suggestion

    row = SimpleNamespace(id=54, guild_id=88, author_id=5, channel_id=6, message_id=7, content="Outra", status="pending", upvotes=0, downvotes=0)
    session = FakeDeleteSession(row)
    with pytest.raises(HTTPException) as exc_info:
        await delete_suggestion(guild_id=77, suggestion_id=54, db=session, user={"id": "33"})
    assert exc_info.value.status_code == 404
    assert session.deleted == []
    assert session.committed is False
