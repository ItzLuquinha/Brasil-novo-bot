from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import GuildPermission


PERMISSION_LABELS = {
    "manage_messages": "Gerenciar Mensagens",
    "moderate_members": "Moderar Membros",
    "kick_members": "Expulsar Membros",
    "ban_members": "Banir Membros",
    "manage_channels": "Gerenciar Canais",
    "manage_guild": "Gerenciar Servidor",
}

COMMAND_PERMISSIONS = {
    "msg": "manage_guild",
    "warn": "manage_messages",
    "t-warn": "manage_messages",
    "warns": "manage_messages",
    "unwarn": "manage_messages",
    "clearwarns": "manage_messages",
    "purge": "manage_messages",
    "timeout": "moderate_members",
    "untimeout": "moderate_members",
    "unmute": "moderate_members",
    "kick": "kick_members",
    "ban": "ban_members",
    "unban": "ban_members",
    "ticket-close": "staff_role",
    "ticket-reopen": "staff_role",
    "ticket-claim": "staff_role",
    "ticket-config": "manage_guild",
    "suggestion-status": "manage_guild",
    "report-status": "manage_guild",
    "giveaway create": "manage_guild",
    "giveaway end": "manage_guild",
    "giveaway reroll": "manage_guild",
    "giveaway cancel": "manage_guild",
    "poll create": "manage_guild",
    "poll end": "manage_guild",
    "community-config": "manage_guild",
    "history": "manage_guild",
    "testall": "manage_guild",
}


def required_permission(command_name: str) -> str | None:
    normalized = command_name.strip().casefold()
    direct = COMMAND_PERMISSIONS.get(normalized)
    if direct is not None:
        return direct
    if normalized == "admin" or normalized.startswith("admin "):
        return "manage_guild"
    if normalized == "automod" or normalized.startswith("automod "):
        return "manage_guild"
    if normalized == "antiraid" or normalized.startswith("antiraid "):
        return "manage_guild"
    return None


def required_permission_text(command_name: str) -> str:
    permission = required_permission(command_name)
    if permission == "staff_role":
        return "Cargo de staff configurado no sistema de tickets"
    if permission is None:
        return "Qualquer membro"
    return PERMISSION_LABELS[permission]


async def allowed(session: AsyncSession, guild_id: int, user_id: int, permission: str, role_ids: set[int] | None = None) -> bool:
    role_ids = role_ids or set()
    result = await session.execute(
        select(GuildPermission)
        .where(GuildPermission.guild_id == guild_id, GuildPermission.permission == permission)
        .order_by(GuildPermission.id.desc())
    )
    rules = list(result.scalars())
    user_rules = [r for r in rules if r.subject_type == "user" and r.subject_id == user_id]
    if user_rules:
        return user_rules[0].allowed
    role_rules = [r for r in rules if r.subject_type == "role" and r.subject_id in role_ids]
    if not role_rules:
        return False
    return role_rules[0].allowed
