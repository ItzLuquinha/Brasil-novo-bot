"""Validation helpers for the committed, secret-free .env.example template."""
from __future__ import annotations

REQUIRED_ENV_KEYS = frozenset({
    "DISCORD_TOKEN",
    "DISCORD_CLIENT_ID",
    "DISCORD_CLIENT_SECRET",
    "DATABASE_URL",
    "REDIS_URL",
    "APP_SECRET_KEY",
})

_PLACEHOLDERS = frozenset({
    "",
    "changeme",
    "change-me",
    "your-token-here",
    "your-secret-here",
    "change-this-to-a-long-random-secret",
})

_LOCAL_EXAMPLES = {
    "database_url": frozenset({
        "postgresql+asyncpg://postgres:postgres@localhost:5432/bn_bot",
    }),
    "redis_url": frozenset({
        "redis://localhost:6379/0",
        "redis://127.0.0.1:6379/0",
    }),
}


def inspect_environment_example(content: str) -> tuple[list[str], list[str]]:
    """Return (missing_required_keys, unsafe_required_values)."""
    entries: set[str] = set()
    unsafe: list[str] = []

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        entries.add(key)
        literal = value.strip().strip('"').strip("'")
        normalized = literal.casefold()
        if key not in REQUIRED_ENV_KEYS or normalized in _PLACEHOLDERS:
            continue
        safe_values = _LOCAL_EXAMPLES.get(key.casefold(), frozenset())
        if normalized not in safe_values:
            unsafe.append(key)

    missing = sorted(REQUIRED_ENV_KEYS - entries)
    return missing, sorted(set(unsafe))
