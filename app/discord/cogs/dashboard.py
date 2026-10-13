from __future__ import annotations

import logging
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

from app.config import get_settings
from app.discord.theme import embed
from app.services.rate_limits import command_rate_limit

logger = logging.getLogger("bn_bot.dashboard")


class DashboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @command_rate_limit("dashboard", 5)
    @app_commands.command(name="dashboard", description="Abre o dashboard web oficial do BN Bot.")
    @app_commands.guild_only()
    async def dashboard(self, interaction: discord.Interaction) -> None:
        dashboard_url = get_settings().dashboard_url.strip()
        parsed_url = urlparse(dashboard_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            await interaction.response.send_message(
                "O dashboard web não está configurado corretamente. Verifique a variável `DASHBOARD_URL`.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        page = embed(
            "BN / DASHBOARD",
            "Abra o dashboard web oficial do BN Bot pelo botão abaixo. Entre com sua conta Discord para gerenciar o servidor.",
            "system",
        )
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="Abrir dashboard web",
                style=discord.ButtonStyle.link,
                url=dashboard_url,
            )
        )
        try:
            await interaction.response.send_message(
                embed=page,
                view=view,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            logger.exception(
                "dashboard link response rejected status=%s code=%s",
                getattr(exc, "status", None),
                getattr(exc, "code", None),
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Não foi possível enviar o link do dashboard agora. Tente novamente.",
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DashboardCog(bot))
