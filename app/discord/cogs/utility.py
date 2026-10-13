from __future__ import annotations
import logging
import re
import secrets
import time
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select, desc, func
from app.core.db import session_factory
from app.core.interactions import defer, respond
from app.services.diagnostics import run_diagnostics
from app.repositories.analytics import COMMAND_CATEGORIES
from app.models import AuditLog, CommandUsage, Reminder
from app.core.time import utc_now
from app.discord.theme import embed, duration, number, ledger, status_line
from app.discord.app_contexts import user_installable
from app.services.permissions import required_permission_text

from app.services.rate_limits import command_rate_limit
logger = logging.getLogger("bn_bot.discord.utility")

MSG_NAME_MENTION_PATTERN = re.compile(r"(?<![\w.@<])@([\w-]+(?:\.[\w-]+)*)", re.UNICODE)
MSG_NATIVE_USER_MENTION_PATTERN = re.compile(r"<@!?(\d+)>")
MSG_NON_PING_TOKENS = {"everyone", "here"}
MSG_MAX_MENTION_LOOKUPS = 10


def _member_matches_mention_name(member: discord.Member, name: str) -> bool:
    wanted = name.casefold()
    candidates = {
        str(getattr(member, "name", "")).casefold(),
        str(getattr(member, "display_name", "")).casefold(),
        str(getattr(member, "global_name", "") or "").casefold(),
        str(getattr(member, "nick", "") or "").casefold(),
    }
    candidates.discard("")
    return wanted in candidates


async def resolve_msg_mentions(
    guild: discord.Guild, content: str
) -> tuple[str, list[discord.Member], list[str]]:
    """Convert exact @member names to safe Discord mentions for /msg.

    Only members of the current guild are eligible. @everyone and @here are
    deliberately never converted, and unresolved or ambiguous names stay text.
    """
    name_matches = list(MSG_NAME_MENTION_PATTERN.finditer(content))
    unique_names: list[str] = []
    seen_names: set[str] = set()
    for match in name_matches:
        name = match.group(1)
        normalized = name.casefold()
        if normalized in MSG_NON_PING_TOKENS or normalized in seen_names:
            continue
        seen_names.add(normalized)
        unique_names.append(name)

    resolved_by_name: dict[str, discord.Member] = {}
    allowed_members: dict[int, discord.Member] = {}
    issues: list[str] = []

    for index, name in enumerate(unique_names):
        normalized = name.casefold()
        if index >= MSG_MAX_MENTION_LOOKUPS:
            issues.append(
                f"@{name} (limite de {MSG_MAX_MENTION_LOOKUPS} nomes diferentes por mensagem)"
            )
            continue

        candidates_by_id: dict[int, discord.Member] = {}
        for member in guild.members:
            if _member_matches_mention_name(member, name):
                candidates_by_id[member.id] = member

        lookup_was_truncated = False
        if not candidates_by_id:
            try:
                queried_members = await guild.query_members(query=name, limit=100, cache=False)
                lookup_was_truncated = len(queried_members) >= 100
                for member in queried_members:
                    if _member_matches_mention_name(member, name):
                        candidates_by_id[member.id] = member
            except (discord.HTTPException, discord.ClientException, TimeoutError) as exc:
                logger.debug(
                    "msg member mention lookup unavailable guild_id=%s query_length=%s error=%s",
                    guild.id,
                    len(name),
                    type(exc).__name__,
                )

        candidates = list(candidates_by_id.values())
        if len(candidates) == 1 and not lookup_was_truncated:
            member = candidates[0]
            resolved_by_name[normalized] = member
            allowed_members[member.id] = member
        elif len(candidates) > 1 or lookup_was_truncated:
            issues.append(f"@{name} (nome ambíguo; use a menção de membro do Discord)")
        else:
            issues.append(f"@{name} (membro não encontrado ou indisponível para consulta)")

    def replace_name(match: re.Match[str]) -> str:
        name = match.group(1)
        if name.casefold() in MSG_NON_PING_TOKENS:
            return match.group(0)
        member = resolved_by_name.get(name.casefold())
        return member.mention if member is not None else match.group(0)

    resolved_content = MSG_NAME_MENTION_PATTERN.sub(replace_name, content)

    native_ids = {
        int(match.group(1)) for match in MSG_NATIVE_USER_MENTION_PATTERN.finditer(content)
    }
    if len(native_ids) > MSG_MAX_MENTION_LOOKUPS:
        issues.append(
            f"menções explícitas adicionais (limite de {MSG_MAX_MENTION_LOOKUPS} por mensagem)"
        )
    for member_id in sorted(native_ids)[:MSG_MAX_MENTION_LOOKUPS]:
        member = guild.get_member(member_id)
        if member is None:
            try:
                member = await guild.fetch_member(member_id)
            except (discord.NotFound, discord.Forbidden):
                member = None
            except (discord.HTTPException, discord.ClientException, TimeoutError) as exc:
                logger.debug(
                    "msg explicit member mention lookup unavailable guild_id=%s error=%s",
                    guild.id,
                    type(exc).__name__,
                )
                member = None
        if member is not None:
            allowed_members[member.id] = member

    return resolved_content, list(allowed_members.values()), issues

CRITICAL_DIAGNOSTIC_NAMES = {
    "PostgreSQL",
    "Schema",
    "Migrations",
    "Sequences",
    "Constraints",
    "Foreign keys",
    "Economia",
    "XP",
    "Rewards",
    "AutoMod",
    "Anti-Raid",
    "Command matrix",
    "Comandos",
    "Interações",
    "Response contract",
    "Erros",
    "Dependências",
    "Discord commands",
    "Dashboard",
}

def diagnostic_severity(result: object) -> str:
    if getattr(result, "ok", False):
        return "OK"
    return "CRÍTICO" if getattr(result, "name", "") in CRITICAL_DIAGNOSTIC_NAMES else "ATENÇÃO"

ACCESS_COMMAND_ORDER = (
    "normal",
    "economia",
    "progressao",
    "moderacao",
    "comunidade",
    "seguranca",
    "administracao",
    "diversao",
)

def tutorial_access_lines(category: str) -> list[str]:
    if category == "painel":
        return ["`/dashboard` · Qualquer membro; as ações administrativas dependem do acesso ao servidor"]
    names = list(COMMAND_CATEGORIES.get(category, set()))
    names.sort(key=lambda name: (" " not in name, name.casefold()))
    lines: list[str] = []
    for name in names:
        if name in {"admin", "automod", "antiraid", "giveaway", "poll"}:
            continue
        lines.append(f"`/{name}` · {required_permission_text(name)}")
    if category == "administracao":
        lines.insert(0, "`/admin ...` · Gerenciar Servidor")
    elif category == "seguranca":
        lines.insert(0, "`/automod ...` e `/antiraid ...` · Gerenciar Servidor")
    return lines


def tutorial_command_chunks(lines: list[str], limit: int = 950) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in lines:
        addition = len(line) + (1 if current else 0)
        if current and current_length + addition > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_length = len(line)
        else:
            current.append(line)
            current_length += addition
    if current:
        chunks.append("\n".join(current))
    return chunks

class TutorialSelect(discord.ui.Select):
    def __init__(self, categories: dict[str, dict[str, object]]) -> None:
        self.categories = categories
        options = [discord.SelectOption(label="Comece aqui", value="intro", description="Atalhos principais e permissões")]
        for key, data in categories.items():
            options.append(discord.SelectOption(label=str(data["label"]), value=key, description=str(data["hint"])[:100]))
        super().__init__(placeholder="Escolha uma área do tutorial", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        if value == "intro":
            title = "BN / TUTORIAL"
            description = "Selecione uma categoria no menu para ver a função dos comandos e os requisitos de acesso."
            page = embed(title, description, "system")
            page.add_field(name="Primeiro contato", value="`/profile` consulta nível, XP e atividade. `/balance` mostra carteira e banco. `/ticket` abre atendimento privado. `/suggest` publica uma ideia para votação.", inline=False)
            page.add_field(name="Para a equipe", value="Use **Moderação** para avisos e punições, **Segurança** para AutoMod e Anti-Raid, e **Administração** para configurações e diagnósticos.", inline=False)
            page.add_field(name="Antes de executar", value="Confira o membro, o canal e o motivo antes de aplicar uma punição. Em páginas de administração, leia os parâmetros e confirme o alvo antes de alterar dados.", inline=False)
        else:
            data = self.categories.get(value, {})
            page = embed(f"BN / {str(data.get('label', value)).upper()}", str(data.get("description", "")), str(data.get("section", "system")))
            if value == "administracao":
                page.remove_image()
                if interaction.client.user is not None:
                    page.set_thumbnail(url=interaction.client.user.display_avatar.url)
            for name, body in data.get("steps", []):
                page.add_field(name=name, value=body, inline=False)
            access_lines = tutorial_access_lines(value)
            if access_lines:
                chunks = tutorial_command_chunks(access_lines)
                for index, chunk in enumerate(chunks, start=1):
                    suffix = f" · {index}/{len(chunks)}" if len(chunks) > 1 else ""
                    page.add_field(name=f"Acesso aos comandos{suffix}", value=chunk, inline=False)
        await interaction.response.edit_message(embed=page, view=self.view)

class TutorialView(discord.ui.View):
    def __init__(self, categories: dict[str, dict[str, object]]) -> None:
        super().__init__(timeout=300)
        self.message = None
        self.add_item(TutorialSelect(categories))

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

class TestallErrorsView(discord.ui.View):
    def __init__(self, owner_id: int, errors: list[object]) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.errors = errors
        self.page_index = 0
        self.page_size = 8
        self._refresh()

    def _refresh(self) -> None:
        total = max(1, (len(self.errors) + self.page_size - 1) // self.page_size)
        self.previous_button.disabled = self.page_index == 0
        self.next_button.disabled = self.page_index >= total - 1
        self.page_button.label = f"{self.page_index + 1} / {total}"

    def _page(self) -> discord.Embed:
        start = self.page_index * self.page_size
        chunk = self.errors[start:start + self.page_size]
        critical = sum(diagnostic_severity(result) == "CRÍTICO" for result in self.errors)
        warnings = len(self.errors) - critical
        failure_label = "falha" if len(self.errors) == 1 else "falhas"
        critical_label = "crítica" if critical == 1 else "críticas"
        page = embed("BN / TESTALL · ERROS", f"{len(self.errors)} {failure_label} · {critical} {critical_label} · {warnings} atenção", "moderation")
        for result in chunk:
            severity = diagnostic_severity(result)
            page.add_field(name=f"{severity} · {getattr(result, 'name', 'desconhecido')}", value=str(getattr(result, 'detail', 'sem detalhes'))[:500], inline=False)
        return page

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Este relatório pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page_index = max(0, self.page_index - 1)
        self._refresh()
        await interaction.response.edit_message(embed=self._page(), view=self)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, row=0, disabled=True)
    async def page_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label="Próxima", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        total = max(1, (len(self.errors) + self.page_size - 1) // self.page_size)
        self.page_index = min(total - 1, self.page_index + 1)
        self._refresh()
        await interaction.response.edit_message(embed=self._page(), view=self)

class TestallView(discord.ui.View):
    def __init__(self, owner_id: int, pages: list[discord.Embed], failed_results: list[object]) -> None:
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.pages = pages
        self.failed_results = failed_results
        self.critical_errors = [result for result in failed_results if diagnostic_severity(result) == "CRÍTICO"]
        self.warning_errors = [result for result in failed_results if diagnostic_severity(result) == "ATENÇÃO"]
        self.page_index = 0
        self._refresh()

    def _refresh(self) -> None:
        total = len(self.pages)
        self.first_button.disabled = self.page_index == 0
        self.previous_button.disabled = self.page_index == 0
        self.page_button.label = f"{self.page_index + 1} / {total}"
        self.next_button.disabled = self.page_index >= total - 1
        self.last_button.disabled = self.page_index >= total - 1
        self.errors_button.disabled = not self.failed_results
        self.errors_button.label = f"Ver erros ({len(self.failed_results)})" if self.failed_results else "Sem erros"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Este relatório pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    async def _go(self, interaction: discord.Interaction, index: int) -> None:
        self.page_index = max(0, min(index, len(self.pages) - 1))
        self._refresh()
        await interaction.response.edit_message(embed=self.pages[self.page_index], view=self)

    @discord.ui.button(label="Primeira", style=discord.ButtonStyle.secondary, row=0)
    async def first_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go(interaction, 0)

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.secondary, row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go(interaction, self.page_index - 1)

    @discord.ui.button(label="1 / 1", style=discord.ButtonStyle.secondary, row=0, disabled=True)
    async def page_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()

    @discord.ui.button(label="Próxima", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go(interaction, self.page_index + 1)

    @discord.ui.button(label="Última", style=discord.ButtonStyle.secondary, row=0)
    async def last_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._go(interaction, len(self.pages) - 1)

    @discord.ui.button(label="Ver erros", style=discord.ButtonStyle.danger, row=1)
    async def errors_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        error_view = TestallErrorsView(self.owner_id, self.failed_results)
        await interaction.response.send_message(embed=error_view._page(), view=error_view, ephemeral=True)

class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.started_at = time.monotonic()

    @user_installable
    @app_commands.command(name="ping", description="Mostra a latência do BN Bot.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency = max(round(self.bot.latency * 1000), 0)
        await interaction.response.send_message(f"Pong! `{latency} ms`")

    @user_installable
    @app_commands.command(name="uptime", description="Mostra o uptime do BN Bot.")
    async def uptime(self, interaction: discord.Interaction) -> None:
        total = int(time.monotonic() - self.started_at)
        page = embed("BN / UPTIME", "Tempo contínuo desde a última inicialização.", "system")
        page.add_field(name="Leitura", value=ledger([
            ("Ativo", duration(total)),
            ("Servidores", number(len(self.bot.guilds))),
            ("Gateway", "pronto" if self.bot.is_ready() else "aguardando"),
        ]), inline=False)
        page.add_field(name="Estado", value=status_line("Processo", "estável" if self.bot.is_ready() else "aguardando", "ok" if self.bot.is_ready() else "warning"), inline=False)
        await interaction.response.send_message(embed=page)

    @user_installable
    @app_commands.command(name="botinfo", description="Mostra informações do BN Bot.")
    async def botinfo(self, interaction: discord.Interaction) -> None:
        page = embed("BN / IDENTIDADE", "Estado operacional e presença do BN Bot.", "system")
        page.add_field(name="Discord.py", value=f"`{discord.__version__}`", inline=True)
        page.add_field(name="Servidores", value=f"`{number(len(self.bot.guilds))}`", inline=True)
        page.add_field(name="Usuário", value=str(self.bot.user) if self.bot.user else "indisponível", inline=False)
        page.add_field(name="Gateway", value=f"`{round(self.bot.latency * 1000)} ms`", inline=True)
        page.add_field(name="Estado", value=status_line("Processo", "pronto" if self.bot.is_ready() else "aguardando", "ok" if self.bot.is_ready() else "warning"), inline=True)
        if self.bot.user:
            page.set_thumbnail(url=self.bot.user.display_avatar.url)
        await interaction.response.send_message(embed=page)

    @app_commands.command(name="serverinfo", description="Mostra informações do servidor.")
    @app_commands.guild_only()
    async def serverinfo(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        page = embed("BN / SERVIDOR", f"**{guild.name}** · inventário rápido deste servidor.", "system")
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        page.add_field(name="Membros", value=f"`{number(guild.member_count or 0)}`", inline=True)
        page.add_field(name="Canais", value=f"`{number(len(guild.channels))}`", inline=True)
        page.add_field(name="Cargos", value=f"`{number(max(len(guild.roles) - 1, 0))}`", inline=True)
        page.add_field(name="Estrutura", value=ledger([
            ("Texto", number(text_channels)),
            ("Voz", number(voice_channels)),
            ("Categorias", number(len(guild.categories))),
        ]), inline=False)
        page.add_field(name="Criado", value=discord.utils.format_dt(guild.created_at, "R"), inline=True)
        page.add_field(name="Dono", value=f"<@{guild.owner_id}>" if guild.owner_id else "indisponível", inline=True)
        page.add_field(name="ID", value=f"`{guild.id}`", inline=True)
        if guild.icon:
            page.set_thumbnail(url=guild.icon.url)
        await interaction.response.send_message(embed=page)

    @app_commands.command(name="userinfo", description="Mostra informações de um usuário.")
    @app_commands.guild_only()
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        page = embed("BN / PERFIL", f"**{target.display_name}**\n{target.mention}", "system")
        page.set_thumbnail(url=target.display_avatar.url)
        joined_at = target.joined_at if isinstance(target, discord.Member) else None
        page.add_field(name="Registro", value=ledger([
            ("ID", str(target.id)),
            ("Conta", discord.utils.format_dt(target.created_at, "R")),
            ("Servidor", discord.utils.format_dt(joined_at, "R") if joined_at else "Não disponível"),
        ]), inline=False)
        if isinstance(target, discord.Member):
            page.add_field(name="Presença", value=status_line("Tipo", "bot" if target.bot else "membro", "warning" if target.bot else "ok"), inline=True)
            page.add_field(name="Cargos", value=f"`{max(len(target.roles) - 1, 0)}`", inline=True)
            page.add_field(name="Posição", value=f"`{target.top_role.name}`" if target.top_role else "@everyone", inline=False)
        await interaction.response.send_message(embed=page)

    @user_installable
    @app_commands.command(name="avatar", description="Mostra o avatar de um usuário.")
    async def avatar(self, interaction: discord.Interaction, user: discord.User | None = None) -> None:
        target = user or interaction.user
        page = embed("BN / AVATAR", f"**{target.display_name}** · imagem original do Discord.", "system")
        page.set_image(url=target.display_avatar.url)
        page.add_field(name="ID", value=f"`{target.id}`", inline=True)
        page.add_field(name="Formato", value="CDN do Discord", inline=True)
        await interaction.response.send_message(embed=page)

    @command_rate_limit("remind", 10)
    @app_commands.command(name="remind", description="Agenda um lembrete para você.")
    @app_commands.guild_only()
    @app_commands.choices(delivery=[app_commands.Choice(name="Canal atual", value="channel"), app_commands.Choice(name="Mensagem direta", value="dm")])
    @app_commands.describe(duration_minutes="Tempo até o lembrete, em minutos", message="Texto do lembrete", delivery="Onde o lembrete será enviado")
    async def remind(self, interaction: discord.Interaction, duration_minutes: app_commands.Range[int, 1, 525600], message: str, delivery: str = "channel") -> None:
        guild = interaction.guild
        assert guild is not None
        text = " ".join(message.split())
        if not text:
            await interaction.response.send_message("O lembrete não pode estar vazio.", ephemeral=True)
            return
        if len(text) > 2000:
            await interaction.response.send_message("O lembrete pode ter no máximo 2000 caracteres.", ephemeral=True)
            return
        channel_id = interaction.channel_id if delivery == "channel" else None
        channel = interaction.channel
        if delivery == "channel" and not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("O lembrete no canal precisa ser usado em um canal de texto ou thread.", ephemeral=True)
            return
        if delivery not in {"channel", "dm"}:
            await interaction.response.send_message("Forma de entrega inválida.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        due_at = utc_now() + timedelta(minutes=int(duration_minutes))
        async with session_factory() as session:
            active_reminders = await session.scalar(
                select(func.count(Reminder.id)).where(
                    Reminder.guild_id == guild.id,
                    Reminder.user_id == interaction.user.id,
                    Reminder.sent_at.is_(None),
                )
            )
            if int(active_reminders or 0) >= 20:
                await respond(interaction, "Você já possui 20 lembretes ativos. Aguarde alguns serem enviados antes de criar outros.", ephemeral=True)
                return
            row = Reminder(id=secrets.randbits(62), guild_id=guild.id, user_id=interaction.user.id, channel_id=channel_id, message=text[:2000], due_at=due_at, sent_at=None, delivery=delivery)
            session.add(row)
            await session.commit()
        page = embed("BN / LEMBRETE", row.message, "system")
        page.add_field(name="Entrega", value="Mensagem direta" if delivery == "dm" else f"Canal <#{channel_id}>", inline=True)
        page.add_field(name="Quando", value=discord.utils.format_dt(row.due_at, "R"), inline=True)
        page.add_field(name="ID", value=f"`{row.id}`", inline=False)
        await interaction.followup.send(embed=page, ephemeral=True)

    @user_installable
    @app_commands.command(name="tutorial", description="Abre o tutorial visual do BN Bot para membros e staff.")
    async def tutorial(self, interaction: discord.Interaction) -> None:
        categories: dict[str, dict[str, object]] = {
            "normal": {
                "label": "Uso geral", "hint": "Consultas, informações e lembretes", "section": "system",
                "description": "Comandos para consultar informações sem alterar configurações do servidor.",
                "steps": [
                    ("Bot e conexão", "`/ping` mostra a latência do Gateway. `/uptime` informa há quanto tempo o processo está ativo. `/botinfo` mostra versão da biblioteca, quantidade de servidores e estado da conexão."),
                    ("Servidor e membros", "`/serverinfo` mostra a estrutura do servidor. `/userinfo` consulta a conta e, dentro do servidor, cargos e data de entrada. `/avatar` abre a imagem de perfil do usuário escolhido ou a sua."),
                    ("Lembretes", "`/remind` agenda um aviso em minutos. Preencha `duration_minutes`, `message` e escolha `delivery`: canal atual ou mensagem direta. São permitidos até 20 lembretes ativos por membro."),
                ],
            },
            "economia": {
                "label": "Economia", "hint": "Saldo, recompensas, loja e empregos", "section": "economy",
                "description": "Use estes comandos para movimentar moedas, comprar itens e trabalhar no sistema de empregos.",
                "steps": [
                    ("Receber moedas", "`/daily` resgata a recompensa diária e registra a sequência de dias. `/weekly` resgata a recompensa semanal. Os valores e bônus são definidos pela administração; cada recompensa tem seu próprio intervalo de resgate."),
                    ("Carteira e banco", "`/balance` mostra carteira e banco. `/bank` detalha os saldos. `/deposit` transfere da carteira para o banco e `/withdraw` faz o caminho inverso. `/pay` envia moedas para outro membro e pede confirmação quando necessário."),
                    ("Loja e inventário", "`/shop` lista os itens disponíveis. Use o ID mostrado pela loja em `/buy`; informe a quantidade quando necessário. `/sell` vende itens do inventário, `/inventory` mostra o que você possui e `/transactions` consulta as movimentações financeiras."),
                    ("Empregos", "`/jobs` lista vagas e requisitos. `/job` abre o seletor de emprego; vagas acima do seu nível aparecem como bloqueadas. Depois de escolher uma vaga, use `/work` para executar o turno e receber a recompensa prevista."),
                ],
            },
            "progressao": {
                "label": "Progressão", "hint": "Nível, XP, reputação e rankings", "section": "progression",
                "description": "Consulte seu progresso e compare os resultados com os demais membros.",
                "steps": [
                    ("Perfil", "`/profile` reúne nível, XP, reputação, conquistas, emprego, saldo e atividade. Informe outro membro quando quiser consultar o perfil dele."),
                    ("Reputação", "`/rep` concede um ponto a outro membro. Não é permitido dar reputação a si mesmo ou a bots, e existe um intervalo entre concessões. `/reps` consulta a pontuação registrada."),
                    ("Ranking", "`/leaderboard` permite ordenar por XP, moedas, reputação, mensagens, tempo em voz ou atividade. Cada página mostra até 10 posições; escolha o critério e informe a página desejada."),
                ],
            },
            "painel": {
                "label": "Dashboard e estatísticas", "hint": "Gráficos, filtros, contadores e cargos", "section": "system",
                "description": "Abra o painel web para consultar a atividade do servidor e configurar os recursos de análise.",
                "steps": [
                    ("Como entrar", "Execute `/dashboard` e abra o link enviado em resposta privada. Entre com sua conta Discord e selecione um servidor que você possa administrar. As ações exibidas dependem das permissões da sua conta."),
                    ("Gráficos", "Na área **Estatísticas**, consulte mensagens, tempo em voz, membros ativos, crescimento e canais mais movimentados. Os períodos disponíveis são 24 horas, 7 dias, 30 dias e 90 dias."),
                    ("Contadores de canais", "Cadastre o ID de um canal de voz ou palco, escolha a métrica e defina o nome. Os campos de modelo disponíveis são `{label}`, `{value}`, `{goal}` e `{percent}`. O bot só atualiza o nome quando o valor muda."),
                    ("Cargos por atividade", "Crie regras com mínimos de mensagens, tempo em voz e dias ativos. Confira o cargo escolhido e a hierarquia do bot. A remoção automática fica desligada por padrão e só deve ser ativada quando a regra estiver revisada."),
                    ("Filtros e histórico", "É possível excluir canais, categorias e cargos, ignorar bots ou comandos e ajustar a retenção. Os gráficos começam a refletir os dados coletados pelo sistema; atividade anterior que não foi registrada não pode ser reconstruída."),
                ],
            },
            "moderacao": {
                "label": "Moderação", "hint": "Avisos, timeout, expulsão e limpeza", "section": "moderation",
                "description": "Use os comandos de moderação com o membro correto e um motivo claro. As permissões do Discord continuam valendo.",
                "steps": [
                    ("Avisos", "`/warn` registra um aviso sem prazo de expiração. `/t-warn` registra um aviso temporário; a duração usa `s`, `m`, `h` ou `d`, por exemplo `30m` ou `2d`."),
                    ("Consultar e corrigir", "`/warns` consulta os avisos do membro. `/unwarn` desativa um aviso pelo ID e `/clearwarns` desativa os avisos ativos daquele membro."),
                    ("Restrições e punições", "`/timeout` restringe temporariamente um membro. `/untimeout` e `/unmute` removem essa restrição. `/kick`, `/ban` e `/unban` cuidam de expulsão e banimento."),
                    ("Apagar mensagens", "`/purge` aceita de 1 a 1000 mensagens e pode filtrar por membro. A exclusão depende das permissões do bot no canal. Mensagens apagadas com sucesso são enviadas ao canal configurado em `/admin purge-log`, se houver um canal de auditoria ativo."),
                ],
            },
            "comunidade": {
                "label": "Comunidade", "hint": "Suporte, sugestões, denúncias e eventos", "section": "community",
                "description": "Os comandos desta área organizam o contato com a equipe e as atividades da comunidade.",
                "steps": [
                    ("Tickets", "`/ticket` abre um canal privado de suporte. A equipe usa `/ticket-claim`, `/ticket-close` e `/ticket-reopen` com o ID exibido no painel do ticket. `/ticket-config` define categoria, cargos de atendimento e canal de transcript."),
                    ("Sugestões", "`/suggest` publica uma ideia para votação. A equipe atualiza o estado com `/suggestion-status`: pendente, em análise, aprovada, rejeitada ou implementada."),
                    ("Denúncias", "`/report` registra uma denúncia contra um membro, com motivo e evidência opcional. A equipe acompanha o caso por `/report-status`. `/community-config` define os canais usados para sugestões e denúncias."),
                    ("Enquetes e sorteios", "Use `/poll create` para criar uma enquete com 2 a 10 opções; `/poll end` encerra a votação. `/giveaway create` configura o prêmio e a duração; `/giveaway end` encerra um sorteio, `/giveaway reroll` sorteia outro vencedor e `/giveaway cancel` cancela um sorteio ativo."),
                ],
            },
            "seguranca": {
                "label": "Segurança", "hint": "AutoMod e Anti-Raid", "section": "security",
                "description": "Configure as proteções antes de depender delas em um incidente real.",
                "steps": [
                    ("AutoMod", "Comece por `/automod setup`: ele ativa a proteção, cria as regras padrão ausentes e preserva as regras existentes. Confira `/automod status` e `/automod rules`. Use `/automod enable` ou `/automod disable` para controlar o módulo. Crie, altere e remova regras com `/automod rule-add`, `/automod rule-update` e `/automod rule-delete`."),
                    ("Listas do AutoMod", "`/automod list-add`, `/automod lists`, `/automod list-remove` e `/automod list-action` gerenciam listas permitidas e bloqueadas de usuários, canais, cargos, palavras e domínios, além da ação aplicada quando há correspondência."),
                    ("Anti-Raid", "Use `/antiraid setup` para criar a configuração inicial, `/antiraid configure` para ajustar limites, ação, canais e quarentena, e `/antiraid status` para conferir o estado. `/antiraid unlock` encerra manualmente um lockdown ativo."),
                ],
            },
            "administracao": {
                "label": "Administração", "hint": "Configuração, economia e diagnóstico", "section": "admin",
                "description": "Estas operações alteram configurações ou dados do servidor. Confira o alvo e os valores antes de confirmar.",
                "steps": [
                    ("Economia e loja", "`/admin credit` adiciona moedas e `/admin debit` remove moedas de um membro. `/admin shop-add` cadastra item na loja. `/admin rewards` configura as recompensas diária e semanal e o bônus de sequência."),
                    ("Empregos", "`/admin job-add` cria uma vaga com seus requisitos. `/admin job-remove` localiza a vaga por autocomplete e solicita confirmação antes de removê-la."),
                    ("Fuso horário", "`/admin timezone` recebe um identificador IANA, por exemplo `America/Sao_Paulo`. Isso define o fuso usado pelos recursos do bot que dependem da configuração do servidor."),
                    ("Auditoria do purge", "`/admin purge-log canal:#canal` define o canal de registro. Sem argumentos, consulta a configuração atual; com `desativar:true`, desativa os registros. O bot precisa conseguir ver o canal e enviar mensagens e anexos."),
                    ("Mensagens e suporte", "`/msg` envia uma mensagem pelo bot a um canal de texto ou tópico. Digite `@nome` para mencionar um membro quando o nome corresponder a uma única pessoa do servidor; nomes ausentes ou ambíguos ficam como texto. `responder_a` aceita o ID ou link da mensagem original. `/ticket-config` e `/community-config` configuram os canais e cargos desses recursos."),
                    ("Diagnóstico", "`/testall` executa verificações não destrutivas e mostra os itens que precisam de atenção. `/history` exibe os últimos comandos registrados; ambos exigem **Gerenciar Servidor**."),
                ],
            },
            "diversao": {
                "label": "Diversão", "hint": "Comandos rápidos e jogos", "section": "fun",
                "description": "Jogos curtos para usar no servidor.",
                "steps": [
                    ("Resultados imediatos", "`/coinflip` sorteia cara ou coroa. `/dice` rola um dado de seis lados. `/eightball` recebe uma pergunta e retorna uma resposta da bola 8."),
                    ("Partida por botões", "`/rps` inicia pedra, papel e tesoura. Escolha sua jogada nos botões da mensagem; a partida pertence a quem abriu o comando."),
                ],
            },
        }
        page = embed("BN / TUTORIAL", "Escolha uma área no menu para ver os comandos, o que fazem e as permissões necessárias.", "system")
        page.add_field(
            name="Primeiro contato",
            value="`/profile` mostra seu progresso; `/balance` consulta os saldos; `/ticket` abre suporte; `/suggest` envia uma ideia. Use `/tutorial` novamente para abrir este painel.",
            inline=False,
        )
        page.add_field(
            name="Para a equipe",
            value="Comece por **Moderação** e **Segurança**. Em **Administração** estão configurações, auditoria do `/purge` e o `/testall` para diagnóstico.",
            inline=False,
        )
        page.add_field(
            name="Permissões",
            value="A lista no fim de cada página mostra a permissão exigida pelo comando. Se o comando não aparecer para você, confira as permissões em **Configurações do servidor → Integrações → BN Bot**. O tutorial não concede acesso.",
            inline=False,
        )
        view = TutorialView(categories)
        await interaction.response.send_message(embed=page, view=view, ephemeral=True)
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass

    @command_rate_limit("msg", 15)
    @app_commands.command(
        name="msg", description="Envia uma mensagem; use @nome para mencionar um membro."
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        canal="Canal de texto ou tópico de destino",
        mensagem="Texto; use @nome para mencionar um membro (até 2000 caracteres)",
        responder_a="ID ou link de uma mensagem neste canal (opcional)",
    )
    async def msg(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel | discord.Thread,
        mensagem: str,
        responder_a: str | None = None,
    ) -> None:
        await defer(interaction, ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await respond(
                interaction,
                "Este comando só pode ser usado em um servidor.",
                ephemeral=True,
            )
            return
        if not mensagem.strip():
            await respond(interaction, "A mensagem não pode estar vazia.", ephemeral=True)
            return
        if len(mensagem) > 2000:
            await respond(
                interaction,
                "A mensagem excede o limite de 2000 caracteres do Discord.",
                ephemeral=True,
            )
            return
        if canal.guild.id != guild.id:
            await respond(
                interaction,
                "Escolha um canal do mesmo servidor em que o comando foi executado.",
                ephemeral=True,
            )
            return
        if isinstance(canal, discord.Thread) and (canal.archived or canal.locked):
            await respond(
                interaction,
                "O tópico está arquivado ou bloqueado e não pode receber a mensagem.",
                ephemeral=True,
            )
            return

        bot_member = guild.me
        if bot_member is None and self.bot.user is not None:
            try:
                bot_member = await guild.fetch_member(self.bot.user.id)
            except discord.HTTPException:
                bot_member = None
        if bot_member is None:
            await respond(
                interaction,
                "Não consegui verificar as permissões do BN Bot nesse servidor.",
                ephemeral=True,
            )
            return

        sender_permissions = canal.permissions_for(interaction.user)
        if not sender_permissions.view_channel:
            await respond(
                interaction,
                "Você precisa conseguir visualizar o destino para usá-lo neste comando.",
                ephemeral=True,
            )
            return

        channel_permissions = canal.permissions_for(bot_member)
        if not channel_permissions.view_channel:
            await respond(
                interaction,
                "Não tenho permissão para visualizar o canal selecionado.",
                ephemeral=True,
            )
            return
        if isinstance(canal, discord.Thread):
            can_send = channel_permissions.send_messages_in_threads
        else:
            can_send = channel_permissions.send_messages
        if not can_send:
            await respond(
                interaction,
                "Não tenho permissão para enviar mensagens nesse destino.",
                ephemeral=True,
            )
            return

        reference: discord.Message | None = None
        if responder_a is not None:
            raw_reference = responder_a.strip()
            if not raw_reference:
                await respond(interaction, "Informe um ID ou link de mensagem válido.", ephemeral=True)
                return
            link = re.fullmatch(
                r"https?://(?:www\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)/?",
                raw_reference,
                flags=re.IGNORECASE,
            )
            if link:
                reference_guild_id, reference_channel_id, reference_message_id = map(int, link.groups())
                if reference_guild_id != guild.id or reference_channel_id != canal.id:
                    await respond(
                        interaction,
                        "O link precisa apontar para uma mensagem deste servidor e do canal de destino selecionado.",
                        ephemeral=True,
                    )
                    return
                message_id = reference_message_id
            elif raw_reference.isdecimal():
                message_id = int(raw_reference)
            else:
                await respond(interaction, "O parâmetro responder_a deve ser um ID ou link de mensagem do Discord.", ephemeral=True)
                return
            if message_id <= 0:
                await respond(interaction, "O ID da mensagem é inválido.", ephemeral=True)
                return
            if not sender_permissions.read_message_history or not channel_permissions.read_message_history:
                await respond(
                    interaction,
                    "Você e o BN Bot precisam conseguir ler o histórico do canal para responder a uma mensagem.",
                    ephemeral=True,
                )
                return
            try:
                reference = await canal.fetch_message(message_id)
            except discord.NotFound:
                await respond(interaction, "A mensagem selecionada não existe mais neste canal.", ephemeral=True)
                return
            except discord.Forbidden:
                await respond(interaction, "Não tenho permissão para acessar a mensagem selecionada.", ephemeral=True)
                return
            except discord.HTTPException as exc:
                logger.warning(
                    "bot message reference lookup failed guild_id=%s channel_id=%s status=%s",
                    guild.id,
                    canal.id,
                    exc.status,
                )
                await respond(interaction, "Não foi possível acessar a mensagem selecionada. Tente novamente.", ephemeral=True)
                return

        mensagem_pronta, membros_mencionados, avisos_mencao = await resolve_msg_mentions(
            guild, mensagem
        )
        if len(mensagem_pronta) > 2000:
            await respond(
                interaction,
                "A mensagem ultrapassa 2000 caracteres depois de converter os nomes em menções. Encurte o texto e tente novamente.",
                ephemeral=True,
            )
            return
        allowed_mentions = discord.AllowedMentions(
            everyone=False,
            users=membros_mencionados,
            roles=False,
            replied_user=False,
        )

        try:
            if reference is None:
                await canal.send(mensagem_pronta, allowed_mentions=allowed_mentions)
            else:
                await canal.send(
                    mensagem_pronta,
                    reference=reference.to_reference(fail_if_not_exists=True),
                    mention_author=False,
                    allowed_mentions=allowed_mentions,
                )
        except discord.Forbidden:
            await respond(
                interaction,
                "O Discord negou o envio. Verifique as permissões do BN Bot no canal.",
                ephemeral=True,
            )
            return
        except discord.NotFound:
            await respond(
                interaction,
                "O canal ou a mensagem de referência não existe mais ou não está disponível.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            logger.warning(
                "bot message dispatch failed guild_id=%s channel_id=%s status=%s",
                guild.id,
                canal.id,
                exc.status,
            )
            await respond(
                interaction,
                "Não foi possível enviar a mensagem agora. Tente novamente mais tarde.",
                ephemeral=True,
            )
            return

        result = f"Mensagem enviada para {canal.mention}."
        if membros_mencionados:
            result += f" {len(membros_mencionados)} membro(s) mencionado(s)."
        if reference is not None:
            result += f" Resposta vinculada à mensagem [original]({reference.jump_url})."
        if avisos_mencao:
            result += " Não converti em ping: " + "; ".join(avisos_mencao) + ". Essas referências foram mantidas como texto."
        await respond(interaction, result, ephemeral=True)

    @command_rate_limit("history", 5)
    @app_commands.command(name="history", description="Mostra os comandos usados recentemente neste servidor.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(limit="Quantidade de registros, de 1 a 50")
    async def history(self, interaction: discord.Interaction, limit: app_commands.Range[int, 1, 50] = 20) -> None:
        guild = interaction.guild
        assert guild is not None
        await defer(interaction, ephemeral=True)
        try:
            async with session_factory() as session:
                stmt = (
                    select(CommandUsage)
                    .where(CommandUsage.guild_id == guild.id)
                    .order_by(desc(CommandUsage.used_at))
                    .limit(int(limit))
                )
                rows = list((await session.execute(stmt)).scalars().all())
        except Exception:
            logger.exception("command history query failed guild=%s", guild.id)
            await respond(interaction, "Não foi possível carregar o histórico agora.", ephemeral=True)
            return

        if not rows:
            await respond(interaction, "Nenhum comando foi registrado ainda.", ephemeral=True)
            return

        lines: list[str] = []
        for row in rows:
            member = guild.get_member(row.user_id)
            actor = discord.utils.escape_markdown(member.display_name[:32]) if member else "Usuário indisponível"
            command_name = discord.utils.escape_markdown(row.command_name[:40])
            outcome = "OK" if row.success else f"ERRO: {discord.utils.escape_markdown((row.error_type or 'falha')[:24])}"
            line = f"{discord.utils.format_dt(row.used_at, 'R')} · {actor} · `/{command_name}` · {outcome}"
            candidate = "\n".join((*lines, line))
            if len(candidate) > 3800:
                lines.append("… demais registros omitidos")
                break
            lines.append(line)

        page = embed("BN / HISTÓRICO", "\n".join(lines), "system")
        await respond(interaction, embed=page, ephemeral=True)

    @command_rate_limit("testall", 30)
    @app_commands.command(name="testall", description="Executa um diagnóstico não destrutivo do BN Bot.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def testall(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        started = time.monotonic()
        await interaction.response.defer(ephemeral=True, thinking=True)
        results = await run_diagnostics(self.bot, guild.id, interaction.user.id, interaction.channel_id)
        elapsed = time.monotonic() - started
        passed = sum(result.ok for result in results)
        failed = len(results) - passed
        failed_results = [result for result in results if not result.ok]
        per_page = 8
        pages: list[discord.Embed] = []
        chunks = [results[index:index + per_page] for index in range(0, len(results), per_page)]
        page_count = len(chunks)
        for index, chunk in enumerate(chunks):
            if index == 0:
                description = f"{passed} OK · {failed} falhas"
            else:
                description = f"Página {index + 1}/{page_count}"
            page = embed("BN / TESTALL", description, "system")
            for result in chunk:
                marker = diagnostic_severity(result)
                page.add_field(name=f"{marker} · {result.name}", value=result.detail[:1024], inline=False)
            pages.append(page)
        view = TestallView(interaction.user.id, pages, failed_results)
        await interaction.edit_original_response(embed=pages[0], view=view)
        try:
            async with session_factory() as session:
                session.add(AuditLog(id=secrets.randbits(62), guild_id=guild.id, executor_id=interaction.user.id, action="diagnostic.testall", resource="bot", before_state=None, after_state={"passed": passed, "failed": failed, "checks": len(results), "elapsed_seconds": round(elapsed, 3), "failed_checks": [result.name for result in failed_results[:20]]}, created_at=utc_now()))
                await session.commit()
        except Exception:
            logger.exception("testall audit persistence failed guild=%s", guild.id)
