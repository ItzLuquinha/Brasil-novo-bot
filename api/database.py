import os
from collections.abc import AsyncIterator

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.db import Base
from app.core.database_options import engine_options

load_dotenv()

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def database_url() -> URL:
    raw_url = os.getenv("DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError("DATABASE_URL must be configured before the API starts")
    url = make_url(raw_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+asyncpg")
    elif url.drivername in {"postgresql+psycopg", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+asyncpg")
    return url


def validate_database_configuration() -> None:
    database_url()


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = database_url()
        _engine = create_async_engine(url, echo=False, **engine_options(url))
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(bind=get_engine(), class_=AsyncSession, expire_on_commit=False, autoflush=False)
    return _session_factory


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
