from __future__ import annotations
import random
import discord
from discord import app_commands
from discord.ext import commands
from app.core.interactions import defer, respond
from app.discord.theme import embed
from app.discord.app_contexts import user_installable

from app.services.rate_limits import command_rate_limit
EIGHT_BALL_ANSWERS = (
    "Sim, sem dúvida.",
    "As chances são boas.",
    "Parece provável.",
    "A resposta ainda não está clara.",
    "Melhor perguntar outra hora.",
    "Não conte com isso.",
    "Provavelmente não.",
    "Não.",
)

RPS_CHOICES = ("pedra", "papel", "tesoura")


class RPSView(discord.ui.View):
    def __init__(self, owner_id: int) -> None:
        super().__init__(timeout=90)
        self.owner_id = owner_id
        self.message: discord.Message | None = None
        self.finished = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Essa partida pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    async def play(self, interaction: discord.Interaction, choice: str) -> None:
        if self.finished:
            await interaction.response.send_message("Essa partida já terminou.", ephemeral=True)
            return
        self.finished = True
        bot_choice = random.choice(RPS_CHOICES)
        if choice == bot_choice:
            result = "Empate."
        elif (choice, bot_choice) in {("pedra", "tesoura"), ("papel", "pedra"), ("tesoura", "papel")}:
            result = "Você venceu."
        else:
            result = "O BN Bot venceu."
        page = embed(
            "BN / PEDRA, PAPEL E TESOURA",
            f"Você: **{choice.title()}**\nBN Bot: **{bot_choice.title()}**\n\n**{result}**",
            "fun",
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=page, view=self)
        self.stop()

    @discord.ui.button(label="Pedra", style=discord.ButtonStyle.secondary, row=0)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.play(interaction, "pedra")

    @discord.ui.button(label="Papel", style=discord.ButtonStyle.primary, row=0)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.play(interaction, "papel")

    @discord.ui.button(label="Tesoura", style=discord.ButtonStyle.danger, row=0)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.play(interaction, "tesoura")

    async def on_timeout(self) -> None:
        if self.finished or self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass


class FunCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @command_rate_limit("coinflip", 2)
    @user_installable
    @app_commands.command(name="coinflip", description="Joga uma moeda e mostra o resultado.")
    @app_commands.guild_only()
    async def coinflip(self, interaction: discord.Interaction) -> None:
        await defer(interaction)
        result = random.choice(("Cara", "Coroa"))
        page = embed("BN / CARA OU COROA", f"Resultado: **{result}**", "fun")
        await respond(interaction, embed=page)

    @command_rate_limit("dice", 2)
    @user_installable
    @app_commands.command(name="dice", description="Rola um dado de seis lados.")
    @app_commands.guild_only()
    async def dice(self, interaction: discord.Interaction) -> None:
        await defer(interaction)
        result = random.randint(1, 6)
        page = embed("BN / DADO", f"Você rolou um **{result}**.", "fun")
        await respond(interaction, embed=page)

    @command_rate_limit("rps", 5)
    @user_installable
    @app_commands.command(name="rps", description="Joga pedra, papel e tesoura usando botões.")
    @app_commands.guild_only()
    async def rps(self, interaction: discord.Interaction) -> None:
        page = embed("BN / PEDRA, PAPEL E TESOURA", "Escolha sua jogada nos botões abaixo. A partida é exclusiva para você.", "fun")
        view = RPSView(interaction.user.id)
        await interaction.response.send_message(embed=page, view=view)
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass

    @command_rate_limit("eightball", 3)
    @user_installable
    @app_commands.command(name="eightball", description="Pergunta alguma coisa à bola 8.")
    @app_commands.guild_only()
    @app_commands.describe(question="Sua pergunta")
    async def eightball(self, interaction: discord.Interaction, question: app_commands.Range[str, 1, 500]) -> None:
        await defer(interaction)
        page = embed("BN / BOLA 8", f"Pergunta: **{question.strip()}**\n\nResposta: **{random.choice(EIGHT_BALL_ANSWERS)}**", "fun")
        await respond(interaction, embed=page)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunCog(bot))
