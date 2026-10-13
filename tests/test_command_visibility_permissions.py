"""Regressions for Discord-native command visibility and backend permission checks."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "app" / "discord" / "cogs"


def _call_name(node: ast.expr) -> str:
    try:
        return ast.unparse(node.func) if isinstance(node, ast.Call) else ast.unparse(node)
    except Exception:
        return ""


def _decorator_calls(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    return [node for node in function.decorator_list if isinstance(node, ast.Call)]


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {item.arg: item.value for item in call.keywords if item.arg}


def _function_nodes(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _group_defaults(tree: ast.AST) -> dict[str, dict[str, ast.expr]]:
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Call) or _call_name(value) != "app_commands.Group":
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                result[target.id] = _keywords(value)
    return result


def test_direct_permission_checked_commands_also_declare_discord_visibility() -> None:
    failures = []
    for path in COGS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in _function_nodes(tree):
            calls = _decorator_calls(function)
            names = [_call_name(call) for call in calls]
            check_calls = [call for call, name in zip(calls, names) if name == "app_commands.checks.has_permissions"]
            direct = any(name == "app_commands.command" for name in names)
            if not (check_calls and direct):
                continue
            defaults = [call for call, name in zip(calls, names) if name == "app_commands.default_permissions"]
            if not defaults:
                failures.append(f"{path.name}:{function.name}: missing default_permissions")
                continue
            required = set()
            for check in check_calls:
                required.update(key for key, value in _keywords(check).items() if isinstance(value, ast.Constant) and value.value is True)
            supplied = set()
            for default in defaults:
                supplied.update(key for key, value in _keywords(default).items() if isinstance(value, ast.Constant) and value.value is True)
            if not required.issubset(supplied):
                failures.append(f"{path.name}:{function.name}: checks={sorted(required)} defaults={sorted(supplied)}")
    assert not failures, "\n".join(failures)


def test_grouped_permission_checked_commands_are_hidden_at_group_level() -> None:
    protected_groups: set[str] = set()
    failures = []
    for path in COGS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        groups = _group_defaults(tree)
        for function in _function_nodes(tree):
            calls = _decorator_calls(function)
            names = [_call_name(call) for call in calls]
            group_calls = [call for call, name in zip(calls, names) if name.endswith(".command") and name != "app_commands.command"]
            checks = [call for call, name in zip(calls, names) if name == "app_commands.checks.has_permissions"]
            if not (group_calls and checks):
                continue
            group_name = _call_name(group_calls[0]).removesuffix(".command")
            required = {key for check in checks for key, value in _keywords(check).items() if isinstance(value, ast.Constant) and value.value is True}
            supplied_call = groups.get(group_name, {})
            permission_expr = supplied_call.get("default_permissions")
            permission_text = ast.unparse(permission_expr) if permission_expr is not None else ""
            supplied = {key for key in ("manage_guild", "manage_messages", "moderate_members", "kick_members", "ban_members", "administrator") if f"{key}=True" in permission_text}
            if not required.issubset(supplied):
                failures.append(f"{path.name}:{group_name}.{function.name}: checks={sorted(required)} group_default={permission_text}")
            protected_groups.add(group_name)
    assert {"admin_group", "raid_group", "automod_group", "giveaway_group", "poll_group"}.issubset(protected_groups)
    assert not failures, "\n".join(failures)


def test_staff_only_commands_with_custom_role_checks_have_safe_discord_defaults() -> None:
    path = COGS / "community.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    expected = {"ticket_reopen_command", "ticket_claim_command", "suggestion_status", "report_status"}
    found = set()
    for function in _function_nodes(tree):
        if function.name not in expected:
            continue
        names = [_call_name(call) for call in _decorator_calls(function)]
        assert "app_commands.default_permissions" in names, f"{function.name} is not hidden by default"
        assert "app_commands.guild_only" in names, f"{function.name} must remain server-only"
        found.add(function.name)
    assert found == expected
