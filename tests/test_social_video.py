from __future__ import annotations

from pathlib import Path


def test_history_uses_interaction_helpers_and_compact_output() -> None:
    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert "from app.core.interactions import defer, respond" in source
    start = source.index("async def history(")
    end = source.index("async def testall(", start)
    history_source = source[start:end]
    assert "await defer(interaction, ephemeral=True)" in history_source
    assert "await respond(" in history_source
    assert "candidate = \"\\n\".join((*lines, line))" in history_source
    assert "if len(candidate) > 3800:" in history_source


def test_removed_social_video_commands_are_not_registered() -> None:
    from app.services.command_matrix import EXPECTED_COMMANDS, audit_commands

    removed = {"instagram", "tiktok"}
    actual = {case.qualified_name for case in audit_commands()}
    assert removed.isdisjoint(EXPECTED_COMMANDS)
    assert removed.isdisjoint(actual)


def test_diagnostics_do_not_require_social_video_dependencies() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert '"yt-dlp", "curl-cffi"' not in source
    assert "yt_dlp" not in source
    assert "curl_cffi" not in source


def test_social_video_dependencies_remain_removed() -> None:
    paths = (Path("requirements.txt"), Path("pyproject.toml"), Path("requirements-dev.txt"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    normalized = combined.casefold()
    assert "yt-dlp" not in normalized
    assert "yt_dlp" not in normalized
    assert "curl-cffi" not in normalized
    assert "curl_cffi" not in normalized
