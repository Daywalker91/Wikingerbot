"""FastAPI-Router fuer den Events-Tab (bot/cogs/events/web/EventsPage.tsx):
Kanal, Ping-Rolle, natives Discord-Event an/aus, naechste Events mit
Discord-Stand, einzelne Events von Hand (neu) posten. Discord-IDs als Text."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.middleware.auth import CurrentUser, require_level
from api.types import Snowflake
from bot.cogs.events.posting import posted_ids, sync_event, upcoming_events
from bot.community import db as community_db
from bot.core import runtime
from bot.core.guild_config import get_config, set_config
from db.models.role import Level

router = APIRouter(prefix="/events", tags=["events"])


class EventsSettings(BaseModel):
    channel_id: Snowflake | None = None
    ping_role_id: Snowflake | None = None
    native: bool = True


@router.get("/config")
async def get_events(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    gid = user.guild_id
    channel = await get_config(gid, "events_channel_id")
    role = await get_config(gid, "events_ping_role_id")
    guild = runtime.bot.get_guild(gid) if runtime.bot else None
    data = {
        "settings": EventsSettings(
            channel_id=int(channel) if channel else None,
            ping_role_id=int(role) if role else None,
            native=await get_config(gid, "events_native", "true") == "true",
        ).model_dump(mode="json"),
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else [],
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default() and not r.managed] if guild else [],
        "can_manage_events": bool(guild and guild.me.guild_permissions.manage_events),
        "community_enabled": community_db.enabled(),
        "upcoming": [],
        "error": None,
    }
    if community_db.enabled():
        try:
            posted = await posted_ids(gid)
            data["upcoming"] = [
                {
                    "id": item.id,
                    "title": item.title,
                    "starts_at": item.starts_at.isoformat(),
                    "cancelled": item.cancelled,
                    "announce": item.announce,
                    "posted": item.id in posted,
                    "link": community_db.site_link("events.view", id=item.id),
                }
                for item in await upcoming_events(15)
            ]
        except Exception as error:
            data["error"] = f"Seite nicht erreichbar: {str(error).splitlines()[0][:200]}"
    return data


@router.put("/config")
async def put_events(body: EventsSettings, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    name = guild.name if guild else str(user.guild_id)
    await set_config(user.guild_id, "events_channel_id", str(body.channel_id) if body.channel_id else "", name)
    await set_config(user.guild_id, "events_ping_role_id", str(body.ping_role_id) if body.ping_role_id else "", name)
    await set_config(user.guild_id, "events_native", "true" if body.native else "false", name)
    return {"ok": True}


@router.post("/{event_id}/sync")
async def sync_one(event_id: int, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    """Postet/aktualisiert ein Event sofort (z.B. bestehende Events nach dem Einrichten)."""
    if runtime.bot is None or not community_db.enabled():
        raise HTTPException(503, "Nur mit laufendem Bot und angebundener Community-Seite.")
    from bot.cogs.events.cog import event_view

    try:
        done = await sync_event(runtime.bot, event_id, event_view)
    except Exception as error:
        raise HTTPException(502, f"Fehlgeschlagen: {error}") from error
    return {"done": done or ["nichts zu tun – kein Event-Kanal oder Haken „In Discord ankündigen“ aus"]}
