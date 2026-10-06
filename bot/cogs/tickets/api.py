"""FastAPI-Router fuer den Tickets-Tab (bot/cogs/tickets/web/TicketsPage.tsx):
Staff-Kanal (Text oder Forum), Ping-Rolle, DMs an/aus, offene Tickets mit
Thread-Stand. Discord-IDs als Text."""

import json

import discord
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.middleware.auth import CurrentUser, require_level
from api.types import Snowflake
from bot.cogs.tickets.cog import ROUTES_KEY
from bot.cogs.tickets.site import CATEGORIES, STATUSES, open_tickets
from bot.community import db as community_db
from bot.core import runtime
from bot.core.guild_config import get_config, set_config
from db.models.community_post import CommunityPost
from db.models.role import Level
from db.session import get_db_session

router = APIRouter(prefix="/tickets", tags=["tickets"])


class TicketRoute(BaseModel):
    channel_id: Snowflake | None = None  # leer = Standard-Kanal
    ping_role_id: Snowflake | None = None  # leer = Standard-Ping (nur ohne eigenen Kanal)


class TicketSettings(BaseModel):
    channel_id: Snowflake | None = None
    ping_role_id: Snowflake | None = None
    dm: bool = True
    routes: dict[str, TicketRoute] = {}


@router.get("/config")
async def get_tickets(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    gid = user.guild_id
    channel = await get_config(gid, "tickets_channel_id")
    role = await get_config(gid, "tickets_ping_role_id")
    guild = runtime.bot.get_guild(gid) if runtime.bot else None
    channels = []
    if guild:
        channels = [{"id": str(c.id), "name": c.name, "forum": False} for c in guild.text_channels]
        channels += [{"id": str(c.id), "name": c.name, "forum": True} for c in guild.channels if isinstance(c, discord.ForumChannel)]
    data = {
        "settings": TicketSettings(
            channel_id=int(channel) if channel else None,
            ping_role_id=int(role) if role else None,
            dm=await get_config(gid, "tickets_dm", "true") == "true",
            routes=_load_routes(await get_config(gid, ROUTES_KEY, "{}")),
        ).model_dump(mode="json"),
        "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()],
        "channels": channels,
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default() and not r.managed] if guild else [],
        "community_enabled": community_db.enabled(),
        "open": [],
        "error": None,
    }
    if community_db.enabled():
        try:
            from sqlalchemy import select

            async with get_db_session() as db:
                with_thread = set(
                    (
                        await db.execute(
                            select(CommunityPost.item_id).where(CommunityPost.kind == "ticket", CommunityPost.guild_id == gid)
                        )
                    ).scalars()
                )
            data["open"] = [
                {
                    "id": t.id,
                    "subject": t.subject,
                    "status": STATUSES.get(t.status, STATUSES["open"])[1],
                    "author": t.author,
                    "assigned": t.assigned_name,
                    "has_thread": t.id in with_thread,
                    "link": community_db.site_link("tickets.view", id=t.id),
                }
                for t in await open_tickets(30)
            ]
        except Exception as error:
            data["error"] = f"Seite nicht erreichbar: {str(error).splitlines()[0][:200]}"
    return data


@router.put("/config")
async def put_tickets(body: TicketSettings, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    name = guild.name if guild else str(user.guild_id)
    await set_config(user.guild_id, "tickets_channel_id", str(body.channel_id) if body.channel_id else "", name)
    await set_config(user.guild_id, "tickets_ping_role_id", str(body.ping_role_id) if body.ping_role_id else "", name)
    await set_config(user.guild_id, "tickets_dm", "true" if body.dm else "false", name)
    routes = {
        key: {"channel_id": str(r.channel_id) if r.channel_id else None, "ping_role_id": str(r.ping_role_id) if r.ping_role_id else None}
        for key, r in body.routes.items()
        if key in CATEGORIES and (r.channel_id or r.ping_role_id)
    }
    await set_config(user.guild_id, ROUTES_KEY, json.dumps(routes), name)
    return {"ok": True}


def _load_routes(raw: str | None) -> dict:
    try:
        stored = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return {k: TicketRoute(**v) for k, v in stored.items() if k in CATEGORIES and isinstance(v, dict)}


@router.post("/{ticket_id}/sync")
async def sync_one(ticket_id: int, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    cog = runtime.bot.get_cog("TicketsCog") if runtime.bot else None
    if cog is None or not community_db.enabled():
        raise HTTPException(503, "Nur mit laufendem Bot, geladenem tickets-Cog und angebundener Seite.")
    try:
        done = await cog.sync_ticket(ticket_id)
    except Exception as error:
        raise HTTPException(502, f"Fehlgeschlagen: {error}") from error
    return {"done": done or ["nichts zu tun – kein Staff-Kanal eingestellt?"]}
