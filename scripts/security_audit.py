from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COGS = ROOT / "app" / "discord" / "cogs"
PROTECTED = {
    "msg",
    "warn", "t-warn", "warns", "unwarn", "clearwarns", "timeout", "kick", "ban", "unban", "purge",
    "ticket-close", "ticket-reopen", "ticket-claim", "ticket-config", "suggestion-status", "report-status",
    "community-config", "history", "testall", "giveaway create", "giveaway end", "giveaway reroll", "giveaway cancel",
    "poll create", "poll end",
    "automod enable", "automod disable", "automod setup", "automod rule-add", "automod rule-update",
    "automod rule-delete", "automod rules", "automod list-action", "automod list-add", "automod lists", "automod list-remove", "automod status",
    "antiraid setup", "antiraid enable", "antiraid disable", "antiraid configure", "antiraid status", "antiraid unlock",
    "admin credit", "admin debit", "admin shop-add", "admin job-add", "admin job-remove", "admin rewards", "admin timezone", "admin purge-log",
}
RATE_LIMITED = {
    "deposit", "withdraw", "pay", "buy", "sell", "job", "suggest", "report", "coinflip", "dice", "rps",
    "msg", "eightball", "remind", "history", "testall", "dashboard",
}


def decorators(node: ast.AsyncFunctionDef) -> list[str]:
    return [ast.unparse(value) for value in node.decorator_list]


def command_name(node: ast.AsyncFunctionDef) -> str | None:
    for value in decorators(node):
        if "command" not in value:
            continue
        tree = ast.parse(value, mode="eval").body
        for keyword in getattr(tree, "keywords", []):
            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value)
    return None


def group_names(module: ast.Module) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        if not ast.unparse(node.value).startswith("app_commands.Group"):
            continue
        group_name = next((keyword.value.value for keyword in node.value.keywords if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)), None)
        if group_name is None:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                result[target.id] = str(group_name)
    return result


def command_group(node: ast.AsyncFunctionDef, groups: dict[str, str]) -> str | None:
    for value in decorators(node):
        prefix = value.split(".", 1)[0]
        if ".command" in value and prefix in groups:
            return groups[prefix]
    return None


def main() -> int:
    issues: list[str] = []
    protected_seen: set[str] = set()
    rate_seen: set[str] = set()
    for path in sorted(COGS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        groups = group_names(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            name = command_name(node)
            if name is None:
                continue
            qualified = f"{command_group(node, groups)} {name}" if command_group(node, groups) else name
            decs = decorators(node)
            file_source = path.read_text(encoding="utf-8")
            source = ast.get_source_segment(file_source, node) or ""
            if qualified in PROTECTED:
                protected_seen.add(qualified)
                guarded = any("has_permissions" in value for value in decs) or "is_staff(" in source
                if not guarded:
                    helper_names = {
                        call.func.attr
                        for call in ast.walk(node)
                        if isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "self"
                    }
                    for helper in helper_names:
                        helper_node = next((item for item in ast.walk(tree) if isinstance(item, ast.AsyncFunctionDef) and item.name == helper), None)
                        if helper_node is not None:
                            helper_source = ast.get_source_segment(file_source, helper_node) or ""
                            if "is_staff(" in helper_source or "has_permissions" in "\n".join(ast.unparse(value) for value in helper_node.decorator_list):
                                guarded = True
                                break
                if not guarded:
                    issues.append(f"protected command without guard: {qualified}")
            if name in RATE_LIMITED or qualified == "history" or qualified == "testall":
                rate_seen.add(name)
                if "command_rate_limit(" not in "\n".join(decs) and name not in {"history", "testall"}:
                    issues.append(f"rate-limited command missing decorator: {qualified}")
    missing = sorted(PROTECTED - protected_seen)
    if missing:
        issues.append("missing protected commands from source: " + ", ".join(missing))
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".html", ".css", ".js", ".ts", ".sql", ".toml", ".yml", ".yaml"}:
            continue
        if any(part in {".venv", "venv", "site-packages", ".git", "__pycache__"} for part in path.parts):
            continue
        if path.name == ".env" or path.name.startswith(".env.") or path.name == "security_audit.py":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "discord.token =" in text.lower() or "discord_token = \"" in text.lower():
            issues.append(f"possible hard-coded Discord token assignment: {path.relative_to(ROOT)}")
    if issues:
        print("BN Bot security audit failed")
        for issue in issues:
            print(issue)
        return 1
    print(f"BN Bot security audit passed · {len(PROTECTED)} protected command policies checked · {len(rate_seen)} rate-limited command surfaces checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
