from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from hashlib import sha256
from re import findall, search, sub
from typing import Any, Iterable
from collections import defaultdict, deque
import asyncio
import logging
import math
import secrets

logger = logging.getLogger("bn_bot.automod")

DEFAULT_RULES = [
    {"name": "Spam", "rule_type": "spam", "action": "timeout", "priority": 80, "config": {"max_messages": 5, "window_seconds": 8, "timeout_seconds": 60}},
    {"name": "Flood", "rule_type": "flood", "action": "timeout", "priority": 90, "config": {"max_messages": 8, "window_seconds": 4, "timeout_seconds": 120}},
    {"name": "Duplicadas", "rule_type": "duplicate", "action": "delete", "priority": 60, "config": {}},
    {"name": "Similaridade", "rule_type": "similarity", "action": "delete", "priority": 55, "config": {"threshold": 0.92, "min_length": 20}},
    {"name": "Links", "rule_type": "link", "action": "delete", "priority": 70, "config": {"block_all": True}},
    {"name": "Convites", "rule_type": "invite", "action": "delete", "priority": 75, "config": {}},
    {"name": "Palavras proibidas", "rule_type": "forbidden_word", "action": "delete", "priority": 85, "config": {"words": []}},
    {"name": "Caps", "rule_type": "caps", "action": "delete", "priority": 40, "config": {"min_letters": 20, "ratio": 0.75}},
    {"name": "Menções", "rule_type": "mentions", "action": "timeout", "priority": 75, "config": {"max_total": 5, "max_roles": 3, "timeout_seconds": 60}},
    {"name": "Arquivos", "rule_type": "attachments", "action": "delete", "priority": 70, "config": {"max_files": 5, "max_total_size_mb": 25, "blocked_extensions": ["exe", "scr", "bat", "cmd", "com", "msi"]}},
    {"name": "Comportamento suspeito", "rule_type": "suspicious", "action": "warn", "priority": 50, "config": {"threshold": 60, "new_account_seconds": 604800, "new_member_seconds": 86400}},
]

RULE_TYPES = {
    "spam",
    "flood",
    "duplicate",
    "similarity",
    "link",
    "invite",
    "forbidden_word",
    "caps",
    "mentions",
    "attachments",
    "suspicious",
}

ACTIONS = {"none", "delete", "warn", "timeout", "kick", "ban"}
LIST_TYPES = {"whitelist", "blacklist"}
ENTRY_TYPES = {"user", "channel", "role", "word", "domain"}

URL_PATTERN = r"https?://[^\s<>()]+|www\.[^\s<>()]+"
INVITE_PATTERN = r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9-]+"
DOMAIN_PATTERN = r"(?:(?:https?|ftp)://)?(?:www\.)?([^/\s:?#]+)"

@dataclass(slots=True)
class AttachmentInfo:
    filename: str
    size: int

@dataclass(slots=True)
class MessageContext:
    guild_id: int
    channel_id: int
    user_id: int
    message_id: int | None = None
    role_ids: set[int] = field(default_factory=set)
    content: str = ""
    mention_count: int = 0
    role_mention_count: int = 0
    attachments: list[AttachmentInfo] = field(default_factory=list)
    author_age_seconds: int | None = None
    member_age_seconds: int | None = None
    recent_contents: list[str] = field(default_factory=list)
    recent_message_timestamps: list[datetime] = field(default_factory=list)

@dataclass(slots=True)
class AutoModDecision:
    rule_type: str
    severity: int
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class RuleDefinition:
    id: int
    name: str
    rule_type: str
    action: str
    enabled: bool
    priority: int
    channels: set[int]
    roles: set[int]
    config: dict[str, Any]

@dataclass(slots=True)
class AutoModEvaluation:
    matched: list[AutoModDecision]
    action: str
    rule: RuleDefinition | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_content(value: str) -> str:
    value = value.casefold()
    value = sub(r"https?://|www\.", "", value)
    value = sub(r"[^\w\s]", " ", value)
    value = sub(r"\s+", " ", value).strip()
    return value


def content_hash(value: str) -> str:
    return sha256(normalize_content(value).encode("utf-8")).hexdigest()


def extract_urls(value: str) -> list[str]:
    return findall(URL_PATTERN, value)


def normalize_domain(value: str) -> str:
    domain = str(value).strip().casefold().strip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def domain_matches(domain: str, configured: str) -> bool:
    normalized_domain = normalize_domain(domain)
    normalized_configured = normalize_domain(configured)
    return bool(normalized_domain and normalized_configured and (normalized_domain == normalized_configured or normalized_domain.endswith("." + normalized_configured)))


def extract_domains(value: str) -> set[str]:
    domains: set[str] = set()
    for url in extract_urls(value):
        match = search(DOMAIN_PATTERN, url.casefold())
        if match:
            normalized = normalize_domain(match.group(1))
            if normalized:
                domains.add(normalized)
    return domains


def is_whitelisted(context: MessageContext, entries: Iterable[dict[str, Any]], content_domains: set[str]) -> bool:
    for entry in entries:
        kind = str(entry.get("entry_type", ""))
        value = str(entry.get("value", ""))
        if kind == "user" and value == str(context.user_id):
            return True
        if kind == "channel" and value == str(context.channel_id):
            return True
        if kind == "role" and value:
            try:
                if int(value) in context.role_ids:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def whitelisted_domains(entries: Iterable[dict[str, Any]]) -> set[str]:
    return {normalize_domain(entry.get("value", "")) for entry in entries if str(entry.get("entry_type", "")) == "domain" and normalize_domain(entry.get("value", ""))}


def is_blacklisted(context: MessageContext, entries: Iterable[dict[str, Any]], content_domains: set[str], whitelisted_words: set[str] | None = None) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    whitelisted_words = whitelisted_words or set()
    for entry in entries:
        kind = str(entry.get("entry_type", ""))
        value = str(entry.get("value", ""))
        if kind == "user" and value == str(context.user_id):
            matches.append(entry)
        elif kind == "channel" and value == str(context.channel_id):
            matches.append(entry)
        elif kind == "role" and value:
            try:
                if int(value) in context.role_ids:
                    matches.append(entry)
            except (TypeError, ValueError):
                continue
        elif kind == "domain" and any(domain_matches(domain, value) for domain in content_domains):
            matches.append(entry)
        elif kind == "word" and value.casefold() and value.casefold() not in whitelisted_words and value.casefold() in context.content.casefold():
            matches.append(entry)
    return matches


def scope_matches(rule: RuleDefinition, context: MessageContext) -> bool:
    if rule.channels and context.channel_id not in rule.channels:
        return False
    if rule.roles and not (rule.roles & context.role_ids):
        return False
    return True


def validate_rule_config(rule_type: str, config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if rule_type not in RULE_TYPES:
        return ["tipo de regra inválido"]
    integer_rules = {"max_messages": (1, 1000), "window_seconds": (1, 3600), "min_letters": (1, 10000), "max_total": (1, 100), "max_roles": (0, 100), "max_files": (0, 100), "new_account_seconds": (0, 31_536_000), "new_member_seconds": (0, 31_536_000), "activity_trigger": (1, 1000)}
    for key, (minimum, maximum) in integer_rules.items():
        if key in config:
            value = config[key]
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > maximum:
                errors.append(f"{key} deve ser inteiro entre {minimum} e {maximum}")
    float_rules = {"ratio": (0.0, 1.0), "max_total_size_mb": (0.0, 2048.0)}
    for key, (minimum, maximum) in float_rules.items():
        if key in config:
            value = config[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or value < minimum or value > maximum:
                errors.append(f"{key} deve ser um número finito entre {minimum} e {maximum}")
    if rule_type == "suspicious" and "threshold" in config:
        value = config["threshold"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 100:
            errors.append("threshold de comportamento suspeito deve ser inteiro entre 1 e 100")
    if rule_type == "similarity" and "threshold" in config:
        value = config["threshold"]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or value < 0.5 or value > 1.0:
            errors.append("threshold de similaridade deve estar entre 0.5 e 1.0")
    if rule_type == "similarity" and "min_length" in config:
        value = config["min_length"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 10_000:
            errors.append("min_length deve ser inteiro entre 1 e 10000")
    if rule_type == "caps" and "ratio" in config:
        value = config["ratio"]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0.5 or value > 1.0:
            errors.append("ratio deve estar entre 0.5 e 1.0")
    if rule_type == "attachments" and "max_total_size_mb" in config:
        value = config["max_total_size_mb"]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) or value < 0 or value > 2048:
            errors.append("max_total_size_mb deve estar entre 0 e 2048")
    if rule_type == "suspicious":
        for key in ("new_account_weight", "new_member_weight", "invite_weight", "link_weight", "mention_weight", "activity_weight"):
            if key in config:
                value = config[key]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 100:
                    errors.append(f"{key} deve ser inteiro entre 0 e 100")
        if "mention_trigger" in config:
            value = config["mention_trigger"]
            if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 100:
                errors.append("mention_trigger deve ser inteiro entre 1 e 100")
    if rule_type in {"forbidden_word", "attachments"}:
        list_key = "words" if rule_type == "forbidden_word" else None
        if list_key and list_key in config and not isinstance(config[list_key], list):
            errors.append("words deve ser uma lista")
        for list_name in ("blocked_extensions", "allowed_extensions"):
            if list_name in config and not isinstance(config[list_name], list):
                errors.append(f"{list_name} deve ser uma lista")
    for list_name in ("blocked_domains", "allowed_domains"):
        if list_name in config and not isinstance(config[list_name], list):
            errors.append(f"{list_name} deve ser uma lista")
    if "timeout_seconds" in config:
        value = config["timeout_seconds"]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 2_419_200:
            errors.append("timeout_seconds deve ser inteiro entre 1 e 2419200")
    return errors


def _timestamp_count(timestamps: list[datetime], window_seconds: int, now: datetime) -> int:
    cutoff = now - timedelta(seconds=window_seconds)
    return sum(1 for item in timestamps if item >= cutoff)


def _caps_ratio(content: str) -> tuple[int, int, float]:
    letters = [char for char in content if char.isalpha()]
    uppercase = sum(char.isupper() for char in letters)
    total = len(letters)
    return uppercase, total, uppercase / total if total else 0.0


def detect_rule(rule: RuleDefinition, context: MessageContext, now: datetime | None = None, domain_whitelist: set[str] | None = None, whitelisted_words: set[str] | None = None) -> AutoModDecision | None:
    if not rule.enabled or rule.rule_type not in RULE_TYPES or rule.action not in ACTIONS:
        return None
    if not scope_matches(rule, context):
        return None
    now = now or utc_now()
    config = rule.config
    content = context.content
    normalized = normalize_content(content)
    domains = extract_domains(content)
    if rule.rule_type in {"link", "invite"}:
        if is_whitelisted(context, config.get("whitelist", []), domains):
            return None
    if rule.rule_type == "spam":
        limit = max(int(config.get("max_messages", 5)), 1)
        window = max(int(config.get("window_seconds", 8)), 1)
        count = _timestamp_count(context.recent_message_timestamps, window, now) + 1
        if count >= limit:
            return AutoModDecision("spam", 70, f"mais de {limit - 1} mensagens em {window}s", {"count": count, "window_seconds": window})
    elif rule.rule_type == "flood":
        limit = max(int(config.get("max_messages", 8)), 1)
        window = max(int(config.get("window_seconds", 4)), 1)
        count = _timestamp_count(context.recent_message_timestamps, window, now) + 1
        if count >= limit:
            return AutoModDecision("flood", 80, f"volume de mensagens acima de {limit - 1} em {window}s", {"count": count, "window_seconds": window})
    elif rule.rule_type == "duplicate":
        recent_hashes = {content_hash(item) for item in context.recent_contents if item.strip()}
        if normalized and content_hash(content) in recent_hashes:
            return AutoModDecision("duplicate", 65, "mensagem duplicada detectada", {"hash": content_hash(content)})
    elif rule.rule_type == "similarity":
        threshold = float(config.get("threshold", 0.92))
        minimum = max(int(config.get("min_length", 20)), 1)
        if len(normalized) >= minimum:
            for previous in context.recent_contents:
                ratio = SequenceMatcher(None, normalized, normalize_content(previous)).ratio()
                if ratio >= threshold:
                    return AutoModDecision("similarity", 60, f"mensagem com similaridade de {ratio:.2f}", {"ratio": round(ratio, 4), "threshold": threshold})
    elif rule.rule_type == "link":
        blocked_domains = {normalize_domain(item) for item in config.get("blocked_domains", []) if normalize_domain(item)}
        allowed_domains = {normalize_domain(item) for item in config.get("allowed_domains", []) if normalize_domain(item)}
        allowed_domains.update(normalize_domain(item) for item in (domain_whitelist or set()) if normalize_domain(item))
        allowed = {domain for domain in domains if any(domain_matches(domain, configured) for configured in allowed_domains)}
        detected = sorted(domain for domain in domains if any(domain_matches(domain, blocked) for blocked in blocked_domains) and domain not in allowed)
        block_all = bool(config.get("block_all", True))
        blocked_by_default = bool(domains and block_all and not allowed_domains)
        outside_allowlist = bool(allowed_domains) and any(domain not in allowed for domain in domains)
        if detected or outside_allowlist or blocked_by_default:
            return AutoModDecision("link", 75, "link não permitido", {"domains": detected or sorted(domain for domain in domains if domain not in allowed)})
    elif rule.rule_type == "invite":
        allowed_domains = {normalize_domain(item) for item in (domain_whitelist or set()) if normalize_domain(item)}
        if search(INVITE_PATTERN, content, flags=0) and not any(domain_matches(domain, allowed) for domain in domains for allowed in allowed_domains):
            return AutoModDecision("invite", 80, "convite do Discord detectado", {})
    elif rule.rule_type == "forbidden_word":
        lowered = content.casefold()
        for word in config.get("words", []):
            value = str(word).casefold().strip()
            if value and value not in whitelisted_words and value in lowered:
                return AutoModDecision("forbidden_word", 85, "palavra proibida detectada", {"word": value})
    elif rule.rule_type == "caps":
        minimum = max(int(config.get("min_letters", 20)), 1)
        threshold = float(config.get("ratio", 0.75))
        uppercase, total, ratio = _caps_ratio(content)
        if total >= minimum and ratio >= threshold:
            return AutoModDecision("caps", 45, f"uso excessivo de letras maiúsculas ({ratio:.0%})", {"uppercase": uppercase, "letters": total, "ratio": ratio})
    elif rule.rule_type == "mentions":
        max_total = int(config.get("max_total", 5))
        max_roles = int(config.get("max_roles", max_total))
        if context.mention_count > max_total or context.role_mention_count > max_roles:
            return AutoModDecision("mentions", 75, "quantidade excessiva de menções", {"mentions": context.mention_count, "role_mentions": context.role_mention_count})
    elif rule.rule_type == "attachments":
        max_files = int(config.get("max_files", 1_000_000))
        max_size_mb = float(config.get("max_total_size_mb", 1_000_000))
        blocked_extensions = {str(item).casefold().lstrip(".") for item in config.get("blocked_extensions", [])}
        allowed_extensions = {str(item).casefold().lstrip(".") for item in config.get("allowed_extensions", [])}
        total_size = sum(item.size for item in context.attachments)
        names = [item.filename.casefold() for item in context.attachments]
        extensions = {name.rsplit(".", 1)[1] for name in names if "." in name}
        blocked = extensions & blocked_extensions
        too_many = len(context.attachments) > max_files
        too_large = total_size > max_size_mb * 1024 * 1024
        outside_allowlist = bool(allowed_extensions and (not extensions or not extensions.issubset(allowed_extensions)))
        if too_many or too_large or blocked or outside_allowlist:
            return AutoModDecision("attachments", 70, "arquivo ou conjunto de arquivos fora da política", {"count": len(context.attachments), "total_size": total_size, "blocked_extensions": sorted(blocked), "extensions": sorted(extensions)})
    elif rule.rule_type == "suspicious":
        score = 0
        signals: list[str] = []
        max_account_age = int(config.get("new_account_seconds", 86_400 * 7))
        max_member_age = int(config.get("new_member_seconds", 86_400))
        if context.author_age_seconds is not None and context.author_age_seconds < max_account_age:
            score += int(config.get("new_account_weight", 25))
            signals.append("conta recente")
        if context.member_age_seconds is not None and context.member_age_seconds < max_member_age:
            score += int(config.get("new_member_weight", 20))
            signals.append("entrada recente")
        if search(INVITE_PATTERN, content):
            score += int(config.get("invite_weight", 30))
            signals.append("convite")
        if domains:
            score += int(config.get("link_weight", 15))
            signals.append("link")
        if context.mention_count >= int(config.get("mention_trigger", 5)):
            score += int(config.get("mention_weight", 20))
            signals.append("menções")
        if len(context.recent_message_timestamps) >= int(config.get("activity_trigger", 8)):
            score += int(config.get("activity_weight", 25))
            signals.append("atividade acelerada")
        threshold = int(config.get("threshold", 60))
        if score >= threshold:
            return AutoModDecision("suspicious", min(score, 100), "comportamento suspeito detectado", {"score": score, "threshold": threshold, "signals": signals})
    return None


def evaluate_rules(
    rules: Iterable[RuleDefinition],
    context: MessageContext,
    whitelist_entries: Iterable[dict[str, Any]] = (),
    blacklist_entries: Iterable[dict[str, Any]] = (),
    blacklist_action: str = "delete",
    now: datetime | None = None,
) -> AutoModEvaluation:
    now = now or utc_now()
    rules_list = list(rules)
    domains = extract_domains(context.content)
    if is_whitelisted(context, whitelist_entries, domains):
        return AutoModEvaluation([], "none", None)
    whitelist_list = list(whitelist_entries)
    whitelisted_words = {str(entry.get("value", "")).casefold().strip() for entry in whitelist_list if str(entry.get("entry_type", "")) == "word" and str(entry.get("value", "")).strip()}
    blacklisted = is_blacklisted(context, blacklist_entries, domains, whitelisted_words)
    decisions: list[AutoModDecision] = []
    domain_allowlist = whitelisted_domains(whitelist_list)
    if blacklisted:
        decisions.append(AutoModDecision("blacklist", 100, "entrada de blacklist correspondente", {"entries": blacklisted, "priority": 1000000}))
    for rule in rules_list:
        decision = detect_rule(rule, context, now, domain_allowlist, whitelisted_words)
        if decision:
            decision.metadata["priority"] = rule.priority
            decision.metadata["rule_id"] = rule.id
            decisions.append(decision)
    if not decisions:
        return AutoModEvaluation([], "none", None)
    ordered = sorted(decisions, key=lambda item: (int(item.metadata.get("priority", 0)), item.severity), reverse=True)
    primary = ordered[0]
    if primary.rule_type == "blacklist":
        pseudo_rule = RuleDefinition(0, "blacklist", "blacklist", blacklist_action if blacklist_action in ACTIONS else "delete", True, 1_000_000, set(), set(), {})
        return AutoModEvaluation(ordered, pseudo_rule.action, pseudo_rule)
    selected_rule = next((rule for rule in rules_list if rule.id == int(primary.metadata.get("rule_id", -1))), None)
    return AutoModEvaluation(ordered, selected_rule.action if selected_rule else "none", selected_rule)


class RedisActivityStore:
    def __init__(self, redis: Any, prefix: str = "bn:automod") -> None:
        self.redis = redis
        self.prefix = prefix

    def key(self, guild_id: int, user_id: int, kind: str) -> str:
        return f"{self.prefix}:{guild_id}:{user_id}:{kind}"

    async def add_message(self, context: MessageContext, now: datetime) -> tuple[list[datetime], list[str]]:
        timestamps_key = self.key(context.guild_id, context.user_id, "timestamps")
        contents_key = self.key(context.guild_id, context.user_id, "contents:v2")
        score = now.timestamp()
        token = str(context.message_id) if context.message_id is not None else secrets.token_hex(12)
        member = f"{score:.6f}:{token}"
        await self.redis.zadd(timestamps_key, {member: score})
        cutoff = (now - timedelta(seconds=120)).timestamp()
        await self.redis.zremrangebyscore(timestamps_key, 0, cutoff)
        values = await self.redis.zrange(timestamps_key, 0, -1, withscores=True)
        timestamps = [datetime.fromtimestamp(float(item[1]), timezone.utc) for item in values if str(item[0]) != member]
        content_entry = f"{token}\t{context.content[:2000]}"
        await self.redis.lpush(contents_key, content_entry)
        await self.redis.ltrim(contents_key, 0, 24)
        raw_contents = [str(item) for item in await self.redis.lrange(contents_key, 0, 24)]
        recent_contents = [item.split("\t", 1)[1] for item in raw_contents if "\t" in item and item.split("\t", 1)[0] != token]
        return timestamps, recent_contents


_memory_timestamps: dict[tuple[int, int], deque[datetime]] = defaultdict(deque)
_memory_contents: dict[tuple[int, int], deque[str]] = defaultdict(deque)
_memory_lock = asyncio.Lock()


async def collect_activity(context: MessageContext) -> MessageContext:
    now = utc_now()
    try:
        from app.core.redis import redis_client
        store = RedisActivityStore(redis_client)
        timestamps, recent_contents = await store.add_message(context, now)
        context.recent_message_timestamps = timestamps
        context.recent_contents = recent_contents
        return context
    except Exception:
        key = (context.guild_id, context.user_id)
        async with _memory_lock:
            timestamps = _memory_timestamps[key]
            contents = _memory_contents[key]
            recent_timestamps = list(timestamps)
            recent_contents = list(contents)
            timestamps.append(now)
            contents.appendleft(context.content[:2000])
            cutoff = now - timedelta(seconds=120)
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()
            while len(contents) > 25:
                contents.pop()
        context.recent_message_timestamps = recent_timestamps
        context.recent_contents = recent_contents
        logger.warning("Redis indisponível para AutoMod; usando fallback local guild=%s user=%s", context.guild_id, context.user_id)
        return context
