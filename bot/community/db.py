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

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable

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
from sqlalchemy import select, union
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bot.core.bot_settings import get_bot_setting, set_bot_setting
from bot.core.config import settings

DB_NAME_KEY = "community_db_name"
SITE_URL_KEY = "community_site_url"
# Optional eigene Verbindung zur Seiten-DB (leerer Server = Server/Benutzer der Bot-DB)
DB_HOST_KEY = "community_db_host"
DB_PORT_KEY = "community_db_port"
DB_USER_KEY = "community_db_user"
DB_PASSWORD_KEY = "community_db_password"  # nie an die Oberflaeche zurueck

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
    # AMP-Zugang (Migration 009 der Seite): requested | active | denied | disabled | reset_requested
    Column("amp_username", String(50)),
    Column("amp_status", String(20)),
    Column("amp_note", String(255)),
    Column("amp_updated_at", DateTime),
)

roles = Table(
    "roles",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("slug", String(32)),
    Column("name", String(50)),
    Column("level", SmallInteger),
    # Migration 010 der Seite: 'rank' (genau einer pro Mitglied) oder 'extra' (Zusatzrolle)
    Column("kind", String(10), server_default="rank"),
    Column("color", String(7)),
    Column("is_default", SmallInteger, default=0),  # Standardrang neuer Mitglieder (z.B. Karl)
)

# Zusatzrollen der Mitglieder (Migration 010 der Seite)
user_extra_roles = Table(
    "user_extra_roles",
    metadata,
    Column("user_id", Integer, primary_key=True),
    Column("role_id", Integer, primary_key=True),
    Column("assigned_by", Integer),
)

# Rollenanfragen der Seite (Migration 011): pending | approved | denied
role_requests = Table(
    "role_requests",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer),
    Column("role_id", Integer),
    Column("ticket_id", Integer),
    Column("reason", String(1000), default=""),
    Column("status", String(10), default="pending"),
    Column("decided_by", Integer),
    Column("decision_note", String(255)),
    Column("created_at", DateTime),
    Column("decided_at", DateTime),
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

role_permissions = Table(
    "role_permissions",
    metadata,
    Column("role_id", Integer, primary_key=True),
    Column("permission", String(50), primary_key=True),
)

events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer),
    Column("title", String(150)),
    Column("description", Text),
    Column("location", String(150), default=""),
    # Ortszeit der Seite (Europe/Berlin), ohne Zeitzone gespeichert
    Column("starts_at", DateTime),
    Column("ends_at", DateTime),
    Column("max_participants", SmallInteger),
    Column("is_cancelled", SmallInteger, default=0),
    Column("announce_discord", SmallInteger, default=1),
)

event_participants = Table(
    "event_participants",
    metadata,
    Column("event_id", Integer, primary_key=True),
    Column("user_id", Integer, primary_key=True),
    Column("status", String(10)),  # yes | maybe | no
    Column("updated_at", DateTime),
)

tickets = Table(
    "tickets",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer),
    Column("subject", String(150)),
    Column("category", String(30)),
    Column("status", String(20), default="open"),  # open | in_progress | waiting | closed
    Column("priority", String(10), default="normal"),
    Column("assigned_to", Integer),
    Column("created_at", DateTime),
    Column("updated_at", DateTime),
    Column("closed_at", DateTime),
)

ticket_messages = Table(
    "ticket_messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ticket_id", Integer),
    Column("user_id", Integer),  # NULL = Systemmeldung
    Column("body", Text),
    Column("is_internal", SmallInteger, default=0),
    Column("created_at", DateTime),
)

wiki_pages = Table(
    "wiki_pages",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("slug", String(120)),
    Column("title", String(120)),
    Column("category", String(60)),
    Column("body", Text),
    Column("min_read_level", SmallInteger, default=0),
)

_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None
_config = {"db_name": "", "url": "", "site_url": "", "db_host": "", "db_port": 0, "db_user": "", "password_set": False}


def _url_for(db_name: str, host: str = "", port: int = 0, user: str = "", password: str = "") -> str:
    """Seiten-DB: ohne eigenen Server auf dem Server der Bot-DB mit deren Benutzer.
    Mit eigenem Server: dessen Port (Standard 3306) und Benutzer - ohne Benutzer der der Bot-DB."""
    if not db_name:
        return ""
    if host:
        own_user = bool(user)
        user, password = (user, password) if own_user else (settings.db_user, settings.db_password)
        port = port or 3306
    elif settings.db_host:
        host, port, user, password = settings.db_host, settings.db_port, settings.db_user, settings.db_password
    else:
        return ""
    return URL.create(
        "mysql+asyncmy", username=user, password=password, host=host, port=port, database=db_name
    ).render_as_string(hide_password=False)


async def load_config() -> dict:
    """Liest die Einstellungen (Oberflaeche vor .env) und verbindet ggf. neu."""
    db_name = await get_bot_setting(DB_NAME_KEY, "") or ""
    site_url = (await get_bot_setting(SITE_URL_KEY, "") or settings.community_site_url).rstrip("/")
    host = await get_bot_setting(DB_HOST_KEY, "") or ""
    port = int(await get_bot_setting(DB_PORT_KEY, "0") or 0)
    user = await get_bot_setting(DB_USER_KEY, "") or ""
    password = await get_bot_setting(DB_PASSWORD_KEY, "") or ""
    url = _url_for(db_name, host, port, user, password) if db_name else settings.community_database_url
    if url != _config["url"]:
        await dispose()
    _config.update(
        db_name=db_name, url=url, site_url=site_url, db_host=host, db_port=port, db_user=user, password_set=bool(password)
    )
    return current_config()


async def save_config(
    db_name: str,
    site_url: str,
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
) -> dict:
    """None = unveraendert lassen (z.B. Passwort, das die Oberflaeche nie kennt)."""
    await set_bot_setting(DB_NAME_KEY, db_name.strip())
    await set_bot_setting(SITE_URL_KEY, site_url.strip().rstrip("/"))
    if host is not None:
        await set_bot_setting(DB_HOST_KEY, host.strip())
    if port is not None:
        await set_bot_setting(DB_PORT_KEY, str(port))
    if user is not None:
        await set_bot_setting(DB_USER_KEY, user.strip())
    if password is not None:
        await set_bot_setting(DB_PASSWORD_KEY, password)
    return await load_config()


def current_config() -> dict:
    return {
        "db_name": _config["db_name"],
        "site_url": _config["site_url"],
        "enabled": enabled(),
        "own_host": _config["db_host"],
        "own_port": _config["db_port"] or None,
        "own_user": _config["db_user"],
        "password_set": _config["password_set"],
    }


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
    global _engine, _session_maker, _extras
    if _engine is not None:
        await _engine.dispose()
    _engine = _session_maker = None
    _extras = None


# --- Rechte: Rang + Zusatzrollen ------------------------------------------------------
#
# Seit Migration 010 der Seite haben Mitglieder neben dem Rang (users.role_id)
# beliebig viele Zusatzrollen (user_extra_roles). Rechte = beide zusammen. Fehlt
# die Tabelle (aeltere Seite) oder das Leserecht darauf, rechnet der Bot nur mit
# dem Rang - einmal geloggt, damit nichts ausfaellt.

_log = logging.getLogger("wikingerbot.community")
_extras: bool | None = None  # None = noch nicht geprueft


async def extras_available() -> bool:
    """Gibt es Zusatzrollen (Spalte roles.kind + Tabelle user_extra_roles) und darf der Bot sie lesen?"""
    global _extras
    if _extras is None:
        try:
            async with session() as db:
                await db.execute(select(roles.c.kind).limit(1))
                await db.execute(select(user_extra_roles.c.user_id).limit(1))
            _extras = True
        except (OperationalError, ProgrammingError) as error:
            _log.warning(
                "Zusatzrollen der Seite nicht lesbar (Migration 010 / Datenbank-Rechte, siehe docs/community-grants.sql) "
                "– es zaehlt nur der Rang: %s",
                str(error).splitlines()[0][:200],
            )
            _extras = False
    return _extras


def permissions_subquery(with_extras: bool):
    """(user_id, permission) aller Mitglieder aus Rang und - falls vorhanden - Zusatzrollen."""
    rp = role_permissions
    by_rank = select(users.c.id.label("user_id"), rp.c.permission).select_from(users.join(rp, rp.c.role_id == users.c.role_id))
    if not with_extras:
        return by_rank.subquery("up")
    by_extra = select(user_extra_roles.c.user_id, rp.c.permission).select_from(
        user_extra_roles.join(rp, rp.c.role_id == user_extra_roles.c.role_id)
    )
    return union(by_rank, by_extra).subquery("up")


async def query_permissions(build: Callable) -> list:
    """Fuehrt build(up) aus - up ist die Unterabfrage (user_id, permission)."""
    sub = permissions_subquery(await extras_available())
    async with session() as db:
        return (await db.execute(build(sub))).all()


async def has_permission(site_user_id: int, permission: str) -> bool:
    rows = await query_permissions(
        lambda up: select(up.c.permission).where(up.c.user_id == site_user_id, up.c.permission.in_([permission, "*"])).limit(1)
    )
    return bool(rows)


async def ranks_only(statement):
    """Nur Raenge (keine Zusatzrollen) - fuer Abfragen auf roles. Ohne Migration 010 gibt es nur Raenge."""
    return statement.where(roles.c.kind == "rank") if await extras_available() else statement


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
