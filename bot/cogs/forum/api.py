"""FastAPI-Router fuer den Tab "Forum" (bot/cogs/forum/web/ForumPage.tsx): Kanal und
Ping-Rolle fuer Ankuendigungen neuer Forum-Themen, die neuesten oeffentlichen Themen mit
Discord-Stand, einzelne Themen von Hand ankuendigen."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.middleware.auth import CurrentUser, require_level
from api.types import Snowflake
from bot.cogs.forum.posting import KIND, announce_thread, recent_threads
from bot.community import db as community_db
from bot.core import runtime
from bot.core.guild_config import get_config, set_config
from db.models.community_post import CommunityPost
from db.models.role import Level
from db.session import get_db_session

router = APIRouter(prefix="/forum", tags=["forum"])


class ForumSettings(BaseModel):
    channel_id: Snowflake | None = None
    ping_role_id: Snowflake | None = None


@router.get("/config")
async def get_forum(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    gid = user.guild_id
    channel = await get_config(gid, "forum_channel_id")
    role = await get_config(gid, "forum_ping_role_id")
    guild = runtime.bot.get_guild(gid) if runtime.bot else None
    data = {
        "settings": ForumSettings(channel_id=int(channel) if channel else None, ping_role_id=int(role) if role else None).model_dump(mode="json"),
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else [],
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default() and not r.managed] if guild else [],
        "community_enabled": community_db.enabled(),
        "cog_loaded": bool(runtime.bot and runtime.bot.get_cog("ForumCog")),
        "recent": [],
        "error": None,
    }
    if community_db.enabled():
        try:
            async with get_db_session() as db:
                posted = set(
                    (await db.execute(select(CommunityPost.item_id).where(CommunityPost.kind == KIND, CommunityPost.guild_id == gid))).scalars()
                )
            data["recent"] = [
                {
                    "id": t.id,
                    "title": t.title,
                    "category": t.category,
                    "author": t.author,
                    "posted": t.id in posted,
                    "link": community_db.site_link("forum.thread", id=t.id),
                }
                for t in await recent_threads(10)
            ]
        except Exception as error:  # z.B. Recht auf die Forum-Tabellen fehlt
            data["error"] = f"Forum der Seite nicht lesbar: {str(error).splitlines()[0][:200]}"
    return data


@router.put("/config")
async def put_forum(body: ForumSettings, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    name = guild.name if guild else str(user.guild_id)
    await set_config(user.guild_id, "forum_channel_id", str(body.channel_id) if body.channel_id else "", name)
    await set_config(user.guild_id, "forum_ping_role_id", str(body.ping_role_id) if body.ping_role_id else "", name)
    return {"ok": True}


@router.post("/{thread_id}/announce")
async def announce_one(thread_id: int, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    if not runtime.bot or not community_db.enabled():
        raise HTTPException(503, "Nur mit laufendem Bot und angebundener Seite.")
    try:
        done = await announce_thread(runtime.bot, thread_id)
    except Exception as error:
        raise HTTPException(502, f"Fehlgeschlagen: {error}") from error
    return {"done": done or ["nichts zu tun – schon angekündigt, nicht öffentlich oder kein Kanal eingestellt"]}
