from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandAuditCase:
    qualified_name: str
    file: str
    function: str
    parameter_count: int
    guild_only: bool
    permission_guard: bool
    response_path: bool
    defer_before_io: bool
    semantic_ok: bool
    issue: str = ""


ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "discord" / "cogs"
LEGACY_COMMAND_FILES = {"bump.py"}

IO_FINAL_NAMES = {
    "ban", "create_role", "create_text_channel", "delete", "edit", "fetch_channel", "fetch_message",
    "history", "kick", "purge", "send", "set_permissions", "timeout", "unban",
}

EXPECTED_COMMANDS = {
    "admin credit", "admin debit", "admin job-add", "admin job-remove", "admin purge-log", "admin rewards", "admin shop-add", "admin timezone",
    "antiraid configure", "antiraid disable", "antiraid enable", "antiraid setup", "antiraid status", "antiraid unlock",
    "automod disable", "automod enable", "automod list-action", "automod list-add", "automod list-remove", "automod lists",
    "automod rule-add", "automod rule-delete", "automod rule-update", "automod rules", "automod setup", "automod status",
    "avatar", "balance", "ban", "bank", "botinfo", "buy", "clearwarns", "community-config", "daily", "dashboard",
    "deposit", "giveaway cancel", "giveaway create", "giveaway end", "giveaway reroll", "history", "inventory", "tutorial", "job", "jobs",
    "kick", "leaderboard", "pay", "ping", "poll create", "poll end", "profile", "purge", "remind", "rep", "report",
    "report-status", "reps", "sell", "serverinfo", "shop", "suggest", "suggestion-status", "testall", "ticket",
    "ticket-claim", "ticket-close", "ticket-config", "ticket-reopen", "timeout", "transactions", "unban", "unmute", "unwarn", "untimeout", "uptime", "userinfo",
    "warn", "t-warn", "warns", "weekly", "withdraw", "work", "coinflip", "dice", "rps", "eightball", "msg",
}


PROTECTED_COMMANDS = {
    "msg",
    "warn", "t-warn", "warns", "unwarn", "clearwarns", "timeout", "untimeout", "unmute", "kick", "ban", "unban", "purge",
    "ticket-close", "ticket-reopen", "ticket-claim", "ticket-config", "suggestion-status", "report-status",
    "community-config", "giveaway create", "giveaway end", "giveaway reroll", "giveaway cancel",
    "poll create", "poll end",
    "automod enable", "automod disable", "automod setup", "automod rule-add", "automod rule-update",
    "automod rule-delete", "automod list-action", "automod list-add", "automod list-remove",
    "automod rules", "automod lists", "automod status",
    "antiraid setup", "antiraid enable", "antiraid disable", "antiraid configure", "antiraid status", "antiraid unlock",
    "admin credit", "admin debit", "admin shop-add", "admin job-add", "admin job-remove", "admin purge-log", "admin rewards", "admin timezone",
}

EXPECTED_TOKENS: dict[str, tuple[str, ...]] = {
    "msg": ("send_messages_in_threads", "users=membros_mencionados", "everyone=False", "roles=False", "len(mensagem) > 2000", "Mensagem enviada para"),
    "balance": ("economy_service.balance",),
    "bank": ("economy_service.balance",),
    "deposit": ("economy_service.deposit",),
    "withdraw": ("economy_service.withdraw",),
    "pay": ("self.complete_pay", "Você não pode transferir moedas para si mesmo"),
    "daily": ("claim_reward", '"daily"'),
    "weekly": ("claim_reward", '"weekly"'),
    "shop": ("get_shop_items",),
    "buy": ("buy_item",),
    "sell": ("sell_item",),
    "inventory": ("InventoryItem", "ShopItem"),
    "jobs": ("select(Job)",),
    "job": ("JobSelectView",),
    "work": ("economy_service.credit", "check_and_set"),
    "profile": ("Experience", "Reputation", "EconomyAccount", "Member", "voice_joined_at", "achievement"),
    "rep": ("give_reputation", "Você não pode conceder reputação a si mesmo"),
    "reps": ("Reputation",),
    "leaderboard": ("kind.value", "Experience", "EconomyAccount", "Reputation", "Member", "page", "Sua posição"),
    "warn": ("_create_warning",),
    "t-warn": ("parse_twarn_duration", "expires_at = utc_now() + timedelta", "duration: str"),
    "warns": ("list_warnings",),
    "unwarn": ("deactivate_warning",),
    "clearwarns": ("list_warnings", "row.active = False"),
    "timeout": ("target_error", "parse_timeout_duration", "timeout("),
    "untimeout": ("self._remove_timeout",),
    "unmute": ("self._remove_timeout",),
    "kick": ("target_error", "kick("),
    "ban": ("target_error", "ban("),
    "unban": ("unban", "parse_snowflake"),
    "purge": ("_delete_purge_candidates", "_record_purge_action", "_send_purge_log"),
    "ticket": ("create_ticket", "ensure_ticket_channel", "TicketView"),
    "ticket-close": ("self.ticket_close",),
    "ticket-reopen": ("set_ticket_status", "ensure_ticket_channel"),
    "ticket-claim": ("self.ticket_claim",),
    "ticket-config": ("staff_role_ids", "transcript_channel_id"),
    "suggest": ("Suggestion(", "SuggestionView"),
    "suggestion-status": ("update_suggestion", "is_staff"),
    "report": ("Report(", "report_channel_id"),
    "report-status": ("update_report", "is_staff"),
    "giveaway create": ("Giveaway(", "GiveawayView"),
    "giveaway end": ("finish_giveaway",),
    "giveaway reroll": ("winner_ids", "SystemRandom"),
    "giveaway cancel": ("status = \"cancelled\"",),
    "poll create": ("validate_poll_options", "PollView", "option1", "option2"),
    "poll end": ("finish_poll",),
    "community-config": ("suggestion_channel_id", "report_channel_id"),
    "automod enable": ("automod_enabled",),
    "automod disable": ("automod_enabled",),
    "automod setup": ("AutoModRule",),
    "automod rule-add": ("validate_rule_config", "AutoModRule"),
    "automod rule-update": ("validate_rule_config", "AutoModRule"),
    "automod rule-delete": ("AutoModRule", "delete"),
    "automod rules": ("AutoModRule",),
    "automod list-action": ("blacklist_action",),
    "automod list-add": ("AutoModListEntry",),
    "automod lists": ("AutoModListEntry",),
    "automod list-remove": ("AutoModListEntry", "session.delete"),
    "automod status": ("automod_enabled", "AutoModRule"),
    "antiraid setup": ("load_protection", "protection.enabled = False"),
    "antiraid enable": ("enabled = True",),
    "antiraid disable": ("enabled = False",),
    "antiraid configure": ("join_threshold", "risk_threshold", "lockdown_seconds"),
    "antiraid status": ("RaidEvent",),
    "antiraid unlock": ("remove_lockdown",),
    "admin credit": ("economy_service.credit",),
    "admin debit": ("economy_service.debit",),
    "admin shop-add": ("ShopItem(",),
    "admin job-add": ("Job(",),
    "admin job-remove": ("JobRemoveConfirmView",),
    "admin timezone": ("ZoneInfo",),
    "admin purge-log": ("purge_log_channel_id", "attach_files", "permissions_for", "ensure_guild"),
    "admin rewards": ('config["rewards"]', "daily_amount", "weekly_amount", "streak_bonus_percent"),
    "transactions": ("EconomyTransaction", "created_at", "kind"),
    "ping": ("self.bot.latency",),
    "uptime": ("time.monotonic",),
    "botinfo": ("discord.__version__", "self.bot.guilds"),
    "serverinfo": ("guild.text_channels", "guild.voice_channels"),
    "userinfo": ("target.display_avatar", "target.created_at"),
    "avatar": ("target.display_avatar",),
    "remind": ("Reminder(", "timedelta"),
    "tutorial": ("TutorialView", "BN / TUTORIAL"),
    "history": ("CommandUsage", "desc(CommandUsage.used_at)", "await defer(interaction, ephemeral=True)"),
    "testall": ("run_diagnostics",),
    "dashboard": ("get_settings().dashboard_url", "discord.ButtonStyle.link"),
}


def _decorators(node: ast.AsyncFunctionDef) -> list[str]:
    return [ast.unparse(value) for value in node.decorator_list]


def _is_command(node: ast.AsyncFunctionDef) -> bool:
    values = _decorators(node)
    return any(value.endswith(".command") or ".command(" in value or value.startswith("app_commands.command") for value in values)


def _group_names(module: ast.Module) -> dict[str, str]:
    result: dict[str, str] = {}
    for assignment in ast.walk(module):
        if not isinstance(assignment, ast.Assign) or not isinstance(assignment.value, ast.Call):
            continue
        if not ast.unparse(assignment.value).startswith("app_commands.Group"):
            continue
        group_name = next((keyword.value.value for keyword in assignment.value.keywords if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)), None)
        if group_name is None:
            continue
        for target in assignment.targets:
            if isinstance(target, ast.Name):
                result[target.id] = str(group_name)
    return result


def _command_name(node: ast.AsyncFunctionDef) -> str:
    for decorator in _decorators(node):
        if ".command" not in decorator:
            continue
        try:
            expression = ast.parse(decorator, mode="eval").body
            for keyword in getattr(expression, "keywords", []):
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
        except SyntaxError:
            continue
    return node.name.replace("_command", "").replace("_", "-")


def _group_for(node: ast.AsyncFunctionDef, groups: dict[str, str]) -> str | None:
    for decorator in _decorators(node):
        prefix = decorator.split(".", 1)[0]
        if decorator.startswith(prefix + ".command") and prefix in groups:
            return groups[prefix]
    return None


def _call_name(call: ast.Call) -> str:
    return ast.unparse(call.func)


def _is_io(call: ast.Call) -> bool:
    name = _call_name(call)
    if name == "session_factory" or name.startswith("redis_client.") or name.endswith("check_and_set"):
        return True
    if name.startswith("session.") and name.rsplit(".", 1)[-1] in {"execute", "get", "scalar", "flush", "commit", "rollback", "delete"}:
        return True
    return name.rsplit(".", 1)[-1] in IO_FINAL_NAMES


def _response_path(calls: list[ast.Call]) -> bool:
    return any(
        name in {"respond", "interaction.response.send_message", "interaction.followup.send", "interaction.response.edit_message", "interaction.edit_original_response"}
        or name.endswith(".followup.send")
        for name in (_call_name(call) for call in calls)
    )


def _semantic_issues(qualified_name: str, source: str) -> list[str]:
    expected = EXPECTED_TOKENS.get(qualified_name)
    if expected:
        return [token for token in expected if token not in source]
    return []


def audit_commands() -> list[CommandAuditCase]:
    cases: list[CommandAuditCase] = []
    for path in sorted(COGS.glob("*.py")):
        if path.name in LEGACY_COMMAND_FILES:
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        groups = _group_names(module)
        source = path.read_text(encoding="utf-8")
        for cls in [node for node in module.body if isinstance(node, ast.ClassDef)]:
            for node in [item for item in cls.body if isinstance(item, ast.AsyncFunctionDef) and _is_command(item)]:
                name = _command_name(node)
                group = _group_for(node, groups)
                qualified = f"{group} {name}" if group else name
                decorators = _decorators(node)
                calls = sorted((value for value in ast.walk(node) if isinstance(value, ast.Call)), key=lambda item: item.lineno)
                defer_lines = [call.lineno for call in calls if _call_name(call).endswith(".defer") or _call_name(call) == "defer"]
                io_lines = [call.lineno for call in calls if _is_io(call)]
                first_defer = min(defer_lines) if defer_lines else None
                first_io = min(io_lines) if io_lines else None
                defer_before_io = first_io is None or (first_defer is not None and first_defer < first_io)
                guild_only = any("guild_only" in value for value in decorators)
                function_lines = source.splitlines()[node.lineno - 1: node.end_lineno or node.lineno]
                function_source = "\n".join(function_lines)
                helper_calls = {
                    call.func.attr
                    for call in calls
                    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == "self"
                }
                helper_guard = any(
                    helper_name in function_source and ("is_staff(" in "\n".join(
                        "\n".join(source.splitlines()[helper.lineno - 1: helper.end_lineno or helper.lineno])
                        for helper in cls.body
                        if isinstance(helper, ast.AsyncFunctionDef) and helper.name == helper_name
                    ))
                    for helper_name in helper_calls
                )
                permission_guard = any("has_permissions" in value for value in decorators) or "is_staff(" in function_source or helper_guard
                response_path = _response_path(calls)
                if not response_path:
                    helper_response_names = {
                        call.func.attr
                        for call in calls
                        if isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "self"
                    }
                    for helper_name in helper_response_names:
                        helper = next((item for item in cls.body if isinstance(item, ast.AsyncFunctionDef) and item.name == helper_name), None)
                        if helper is not None:
                            helper_calls = [value for value in ast.walk(helper) if isinstance(value, ast.Call)]
                            if _response_path(helper_calls):
                                response_path = True
                                break
                semantic = _semantic_issues(qualified, function_source)
                if qualified in EXPECTED_TOKENS and "" in semantic:
                    semantic.remove("")
                cases.append(CommandAuditCase(qualified, path.name, node.name, max(len(node.args.args) - 2, 0), guild_only, permission_guard, response_path, defer_before_io, not semantic, ", ".join(semantic)))
    return sorted(cases, key=lambda case: case.qualified_name)


def case_issues(case: CommandAuditCase) -> list[str]:
    issues: list[str] = []
    if not case.response_path:
        issues.append("sem resposta")
    if not case.defer_before_io:
        issues.append("I/O antes de defer")
    if not case.guild_only and case.qualified_name not in {"ping", "uptime", "botinfo", "avatar", "tutorial", "dashboard"}:
        issues.append("sem guild_only")
    if not case.semantic_ok:
        issues.append(f"contrato incompleto: {case.issue}")
    if case.qualified_name in PROTECTED_COMMANDS and not case.permission_guard:
        issues.append("sem proteção de permissão detectável")
    if not case.qualified_name in EXPECTED_COMMANDS:
        issues.append("comando inesperado")
    return issues


def audit_summary(expected_count: int | None = None) -> tuple[bool, list[CommandAuditCase], list[str]]:
    cases = audit_commands()
    issues: list[str] = []
    actual = {case.qualified_name for case in cases}
    expected_count = len(EXPECTED_COMMANDS) if expected_count is None else expected_count
    if len(cases) != expected_count:
        issues.append(f"quantidade de comandos: {len(cases)} != {expected_count}")
    missing = sorted(EXPECTED_COMMANDS - actual)
    extra = sorted(actual - EXPECTED_COMMANDS)
    if missing:
        issues.append(f"comandos ausentes: {', '.join(missing[:12])}")
    if extra:
        issues.append(f"comandos inesperados: {', '.join(extra[:12])}")
    for case in cases:
        for issue in case_issues(case):
            issues.append(f"/{case.qualified_name}: {issue}")
    return not issues, cases, issues
