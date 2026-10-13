from __future__ import annotations
import math
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import desc, func, select
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.models import Achievement, Experience, Reputation, Member, EconomyAccount, Job, UserAchievement, UserJob
from app.services.analytics import member_activity_report
from app.services.reputation import give_reputation
from app.core.exceptions import CooldownActive
from app.discord.theme import embed, money, number, bar, ledger, duration


class ProgressionCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="profile", description="Mostra o perfil persistido do usuário.")
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        target = user or interaction.user
        async with session_factory() as session:
            xp = await session.scalar(select(Experience).where(Experience.guild_id == guild.id, Experience.user_id == target.id))
            rep = await session.scalar(select(Reputation).where(Reputation.guild_id == guild.id, Reputation.user_id == target.id))
            account = await session.scalar(select(EconomyAccount).where(EconomyAccount.guild_id == guild.id, EconomyAccount.user_id == target.id))
            member = await session.scalar(select(Member).where(Member.guild_id == guild.id, Member.user_id == target.id))
            job = await session.scalar(select(Job.name).join(UserJob, UserJob.job_id == Job.id).where(UserJob.guild_id == guild.id, UserJob.user_id == target.id, Job.guild_id == guild.id))
            achievements = int(await session.scalar(select(func.count(UserAchievement.id)).join(Achievement, UserAchievement.achievement_id == Achievement.id).where(Achievement.guild_id == guild.id, UserAchievement.user_id == target.id)) or 0)
        level = xp.level if xp else 0
        total_xp = xp.total_xp if xp else 0
        span = max(100 * (level + 1) ** 2, 1)
        previous_threshold = sum(100 * (step + 1) ** 2 for step in range(level))
        progress = min(max(total_xp - previous_threshold, 0), span)
        persisted_voice = member.voice_seconds if member else 0
        active_voice = target.voice is not None and target.voice.channel is not None and member is not None and member.voice_joined_at is not None
        if active_voice and member and member.voice_joined_at:
            persisted_voice += max(int((discord.utils.utcnow() - member.voice_joined_at).total_seconds()), 0)
        page = embed("BN / PERFIL", f"**{target.display_name}**\n{target.mention}\nNível `{level}` · XP `{number(total_xp)}`", "progression")
        page.set_thumbnail(url=target.display_avatar.url)
        page.add_field(name="Nível", value=f"`{level}`", inline=True)
        page.add_field(name="Reputação", value=f"`{number(rep.score if rep else 0)}`", inline=True)
        page.add_field(name="Conquistas", value=f"`{achievements}`", inline=True)
        page.add_field(name="Financeiro", value=ledger([
            ("Carteira", money(account.wallet) if account else money(0)),
            ("Banco", money(account.bank) if account else money(0)),
            ("Total", money(account.wallet + account.bank) if account else money(0)),
        ]), inline=False)
        page.add_field(name="Atividade", value=ledger([
            ("Mensagens", number(member.message_count if member else 0)),
            ("Voz", duration(persisted_voice)),
            ("Mensagens em 7 dias", number(recent_activity["messages"])),
            ("Voz em 7 dias", duration(recent_activity["voice_seconds"])),
            ("Dias ativos em 7 dias", number(recent_activity["active_days"])),
            ("Status de voz", "Em voz agora" if active_voice else "Fora de voz"),
        ]), inline=False)
        page.add_field(name="Emprego", value=job or "Nenhum emprego equipado", inline=True)
        page.add_field(name="Progresso do nível", value=f"{bar(progress, span)}\n`{number(progress)}/{number(span)}` XP", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="rep", description="Concede um ponto de reputação.")
    @app_commands.guild_only()
    async def rep(self, interaction: discord.Interaction, user: discord.Member, reason: str | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        if user.id == interaction.user.id:
            await respond(interaction, "Você não pode conceder reputação a si mesmo.", ephemeral=True)
            return
        if user.bot:
            await respond(interaction, "Bots não recebem reputação.", ephemeral=True)
            return
        await defer(interaction)
        try:
            async with session_factory() as session:
                await give_reputation(session, guild.id, interaction.user.id, user.id, reason[:500] if reason else None)
        except CooldownActive as exc:
            await respond(interaction, f"Você já concedeu reputação nesta janela. Aguarde {exc.seconds // 3600}h.", ephemeral=True)
            return
        page = embed("BN / REPUTAÇÃO", f"{user.mention} recebeu **+1** ponto.", "progression")
        page.add_field(name="Motivo", value=reason[:1024] if reason else "Não informado", inline=False)
        await respond(interaction, embed=page)

    @app_commands.command(name="reps", description="Mostra a reputação de um usuário.")
    @app_commands.guild_only()
    async def reps(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        target = user or interaction.user
        async with session_factory() as session:
            row = (await session.execute(select(Reputation).where(Reputation.guild_id == guild.id, Reputation.user_id == target.id))).scalar_one_or_none()
        score = row.score if row else 0
        page = embed("BN / REPUTAÇÃO", f"**{target.display_name}** · reputação registrada.", "progression")
        page.set_thumbnail(url=target.display_avatar.url)
        page.add_field(name="Pontuação", value=f"`{number(score)}`", inline=False)
        page.add_field(name="Leitura", value="Positiva" if score > 0 else "Neutra" if score == 0 else "Negativa", inline=True)
        await respond(interaction, embed=page)

    @app_commands.command(name="leaderboard", description="Mostra um ranking do servidor.")
    @app_commands.guild_only()
    @app_commands.choices(kind=[
        app_commands.Choice(name="XP", value="xp"),
        app_commands.Choice(name="Moedas", value="coins"),
        app_commands.Choice(name="Reputação", value="reputation"),
        app_commands.Choice(name="Mensagens", value="messages"),
        app_commands.Choice(name="Tempo em voz", value="voice"),
        app_commands.Choice(name="Atividade", value="activity"),
    ])
    @app_commands.describe(kind="Critério do ranking", page="Página do ranking, com 10 posições por página")
    async def leaderboard(self, interaction: discord.Interaction, kind: app_commands.Choice[str], page: app_commands.Range[int, 1, 100] = 1) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction)
        if kind.value == "xp":
            user_id_col = Experience.user_id
            guild_col = Experience.guild_id
            value_col = Experience.total_xp
            base_query = select(user_id_col.label("user_id"), value_col.label("value")).where(guild_col == guild.id)
            label = "XP"
        elif kind.value == "coins":
            user_id_col = EconomyAccount.user_id
            guild_col = EconomyAccount.guild_id
            value_col = EconomyAccount.wallet + EconomyAccount.bank
            base_query = select(user_id_col.label("user_id"), value_col.label("value")).where(guild_col == guild.id)
            label = "Moedas"
        elif kind.value == "reputation":
            user_id_col = Reputation.user_id
            guild_col = Reputation.guild_id
            value_col = Reputation.score
            base_query = select(user_id_col.label("user_id"), value_col.label("value")).where(guild_col == guild.id)
            label = "Reputação"
        elif kind.value == "messages":
            user_id_col = Member.user_id
            guild_col = Member.guild_id
            value_col = Member.message_count
            base_query = select(user_id_col.label("user_id"), value_col.label("value")).where(guild_col == guild.id)
            label = "Mensagens"
        elif kind.value == "voice":
            user_id_col = Member.user_id
            guild_col = Member.guild_id
            value_col = Member.voice_seconds
            base_query = select(user_id_col.label("user_id"), value_col.label("value")).where(guild_col == guild.id)
            label = "Tempo em voz"
        else:
            user_id_col = Member.user_id
            guild_col = Member.guild_id
            value_col = Member.activity_score
            base_query = select(user_id_col.label("user_id"), value_col.label("value")).where(guild_col == guild.id)
            label = "Atividade"
        subquery = base_query.subquery()
        async with session_factory() as session:
            total = int(await session.scalar(select(func.count()).select_from(subquery)) or 0)
            page_count = max(math.ceil(total / 10), 1)
            current_page = min(page, page_count)
            rows = (await session.execute(select(subquery.c.user_id, subquery.c.value).order_by(desc(subquery.c.value), subquery.c.user_id.asc()).offset((current_page - 1) * 10).limit(10))).all()
            current_value = await session.scalar(select(value_col).where(user_id_col == interaction.user.id, guild_col == guild.id))
            personal_rank = None
            if current_value is not None:
                greater = int(await session.scalar(select(func.count()).select_from(subquery).where(subquery.c.value > current_value)) or 0)
                personal_rank = greater + 1
        page_embed = embed("BN / RANKING", f"Top do servidor por **{label}** · página `{current_page}/{page_count}`.", "progression")
        if not rows:
            page_embed.add_field(name="Sem dados", value="Ainda não existem registros suficientes.", inline=False)
        else:
            lines = []
            max_value = max(abs(int(rows[0][1] or 0)), 1)
            for offset, (user_id, value) in enumerate(rows, start=(current_page - 1) * 10 + 1):
                member = guild.get_member(user_id)
                name = member.display_name if member else f"Usuário {user_id}"
                numeric_value = int(value or 0)
                rendered = duration(numeric_value) if kind.value == "voice" else number(numeric_value)
                lines.append(f"`{offset:02d}.` **{name[:24]}**\n{bar(abs(numeric_value), max_value, 10)} `{rendered}`")
            page_embed.add_field(name="Classificação", value="\n".join(lines)[:1024], inline=False)
        if personal_rank is not None:
            rendered_personal = duration(int(current_value)) if kind.value == "voice" else number(int(current_value))
            page_embed.add_field(name="Sua posição", value=f"`#{personal_rank}` · {rendered_personal}", inline=False)
        else:
            page_embed.add_field(name="Sua posição", value="Sem registro neste ranking ainda.", inline=False)
        await respond(interaction, embed=page_embed)
