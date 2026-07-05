from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.base import create_engine

engine = create_engine()
async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI-Dependency fuer eine DB-Session pro Request."""
    async with async_session_maker() as session:
        yield session


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Context-Manager fuer die Bot-Seite (Cogs), z.B.:

    async with get_db_session() as db:
        ...
    """
    async with async_session_maker() as session:
        yield session
