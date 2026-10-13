import os
from sqlalchemy.engine import URL


def _positive_int(name: str, default: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer") from None
    if value < 1 or value > maximum:
        raise RuntimeError(f"{name} must be between 1 and {maximum}")
    return value


def engine_options(url: URL) -> dict[str, object]:
    options: dict[str, object] = {"pool_pre_ping": True}
    if url.drivername.startswith("postgresql"):
        pool_size = _positive_int("DB_POOL_SIZE", 5, 50)
        max_overflow = _positive_int("DB_MAX_OVERFLOW", 10, 100)
        pool_timeout = _positive_int("DB_POOL_TIMEOUT", 30, 300)
        pool_recycle = _positive_int("DB_POOL_RECYCLE", 1800, 86400)
        options.update({
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": pool_timeout,
            "pool_recycle": pool_recycle,
        })
    return options
