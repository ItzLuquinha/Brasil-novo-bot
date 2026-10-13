from datetime import datetime, timedelta, timezone
from app.services.automod import AttachmentInfo, MessageContext, RuleDefinition, evaluate_rules, validate_rule_config


def rule(rule_id: int, rule_type: str, action: str = "delete", config: dict | None = None, channels=None, roles=None, priority: int = 0) -> RuleDefinition:
    return RuleDefinition(rule_id, rule_type, rule_type, action, True, priority, set(channels or []), set(roles or []), config or {})


def context(content: str = "", **kwargs) -> MessageContext:
    return MessageContext(1, 2, 3, {4}, content=content, **kwargs)


def test_caps_rule() -> None:
    result = evaluate_rules([rule(1, "caps", config={"min_letters": 10, "ratio": 0.75})], context("THIS IS A VERY LOUD MESSAGE"))
    assert result.action == "delete"
    assert result.matched[0].rule_type == "caps"


def test_link_and_invite_rules() -> None:
    result = evaluate_rules([rule(1, "link"), rule(2, "invite", action="timeout", config={"timeout_seconds": 60})], context("entra https://example.com e discord.gg/test"))
    assert {item.rule_type for item in result.matched} == {"link", "invite"}
    assert result.action == "timeout"


def test_duplicate_similarity_mentions_and_attachments() -> None:
    result = evaluate_rules(
        [
            rule(1, "duplicate"),
            rule(2, "similarity"),
            rule(3, "mentions"),
            rule(4, "attachments"),
        ],
        context(
            "This message is extremely similar to the previous message",
            mention_count=8,
            role_mention_count=2,
            attachments=[AttachmentInfo("payload.exe", 5_000_000)],
            recent_contents=["This message is extremely similar to the previous message"],
        ),
    )
    assert len(result.matched) >= 3
    assert result.action == "delete"


def test_spam_and_flood_use_recent_window() -> None:
    now = datetime.now(timezone.utc)
    timestamps = [now - timedelta(seconds=value) for value in (1, 2, 3, 4, 5, 6, 7)]
    result = evaluate_rules([rule(1, "spam", config={"max_messages": 5, "window_seconds": 8}), rule(2, "flood", action="timeout", config={"max_messages": 8, "window_seconds": 8})], context(recent_message_timestamps=timestamps), now=now)
    assert result.matched[0].rule_type == "flood"
    assert result.action == "timeout"


def test_scope_is_respected_and_whitelist_wins() -> None:
    scoped = rule(1, "forbidden_word", config={"words": ["banido"]}, channels=[99])
    result = evaluate_rules([scoped], context("texto banido"))
    assert not result.matched
    result = evaluate_rules([scoped], context("texto banido",), whitelist_entries=[{"entry_type": "user", "value": "3"}])
    assert not result.matched


def test_blacklist_overrides_normal_rules() -> None:
    result = evaluate_rules([rule(1, "caps", action="warn")], context("HELLO THERE GENERAL KENOBI"), blacklist_entries=[{"entry_type": "user", "value": "3"}], blacklist_action="warn")
    assert result.action == "warn"
    assert result.matched[0].rule_type == "blacklist"


def test_priority_controls_conflicting_actions() -> None:
    result = evaluate_rules([rule(1, "caps", action="delete", config={"min_letters": 10, "ratio": 0.75}), rule(2, "mentions", action="timeout", config={"max_total": 3}, priority=100)], context("HELLO THERE EVERYONE", mention_count=6))
    assert result.action == "timeout"


def test_rule_config_validation() -> None:
    errors = validate_rule_config("spam", {"max_messages": 0, "window_seconds": 5000})
    assert len(errors) == 2
    assert not validate_rule_config("caps", {"min_letters": 10, "ratio": 0.8})


def test_domain_whitelist_only_bypasses_link_rule() -> None:
    result = evaluate_rules([rule(1, "link", config={"block_all": True}), rule(2, "caps", config={"min_letters": 10, "ratio": 0.75})], context("HTTPS://EXAMPLE.COM THIS MESSAGE IS LOUD"), whitelist_entries=[{"entry_type": "domain", "value": "example.com"}])
    assert {item.rule_type for item in result.matched} == {"caps"}


def test_matching_same_type_rule_keeps_highest_priority_rule() -> None:
    result = evaluate_rules([rule(1, "caps", action="delete", config={"min_letters": 10, "ratio": 0.75}, priority=10, channels=[2]), rule(2, "caps", action="timeout", config={"min_letters": 10, "ratio": 0.75}, priority=20, channels=[2])], context("THIS IS VERY LOUD"))
    assert result.action == "timeout"
    assert result.rule is not None
    assert result.rule.id == 2


def test_domain_whitelist_allows_invite_domain() -> None:
    result = evaluate_rules([rule(1, "invite")], context("https://discord.gg/test"), whitelist_entries=[{"entry_type": "domain", "value": "discord.gg"}])
    assert not result.matched


def test_suspicious_threshold_accepts_score_range() -> None:
    assert not validate_rule_config("suspicious", {"threshold": 60})


def test_malformed_whitelist_role_does_not_crash_evaluation() -> None:
    result = evaluate_rules([rule(1, "caps", config={"min_letters": 10, "ratio": 0.75})], context("THIS IS VERY LOUD"), whitelist_entries=[{"entry_type": "role", "value": "invalid"}])
    assert result.action == "delete"


def test_validate_rule_config_rejects_invalid_suspicious_weights() -> None:
    from app.services.automod import validate_rule_config
    errors = validate_rule_config("suspicious", {"new_account_weight": -1, "mention_trigger": 0, "activity_weight": 101})
    assert errors


def test_validate_rule_config_rejects_invalid_similarity_min_length_and_nan() -> None:
    from app.services.automod import validate_rule_config
    errors = validate_rule_config("similarity", {"min_length": 0, "threshold": float("nan")})
    assert any("min_length" in error for error in errors)
    assert any("threshold" in error for error in errors)


def test_domain_whitelist_overrides_blocked_domain_and_www_subdomain() -> None:
    rules = [rule(1, "link", config={"block_all": True, "blocked_domains": ["example.com"]})]
    allowed = [{"entry_type": "domain", "value": "example.com"}]
    result = evaluate_rules(rules, context("https://www.example.com/path"), whitelist_entries=allowed)
    assert not result.matched


def test_invite_domain_whitelist_requires_matching_domain() -> None:
    rules = [rule(1, "invite")]
    blocked = evaluate_rules(rules, context("https://discord.gg/test"), whitelist_entries=[{"entry_type": "domain", "value": "example.com"}])
    allowed = evaluate_rules(rules, context("https://discord.gg/test"), whitelist_entries=[{"entry_type": "domain", "value": "discord.gg"}])
    assert blocked.action == "delete"
    assert not allowed.matched
