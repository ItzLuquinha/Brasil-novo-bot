from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _signature_helpers() -> dict[str, Any]:
    source = ast.parse((ROOT / "app/services/diagnostics.py").read_text(encoding="utf-8"))
    names = {
        "_enum_int",
        "_command_option_signature",
        "_remote_option_signature",
        "_permission_signature",
        "_local_top_level_permission_signatures",
        "_remote_top_level_permission_signatures",
    }
    functions = [
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "signature_helpers.py", "exec"), namespace)
    return namespace


def test_channel_type_order_does_not_mark_guild_command_stale() -> None:
    helpers = _signature_helpers()
    local_options = [{
        "name": "canal",
        "type": 7,
        "required": True,
        "description": "Canal de destino",
        "channel_types": [0, 5, 10, 11, 12],
    }]
    discord_response_options = [{
        "name": "canal",
        "type": 7,
        "required": True,
        "description": "Canal de destino",
        "channel_types": [0, 5, 12, 10, 11],
    }]
    assert helpers["_command_option_signature"](local_options) == helpers["_remote_option_signature"](discord_response_options)


def test_guild_command_schema_mismatch_is_retried_boundedly() -> None:
    source = (ROOT / "app/discord/bot.py").read_text(encoding="utf-8")
    assert '"command synchronization mismatch" in str(error).lower()' in source
    assert "return 5.0" in source
    assert "retryable_error = next(" in source
    assert "for attempt in range(5)" in source

def test_command_sync_detects_default_permission_changes_for_visibility() -> None:
    helpers = _signature_helpers()

    class LocalCommand:
        name = "msg"

        def __init__(self, permissions):
            self.permissions = permissions

        def to_dict(self, _tree):
            return {"name": self.name, "default_member_permissions": self.permissions}

    class RemoteCommand:
        def __init__(self, permissions):
            self.permissions = permissions

        def to_dict(self):
            return {"name": "msg", "default_member_permissions": self.permissions}

    local = helpers["_local_top_level_permission_signatures"]([LocalCommand("32")], object())
    matching_remote = helpers["_remote_top_level_permission_signatures"]([RemoteCommand("32")])
    stale_remote = helpers["_remote_top_level_permission_signatures"]([RemoteCommand(None)])

    assert local == matching_remote
    assert local != stale_remote


def test_command_sync_tracks_group_permission_visibility() -> None:
    helpers = _signature_helpers()

    class LocalGroup:
        name = "automod"

        def to_dict(self, _tree):
            return {"name": self.name, "default_member_permissions": "32"}

    class RemoteGroup:
        def to_dict(self):
            return {"name": "automod", "default_member_permissions": None}

    local = helpers["_local_top_level_permission_signatures"]([LocalGroup()], object())
    remote = helpers["_remote_top_level_permission_signatures"]([RemoteGroup()])
    assert local != remote


def _permission_reconcile_function():
    source = ast.parse((ROOT / "app/discord/bot.py").read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(source)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_reconcile_remote_command_permissions"
    )
    function.decorator_list = []
    function.returns = None
    for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
        argument.annotation = None
    namespace = {"logger": __import__("logging").getLogger("test.command_sync")}
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, "permission_reconcile_test.py", "exec"), namespace)
    return namespace[function.name]


@pytest.mark.asyncio
async def test_discord_remote_default_permissions_are_patched_after_bulk_sync() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    reconcile = _permission_reconcile_function()
    desired = SimpleNamespace(value=32)
    local = SimpleNamespace(name="admin", default_permissions=desired)

    async def apply_permission(*, default_member_permissions):
        remote.default_member_permissions = default_member_permissions

    remote = SimpleNamespace(name="admin", default_member_permissions=None)
    remote.edit = AsyncMock(side_effect=apply_permission)

    repaired = await reconcile([local], [remote], scope="test-guild")

    assert repaired == 1
    remote.edit.assert_awaited_once_with(default_member_permissions=desired)
    assert remote.default_member_permissions is desired


@pytest.mark.asyncio
async def test_discord_permissions_are_not_patched_when_already_matching() -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    reconcile = _permission_reconcile_function()
    permissions = SimpleNamespace(value=32)
    local = SimpleNamespace(name="admin", default_permissions=permissions)
    remote = SimpleNamespace(name="admin", default_member_permissions=permissions)
    remote.edit = AsyncMock()

    repaired = await reconcile([local], [remote], scope="test-guild")

    assert repaired == 0
    remote.edit.assert_not_awaited()


def test_remote_permission_signature_reads_discordpy_attribute_not_to_dict() -> None:
    """discord.py AppCommand.to_dict omits default_member_permissions."""
    helpers = _signature_helpers()
    from types import SimpleNamespace

    class RemoteCommand:
        name = "admin"
        def to_dict(self):
            return {"name": self.name, "type": 1}

        default_member_permissions = SimpleNamespace(value=32)

    signatures = helpers["_remote_top_level_permission_signatures"]([RemoteCommand()])
    assert signatures == {"admin": "32"}
