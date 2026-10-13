from collections.abc import AsyncIterator
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings
from app.core.database_options import engine_options


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def async_database_url() -> URL:
    url = make_url(get_settings().database_url)
    if url.drivername in {"postgresql", "postgresql+psycopg", "postgresql+psycopg2"}:
        return url.set(drivername="postgresql+asyncpg")
    return url


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = async_database_url()
        _engine = create_async_engine(url, **engine_options(url))
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _session_factory


def session_factory(**kwargs):
    return get_session_factory()(**kwargs)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
