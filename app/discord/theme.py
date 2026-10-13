from __future__ import annotations
from datetime import timedelta
from decimal import Decimal
import discord

COLORS = {
    "system": 0x26313D,
    "economy": 0x247A62,
    "progression": 0x6D5B98,
    "moderation": 0xB6534B,
    "community": 0x287987,
    "security": 0x9D3947,
    "admin": 0x9A7735,
    "fun": 0x765A91,
}

SECTIONS = {
    "system": "sistema",
    "economy": "economia",
    "progression": "progressão",
    "moderation": "moderação",
    "community": "comunidade",
    "security": "segurança",
    "admin": "administração",
    "fun": "diversão",
}

GIFS = {
    "system": "https://media.giphy.com/media/MXo6HLOu0KHcYQ7pVy/giphy.gif",
    "progression": "https://media.giphy.com/media/26gR25WguJx0Var6w/giphy.gif",
    "levelup": "https://media.giphy.com/media/26u4exk4zsAqPcq08/giphy.gif",
    "dashboard": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExZjBiaWR2b2I0M2ZreDZvcW05OHFtcHNreXN1amhocGVzZGpiYXFucCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/8OYnFrez06yQt9zJFW/giphy.gif",
    "economy": "https://media.giphy.com/media/l0HlIvLpzz624GAUM/giphy.gif",
    "moderation": "https://media.giphy.com/media/ltoVrEYgv30GJvSDOk/giphy.gif",
    "timed_warning": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExcW9wbTlsdTNwOWh0dzh0aXB2ODAzNnFlOTZic2ZlNW83b2p0b2J6NiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/ioa0Au2SQOO9LKv9Fz/giphy.gif",
    "community": "https://media.giphy.com/media/7PN60wMzjUzbtkhIMF/giphy.gif",
    "security": "https://media.giphy.com/media/gHPOb1fEVWu5GHL2tk/giphy.gif",
    "admin": "https://media.giphy.com/media/l0HlIvLpzz624GAUM/giphy.gif",
    "fun": "https://media.giphy.com/media/pI2kp3Sg16ULOPjGN1/giphy.gif",
    "work": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExcms4a2Vka3AzbWJoZnBneHRmNW9teWdpZTR6c2Nna2xrZjdzZG5idyZlcD12MV9naWZzX3NlYXJjaCZjdD1n/E0mxSX7mzkAhsKyvSE/giphy.gif",
    "money": "https://media.giphy.com/media/sSl9CkCVbMa9q/giphy.gif",
    "shopping": "https://media.giphy.com/media/l3vRetKo0xRr7w3pm/giphy.gif",
    "purchase": "https://media.giphy.com/media/l3vRetKo0xRr7w3pm/giphy.gif",
    "reward": "https://media.giphy.com/media/26u4exk4zsAqPcq08/giphy.gif",
    "warning": "https://media.giphy.com/media/S9NByAZebNkSJcPnHx/giphy.gif",
    "timeout": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbmo3ZDM1YTJzMzM4MTU3a21iZW8xMmg2MXpqMDNjcTNyM3l5d3FvNiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/vOVFNit4dmql2N2Gm4/giphy.gif",
    "kick": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbXRnbXJ5ZHIzOXlmeHh1ZnByb2tmNGhuZ3lpNDh6Yjh5bmVtbWlsbSZlcD12MV9naWZzX3NlYXJjaCZjdD1n/h8lX2S1NyWtLdOP5ly/giphy.gif",
    "ban": "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3enM1cGliaGp1dTJiZ3N4OTN4dTY1YTBjN2NwOGo4bXljbTI5cXV5OCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/EP4afMcy8znubNpbMn/giphy.gif",
    "unban": "https://media.giphy.com/media/psfjpMeC1cEPmYQbs4/giphy.gif",
    "purge": "https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3am5jMXhsMXN1NndsMXBsaWZudGhoeHZ0aDdqZmQ0YmJxeWhld2lxbCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/uBNVKNhBRXtRPrlYU2/giphy.gif",
    "support": "https://media.giphy.com/media/7PN60wMzjUzbtkhIMF/giphy.gif",
    "idea": "https://media.giphy.com/media/pylpD8AoQCf3CQ1oO2/giphy.gif",
    "report": "https://media.giphy.com/media/Yqhr57aohKbKH2emhK/giphy.gif",
    "giveaway": "https://media.giphy.com/media/VvC4alRMPckApd9nUy/giphy.gif",
    "poll": "https://media.giphy.com/media/KVZcNQzDpbl1teu97Y/giphy.gif",
    "lockdown": "https://media.giphy.com/media/gHPOb1fEVWu5GHL2tk/giphy.gif",
    "respect": "https://media.giphy.com/media/3oz8xBrNCsITwSsnPa/giphy.gif",
    "coinflip": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExMGIyMzZwN25hOXEwdGt3MXhwMGRlZmVwdHVzbzhoNXFpY2duY3A5YiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/6jqfXikz9yzhS/giphy.gif",
    "dice": "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExa2R3MTJxc2pneGZqY2pkMXNmZm9sYjVxbmFpbXlyNGIwYThjczcwZiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/I38qmkMXsMOFKsuer9/giphy.gif",
    "rps": "https://media.giphy.com/media/RD3QScf0fgktocr353/giphy.gif",
    "eightball": "https://media.giphy.com/media/3o7bubjk9UPTmtMX9m/giphy.gif",
    "reminder": "https://media.giphy.com/media/N0MahGQUc32pmHbC99/giphy.gif",
    "robot": "https://media.giphy.com/media/MXo6HLOu0KHcYQ7pVy/giphy.gif",
    "celebrate": "https://media.giphy.com/media/26gR25WguJx0Var6w/giphy.gif",
}


GIF_SOURCES = {
    "system": "GIPHY estudacom",
    "progression": "GIPHY Jonas Blue",
    "levelup": "GIPHY Awkwafina",
    "dashboard": "GIPHY user selected",
    "economy": "GIPHY Originals",
    "moderation": "GIPHY News",
    "timed_warning": "GIPHY user selected",
    "community": "GIPHY Ryn Dean",
    "security": "GIPHY GiveGab",
    "admin": "GIPHY Originals",
    "fun": "GIPHY DailyPay",
    "work": "GIPHY user selected",
    "money": "GIPHY Ashlyn Anstee",
    "shopping": "GIPHY Superstore",
    "purchase": "GIPHY Superstore",
    "reward": "GIPHY Awkwafina",
    "warning": "GIPHY warning GIF",
    "timeout": "GIPHY News",
    "kick": "GIPHY user selected",
    "ban": "GIPHY user selected",
    "unban": "GIPHY Pudgy Penguins",
    "purge": "GIPHY user selected",
    "support": "GIPHY Ryn Dean",
    "idea": "GIPHY Julie Smith Schneider",
    "report": "GIPHY memecandy",
    "giveaway": "GIPHY Schoolgirl Style",
    "poll": "GIPHY Petland Florida",
    "lockdown": "GIPHY GiveGab",
    "respect": "GIPHY Landon Moss",
    "coinflip": "GIPHY user selected",
    "dice": "GIPHY existing dice GIF",
    "rps": "GIPHY BenJammins",
    "eightball": "GIPHY Matt Cutshall",
    "reminder": "GIPHY Death In Paradise",
    "robot": "GIPHY estudacom",
    "celebrate": "GIPHY Jonas Blue",
}




def _clean_title(title: str) -> str:
    cleaned = title.strip()
    if cleaned.upper().startswith("BN /"):
        cleaned = cleaned[3:].strip()
    return cleaned


def gif_for_title(title: str, section: str = "system") -> str | None:
    cleaned = _clean_title(title).casefold()
    ordered_rules = (
        (("dashboard",), "dashboard"),
        (("unban",), "unban"),
        (("ban",), "ban"),
        (("kick",), "kick"),
        (("timeout",), "timeout"),
        (("warn desativado", "warns limpos"), "warning"),
        (("t-warn", "timed warn"), "timed_warning"),
        (("warn",), "warning"),
        (("purge", "limpeza"), "purge"),
        (("anti-raid", "lockdown"), "lockdown"),
        (("automod", "lista", "regra"), "security"),
        (("sugestão",), "idea"),
        (("denúncia",), "report"),
        (("ticket",), "support"),
        (("sorteio",), "giveaway"),
        (("enquete", "voto"), "poll"),
        (("turbo",), "system"),
        (("daily", "weekly", "recompensa"), "reward"),
        (("compra",), "purchase"),
        (("loja", "item publicado"), "shopping"),
        (("venda",), "money"),
        (("inventário",), "shopping"),
        (("emprego", "trabalho", "turno"), "work"),
        (("carteira", "banco", "depósito", "saque", "transferência", "crédito", "débito"), "money"),
        (("nível", "ranking", "reputação"), "levelup"),
        (("perfil",), "levelup" if section == "progression" else "system"),
        (("moeda", "cara ou coroa"), "coinflip"),
        (("dado",), "dice"),
        (("pedra, papel",), "rps"),
        (("bola 8",), "eightball"),
        (("lembrete",), "reminder"),
        (("ping", "uptime", "identidade", "servidor", "avatar", "comandos", "testall"), "robot"),
        (("tempo", "timezone"), "robot"),
        (("admin",), "robot"),
    )
    for phrases, key in ordered_rules:
        if any(phrase in cleaned for phrase in phrases):
            if key == "progression":
                return GIFS["progression"]
            if key == "levelup":
                return GIFS["levelup"]
            return GIFS[key]
    if section == "progression":
        return GIFS["progression"]
    return GIFS.get(section, GIFS["system"])


def embed(
    title: str,
    description: str | None = None,
    section: str = "system",
    *,
    show_gif: bool = False,
    color_override: int | None = None,
) -> discord.Embed:
    result = discord.Embed(
        title=_clean_title(title),
        description=description,
        color=color_override if color_override is not None else COLORS.get(section, COLORS["system"]),
    )
    if show_gif:
        gif_url = gif_for_title(title, section)
        if gif_url:
            result.set_image(url=gif_url)
    return result


def money(value: Decimal | int | float) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    formatted = f"{amount:,.2f}"
    formatted = formatted.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{formatted} moedas"


def compact_money(value: Decimal | int | float) -> str:
    amount = Decimal(str(value))
    if amount >= 1_000_000_000:
        return f"{amount / Decimal('1000000000'):.1f} bi"
    if amount >= 1_000_000:
        return f"{amount / Decimal('1000000'):.1f} mi"
    if amount >= 1_000:
        return f"{amount / Decimal('1000'):.1f} mil"
    return f"{amount:.2f}".replace(".", ",")


def number(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def bar(value: int | float, maximum: int | float, width: int = 12) -> str:
    safe_width = max(1, int(width))
    ratio = 0.0 if maximum <= 0 else min(max(float(value) / float(maximum), 0.0), 1.0)
    filled = min(max(round(ratio * safe_width), 0), safe_width)
    return f"[{'█' * filled}{'░' * (safe_width - filled)}] {ratio * 100:.0f}%"


def percent(value: int | float, maximum: int | float) -> str:
    if maximum <= 0:
        return "0%"
    return f"{min(max(float(value) / float(maximum) * 100, 0.0), 100.0):.0f}%"


def duration(value: timedelta | int) -> str:
    seconds = int(value.total_seconds()) if isinstance(value, timedelta) else int(value)
    days, remainder = divmod(max(seconds, 0), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def user_line(member: discord.abc.User) -> str:
    return f"{member.mention} · `{member.id}`"


def status_line(label: str, value: str, status: str = "ok") -> str:
    labels = {
        "ok": "OK",
        "error": "ERRO",
        "open": "ABERTA",
        "active": "ATIVA",
        "closed": "ENCERRADA",
        "pending": "PENDENTE",
        "warning": "AVISO",
    }
    state = labels.get(status, status.upper())
    return f"**{label}** · {value} · {state}"


def result_embed(title: str, description: str, section: str, success: bool = True) -> discord.Embed:
    result = embed(title, description, section)
    result.set_footer(text=f"BN Bot · {SECTIONS.get(section, section)} · {'OK' if success else 'atenção'}")
    return result


def add_result(embed_obj: discord.Embed, label: str, value: str, inline: bool = True) -> None:
    embed_obj.add_field(name=label, value=value, inline=inline)


def ledger(rows: list[tuple[str, str]], width: int = 14) -> str:
    _ = width
    return "\n".join(f"**{label}**  {value}" for label, value in rows)


def divider(label: str) -> str:
    return f"**{label}**"


def line_chunks(lines: list[str], limit: int = 3800) -> list[str]:
    pages: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            pages.append(current)
            current = line
        else:
            current = candidate
    if current:
        pages.append(current)
    return pages or [""]
