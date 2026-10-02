"""FastAPI-Router fuer den News-Tab (bot/cogs/news/web/NewsPage.tsx):
Kanal und Ping-Rolle einstellen, neueste News der Seite mit Discord-Stand,
einzelne News von Hand (neu) posten. Discord-IDs als Text."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.middleware.auth import CurrentUser, require_level
from api.types import Snowflake
from bot.cogs.news.posting import posted_ids, recent_news, sync_news
from bot.community import db as community_db
from bot.core import runtime
from bot.core.guild_config import get_config, set_config
from db.models.role import Level

router = APIRouter(prefix="/news", tags=["news"])


class NewsSettings(BaseModel):
    channel_id: Snowflake | None = None
    ping_role_id: Snowflake | None = None


@router.get("/config")
async def get_news(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    gid = user.guild_id
    channel = await get_config(gid, "news_channel_id")
    role = await get_config(gid, "news_ping_role_id")
    guild = runtime.bot.get_guild(gid) if runtime.bot else None
    data = {
        "settings": NewsSettings(channel_id=int(channel) if channel else None, ping_role_id=int(role) if role else None).model_dump(mode="json"),
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else [],
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default() and not r.managed] if guild else [],
        "community_enabled": community_db.enabled(),
        "news_loaded": bool(runtime.bot and runtime.bot.get_cog("NewsCog")),
        "recent": [],
        "error": None,
    }
    if community_db.enabled():
        try:
            posted = await posted_ids(gid)
            data["recent"] = [
                {
                    "id": item.id,
                    "title": item.title,
                    "published": item.is_published,
                    "announce": item.announce,
                    "posted": item.id in posted,
                    "link": community_db.site_link("news.view", id=item.id),
                }
                for item in await recent_news(15)
            ]
        except Exception as error:
            data["error"] = f"Seite nicht erreichbar: {str(error).splitlines()[0][:200]}"
    return data


@router.put("/config")
async def put_news(body: NewsSettings, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    name = guild.name if guild else str(user.guild_id)
    await set_config(user.guild_id, "news_channel_id", str(body.channel_id) if body.channel_id else "", name)
    await set_config(user.guild_id, "news_ping_role_id", str(body.ping_role_id) if body.ping_role_id else "", name)
    return {"ok": True}


@router.post("/{news_id}/sync")
async def sync_one(news_id: int, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    """Postet/aktualisiert eine News sofort (z.B. aeltere News nach dem Einrichten des Kanals)."""
    if runtime.bot is None or not community_db.enabled():
        raise HTTPException(503, "Nur mit laufendem Bot und angebundener Community-Seite.")
    try:
        done = await sync_news(runtime.bot, news_id)
    except Exception as error:
        raise HTTPException(502, f"Fehlgeschlagen: {error}") from error
    return {"done": done or ["nichts zu tun – kein News-Kanal, Entwurf oder Haken „In Discord ankündigen“ aus"]}

