from __future__ import annotations
from collections.abc import Iterable
from datetime import datetime, timezone
import secrets
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Giveaway, GiveawayEntry, Poll, PollVote, Report, Suggestion, SuggestionVote, Ticket, TicketEvent


def entity_id() -> int:
    return secrets.randbits(62)


def now() -> datetime:
    return datetime.now(timezone.utc)


def validate_poll_options(options: Iterable[str | None]) -> list[str]:
    parsed: list[str] = []
    seen: set[str] = set()
    for option in options:
        if option is None:
            continue
        value = " ".join(option.split())
        if not value:
            continue
        if len(value) > 80:
            raise ValueError("cada opção da enquete deve ter no máximo 80 caracteres")
        key = value.casefold()
        if key in seen:
            raise ValueError("as opções da enquete não podem ser duplicadas")
        seen.add(key)
        parsed.append(value)
    if len(parsed) < 2:
        raise ValueError("uma enquete precisa de pelo menos 2 opções")
    if len(parsed) > 10:
        raise ValueError("uma enquete pode ter no máximo 10 opções")
    return parsed


async def create_ticket(session: AsyncSession, guild_id: int, opener_id: int, category: str, priority: str, reason: str) -> Ticket:
    current = now()
    ticket = Ticket(guild_id=guild_id, opener_id=opener_id, category=category, priority=priority, status="open", reason=reason, created_at=current, updated_at=current)
    session.add(ticket)
    await session.flush()
    session.add(TicketEvent(id=entity_id(), ticket_id=ticket.id, actor_id=opener_id, event_type="created", data={"category": category, "priority": priority, "reason": reason}, created_at=current))
    await session.flush()
    return ticket


async def set_ticket_status(session: AsyncSession, ticket_id: int, actor_id: int, status: str, data: dict | None = None) -> Ticket:
    ticket = await session.get(Ticket, ticket_id, with_for_update=True)
    if ticket is None:
        raise ValueError("ticket not found")
    if status not in {"open", "closed", "reopened"}:
        raise ValueError("invalid ticket status")
    if status == "closed" and ticket.status != "open":
        raise ValueError("ticket is not open")
    if status == "reopened" and ticket.status != "closed":
        raise ValueError("ticket is not closed")
    if status == "open" and ticket.status != "open":
        raise ValueError("ticket status must be reopened from closed")
    current = now()
    ticket.status = "open" if status == "reopened" else status
    ticket.updated_at = current
    session.add(TicketEvent(id=entity_id(), ticket_id=ticket.id, actor_id=actor_id, event_type=status, data=data or {}, created_at=current))
    return ticket


async def assign_ticket(session: AsyncSession, ticket_id: int, actor_id: int, assignee_id: int | None) -> Ticket:
    ticket = await session.get(Ticket, ticket_id, with_for_update=True)
    if ticket is None:
        raise ValueError("ticket not found")
    ticket.assignee_id = assignee_id
    ticket.updated_at = now()
    session.add(TicketEvent(id=entity_id(), ticket_id=ticket.id, actor_id=actor_id, event_type="assigned", data={"assignee_id": assignee_id}, created_at=now()))
    return ticket


async def save_ticket_transcript(session: AsyncSession, ticket_id: int, transcript: str, actor_id: int) -> None:
    ticket = await session.get(Ticket, ticket_id, with_for_update=True)
    if ticket is None:
        raise ValueError("ticket not found")
    ticket.transcript = transcript
    ticket.updated_at = now()
    session.add(TicketEvent(id=entity_id(), ticket_id=ticket.id, actor_id=actor_id, event_type="transcript_saved", data={"length": len(transcript)}, created_at=now()))


async def cast_suggestion_vote(session: AsyncSession, suggestion_id: int, user_id: int, value: int, guild_id: int | None = None) -> tuple[int, int]:
    if value not in {-1, 1}:
        raise ValueError("invalid suggestion vote")
    suggestion = await session.get(Suggestion, suggestion_id, with_for_update=True)
    if suggestion is None or (guild_id is not None and suggestion.guild_id != guild_id):
        raise ValueError("suggestion not found")
    if suggestion.status not in {"pending", "analysis"}:
        raise ValueError("suggestion voting is closed")
    existing_result = await session.execute(select(SuggestionVote).where(SuggestionVote.suggestion_id == suggestion_id, SuggestionVote.user_id == user_id).with_for_update())
    existing = existing_result.scalar_one_or_none()
    if existing is None:
        try:
            async with session.begin_nested():
                session.add(SuggestionVote(id=entity_id(), suggestion_id=suggestion_id, user_id=user_id, value=value, created_at=now()))
                await session.flush()
        except IntegrityError:
            retry = await session.execute(select(SuggestionVote).where(SuggestionVote.suggestion_id == suggestion_id, SuggestionVote.user_id == user_id).with_for_update())
            existing = retry.scalar_one_or_none()
            if existing is None:
                raise
    if existing is not None:
        if existing.value == value:
            return suggestion.upvotes, suggestion.downvotes
        if existing.value == 1:
            suggestion.upvotes -= 1
        else:
            suggestion.downvotes -= 1
        existing.value = value
    if value == 1:
        suggestion.upvotes += 1
    else:
        suggestion.downvotes += 1
    suggestion.updated_at = now()
    await session.flush()
    return suggestion.upvotes, suggestion.downvotes


async def update_suggestion(session: AsyncSession, suggestion_id: int, actor_id: int, status: str, staff_note: str | None, guild_id: int | None = None) -> Suggestion:
    suggestion = await session.get(Suggestion, suggestion_id, with_for_update=True)
    if suggestion is None:
        raise ValueError("suggestion not found")
    if guild_id is not None and suggestion.guild_id != guild_id:
        raise ValueError("suggestion not found")
    transitions = {
        "pending": {"pending", "analysis", "approved", "rejected"},
        "analysis": {"analysis", "approved", "rejected", "pending"},
        "approved": {"approved", "implemented", "analysis"},
        "rejected": {"rejected", "pending", "analysis"},
        "implemented": {"implemented"},
    }
    if status not in transitions:
        raise ValueError("invalid suggestion status")
    if status not in transitions.get(suggestion.status, {suggestion.status}):
        raise ValueError(f"suggestion cannot move from {suggestion.status} to {status}")
    note = " ".join(staff_note.split())[:2000] if staff_note else None
    if status in {"rejected", "implemented"} and not note:
        raise ValueError("this status requires a staff note")
    suggestion.status = status
    suggestion.staff_note = note
    suggestion.updated_at = now()
    return suggestion


async def update_report(session: AsyncSession, report_id: int, resolver_id: int, status: str, resolution: str | None, guild_id: int | None = None) -> Report:
    report = await session.get(Report, report_id, with_for_update=True)
    if report is None:
        raise ValueError("report not found")
    if guild_id is not None and report.guild_id != guild_id:
        raise ValueError("report not found")
    transitions = {
        "open": {"open", "investigating", "resolved", "rejected"},
        "investigating": {"investigating", "resolved", "rejected", "open"},
        "resolved": {"resolved"},
        "rejected": {"rejected", "open", "investigating"},
    }
    if status not in transitions:
        raise ValueError("invalid report status")
    if status not in transitions.get(report.status, {report.status}):
        raise ValueError(f"report cannot move from {report.status} to {status}")
    clean_resolution = " ".join(resolution.split())[:2000] if resolution else None
    if status in {"resolved", "rejected"} and not clean_resolution:
        raise ValueError("this status requires a resolution note")
    report.status = status
    report.resolver_id = resolver_id
    report.resolution = clean_resolution
    report.updated_at = now()
    return report


async def enter_giveaway(session: AsyncSession, giveaway_id: int, user_id: int) -> bool:
    giveaway = await session.get(Giveaway, giveaway_id, with_for_update=True)
    if giveaway is None or giveaway.status != "active" or giveaway.ends_at <= now():
        return False
    existing = await session.execute(select(GiveawayEntry.id).where(GiveawayEntry.giveaway_id == giveaway_id, GiveawayEntry.user_id == user_id))
    if existing.scalar_one_or_none() is not None:
        await session.execute(delete(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway_id, GiveawayEntry.user_id == user_id))
        return False
    try:
        async with session.begin_nested():
            session.add(GiveawayEntry(id=entity_id(), giveaway_id=giveaway_id, user_id=user_id, created_at=now()))
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(select(GiveawayEntry.id).where(GiveawayEntry.giveaway_id == giveaway_id, GiveawayEntry.user_id == user_id))
        if existing is not None:
            await session.execute(delete(GiveawayEntry).where(GiveawayEntry.giveaway_id == giveaway_id, GiveawayEntry.user_id == user_id))
            await session.flush()
            return False
        raise
    return True


async def end_giveaway(session: AsyncSession, giveaway_id: int, winner_count: int | None = None) -> list[int]:
    giveaway = await session.get(Giveaway, giveaway_id, with_for_update=True)
    if giveaway is None:
        raise ValueError("giveaway not found")
    if giveaway.status != "active":
        raise ValueError("giveaway is not active")
    result = await session.execute(select(GiveawayEntry.user_id).where(GiveawayEntry.giveaway_id == giveaway_id))
    entrants = [int(row[0]) for row in result.all()]
    count = max(1, winner_count or giveaway.winners)
    winners = secrets.SystemRandom().sample(entrants, min(count, len(entrants))) if entrants else []
    requirements = dict(giveaway.requirements or {})
    requirements["winner_ids"] = winners
    giveaway.requirements = requirements
    giveaway.status = "ended"
    giveaway.updated_at = now()
    return winners


async def add_poll_vote(session: AsyncSession, poll_id: int, user_id: int, option_index: int) -> tuple[int, list[int]]:
    poll = await session.get(Poll, poll_id, with_for_update=True)
    if poll is None or poll.status != "active" or poll.ends_at <= now():
        raise ValueError("poll is not active")
    if option_index < 0 or option_index >= len(poll.options):
        raise ValueError("invalid poll option")
    existing_result = await session.execute(select(PollVote).where(PollVote.poll_id == poll_id, PollVote.user_id == user_id).with_for_update())
    existing = existing_result.scalar_one_or_none()
    if existing is None:
        try:
            async with session.begin_nested():
                session.add(PollVote(id=entity_id(), poll_id=poll_id, user_id=user_id, option_index=option_index, created_at=now()))
                await session.flush()
        except IntegrityError:
            retry = await session.execute(select(PollVote).where(PollVote.poll_id == poll_id, PollVote.user_id == user_id).with_for_update())
            existing = retry.scalar_one_or_none()
            if existing is None:
                raise
    if existing is not None:
        existing.option_index = option_index
        existing.created_at = now()
    await session.flush()
    return option_index, await poll_counts(session, poll_id, len(poll.options))


async def poll_counts(session: AsyncSession, poll_id: int, option_count: int) -> list[int]:
    result = await session.execute(select(PollVote.option_index, func.count(PollVote.id)).where(PollVote.poll_id == poll_id).group_by(PollVote.option_index))
    counts = [0] * option_count
    for index, count in result.all():
        if 0 <= index < option_count:
            counts[index] = int(count)
    return counts


async def end_poll(session: AsyncSession, poll_id: int) -> list[int]:
    poll = await session.get(Poll, poll_id, with_for_update=True)
    if poll is None:
        raise ValueError("poll not found")
    if poll.status != "active":
        raise ValueError("poll is not active")
    counts = await poll_counts(session, poll_id, len(poll.options))
    poll.status = "ended"
    poll.updated_at = now()
    return counts


async def open_items(session: AsyncSession, guild_id: int) -> dict[str, list]:
    tickets = list((await session.execute(select(Ticket).where(Ticket.guild_id == guild_id, Ticket.status == "open").order_by(Ticket.created_at.desc()).limit(100))).scalars())
    suggestions = list((await session.execute(select(Suggestion).where(Suggestion.guild_id == guild_id, Suggestion.status.in_(["pending", "analysis"])) .order_by(Suggestion.created_at.desc()).limit(100))).scalars())
    reports = list((await session.execute(select(Report).where(Report.guild_id == guild_id, Report.status.in_(["open", "investigating"])) .order_by(Report.created_at.desc()).limit(100))).scalars())
    giveaways = list((await session.execute(select(Giveaway).where(Giveaway.guild_id == guild_id, Giveaway.status == "active").order_by(Giveaway.ends_at))).scalars())
    polls = list((await session.execute(select(Poll).where(Poll.guild_id == guild_id, Poll.status == "active").order_by(Poll.ends_at))).scalars())
    return {"tickets": tickets, "suggestions": suggestions, "reports": reports, "giveaways": giveaways, "polls": polls}
