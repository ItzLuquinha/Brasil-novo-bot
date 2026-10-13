import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import cast, func, literal, or_, select, union_all, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.security import SystemRole
from api.database import get_db
from api.dependencies import get_current_user, require_guild_manager, require_system_moderator
from app.models import (
    ActivityRoleRule,
    AnalyticsConfig,
    AuditLog,
    AutoModEvent,
    AutoModListEntry,
    AutoModRule,
    Experience,
    Guild,
    GuildSettings,
    GuildActivity,
    Member,
    MemberActivity,
    ChannelActivity,
    StatCounter,
    ModerationLog,
    Suggestion,
    User,
)
from app.repositories.analytics import overview, record_voice_segment
from app.services.automod import ACTIONS, DEFAULT_RULES, RULE_TYPES, validate_rule_config
from app.services.analytics import (
    SUPPORTED_METRICS, analytics_report, get_or_create_analytics_config, member_activity_report,
    normalize_id_list, period_bounds, percent_change, validate_counter_template,
)

router = APIRouter()
SUPPORTED_LOCALES = {"pt-BR", "en-US"}


def _can_view_all_channel_statistics(guild: Guild, user: dict) -> bool:
    if user.get("system_role") == SystemRole.ADMIN.value:
        return True
    try:
        return int(user.get("id", 0)) == int(guild.owner_id)
    except (TypeError, ValueError, OverflowError):
        return False


class GuildSettingsUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    locale: str | None = Field(default=None, min_length=2, max_length=16)
    economy_enabled: bool | None = None
    levels_enabled: bool | None = None
    analytics_enabled: bool | None = None
    automod_enabled: bool | None = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("timezone não pode ficar vazio")
        try:
            ZoneInfo(normalized)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone deve ser um fuso horário IANA válido") from None
        return normalized

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized not in SUPPORTED_LOCALES:
            raise ValueError("locale deve ser pt-BR ou en-US")
        return normalized


class GuildStatusUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    reason: str | None = Field(default=None, max_length=500)


class AutoModRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    enabled: bool
    action: str = Field(min_length=1, max_length=20)
    priority: int = Field(ge=-10000, le=10000)
    channel_ids: list[int] = Field(default_factory=list, max_length=100)
    role_ids: list[int] = Field(default_factory=list, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)


class AutoModUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    blacklist_action: str = Field(default="delete", min_length=1, max_length=20)
    rules: list[AutoModRuleUpdate] | None = Field(default=None, max_length=200)


class AutoModRuleCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    rule_type: str = Field(min_length=1, max_length=40)
    action: str = Field(default="delete", min_length=1, max_length=20)
    enabled: bool = True
    priority: int = Field(default=0, ge=-10000, le=10000)
    channel_ids: list[int] = Field(default_factory=list, max_length=100)
    role_ids: list[int] = Field(default_factory=list, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)


class AutoModListCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_type: Literal["whitelist", "blacklist"]
    entry_type: Literal["user", "channel", "role", "word", "domain"]
    value: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=500)


def _guild_json(guild: Guild) -> dict[str, Any]:
    return {
        "id": str(guild.id),
        "name": guild.name,
        "icon_url": guild.icon_url,
        "owner_id": str(guild.owner_id) if guild.owner_id else None,
        "active": guild.active,
        "created_at": guild.created_at.isoformat() if guild.created_at else None,
        "updated_at": guild.updated_at.isoformat() if guild.updated_at else None,
    }


def _rule_json(rule: AutoModRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "name": rule.name,
        "rule_type": rule.rule_type,
        "action": rule.action,
        "enabled": rule.enabled,
        "priority": rule.priority,
        "channel_ids": rule.channel_ids or [],
        "role_ids": rule.role_ids or [],
        "config": rule.config or {},
    }


def _settings_json(settings: GuildSettings) -> dict[str, Any]:
    return {
        "guild_id": str(settings.guild_id),
        "timezone": settings.timezone,
        "locale": settings.locale,
        "economy_enabled": settings.economy_enabled,
        "levels_enabled": settings.levels_enabled,
        "analytics_enabled": settings.analytics_enabled,
        "automod_enabled": settings.automod_enabled,
        "config": settings.config or {},
        "created_at": settings.created_at.isoformat() if settings.created_at else None,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


async def _write_audit(
    db: AsyncSession,
    guild_id: int,
    user: dict[str, Any],
    action: str,
    resource: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    db.add(AuditLog(
        id=secrets.randbits(62),
        guild_id=guild_id,
        executor_id=int(user["id"]),
        action=action,
        resource=resource[:120],
        before_state=before,
        after_state=after,
        created_at=datetime.now(timezone.utc),
    ))


@router.get("", summary="Listar servidores acessíveis ao usuário")
async def list_guilds(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    if user.get("system_role") == SystemRole.ADMIN.value:
        query = select(Guild).where(Guild.active.is_(True))
    else:
        user_id = int(user["id"])
        manageable_ids = [int(guild_id) for guild_id in user.get("guilds", []) if str(guild_id).isdigit()]
        scope = [Guild.owner_id == user_id]
        if manageable_ids:
            scope.append(Guild.id.in_(manageable_ids))
        query = select(Guild).where(Guild.active.is_(True), or_(*scope))
    result = await db.execute(query.order_by(Guild.name.asc(), Guild.id.asc()))
    return [_guild_json(guild) for guild in result.scalars().all()]


@router.get("/{guild_id}", summary="Obter detalhes de um servidor")
async def get_guild(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    guild = await db.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    return _guild_json(guild)


@router.get("/{guild_id}/overview", summary="Resumo de atividade do servidor")
async def get_guild_overview(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    return await overview(db, guild_id)


@router.get("/{guild_id}/suggestions", summary="Listar sugestões pendentes do servidor")
async def list_pending_suggestions(
    guild_id: int,
    limit: int = Query(default=100, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    result = await db.execute(
        select(Suggestion)
        .where(Suggestion.guild_id == guild_id, Suggestion.status == "pending")
        .order_by(Suggestion.created_at.desc(), Suggestion.id.desc())
        .limit(limit)
    )
    items = result.scalars().all()
    return {
        "items": [
            {
                "id": str(item.id),
                "author_id": str(item.author_id),
                "channel_id": str(item.channel_id) if item.channel_id is not None else None,
                "message_id": str(item.message_id) if item.message_id is not None else None,
                "content": item.content,
                "status": item.status,
                "upvotes": item.upvotes,
                "downvotes": item.downvotes,
                "staff_note": item.staff_note,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in items
        ]
    }


@router.delete("/{guild_id}/suggestions/{suggestion_id}", summary="Excluir uma sugestão")
async def delete_suggestion(
    guild_id: int,
    suggestion_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    row = await db.scalar(
        select(Suggestion)
        .where(Suggestion.id == suggestion_id, Suggestion.guild_id == guild_id)
        .with_for_update()
    )
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sugestão não encontrada")
    before = {
        "status": row.status,
        "author_id": row.author_id,
        "channel_id": row.channel_id,
        "message_id": row.message_id,
        "content": row.content[:1000],
        "upvotes": row.upvotes,
        "downvotes": row.downvotes,
    }
    actor_id = int(user.get("id", 0))
    db.add(AuditLog(
        id=secrets.randbits(62),
        guild_id=guild_id,
        executor_id=actor_id,
        action="suggestion.delete",
        resource=f"suggestion:{suggestion_id}",
        before_state=before,
        after_state=None,
        created_at=datetime.now(timezone.utc),
    ))
    await db.delete(row)
    await db.commit()
    return {"deleted": str(suggestion_id)}


@router.get("/{guild_id}/settings", summary="Obter configurações do servidor")
async def get_guild_settings(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configurações deste servidor ainda não foram inicializadas")
    return _settings_json(settings)


@router.patch("/{guild_id}/settings", summary="Atualizar configurações do servidor")
async def update_guild_settings(
    guild_id: int,
    payload: GuildSettingsUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configurações deste servidor ainda não foram inicializadas")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe ao menos uma configuração para atualizar")
    before = {field: getattr(settings, field) for field in changes}
    for field, value in changes.items():
        setattr(settings, field, value)
    settings.updated_at = datetime.now(timezone.utc)
    after = {field: getattr(settings, field) for field in changes}
    await _write_audit(db, guild_id, user, "guild.settings_update", "settings", before, after)
    await db.commit()
    await db.refresh(settings)
    return _settings_json(settings)


@router.get("/{guild_id}/members", summary="Listar membros e experiência")
async def list_members(
    guild_id: int,
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    base = select(Member, User, Experience).join(User, User.id == Member.user_id).outerjoin(
        Experience, (Experience.guild_id == Member.guild_id) & (Experience.user_id == Member.user_id)
    ).where(Member.guild_id == guild_id, Member.left_at.is_(None))
    count_result = await db.execute(select(func.count(Member.id)).where(Member.guild_id == guild_id, Member.left_at.is_(None)))
    total = int(count_result.scalar_one() or 0)
    result = await db.execute(base.order_by(Member.activity_score.desc(), Member.user_id.asc()).offset((page - 1) * page_size).limit(page_size))
    items = []
    for member, profile, experience in result.all():
        items.append({
            "user_id": str(member.user_id),
            "username": profile.username,
            "display_name": profile.display_name,
            "avatar_url": profile.avatar_url,
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
            "messages": member.message_count,
            "voice_seconds": member.voice_seconds,
            "activity": member.activity_score,
            "level": experience.level if experience else None,
            "xp": experience.total_xp if experience else None,
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{guild_id}/audit", summary="Listar logs de auditoria e moderação")
async def list_audit_logs(
    guild_id: int,
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    moderation = select(
        cast(ModerationLog.id, String).label("id"),
        ModerationLog.created_at.label("created_at"),
        ModerationLog.kind.label("kind"),
        cast(ModerationLog.actor_id, String).label("actor_id"),
        cast(ModerationLog.target_id, String).label("target_id"),
        ModerationLog.reason.label("reason"),
        literal("moderação").label("source"),
    ).where(ModerationLog.guild_id == guild_id)
    audit = select(
        cast(AuditLog.id, String).label("id"),
        AuditLog.created_at.label("created_at"),
        AuditLog.action.label("kind"),
        cast(AuditLog.executor_id, String).label("actor_id"),
        cast(AuditLog.resource, String).label("target_id"),
        literal(None, type_=String).label("reason"),
        literal("auditoria").label("source"),
    ).where(AuditLog.guild_id == guild_id)
    automod = select(
        cast(AutoModEvent.id, String).label("id"),
        AutoModEvent.created_at.label("created_at"),
        AutoModEvent.rule_type.label("kind"),
        literal(None, type_=String).label("actor_id"),
        cast(AutoModEvent.user_id, String).label("target_id"),
        AutoModEvent.reason.label("reason"),
        literal("automod").label("source"),
    ).where(AutoModEvent.guild_id == guild_id)
    events = union_all(moderation, audit, automod).subquery("guild_audit_events")
    total_result = await db.execute(select(func.count()).select_from(events))
    total = int(total_result.scalar_one() or 0)
    result = await db.execute(
        select(events)
        .order_by(events.c.created_at.desc(), events.c.source.asc(), events.c.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = []
    for row in result.mappings().all():
        created_at = row["created_at"]
        items.append({
            "id": row["id"],
            "created_at": created_at.isoformat() if created_at else None,
            "kind": row["kind"],
            "actor_id": row["actor_id"],
            "target_id": row["target_id"],
            "reason": row["reason"],
            "source": row["source"],
        })
    return {"items": items, "total": total, "page": page, "page_size": page_size}


async def _lock_automod_guild_writes(db: AsyncSession, guild_id: int) -> int:
    locked_guild_id = await db.scalar(
        select(Guild.id).where(Guild.id == guild_id).with_for_update()
    )
    if locked_guild_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    return int(locked_guild_id)


@router.get("/{guild_id}/automod", summary="Ler configuração real do AutoMod")
async def get_automod(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        return {"configured": False, "rules": [], "lists": []}
    rules_result = await db.execute(select(AutoModRule).where(AutoModRule.guild_id == guild_id).order_by(AutoModRule.priority.desc(), AutoModRule.id.asc()))
    entries_result = await db.execute(select(AutoModListEntry).where(AutoModListEntry.guild_id == guild_id).order_by(AutoModListEntry.list_type.asc(), AutoModListEntry.entry_type.asc(), AutoModListEntry.value.asc()))
    automod_config = dict((settings.config or {}).get("automod", {}))
    entries = entries_result.scalars().all()
    return {
        "configured": True,
        "enabled": settings.automod_enabled,
        "blacklist_action": automod_config.get("blacklist_action", "delete"),
        "rules": [_rule_json(rule) for rule in rules_result.scalars().all()],
        "lists": [{"id": row.id, "list_type": row.list_type, "entry_type": row.entry_type, "value": row.value, "reason": row.reason} for row in entries],
    }


@router.post("/{guild_id}/automod/setup", summary="Criar regras iniciais sem remover regras existentes")
async def setup_automod(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    await _lock_automod_guild_writes(db, guild_id)
    now = datetime.now(timezone.utc)
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        settings = GuildSettings(
            guild_id=guild_id,
            timezone="UTC",
            locale="pt-BR",
            economy_enabled=True,
            levels_enabled=True,
            analytics_enabled=True,
            automod_enabled=True,
            config={"automod": {"blacklist_action": "delete"}},
            created_at=now,
            updated_at=now,
        )
        db.add(settings)
    else:
        config = dict(settings.config or {})
        automod_config = dict(config.get("automod", {}))
        automod_config.setdefault("blacklist_action", "delete")
        config["automod"] = automod_config
        settings.config = config
        settings.automod_enabled = True
        settings.updated_at = now
    existing_result = await db.execute(select(AutoModRule.name).where(AutoModRule.guild_id == guild_id))
    existing_names = {str(name).casefold() for name in existing_result.scalars().all()}
    created = 0
    for definition in DEFAULT_RULES:
        name = str(definition["name"]).strip()
        if name.casefold() in existing_names:
            continue
        db.add(AutoModRule(
            guild_id=guild_id,
            name=name,
            rule_type=definition["rule_type"],
            action=definition["action"],
            enabled=True,
            priority=definition["priority"],
            channel_ids=[],
            role_ids=[],
            config=dict(definition["config"]),
            created_at=now,
            updated_at=now,
        ))
        created += 1
    await _write_audit(db, guild_id, user, "automod.setup", "rules", None, {"created": created})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A configuração inicial foi alterada em paralelo. Atualize a tela e tente novamente.") from None
    return await get_automod(guild_id, db, user)


@router.put("/{guild_id}/automod", summary="Salvar AutoMod e regras atomicamente")
async def update_automod(
    guild_id: int,
    payload: AutoModUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    if payload.blacklist_action not in ACTIONS - {"none"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A ação da blacklist é inválida")
    if payload.rules is not None and len({rule.id for rule in payload.rules}) != len(payload.rules):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Há IDs de regras repetidos na solicitação")
    await _lock_automod_guild_writes(db, guild_id)
    settings = await db.get(GuildSettings, guild_id)
    if settings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inicialize o AutoMod antes de salvar configurações")
    current_config = dict(settings.config or {})
    automod_config = dict(current_config.get("automod", {}))
    previous = {"enabled": settings.automod_enabled, "blacklist_action": automod_config.get("blacklist_action", "delete")}
    new_rule_values: list[tuple[AutoModRule, AutoModRuleUpdate]] = []
    if payload.rules is not None:
        rule_ids = [rule.id for rule in payload.rules]
        rows_result = await db.execute(select(AutoModRule).where(AutoModRule.guild_id == guild_id, AutoModRule.id.in_(rule_ids)))
        rows_by_id = {row.id: row for row in rows_result.scalars().all()}
        if set(rows_by_id) != set(rule_ids):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Uma ou mais regras não existem neste servidor")
        for update in payload.rules:
            row = rows_by_id[update.id]
            if update.action not in ACTIONS:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Ação inválida na regra {row.name}")
            if any(item <= 0 for item in update.channel_ids + update.role_ids):
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="IDs de canais e cargos devem ser positivos")
            errors = validate_rule_config(row.rule_type, update.config)
            if errors:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Configuração inválida em {row.name}: {'; '.join(errors)}")
            new_rule_values.append((row, update))
    settings.automod_enabled = payload.enabled
    automod_config["blacklist_action"] = payload.blacklist_action
    current_config["automod"] = automod_config
    settings.config = current_config
    settings.updated_at = datetime.now(timezone.utc)
    for row, update in new_rule_values:
        row.enabled = update.enabled
        row.action = update.action
        row.priority = update.priority
        row.channel_ids = update.channel_ids
        row.role_ids = update.role_ids
        row.config = update.config
        row.updated_at = settings.updated_at
    after = {"enabled": payload.enabled, "blacklist_action": payload.blacklist_action, "updated_rules": [row.id for row, _ in new_rule_values]}
    await _write_audit(db, guild_id, user, "automod.settings_update", "settings", previous, after)
    await db.commit()
    return await get_automod(guild_id, db, user)


@router.post("/{guild_id}/automod/rules", summary="Criar uma regra AutoMod")
async def create_automod_rule(
    guild_id: int,
    payload: AutoModRuleCreateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    name = " ".join(payload.name.split())
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O nome da regra não pode ficar vazio")
    if payload.rule_type not in RULE_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tipo de regra inválido")
    if payload.action not in ACTIONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ação inválida")
    errors = validate_rule_config(payload.rule_type, payload.config)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    if any(item <= 0 for item in payload.channel_ids + payload.role_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="IDs de canais e cargos devem ser positivos")
    await _lock_automod_guild_writes(db, guild_id)
    existing = await db.scalar(select(AutoModRule.id).where(AutoModRule.guild_id == guild_id, func.lower(AutoModRule.name) == name.casefold()).limit(1))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma regra com este nome")
    now = datetime.now(timezone.utc)
    row = AutoModRule(guild_id=guild_id, name=name, rule_type=payload.rule_type, action=payload.action, enabled=payload.enabled, priority=payload.priority, channel_ids=payload.channel_ids, role_ids=payload.role_ids, config=payload.config, created_at=now, updated_at=now)
    db.add(row)
    try:
        await db.flush()
        await _write_audit(db, guild_id, user, "automod.rule_create", f"rule:{row.id}", None, _rule_json(row))
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma regra com este nome") from None
    return _rule_json(row)


@router.patch("/{guild_id}/automod/rules/{rule_id}", summary="Atualizar uma regra AutoMod")
async def patch_automod_rule(
    guild_id: int,
    rule_id: int,
    payload: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    allowed_fields = {"enabled", "action", "priority", "channel_ids", "role_ids", "config"}
    if not payload or set(payload) - allowed_fields:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Campos de atualização inválidos")
    await _lock_automod_guild_writes(db, guild_id)
    row = await db.get(AutoModRule, rule_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regra não encontrada neste servidor")
    update = AutoModRuleUpdate.model_validate({
        "id": rule_id,
        "enabled": payload.get("enabled", row.enabled),
        "action": payload.get("action", row.action),
        "priority": payload.get("priority", row.priority),
        "channel_ids": payload.get("channel_ids", row.channel_ids or []),
        "role_ids": payload.get("role_ids", row.role_ids or []),
        "config": payload.get("config", row.config or {}),
    })
    if update.action not in ACTIONS or any(item <= 0 for item in update.channel_ids + update.role_ids):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ação ou IDs inválidos")
    errors = validate_rule_config(row.rule_type, update.config)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))
    before = _rule_json(row)
    row.enabled = update.enabled
    row.action = update.action
    row.priority = update.priority
    row.channel_ids = update.channel_ids
    row.role_ids = update.role_ids
    row.config = update.config
    row.updated_at = datetime.now(timezone.utc)
    await _write_audit(db, guild_id, user, "automod.rule_update", f"rule:{rule_id}", before, _rule_json(row))
    await db.commit()
    return _rule_json(row)


@router.delete("/{guild_id}/automod/rules/{rule_id}", summary="Excluir uma regra AutoMod")
async def delete_automod_rule(guild_id: int, rule_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    await _lock_automod_guild_writes(db, guild_id)
    row = await db.get(AutoModRule, rule_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regra não encontrada neste servidor")
    await _write_audit(db, guild_id, user, "automod.rule_delete", f"rule:{rule_id}", _rule_json(row), None)
    await db.delete(row)
    await db.commit()
    return {"deleted": rule_id}


@router.post("/{guild_id}/automod/lists", summary="Adicionar entrada à whitelist ou blacklist")
async def create_automod_list(guild_id: int, payload: AutoModListCreateSchema, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    value = payload.value.casefold().strip() if payload.entry_type in {"word", "domain"} else payload.value.strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O valor não pode ficar vazio")
    if payload.entry_type in {"user", "channel", "role"} and (not value.isdigit() or int(value) <= 0):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O ID deve ser um número positivo")
    await _lock_automod_guild_writes(db, guild_id)
    existing = await db.scalar(select(AutoModListEntry.id).where(AutoModListEntry.guild_id == guild_id, AutoModListEntry.list_type == payload.list_type, AutoModListEntry.entry_type == payload.entry_type, AutoModListEntry.value == value).limit(1))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta entrada já existe")
    now = datetime.now(timezone.utc)
    row = AutoModListEntry(guild_id=guild_id, list_type=payload.list_type, entry_type=payload.entry_type, value=value, reason=payload.reason, created_at=now, updated_at=now)
    db.add(row)
    try:
        await db.flush()
        await _write_audit(db, guild_id, user, "automod.list_add", f"{row.list_type}:{row.entry_type}", None, {"value": row.value, "reason": row.reason})
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta entrada já existe") from None
    return {"id": row.id, "list_type": row.list_type, "entry_type": row.entry_type, "value": row.value, "reason": row.reason}


@router.delete("/{guild_id}/automod/lists/{entry_id}", summary="Excluir entrada de lista AutoMod")
async def delete_automod_list(guild_id: int, entry_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    await _lock_automod_guild_writes(db, guild_id)
    row = await db.get(AutoModListEntry, entry_id)
    if row is None or row.guild_id != guild_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entrada não encontrada neste servidor")
    await _write_audit(db, guild_id, user, "automod.list_delete", f"{row.list_type}:{row.entry_type}", {"value": row.value}, None)
    await db.delete(row)
    await db.commit()
    return {"deleted": entry_id}


@router.get("/{guild_id}/status", summary="Consultar disponibilidade do servidor para a equipe")
async def get_guild_status(guild_id: int, db: AsyncSession = Depends(get_db), moderator: dict = Depends(require_system_moderator)):
    guild = await db.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    return {"guild_id": str(guild.id), "active": guild.active}


@router.patch("/{guild_id}/status", summary="Moderação global: ativar ou desativar servidor")
async def toggle_guild_status(
    guild_id: int,
    payload: GuildStatusUpdateSchema,
    db: AsyncSession = Depends(get_db),
    moderator: dict = Depends(require_system_moderator),
):
    guild = await db.get(Guild, guild_id)
    if guild is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Servidor não encontrado")
    previous_active = guild.active
    guild.active = payload.active
    guild.updated_at = datetime.now(timezone.utc)
    await _write_audit(db, guild_id, moderator, "guild.status_update", "guild", {"active": previous_active}, {"active": guild.active, "reason": payload.reason})
    await db.commit()
    await db.refresh(guild)
    return {"guild_id": str(guild.id), "active": guild.active, "updated_at": guild.updated_at.isoformat(), "action_by": moderator.get("username", moderator["id"]), "reason": payload.reason}


@router.get("/{guild_id}/economy", summary="Listar saldos de economia")
async def list_economy(guild_id: int, page: int = Query(default=1, ge=1, le=10000), page_size: int = Query(default=25, ge=1, le=100), db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    from app.models import EconomyAccount

    count = await db.scalar(select(func.count(EconomyAccount.id)).where(EconomyAccount.guild_id == guild_id))
    result = await db.execute(select(EconomyAccount).where(EconomyAccount.guild_id == guild_id).order_by((EconomyAccount.wallet + EconomyAccount.bank).desc()).offset((page - 1) * page_size).limit(page_size))
    items = [{"user_id": str(row.user_id), "wallet": str(row.wallet), "bank": str(row.bank), "total": str(row.wallet + row.bank)} for row in result.scalars().all()]
    return {"items": items, "total": int(count or 0), "page": page, "page_size": page_size}


@router.get("/{guild_id}/levels", summary="Listar níveis e experiência")
async def list_levels(guild_id: int, page: int = Query(default=1, ge=1, le=10000), page_size: int = Query(default=25, ge=1, le=100), db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    count = await db.scalar(select(func.count(Experience.id)).where(Experience.guild_id == guild_id))
    result = await db.execute(select(Experience).where(Experience.guild_id == guild_id).order_by(Experience.total_xp.desc()).offset((page - 1) * page_size).limit(page_size))
    items = [{"user_id": str(row.user_id), "level": row.level, "xp": row.total_xp} for row in result.scalars().all()]
    return {"items": items, "total": int(count or 0), "page": page, "page_size": page_size}


@router.get("/{guild_id}/moderation", summary="Listar casos de moderação")
async def list_moderation_cases(guild_id: int, page: int = Query(default=1, ge=1, le=10000), page_size: int = Query(default=25, ge=1, le=100), db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    count = await db.scalar(select(func.count(ModerationLog.id)).where(ModerationLog.guild_id == guild_id))
    result = await db.execute(select(ModerationLog).where(ModerationLog.guild_id == guild_id).order_by(ModerationLog.created_at.desc(), ModerationLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    items = [{"id": str(row.id), "created_at": row.created_at.isoformat() if row.created_at else None, "kind": row.kind, "actor_id": str(row.actor_id), "target_id": str(row.target_id) if row.target_id is not None else None, "reason": row.reason, "data": row.data or {}} for row in result.scalars().all()]
    return {"items": items, "total": int(count or 0), "page": page, "page_size": page_size}


class AnalyticsConfigUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    excluded_channel_ids: list[int] | None = Field(default=None, max_length=200)
    excluded_category_ids: list[int] | None = Field(default=None, max_length=200)
    excluded_role_ids: list[int] | None = Field(default=None, max_length=200)
    exclude_commands: bool | None = None
    exclude_bots: bool | None = None
    track_voice: bool | None = None
    retention_days: int | None = Field(default=None, ge=30, le=3650)
    member_statistics_for_managers: bool | None = None

    @field_validator("excluded_channel_ids", "excluded_category_ids", "excluded_role_ids")
    @classmethod
    def validate_id_lists(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if any(isinstance(item, bool) or item <= 0 for item in value):
            raise ValueError("Todos os IDs devem ser números positivos")
        if len(set(value)) != len(value):
            raise ValueError("Não repita IDs nas listas de exclusão")
        return value


class StatCounterCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: int = Field(gt=0)
    metric: Literal["member_count", "human_members", "bot_members", "voice_members", "messages_period", "active_members_period"]
    format_template: str = Field(min_length=1, max_length=100)
    period_days: int | None = Field(default=7, ge=1, le=365)
    goal_value: int | None = Field(default=None, ge=1, le=2_000_000_000)
    enabled: bool = True


class StatCounterUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Literal["member_count", "human_members", "bot_members", "voice_members", "messages_period", "active_members_period"] | None = None
    format_template: str | None = Field(default=None, min_length=1, max_length=100)
    period_days: int | None = Field(default=None, ge=1, le=365)
    goal_value: int | None = Field(default=None, ge=1, le=2_000_000_000)
    enabled: bool | None = None


class ActivityRoleRuleCreateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    role_id: int = Field(gt=0)
    min_messages: int | None = Field(default=None, ge=1, le=1_000_000)
    messages_window_days: int = Field(default=7, ge=1, le=365)
    min_voice_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    voice_window_days: int = Field(default=7, ge=1, le=365)
    min_active_days: int | None = Field(default=None, ge=1, le=365)
    active_days_window_days: int = Field(default=7, ge=1, le=365)
    enabled: bool = True
    remove_when_unqualified: bool = False


class ActivityRoleRuleUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_messages: int | None = Field(default=None, ge=1, le=1_000_000)
    messages_window_days: int | None = Field(default=None, ge=1, le=365)
    min_voice_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    voice_window_days: int | None = Field(default=None, ge=1, le=365)
    min_active_days: int | None = Field(default=None, ge=1, le=365)
    active_days_window_days: int | None = Field(default=None, ge=1, le=365)
    enabled: bool | None = None
    remove_when_unqualified: bool | None = None


def _analytics_config_json(row: AnalyticsConfig) -> dict[str, Any]:
    return {
        "guild_id": str(row.guild_id),
        "excluded_channel_ids": [str(item) for item in normalize_id_list(row.excluded_channel_ids)],
        "excluded_category_ids": [str(item) for item in normalize_id_list(row.excluded_category_ids)],
        "excluded_role_ids": [str(item) for item in normalize_id_list(row.excluded_role_ids)],
        "exclude_commands": row.exclude_commands,
        "exclude_bots": row.exclude_bots,
        "track_voice": row.track_voice,
        "retention_days": row.retention_days,
        "member_statistics_for_managers": row.member_statistics_for_managers,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _counter_json(row: StatCounter) -> dict[str, Any]:
    return {
        "id": str(row.id), "guild_id": str(row.guild_id), "channel_id": str(row.channel_id),
        "metric": row.metric, "metric_label": SUPPORTED_METRICS.get(row.metric, row.metric),
        "format_template": row.format_template, "period_days": row.period_days,
        "goal_value": row.goal_value, "enabled": row.enabled, "last_value": row.last_value,
        "last_attempt_at": row.last_attempt_at.isoformat() if row.last_attempt_at else None,
        "last_updated_at": row.last_updated_at.isoformat() if row.last_updated_at else None,
        "last_error": row.last_error, "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _activity_rule_json(row: ActivityRoleRule) -> dict[str, Any]:
    return {
        "id": str(row.id), "guild_id": str(row.guild_id), "name": row.name,
        "role_id": str(row.role_id), "min_messages": row.min_messages,
        "messages_window_days": row.messages_window_days, "min_voice_seconds": row.min_voice_seconds,
        "voice_window_days": row.voice_window_days, "min_active_days": row.min_active_days,
        "active_days_window_days": row.active_days_window_days, "enabled": row.enabled,
        "remove_when_unqualified": row.remove_when_unqualified,
        "last_evaluated_at": row.last_evaluated_at.isoformat() if row.last_evaluated_at else None,
        "last_error": row.last_error, "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/{guild_id}/analytics", summary="Estatísticas avançadas do servidor")
async def get_advanced_analytics(
    guild_id: int,
    period: Literal["24h", "7d", "30d", "90d"] = "7d",
    start: datetime | None = None,
    end: datetime | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    if (start is None) != (end is None):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe início e fim juntos para consultar um intervalo personalizado")
    if start is not None and end is not None:
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        if start >= end or end - start > timedelta(days=366):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O intervalo precisa ser válido e não pode exceder 366 dias")
        current_start, current_end = start, end
        period_label = "custom"
    else:
        current_start, current_end, period_label = period_bounds(period)
    duration = current_end - current_start
    previous_start = current_start - duration
    config = await db.get(AnalyticsConfig, guild_id)
    report = await analytics_report(db, guild_id, current_start, current_end)
    previous = await analytics_report(db, guild_id, previous_start, current_start)
    current_totals = report["totals"]
    previous_totals = previous["totals"]
    report["period"]["label"] = period_label
    report["comparison"] = {
        key: {"current": current_totals[key], "previous": previous_totals[key],
              "change_percent": percent_change(current_totals[key], previous_totals[key])}
        for key in ("messages", "voice_seconds", "active_members", "joins", "leaves")
    }
    report["tracking_enabled"] = True
    settings = await db.get(GuildSettings, guild_id)
    report["tracking_enabled"] = bool(settings is None or settings.analytics_enabled)
    guild_row = await db.get(Guild, guild_id)
    can_view_channel_details = guild_row is not None and _can_view_all_channel_statistics(guild_row, user)
    report["channel_details_available"] = can_view_channel_details
    if not can_view_channel_details:
        report["top_channels"] = []
    manager_can_view_member_details = config is None or config.member_statistics_for_managers or user.get("system_role") == SystemRole.ADMIN.value
    report["member_statistics_hidden"] = not manager_can_view_member_details
    if not manager_can_view_member_details:
        report["top_members"] = []
    report["filters_apply_prospectively"] = True
    report["retention_days"] = config.retention_days if config else 365
    report["excluded_channel_ids"] = [str(item) for item in normalize_id_list(config.excluded_channel_ids)] if config else []
    return report


@router.get("/{guild_id}/analytics/channels/{channel_id}", summary="Detalhar atividade de um canal")
async def get_channel_analytics(
    guild_id: int,
    channel_id: int,
    days: int = Query(default=7, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    guild_row = await db.get(Guild, guild_id)
    if guild_row is None or not _can_view_all_channel_statistics(guild_row, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="O detalhamento por canal é restrito ao proprietário do servidor e aos administradores do BN Bot até que as permissões individuais de canal possam ser verificadas")
    from datetime import timedelta
    from app.models import MessageLog
    start = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(ChannelActivity.bucket_start, ChannelActivity.metric, func.sum(ChannelActivity.value))
        .where(ChannelActivity.guild_id == guild_id, ChannelActivity.channel_id == channel_id,
               ChannelActivity.bucket_start >= start, ChannelActivity.metric.in_(["messages", "voice_seconds"]))
        .group_by(ChannelActivity.bucket_start, ChannelActivity.metric)
        .order_by(ChannelActivity.bucket_start.asc())
    )
    series: dict[str, dict[str, int]] = {}
    for bucket, metric, value in result.all():
        series.setdefault(bucket.isoformat(), {})[metric] = int(value or 0)
    totals = {"messages": 0, "voice_seconds": 0}
    for values in series.values():
        for metric in totals:
            totals[metric] += values.get(metric, 0)
    unique_users = await db.scalar(
        select(func.count(func.distinct(MessageLog.user_id))).where(
            MessageLog.guild_id == guild_id, MessageLog.channel_id == channel_id,
            MessageLog.created_at >= start, MessageLog.event == "create",
        )
    )
    return {"guild_id": str(guild_id), "channel_id": str(channel_id), "days": days,
            "totals": totals, "unique_active_members": int(unique_users or 0),
            "series": [{"bucket": key, **series[key]} for key in sorted(series)]}


@router.get("/{guild_id}/analytics/members/{user_id}", summary="Detalhar atividade estatística de um membro")
async def get_member_analytics(
    guild_id: int,
    user_id: int,
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    config = await db.get(AnalyticsConfig, guild_id)
    if config is not None and not config.member_statistics_for_managers and user.get("system_role") != SystemRole.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="As estatísticas individuais estão restritas pela configuração do servidor")
    member = await db.scalar(select(Member).where(Member.guild_id == guild_id, Member.user_id == user_id))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro não encontrado neste servidor")
    result = await member_activity_report(db, guild_id, user_id, days)
    result["lifetime_messages"] = member.message_count
    result["lifetime_voice_seconds"] = member.voice_seconds
    result["joined_at"] = member.joined_at.isoformat() if member.joined_at else None
    result["currently_active_member"] = member.left_at is None
    return result


@router.get("/{guild_id}/analytics/settings", summary="Consultar filtros de estatísticas")
async def get_analytics_settings(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    row = await get_or_create_analytics_config(db, guild_id)
    await db.commit()
    await db.refresh(row)
    return _analytics_config_json(row)


@router.patch("/{guild_id}/analytics/settings", summary="Atualizar filtros de estatísticas")
async def update_analytics_settings(
    guild_id: int,
    payload: AnalyticsConfigUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe ao menos uma configuração")
    row = await get_or_create_analytics_config(db, guild_id)
    before = _analytics_config_json(row)
    now = datetime.now(timezone.utc)
    disabling_voice = changes.get("track_voice") is False and row.track_voice is True
    if disabling_voice:
        active_sessions = list((await db.execute(
            select(Member).where(Member.guild_id == guild_id, Member.voice_joined_at.is_not(None),
                                 Member.voice_analytics_active.is_(True)).with_for_update()
        )).scalars())
        for member_row in active_sessions:
            started_at = member_row.voice_joined_at
            if started_at is not None and member_row.voice_channel_id is not None:
                await record_voice_segment(db, guild_id, member_row.user_id, member_row.voice_channel_id, started_at, now)
            member_row.voice_analytics_active = False
            member_row.updated_at = now
    for field, value in changes.items():
        if field in {"excluded_channel_ids", "excluded_category_ids", "excluded_role_ids"}:
            value = normalize_id_list(value)
        setattr(row, field, value)
    row.updated_at = now
    await _write_audit(db, guild_id, user, "analytics.settings_update", "analytics_settings", before, _analytics_config_json(row))
    await db.commit()
    await db.refresh(row)
    return _analytics_config_json(row)


@router.get("/{guild_id}/analytics/counters", summary="Listar contadores automáticos")
async def list_stat_counters(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    result = await db.execute(select(StatCounter).where(StatCounter.guild_id == guild_id).order_by(StatCounter.id.asc()))
    return {"items": [_counter_json(row) for row in result.scalars().all()]}


@router.post("/{guild_id}/analytics/counters", status_code=status.HTTP_201_CREATED, summary="Criar um contador automático")
async def create_stat_counter(
    guild_id: int,
    payload: StatCounterCreateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    if payload.metric in {"messages_period", "active_members_period"} and payload.period_days is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Esta métrica exige period_days")
    try:
        template = validate_counter_template(payload.format_template)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    await db.scalar(select(Guild.id).where(Guild.id == guild_id).with_for_update())
    existing_counters = int(await db.scalar(select(func.count(StatCounter.id)).where(StatCounter.guild_id == guild_id)) or 0)
    if existing_counters >= 100:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="O limite de 100 contadores por servidor foi atingido")
    now = datetime.now(timezone.utc)
    row = StatCounter(guild_id=guild_id, channel_id=payload.channel_id, metric=payload.metric,
                      format_template=template, period_days=payload.period_days, goal_value=payload.goal_value,
                      enabled=payload.enabled, created_at=now, updated_at=now)
    db.add(row)
    try:
        await db.flush()
        await _write_audit(db, guild_id, user, "analytics.counter_create", f"counter:{row.id}", None, _counter_json(row))
        await db.commit()
        await db.refresh(row)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Este canal já possui um contador configurado") from None
    return _counter_json(row)


@router.patch("/{guild_id}/analytics/counters/{counter_id}", summary="Atualizar um contador automático")
async def update_stat_counter(
    guild_id: int,
    counter_id: int,
    payload: StatCounterUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    row = await db.scalar(select(StatCounter).where(StatCounter.id == counter_id, StatCounter.guild_id == guild_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contador não encontrado")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe ao menos um campo")
    next_metric = changes.get("metric", row.metric)
    next_period = changes.get("period_days", row.period_days)
    if next_metric in {"messages_period", "active_members_period"} and next_period is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Esta métrica exige um período")
    if "format_template" in changes and changes["format_template"] is not None:
        try:
            changes["format_template"] = validate_counter_template(changes["format_template"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    before = _counter_json(row)
    for field, value in changes.items():
        if field == "period_days" and value is None and next_metric in {"messages_period", "active_members_period"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Esta métrica exige um período")
        setattr(row, field, value)
    row.updated_at = datetime.now(timezone.utc)
    await _write_audit(db, guild_id, user, "analytics.counter_update", f"counter:{counter_id}", before, _counter_json(row))
    await db.commit()
    await db.refresh(row)
    return _counter_json(row)


@router.delete("/{guild_id}/analytics/counters/{counter_id}", summary="Excluir um contador automático")
async def delete_stat_counter(guild_id: int, counter_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    row = await db.scalar(select(StatCounter).where(StatCounter.id == counter_id, StatCounter.guild_id == guild_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contador não encontrado")
    before = _counter_json(row)
    await _write_audit(db, guild_id, user, "analytics.counter_delete", f"counter:{counter_id}", before, None)
    await db.delete(row)
    await db.commit()
    return {"deleted": str(counter_id)}


@router.get("/{guild_id}/analytics/role-rules", summary="Listar regras de cargos por atividade")
async def list_activity_role_rules(guild_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    result = await db.execute(select(ActivityRoleRule).where(ActivityRoleRule.guild_id == guild_id).order_by(ActivityRoleRule.id.asc()))
    return {"items": [_activity_rule_json(row) for row in result.scalars().all()]}


@router.post("/{guild_id}/analytics/role-rules", status_code=status.HTTP_201_CREATED, summary="Criar regra de cargo por atividade")
async def create_activity_role_rule(
    guild_id: int,
    payload: ActivityRoleRuleCreateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    if all(value is None for value in (payload.min_messages, payload.min_voice_seconds, payload.min_active_days)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Configure ao menos um requisito de atividade")
    if payload.role_id == guild_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O cargo @everyone não pode ser automatizado")
    await db.scalar(select(Guild.id).where(Guild.id == guild_id).with_for_update())
    existing_rules = int(await db.scalar(select(func.count(ActivityRoleRule.id)).where(ActivityRoleRule.guild_id == guild_id)) or 0)
    if existing_rules >= 100:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="O limite de 100 regras de cargos por servidor foi atingido")
    now = datetime.now(timezone.utc)
    row = ActivityRoleRule(guild_id=guild_id, name=payload.name.strip(), role_id=payload.role_id,
                           min_messages=payload.min_messages, messages_window_days=payload.messages_window_days,
                           min_voice_seconds=payload.min_voice_seconds, voice_window_days=payload.voice_window_days,
                           min_active_days=payload.min_active_days, active_days_window_days=payload.active_days_window_days,
                           enabled=payload.enabled, remove_when_unqualified=payload.remove_when_unqualified,
                           created_at=now, updated_at=now)
    if not row.name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="O nome da regra não pode ficar vazio")
    db.add(row)
    try:
        await db.flush()
        await _write_audit(db, guild_id, user, "analytics.role_rule_create", f"role-rule:{row.id}", None, _activity_rule_json(row))
        await db.commit()
        await db.refresh(row)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Já existe uma regra com este nome neste servidor") from None
    return _activity_rule_json(row)


@router.patch("/{guild_id}/analytics/role-rules/{rule_id}", summary="Atualizar regra de cargo por atividade")
async def update_activity_role_rule(
    guild_id: int,
    rule_id: int,
    payload: ActivityRoleRuleUpdateSchema,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_guild_manager),
):
    row = await db.scalar(select(ActivityRoleRule).where(ActivityRoleRule.id == rule_id, ActivityRoleRule.guild_id == guild_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regra não encontrada")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe ao menos um campo")
    resulting = {field: changes.get(field, getattr(row, field)) for field in (
        "min_messages", "min_voice_seconds", "min_active_days"
    )}
    if all(value is None for value in resulting.values()):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A regra precisa manter ao menos um requisito")
    before = _activity_rule_json(row)
    for field, value in changes.items():
        setattr(row, field, value)
    row.last_error = None
    row.updated_at = datetime.now(timezone.utc)
    await _write_audit(db, guild_id, user, "analytics.role_rule_update", f"role-rule:{rule_id}", before, _activity_rule_json(row))
    await db.commit()
    await db.refresh(row)
    return _activity_rule_json(row)


@router.delete("/{guild_id}/analytics/role-rules/{rule_id}", summary="Excluir regra de cargo por atividade")
async def delete_activity_role_rule(guild_id: int, rule_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(require_guild_manager)):
    row = await db.scalar(select(ActivityRoleRule).where(ActivityRoleRule.id == rule_id, ActivityRoleRule.guild_id == guild_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Regra não encontrada")
    before = _activity_rule_json(row)
    await _write_audit(db, guild_id, user, "analytics.role_rule_delete", f"role-rule:{rule_id}", before, None)
    await db.delete(row)
    await db.commit()
    return {"deleted": str(rule_id)}
