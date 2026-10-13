from __future__ import annotations
import discord


async def defer(interaction: discord.Interaction, ephemeral: bool = False) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=ephemeral, thinking=True)


async def respond(interaction: discord.Interaction, content: str | None = None, **kwargs):
    if interaction.response.is_done():
        return await interaction.followup.send(content, **kwargs)
    return await interaction.response.send_message(content, **kwargs)
