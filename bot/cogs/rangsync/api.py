"""FastAPI-Router fuer den Rang-Sync-Tab (bot/cogs/rangsync/web/RangsyncPage.tsx).
Discord-IDs als Text."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import CurrentUser, require_level
from api.types import Snowflake
from bot.cogs.rangsync.sync import DIRECTIONS, load_mapping, save_mapping
from bot.community import db as community_db
from bot.community.system_tickets import default_owner_id
from bot.core import runtime
from bot.core.guild_config import get_config, set_config
from db.models.role import Level

router = APIRouter(prefix="/rangsync", tags=["rangsync"])

# Standardvorschlag fuer die mitgelieferten Raenge: Rang -> Name der Discord-Rolle
# (passt eine gleichnamige Rolle, wird sie vorbelegt)
SUGGESTED_ROLE_NAMES = {"karl": "member", "huskarl": "mod", "jarl": "admin", "konig": "owner"}


async def _staff_candidates() -> list[dict]:
    """Konten, die System-Tickets besitzen koennen (alle Rechte oder Tickets verwalten)."""
    from sqlalchemy import select

    u = community_db.users
    rows = await community_db.query_permissions(
        lambda up: select(u.c.id, u.c.username)
        .select_from(u.join(up, up.c.user_id == u.c.id))
        .where(up.c.permission.in_(["*", "ticket.manage"]), u.c.deleted_at.is_(None))
        .distinct()
        .order_by(u.c.username)
    )
    return [{"id": r[0], "name": r[1]} for r in rows]


@router.get("/config")
async def get_rangsync(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    gid = user.guild_id
    guild = runtime.bot.get_guild(gid) if runtime.bot else None
    roles = []
    if guild:
        top = guild.me.top_role.position
        roles = [
            {"id": str(r.id), "name": r.name, "above_bot": r.position >= top}
            for r in sorted(guild.roles, key=lambda r: -r.position)
            if not r.is_default() and not r.managed
        ]
    data = {
        "enabled": await get_config(gid, "rangsync_enabled", "false") == "true",
        "community_enabled": community_db.enabled(),
        "roles": roles,
        "ranks": [],
        "ticket_owner": None,
        "owners": [],
        "error": None,
    }
    if not community_db.enabled():
        return data
    try:
        ranks = await load_mapping(gid)
        by_name = {r["name"].lower(): r["id"] for r in roles}
        data["ranks"] = [
            {
                "slug": r.slug,
                "name": r.name,
                "level": r.level,
                "role_id": str(r.role_id) if r.role_id else None,
                # gleichnamige Discord-Rolle zuerst (Rang "Karl" -> @Karl), sonst die uebliche Entsprechung
                "suggested_role_id": by_name.get(r.name.lower()) or by_name.get(SUGGESTED_ROLE_NAMES.get(r.slug, "")),
                "direction": r.direction,
                "is_king": r.is_king,
            }
            for r in reversed(ranks)
        ]
        owner = await get_config(gid, "rangsync_ticket_owner")
        data["ticket_owner"] = int(owner) if owner else await default_owner_id()
        data["owners"] = await _staff_candidates()
    except Exception as error:
        data["error"] = f"Seite nicht erreichbar: {str(error).splitlines()[0][:200]}"
    return data


class RankMapping(BaseModel):
    role_id: Snowflake | None = None
    direction: str = Field(pattern="^(" + "|".join(DIRECTIONS) + ")$")


class RangsyncConfig(BaseModel):
    enabled: bool
    ranks: dict[str, RankMapping]
    ticket_owner: int | None = None


@router.put("/config")
async def put_rangsync(body: RangsyncConfig, user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    name = guild.name if guild else str(user.guild_id)
    await save_mapping(user.guild_id, name, {slug: m.model_dump() for slug, m in body.ranks.items()})
    await set_config(user.guild_id, "rangsync_enabled", "true" if body.enabled else "false", name)
    await set_config(user.guild_id, "rangsync_ticket_owner", str(body.ticket_owner) if body.ticket_owner else "", name)
    return {"ok": True}


@router.post("/sync-all")
async def sync_all(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    cog = runtime.bot.get_cog("RangsyncCog") if runtime.bot else None
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    if cog is None or guild is None or not community_db.enabled():
        raise HTTPException(503, "Nur mit laufendem Bot, geladenem rangsync-Cog und angebundener Seite.")
    if await get_config(user.guild_id, "rangsync_enabled", "false") != "true":
        raise HTTPException(400, "Erst den Rang-Sync einschalten und speichern.")
    return {"result": await cog.sync_all(guild)}
