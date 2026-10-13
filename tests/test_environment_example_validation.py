from pathlib import Path

from app.services.environment_example import inspect_environment_example


def test_committed_env_example_accepts_ipv4_loopback_redis_url() -> None:
    content = Path(".env.example").read_text(encoding="utf-8")
    missing, unsafe = inspect_environment_example(content)
    assert missing == []
    assert unsafe == []


def test_env_example_accepts_localhost_redis_url_too() -> None:
    content = """\
DISCORD_TOKEN=
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/bn_bot
REDIS_URL=redis://localhost:6379/0
APP_SECRET_KEY=
"""
    assert inspect_environment_example(content) == ([], [])


def test_env_example_still_rejects_credential_bearing_redis_url() -> None:
    content = """\
DISCORD_TOKEN=
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/bn_bot
REDIS_URL=redis://:real-password@127.0.0.1:6379/0
APP_SECRET_KEY=
"""
    missing, unsafe = inspect_environment_example(content)
    assert missing == []
    assert unsafe == ["REDIS_URL"]


def test_testall_environment_check_uses_shared_validator() -> None:
    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert "from app.services.environment_example import inspect_environment_example" in source
    assert "inspect_environment_example(example.read_text(encoding=\"utf-8\"))" in source
