"""FastAPI-Router fuer den Tab "AMP-Konten" (bot/cogs/ampkonten/web/AmpKontenPage.tsx):
oeffentliche Panel-Adresse, Rang -> AMP-Rolle, angelegte Konten. Nur Owner."""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.middleware.auth import CurrentUser, require_level
from bot.cogs.ampkonten.accounts import (
    MAP_KEY,
    REQUIRES_KEY,
    URL_KEY,
    accounts_overview,
    available_roles,
    load_map,
    load_requirement,
)
from bot.community import db as community_db
from bot.core import runtime
from bot.core.amp_client import amp_client
from bot.core.bot_settings import get_bot_setting, set_bot_setting
from bot.core.config import settings
from db.models.role import Level

router = APIRouter(prefix="/ampkonten", tags=["ampkonten"])


async def _ranks_and_names(user_ids: list[int]) -> tuple[list[dict], dict[int, str]]:
    r, u = community_db.roles, community_db.users
    rank_query = await community_db.ranks_only(select(r.c.slug, r.c.name, r.c.level).order_by(r.c.level.desc()))
    async with community_db.session() as db:
        ranks = (await db.execute(rank_query)).all()
        names = dict((await db.execute(select(u.c.id, u.c.username).where(u.c.id.in_(user_ids or [0])))).all())
    return [{"slug": s, "name": n, "level": lvl} for s, n, lvl in ranks], names


async def _extra_roles() -> list[dict]:
    if not await community_db.extras_available():
        return []
    r = community_db.roles
    async with community_db.session() as db:
        rows = (await db.execute(select(r.c.slug, r.c.name).where(r.c.kind == "extra").order_by(r.c.name))).all()
    return [{"slug": s, "name": n} for s, n in rows]


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
        "requires": await load_requirement(),
        "extra_roles": [],
        "accounts": [],
        "error": None,
    }
    accounts = await accounts_overview()
    names_by_role = {rid: name for name, rid in roles.items()}
    if community_db.enabled():
        try:
            data["ranks"], names = await _ranks_and_names([a["site_user_id"] for a in accounts])
            data["extra_roles"] = await _extra_roles()
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
    requires: str = Field(default="", max_length=32)


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
    await set_bot_setting(REQUIRES_KEY, body.requires.strip())
    return {"ok": True}


@router.post("/refresh-roles")
async def refresh_roles(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    roles, fresh = await available_roles(amp_client.core_call)
    return {
        "roles": [{"id": rid, "name": name} for name, rid in sorted(roles.items())],
        "fresh": fresh,
    }
