from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from bot.core.config import settings


class Base(DeclarativeBase):
    """Basisklasse fuer alle SQLAlchemy-Modelle."""


def create_engine() -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)
