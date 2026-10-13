from __future__ import annotations

from datetime import datetime
from typing import Any

ARCHIVE_PART_LIMIT = 7 * 1024 * 1024


def build_purge_archive_parts(
    messages: list[Any],
    *,
    guild_name: str,
    guild_id: int,
    channel_name: str,
    channel_id: int,
    moderator_name: str,
    moderator_id: int,
    executed_at: datetime,
    partial: bool = False,
    max_bytes: int = ARCHIVE_PART_LIMIT,
) -> list[bytes]:
    """Serialize only messages returned by successful Discord deletion calls."""
    if not messages:
        return []
    header = (
        "AUDITORIA DE MENSAGENS REMOVIDAS PELO /purge\n"
        f"Servidor: {guild_name} (ID {guild_id})\n"
        f"Canal de origem: #{channel_name} (ID {channel_id})\n"
        f"Responsável pela exclusão: {moderator_name} (ID {moderator_id})\n"
        f"Data/hora da ação (UTC): {executed_at.isoformat()}\n"
        f"Estado da operação: {'PARCIAL' if partial else 'CONCLUÍDA'}\n"
        f"Mensagens removidas e incluídas neste arquivo: {len(messages)}\n"
        "O conteúdo de cada bloco foi obtido da mensagem removida retornada pelo Discord.\n"
        "\n"
    ).encode("utf-8")
    parts: list[bytes] = []
    current = bytearray(header)

    for message in messages:
        author = getattr(message, "author", None)
        author_name = getattr(author, "display_name", None) or getattr(author, "name", None) or "Autor indisponível"
        author_id = getattr(author, "id", "desconhecido")
        content = getattr(message, "content", None) or "[sem conteúdo textual disponível]"
        timestamp = getattr(message, "created_at", None)
        timestamp_text = timestamp.isoformat() if timestamp else "data de criação indisponível"
        jump_url = getattr(message, "jump_url", None) or "link indisponível"
        section_lines = [
            "=" * 72,
            f"Mensagem ID: {getattr(message, 'id', 'desconhecido')}",
            f"Autor: {author_name} (ID {author_id})",
            f"Enviada em: {timestamp_text}",
            f"Link original: {jump_url}",
            "Conteúdo:",
            content,
        ]
        attachments = list(getattr(message, "attachments", []) or [])
        if attachments:
            section_lines.append("Anexos:")
            section_lines.extend(
                f"- {getattr(item, 'filename', 'arquivo')} | {getattr(item, 'url', 'URL indisponível')}"
                for item in attachments
            )
        embeds = list(getattr(message, "embeds", []) or [])
        if embeds:
            section_lines.append("Embeds:")
            for index, item in enumerate(embeds, start=1):
                section_lines.append(f"- Embed {index}: {getattr(item, 'title', None) or '[sem título]'}")
                description = getattr(item, "description", None)
                if description:
                    section_lines.append(f"  Descrição: {description}")
                url = getattr(item, "url", None)
                if url:
                    section_lines.append(f"  URL: {url}")
                for field in list(getattr(item, "fields", []) or []):
                    section_lines.append(f"  {getattr(field, 'name', 'Campo')}: {getattr(field, 'value', '')}")
        section = ("\n".join(section_lines) + "\n\n").encode("utf-8", errors="replace")
        if len(current) + len(section) > max_bytes and len(current) > len(header):
            parts.append(bytes(current))
            current = bytearray(header)
        current.extend(section)

    if current:
        parts.append(bytes(current))
    return parts
