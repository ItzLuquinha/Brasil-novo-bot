from datetime import datetime, timezone
import pytest
from app.models import Ticket, Suggestion, Report
from app.services.community import assign_ticket, create_ticket, entity_id, save_ticket_transcript, set_ticket_status, update_report, update_suggestion


class FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.added = []

    async def get(self, model, item_id, with_for_update=False):
        return self.rows.get((model, item_id))

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None


def timestamp() -> datetime:
    return datetime.now(timezone.utc)


def test_entity_id_is_positive_and_within_bigint_range() -> None:
    value = entity_id()
    assert 0 < value < 2**63


@pytest.mark.asyncio
async def test_create_ticket_persists_ticket_and_creation_event() -> None:
    session = FakeSession()
    ticket = await create_ticket(session, 100, 200, "support", "high", "Problema")
    assert ticket.guild_id == 100
    assert ticket.opener_id == 200
    assert ticket.status == "open"
    assert len(session.added) == 2
    assert session.added[1].event_type == "created"


@pytest.mark.asyncio
async def test_ticket_close_assign_and_transcript() -> None:
    ticket = Ticket(id=10, guild_id=100, opener_id=200, category="general", priority="normal", status="open", reason="Ajuda", transcript=None, panel_message_id=None, created_at=timestamp(), updated_at=timestamp())
    session = FakeSession({(Ticket, 10): ticket})
    await assign_ticket(session, 10, 300, 300)
    await set_ticket_status(session, 10, 300, "closed")
    await save_ticket_transcript(session, 10, "linha 1", 300)
    assert ticket.assignee_id == 300
    assert ticket.status == "closed"
    assert ticket.transcript == "linha 1"
    assert [row.event_type for row in session.added] == ["assigned", "closed", "transcript_saved"]


@pytest.mark.asyncio
async def test_suggestion_status_validation() -> None:
    suggestion = Suggestion(id=11, guild_id=100, author_id=200, content="Nova regra", status="pending", upvotes=0, downvotes=0, staff_note=None, message_id=None, created_at=timestamp(), updated_at=timestamp())
    session = FakeSession({(Suggestion, 11): suggestion})
    await update_suggestion(session, 11, 300, "approved", "Equipe aprovou")
    assert suggestion.status == "approved"
    assert suggestion.staff_note == "Equipe aprovou"
    with pytest.raises(ValueError):
        await update_suggestion(session, 11, 300, "invalid", None)


@pytest.mark.asyncio
async def test_report_status_updates_resolver_and_resolution() -> None:
    report = Report(id=12, guild_id=100, reporter_id=200, reported_id=400, reason="spam", evidence=None, channel_id=500, status="open", resolver_id=None, resolution=None, created_at=timestamp(), updated_at=timestamp())
    session = FakeSession({(Report, 12): report})
    await update_report(session, 12, 300, "resolved", "Ação tomada")
    assert report.status == "resolved"
    assert report.resolver_id == 300
    assert report.resolution == "Ação tomada"

from app.models import Giveaway
from app.services.community import end_giveaway


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class GiveawaySession(FakeSession):
    async def execute(self, statement):
        return FakeResult([(101,), (102,), (103,)])


@pytest.mark.asyncio
async def test_end_giveaway_persists_winners() -> None:
    giveaway = Giveaway(id=20, guild_id=100, channel_id=300, prize="Teste", winners=2, ends_at=timestamp(), requirements={}, status="active", message_id=500, created_at=timestamp(), updated_at=timestamp())
    session = GiveawaySession({(Giveaway, 20): giveaway})
    winners = await end_giveaway(session, 20)
    assert len(winners) == 2
    assert set(winners).issubset({101, 102, 103})
    assert giveaway.status == "ended"
    assert set(giveaway.requirements["winner_ids"]) == set(winners)


@pytest.mark.asyncio
async def test_end_giveaway_rejects_non_active_state() -> None:
    giveaway = Giveaway(id=21, guild_id=100, channel_id=300, prize="Teste", winners=1, ends_at=timestamp(), requirements={}, status="cancelled", message_id=None, created_at=timestamp(), updated_at=timestamp())
    session = GiveawaySession({(Giveaway, 21): giveaway})
    with pytest.raises(ValueError, match="not active"):
        await end_giveaway(session, 21)


@pytest.mark.asyncio
async def test_end_poll_rejects_non_active_state() -> None:
    from app.models import Poll
    from app.services.community import end_poll
    poll = Poll(id=22, guild_id=100, channel_id=300, question="Q?", options=["A", "B"], ends_at=timestamp(), status="cancelled", message_id=None, created_at=timestamp(), updated_at=timestamp())
    class PollSession(GiveawaySession):
        async def execute(self, statement):
            return FakeResult([])
    session = PollSession({(Poll, 22): poll})
    with pytest.raises(ValueError, match="not active"):
        await end_poll(session, 22)
