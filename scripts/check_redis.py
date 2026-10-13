from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.core.redis import redis_client


async def main() -> int:
    settings = get_settings()
    parsed = urlparse(settings.redis_url)
    host = parsed.hostname or "unknown"
    port = parsed.port or (6380 if parsed.scheme == "rediss" else 6379)
    database = parsed.path.lstrip("/") or "0"
    print(f"Redis target: {host}:{port}, database={database}")
    try:
        await asyncio.wait_for(redis_client.ping(), timeout=4)
    except Exception as exc:
        print(f"Redis check FAILED: {type(exc).__name__}")
        print("If Python is running directly on Windows, use REDIS_URL=redis://127.0.0.1:6379/0 (IPv4).")
        print("If Python is running inside Docker on the Compose network, the host is usually redis.")
        print("Start/check the container with: docker compose up -d redis")
        return 1
    else:
        print("Redis check OK: PING returned PONG")
        return 0
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
