from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.purge_audit import build_purge_archive_parts


def _message(message_id: int, content: str):
    return SimpleNamespace(
        id=message_id,
        author=SimpleNamespace(id=100 + message_id, display_name=f"Membro {message_id}"),
        content=content,
        created_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
        jump_url=f"https://discord.com/channels/1/2/{message_id}",
        attachments=[SimpleNamespace(filename="imagem.png", url="https://cdn.example/imagem.png")],
        embeds=[SimpleNamespace(title="Info", description="Detalhes", url="https://example.com", fields=[SimpleNamespace(name="Campo", value="Valor")])],
    )


def test_purge_archive_contains_message_context_and_attachment_metadata():
    payloads = build_purge_archive_parts(
        [_message(123, "conteúdo removido")],
        guild_name="Servidor", guild_id=1, channel_name="geral", channel_id=2,
        moderator_name="Staff#0001", moderator_id=9,
        executed_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
    )
    assert len(payloads) == 1
    text = payloads[0].decode("utf-8")
    for expected in ("conteúdo removido", "Membro 123", "123", "geral", "Staff#0001", "imagem.png", "https://cdn.example/imagem.png", "Detalhes", "Campo: Valor"):
        assert expected in text


def test_purge_archive_splits_payload_into_bounded_parts_without_losing_messages():
    messages = [_message(index, f"mensagem-{index}-" + ("x" * 450)) for index in range(1, 8)]
    payloads = build_purge_archive_parts(
        messages, guild_name="Servidor", guild_id=1, channel_name="geral", channel_id=2,
        moderator_name="Staff", moderator_id=9,
        executed_at=datetime(2026, 10, 12, tzinfo=timezone.utc), max_bytes=1400,
    )
    combined = "\n".join(part.decode("utf-8") for part in payloads)
    assert len(payloads) > 1
    assert all(len(part) <= 1400 for part in payloads)
    for index in range(1, 8):
        assert combined.count(f"Mensagem ID: {index}") == 1
