"""Kategorien der Community-Seite fuer News und Events -> Discord-Rollen zum Anpingen.

Die Kategorien legt die Seite an (Verwaltung -> Kategorien), welche Rollen zu einer
Kategorie gehoeren, steht im Bot (Tabs News und Events, eine gemeinsame Zuordnung).
Beim ersten Posten pingt der Bot alle Rollen der gewaehlten Kategorien; hat eine
News/ein Event keine Kategorie mit Rollen, gilt die allgemeine Ping-Rolle des Tabs.

Aeltere Seiten ohne die Tabellen (Migration 015) oder ohne Leserecht darauf: es
gibt dann einfach keine Kategorien, einmal geloggt.
"""

import json
import logging

import discord
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from bot.community import db as community_db
from bot.core.guild_config import get_config, set_config

log = logging.getLogger("wikingerbot.community")

ROLES_KEY = "announce_category_roles"  # {"<Kategorie-ID>": ["<Rollen-ID>", ...]}
MAX_ROLES_PER_CATEGORY = 10
_LINKS = {
    "news": (community_db.news_categories, "news_id"),
    "event": (community_db.event_categories, "event_id"),
}
_warned = False


class CategoriesUnavailable(Exception):
    """Die Seite hat (noch) keine Kategorien-Tabellen oder der Bot darf sie nicht lesen."""


def _unavailable(error: Exception) -> CategoriesUnavailable:
    global _warned
    text = str(error).splitlines()[0][:200]
    if not _warned:
        log.warning("Kategorien der Seite nicht lesbar (Migration 015 / Datenbank-Rechte, siehe docs/community-grants.sql): %s", text)
        _warned = True
    return CategoriesUnavailable(text)


async def list_categories() -> list[dict]:
    """[{id, name}] alphabetisch. Wirft CategoriesUnavailable."""
    c = community_db.announce_categories
    try:
        async with community_db.session() as db:
            rows = (await db.execute(select(c.c.id, c.c.name).order_by(c.c.name))).all()
    except (OperationalError, ProgrammingError) as error:
        raise _unavailable(error) from None
    return [{"id": row[0], "name": row[1]} for row in rows]


async def item_category_ids(kind: str, item_id: int) -> list[int]:
    """Kategorien einer News ("news") bzw. eines Events ("event"); [] ohne Tabellen."""
    table, column = _LINKS[kind]
    try:
        async with community_db.session() as db:
            rows = (await db.execute(select(table.c.category_id).where(table.c[column] == item_id))).all()
    except (OperationalError, ProgrammingError) as error:
        _unavailable(error)
        return []
    return [row[0] for row in rows]


async def load_role_map(guild_id: int) -> dict[int, list[int]]:
    raw = await get_config(guild_id, ROLES_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    result = {}
    for category_id, role_ids in data.items() if isinstance(data, dict) else []:
        try:
            result[int(category_id)] = [int(r) for r in role_ids][:MAX_ROLES_PER_CATEGORY]
        except (TypeError, ValueError):
            continue
    return result


async def save_role_map(guild_id: int, guild_name: str, mapping: dict[int, list[int]]) -> None:
    clean = {str(cid): [str(r) for r in dict.fromkeys(roles)][:MAX_ROLES_PER_CATEGORY] for cid, roles in mapping.items() if roles}
    await set_config(guild_id, ROLES_KEY, json.dumps(clean), guild_name)


async def ping_roles(guild: discord.Guild, kind: str, item_id: int, fallback_key: str) -> list:
    """Rollen, die beim ersten Posten angepingt werden: die der Kategorien, sonst die
    allgemeine Ping-Rolle (fallback_key, z.B. "news_ping_role_id"). Geloeschte Rollen fallen weg."""
    roles = []
    category_ids = await item_category_ids(kind, item_id)
    if category_ids:
        mapping = await load_role_map(guild.id)
        for category_id in category_ids:
            for role_id in mapping.get(category_id, []):
                role = guild.get_role(role_id)
                if role is not None and role not in roles:
                    roles.append(role)
    if not roles:
        role_id = await get_config(guild.id, fallback_key)
        role = guild.get_role(int(role_id)) if role_id else None
        if role is not None:
            roles.append(role)
    return roles


def ping_message_kwargs(roles: list) -> dict:
    """content + allowed_mentions fuer channel.send - pingt genau diese Rollen."""
    return {
        "content": " ".join(role.mention for role in roles) or None,
        "allowed_mentions": discord.AllowedMentions(roles=roles or False, everyone=False, users=False),
    }


async def categories_for_ui(guild_id: int) -> dict:
    """Fuer die Tabs News/Events: Kategorien der Seite mit den zugeordneten Rollen."""
    if not community_db.enabled():
        return {"categories": [], "categories_error": None}
    try:
        categories = await list_categories()
    except CategoriesUnavailable as error:
        return {"categories": [], "categories_error": f"Kategorien nicht lesbar: {error}"}
    mapping = await load_role_map(guild_id)
    return {
        "categories": [{**c, "role_ids": [str(r) for r in mapping.get(c["id"], [])]} for c in categories],
        "categories_error": None,
    }
