"""Verbindung zur Datenbank der Community-Seite.

Gemeinsam fuer alle Community-Cogs (community, news, events, tickets, ...) -
der Bot-Kern importiert hiervon nichts. Ist COMMUNITY_DB_NAME bzw.
COMMUNITY_DATABASE_URL nicht gesetzt, ist enabled() False und die Cogs laden nicht.

Die Tabellen gehoeren der Seite (deren Migrationen legen sie an, nicht Alembic).
Hier stehen nur die Spalten, die der Bot braucht und lesen darf - die Rechte des
Bot-Benutzers auf diese Datenbank sind spaltengenau (z.B. keine E-Mail, kein
Passwort-Hash). Deshalb nie "SELECT *" auf users.

Zeiten: NOW() der Datenbank ist die gemeinsame Uhr von Seite und Bot (z.B. fuer
den Ablauf der Verknuepfungs-Codes). Event-Zeiten (events.starts_at) schreibt
die Seite dagegen in Europe/Berlin.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bot.core.config import settings

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(30)),
    Column("role_id", Integer),
    Column("is_banned", SmallInteger),
    Column("deleted_at", DateTime),
    Column("created_at", DateTime),
    Column("discord_id", BigInteger, unique=True),
    Column("discord_name", String(100)),
    Column("discord_linked_at", DateTime),
)

roles = Table(
    "roles",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("slug", String(32)),
    Column("name", String(50)),
    Column("level", SmallInteger),
    Column("color", String(7)),
)

discord_link_codes = Table(
    "discord_link_codes",
    metadata,
    Column("user_id", Integer, primary_key=True),
    Column("code", String(8), unique=True),
    Column("expires_at", DateTime),
)

bot_outbox = Table(
    "bot_outbox",
    metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("type", String(40)),
    Column("payload", Text),
    Column("created_at", DateTime),
    Column("processed_at", DateTime),
    Column("attempts", SmallInteger, default=0),
    Column("last_error", String(500)),
)

_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def enabled() -> bool:
    return bool(settings.community_database_url)


def engine() -> AsyncEngine:
    global _engine, _session_maker
    if _engine is None:
        _engine = create_async_engine(settings.community_database_url, pool_pre_ping=True, pool_recycle=3600)
        _session_maker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    engine()
    async with _session_maker() as db:
        yield db


async def dispose() -> None:
    global _engine, _session_maker
    if _engine is not None:
        await _engine.dispose()
    _engine = _session_maker = None


def site_link(page: str, **params) -> str | None:
    """Link auf die Seite (index.php?p=...), None ohne COMMUNITY_SITE_URL."""
    if not settings.community_site_url:
        return None
    from urllib.parse import urlencode

    query = urlencode({"p": page, **params})
    return f"{settings.community_site_url}/index.php?{query}"
