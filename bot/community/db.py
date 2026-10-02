"""Verbindung zur Datenbank der Community-Seite.

Gemeinsam fuer alle Community-Cogs (community, news, events, tickets, ...) -
der Bot-Kern importiert hiervon nichts.

Eingestellt wird die Anbindung in der Web-Oberflaeche (Seite "Community"):
Datenbankname und Adresse der Seite liegen in den Bot-Einstellungen (bot_settings).
Host, Benutzer und Passwort sind dieselben wie fuer die eigene Datenbank des Bots
(AMP-Felder DB_*). Ohne Datenbankname ist enabled() False - die Community-Cogs
tun dann nichts, der Bot laeuft allein. COMMUNITY_DATABASE_URL/COMMUNITY_SITE_URL
in der .env gelten nur, solange in der Oberflaeche nichts eingetragen ist
(lokale Entwicklung, Tests).

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
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bot.core.bot_settings import get_bot_setting, set_bot_setting
from bot.core.config import settings

DB_NAME_KEY = "community_db_name"
SITE_URL_KEY = "community_site_url"

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

news = Table(
    "news",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer),
    Column("title", String(150)),
    Column("body", Text),
    Column("image", String(500)),
    Column("is_pinned", SmallInteger, default=0),
    Column("is_published", SmallInteger, default=1),
    Column("announce_discord", SmallInteger, default=1),
    Column("created_at", DateTime),
)

_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None
_config = {"db_name": "", "url": "", "site_url": ""}


def _url_for(db_name: str) -> str:
    """Seiten-DB auf demselben Server mit demselben Benutzer wie die Bot-DB."""
    if not db_name or not settings.db_host:
        return ""
    return URL.create(
        "mysql+asyncmy",
        username=settings.db_user,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port,
        database=db_name,
    ).render_as_string(hide_password=False)


async def load_config() -> dict:
    """Liest die Einstellungen (Oberflaeche vor .env) und verbindet ggf. neu."""
    db_name = await get_bot_setting(DB_NAME_KEY, "") or ""
    site_url = (await get_bot_setting(SITE_URL_KEY, "") or settings.community_site_url).rstrip("/")
    url = _url_for(db_name) if db_name else settings.community_database_url
    if url != _config["url"]:
        await dispose()
    _config.update(db_name=db_name, url=url, site_url=site_url)
    return current_config()


async def save_config(db_name: str, site_url: str) -> dict:
    await set_bot_setting(DB_NAME_KEY, db_name.strip())
    await set_bot_setting(SITE_URL_KEY, site_url.strip().rstrip("/"))
    return await load_config()


def current_config() -> dict:
    return {"db_name": _config["db_name"], "site_url": _config["site_url"], "enabled": enabled()}


def enabled() -> bool:
    return bool(_config["url"])


def engine() -> AsyncEngine:
    global _engine, _session_maker
    if not enabled():
        raise RuntimeError("Community-Seite nicht angebunden")
    if _engine is None:
        _engine = create_async_engine(_config["url"], pool_pre_ping=True, pool_recycle=3600)
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
    """Link auf die Seite (index.php?p=...), None ohne eingetragene Adresse."""
    if not _config["site_url"]:
        return None
    from urllib.parse import urlencode

    query = urlencode({"p": page, **params})
    return f"{_config['site_url']}/index.php?{query}"


async def check_connection() -> tuple[bool, str]:
    """Fuer die Oberflaeche: erreichbar, Migration der Seite da, Rechte gesetzt?"""
    if not enabled():
        return False, "Nicht angebunden – Datenbankname eintragen."
    try:
        async with session() as db:
            from sqlalchemy import select

            await db.execute(select(bot_outbox.c.id).limit(1))
            await db.execute(select(users.c.discord_id).limit(1))
    except Exception as error:
        text = str(error).splitlines()[0][:300]
        if "1142" in text or "1143" in text or "denied" in text.lower():
            return False, f"Keine Rechte auf die Tabellen der Seite: {text}"
        if "1146" in text or "doesn't exist" in text:
            return False, f"Tabellen fehlen – ist die Migration 008_discord auf der Seite gelaufen? {text}"
        return False, f"Nicht erreichbar: {text}"
    return True, "Verbunden"
