from __future__ import annotations

from discord import app_commands


USER_APP_INSTALLS = app_commands.AppInstallationType(guild=True, user=True)
USER_APP_CONTEXTS = app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True)
GUILD_ONLY_INSTALLS = app_commands.AppInstallationType(guild=True, user=False)
GUILD_ONLY_CONTEXTS = app_commands.AppCommandContext(guild=True, dm_channel=False, private_channel=False)


def user_installable(command):
    command.allowed_installs = USER_APP_INSTALLS
    command.allowed_contexts = USER_APP_CONTEXTS
    return command


def guild_install_only(command):
    command.allowed_installs = GUILD_ONLY_INSTALLS
    command.allowed_contexts = GUILD_ONLY_CONTEXTS
    return command
