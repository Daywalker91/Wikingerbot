"""FastAPI-Router fuer den Tab "AMP-Konten" (bot/cogs/ampkonten/web/AmpKontenPage.tsx):
oeffentliche Panel-Adresse, Rang -> AMP-Rolle, angelegte Konten. Nur Owner."""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.middleware.auth import CurrentUser, require_level
from bot.cogs.ampkonten.accounts import MAP_KEY, URL_KEY, accounts_overview, available_roles, load_map
from bot.community import db as community_db
from bot.core import runtime
from bot.core.amp_client import amp_client
from bot.core.bot_settings import get_bot_setting, set_bot_setting
from bot.core.config import settings
from db.models.role import Level

router = APIRouter(prefix="/ampkonten", tags=["ampkonten"])


async def _ranks_and_names(user_ids: list[int]) -> tuple[list[dict], dict[int, str]]:
    r, u = community_db.roles, community_db.users
    async with community_db.session() as db:
        ranks = (await db.execute(select(r.c.slug, r.c.name, r.c.level).order_by(r.c.level.desc()))).all()
        names = dict((await db.execute(select(u.c.id, u.c.username).where(u.c.id.in_(user_ids or [0])))).all())
    return [{"slug": s, "name": n, "level": lvl} for s, n, lvl in ranks], names


@router.get("/config")
async def get_config(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    roles, fresh = await available_roles(None)
    data = {
        "url": await get_bot_setting(URL_KEY, "") or "",
        "map": await load_map(),
        "roles": [{"id": rid, "name": name} for name, rid in sorted(roles.items())],
        "roles_fresh": fresh,
        "amp_configured": bool(settings.amp_user),
        "loaded": bool(runtime.bot and runtime.bot.get_cog("AmpKontenCog")),
        "community_enabled": community_db.enabled(),
        "ranks": [],
        "accounts": [],
        "error": None,
    }
    accounts = await accounts_overview()
    names_by_role = {rid: name for name, rid in roles.items()}
    if community_db.enabled():
        try:
            data["ranks"], names = await _ranks_and_names([a["site_user_id"] for a in accounts])
        except Exception as error:
            names = {}
            data["error"] = f"Seite nicht erreichbar: {str(error).splitlines()[0][:200]}"
    else:
        names = {}
    data["accounts"] = [
        {
            "member": names.get(a["site_user_id"], f"#{a['site_user_id']}"),
            "amp_username": a["amp_username"],
            "disabled": a["disabled"],
            "roles": [names_by_role.get(r, r) for r in a["role_ids"]],
        }
        for a in accounts
    ]
    return data


class AmpKontenConfig(BaseModel):
    url: str = Field(default="", max_length=200, pattern=r"^(https?://\S+)?$")
    map: dict[str, str | None] = {}


@router.put("/config")
async def put_config(body: AmpKontenConfig, user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    roles, _ = await available_roles(None)
    allowed = set(roles.values())
    clean = {slug: rid for slug, rid in body.map.items() if rid}
    bad = [rid for rid in clean.values() if rid not in allowed]
    if bad:
        raise HTTPException(400, "Unbekannte oder gesperrte AMP-Rolle (Super Admins und die Bot-Rolle gehen nie).")
    await set_bot_setting(URL_KEY, body.url.rstrip("/"))
    await set_bot_setting(MAP_KEY, json.dumps(clean))
    return {"ok": True}


@router.post("/refresh-roles")
async def refresh_roles(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    roles, fresh = await available_roles(amp_client.core_call)
    return {
        "roles": [{"id": rid, "name": name} for name, rid in sorted(roles.items())],
        "fresh": fresh,
    }
