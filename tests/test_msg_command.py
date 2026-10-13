from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]


def test_msg_command_is_registered_as_a_guild_channel_command() -> None:
    source = (ROOT / "app/discord/cogs/utility.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    commands = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "msg"
    ]
    assert len(commands) == 1
    node = commands[0]
    decorators = [ast.unparse(item) for item in node.decorator_list]
    assert any("app_commands.command" in item for item in decorators)
    assert 'name="msg"' in source
    assert any("app_commands.guild_only()" in item for item in decorators)
    assert any(
        "app_commands.checks.has_permissions(manage_guild=True)" in item
        for item in decorators
    )
    assert any("app_commands.default_permissions(manage_guild=True)" in item for item in decorators)
    assert any(
        "command_rate_limit" in item and "msg" in item and "15" in item
        for item in decorators
    )
    assert [arg.arg for arg in node.args.args][-3:] == ["canal", "mensagem", "responder_a"]
    assert "responder_a: str | None = None" in source


def test_msg_validates_content_and_destination_permissions() -> None:
    source = (ROOT / "app/discord/cogs/utility.py").read_text(encoding="utf-8")
    start = source.index('@command_rate_limit("msg", 15)')
    end = source.index('    @command_rate_limit("history", 5)', start)
    block = source[start:end]
    required = (
        "if not mensagem.strip()",
        "len(mensagem) > 2000",
        "canal.guild.id != guild.id",
        "canal.archived or canal.locked",
        "sender_permissions.view_channel",
        "channel_permissions.view_channel",
        "channel_permissions.send_messages_in_threads",
        "channel_permissions.send_messages",
        "discord.AllowedMentions(",
        "users=membros_mencionados",
        "everyone=False",
        "roles=False",
        "resolve_msg_mentions(",
        "responder_a: str | None = None",
        "canal.fetch_message(message_id)",
        "to_reference(fail_if_not_exists=True)",
        "except discord.Forbidden",
        "except discord.NotFound",
        "except discord.HTTPException",
        "Mensagem enviada para",
    )
    for item in required:
        assert item in block


def test_message_command_is_part_of_permission_and_audit_contracts() -> None:
    permissions = (ROOT / "app/services/permissions.py").read_text(encoding="utf-8")
    audit = (ROOT / "app/services/command_matrix.py").read_text(encoding="utf-8")
    security = (ROOT / "scripts/security_audit.py").read_text(encoding="utf-8")
    assert '"msg": "manage_guild"' in permissions
    assert '"msg": ("send_messages_in_threads"' in audit
    assert '"msg",' in security


def test_msg_resolves_plain_names_without_enabling_broadcast_mentions() -> None:
    import ast
    import re

    utility_source = (ROOT / "app/discord/cogs/utility.py").read_text(encoding="utf-8")
    tree = ast.parse(utility_source)
    pattern_node = next(
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "MSG_NAME_MENTION_PATTERN"
            for target in node.targets
        )
    )
    pattern = re.compile(ast.literal_eval(pattern_node.args[0]))
    assert [match.group(1) for match in pattern.finditer("Olá @rian, veja isso.")] == ["rian"]
    assert pattern.search("contato@rian.com") is None
    assert pattern.search("<@123456789>") is None
    assert 'MSG_NON_PING_TOKENS = {"everyone", "here"}' in utility_source
    assert "allowed_members: dict[int, discord.Member]" in utility_source
    assert "users=membros_mencionados" in utility_source
    assert "roles=False" in utility_source
    assert "everyone=False" in utility_source
    assert "nome ambíguo" in utility_source
