"""FastAPI-Router fuer den Tab "AMP-Konten" (bot/cogs/ampkonten/web/AmpKontenPage.tsx):
oeffentliche Panel-Adresse, Rang -> AMP-Rolle, angelegte Konten. Nur Owner."""

import json
from dataclasses import asdict

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
from bot.cogs.ampkonten import role_setup
from bot.cogs.ampkonten.role_setup import CAPABILITIES, TIERS
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


DONE_KEY = "ampkonten_roles_done"  # Instanz-ID -> Rechte-Stand (role_setup.PLAN_VERSION), mit dem eingerichtet wurde


async def _game_instances(guild_id: int) -> dict[str, str]:
    """Spiel-Instanzen dieses Discord-Servers (Tab Server): Instanz-ID -> Anzeigename."""
    from sqlalchemy import select as sa_select

    from db.models.server import Server
    from db.session import get_db_session

    async with get_db_session() as db:
        rows = (await db.execute(sa_select(Server.amp_instance_id, Server.display_name).where(Server.guild_id == guild_id))).all()
    return {iid: name for iid, name in rows}


async def _done() -> dict[str, int]:
    """Eingerichtete Instanzen mit ihrem Rechte-Stand (aeltere Bot-Versionen: nur eine Liste = Stand 1)."""
    try:
        data = json.loads(await get_bot_setting(DONE_KEY, "{}") or "{}")
    except json.JSONDecodeError:
        return {}
    if isinstance(data, list):
        return {iid: 1 for iid in data}
    return {str(iid): int(v) for iid, v in data.items()} if isinstance(data, dict) else {}


async def _up_to_date() -> set[str]:
    return {iid for iid, version in (await _done()).items() if version >= role_setup.PLAN_VERSION}


@router.get("/roles/status")
async def roles_status(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    instances = await _game_instances(user.guild_id)
    known = await _done()
    done = await _up_to_date()
    return {
        "tiers": [
            {
                "key": t.key,
                "name": t.name,
                "caps": [CAPABILITIES[c][0] for c in t.caps]
                + (["Instanzen anlegen, löschen und umbauen"] if t.key == "admin" else []),
            }
            for t in TIERS
        ],
        "pending": sorted(name for iid, name in instances.items() if iid not in known),
        "outdated": sorted(name for iid, name in instances.items() if iid in known and iid not in done),
        "done": sorted(name for iid, name in instances.items() if iid in done),
    }


class AdminLogin(BaseModel):
    """Optional: Zugangsdaten eines AMP-Super-Admins, nur fuer diesen einen Vorgang.
    Werden weder gespeichert noch geloggt."""

    username: str = Field(default="", max_length=100)
    password: str = Field(default="", max_length=200)
    token: str = Field(default="", max_length=20)  # Zwei-Faktor-Code, falls aktiv


async def _run_setup(guild_id: int, apply: bool, login: AdminLogin | None, redo: bool = False) -> dict:
    instances = await _game_instances(guild_id)
    if not instances:
        raise HTTPException(400, "Noch keine Gameserver angelegt (Tab Server).")
    # schon eingerichtete Instanzen auslassen - ausser ausdruecklich "alle erneut"
    only = None if redo else set(instances) - await _up_to_date()
    # frische Anmeldung: mit Admin-Zugangsdaten oder als Bot (gerade vergebene Super Admins gelten sofort)
    login = login or AdminLogin()
    controller_call, instance_call = amp_client.fresh_calls(login.username.strip(), login.password, login.token.strip())
    try:
        try:
            controller_ids = tuple(await amp_client.controller_instance_ids())
        except Exception:
            controller_ids = ()
        report = await role_setup.run(
            controller_call, instance_call, instances, apply=apply, controller_ids=controller_ids, only=only
        )
    except Exception as error:  # z.B. Anmeldung abgelehnt - ohne die Zugangsdaten zu nennen
        raise HTTPException(400, "Anmeldung bei AMP fehlgeschlagen – Benutzername, Passwort oder Zwei-Faktor-Code prüfen.") from None
    finally:
        login.password = ""
    if apply:
        ok = [iid for iid, name in instances.items() if name in report.instances and not report.instances[name].get("error")
              and not any(isinstance(v, dict) and v.get("error") for v in report.instances.get(name, {}).values())]
        if not report.errors:
            done = await _done()
            done.update({iid: role_setup.PLAN_VERSION for iid in ok})
            await set_bot_setting(DONE_KEY, json.dumps(dict(sorted(done.items()))))
        await available_roles(controller_call)  # neue Rollen gleich in die Auswahl
    return asdict(report)


@router.post("/roles/check")
async def roles_check(
    login: AdminLogin | None = None, redo: bool = False, user: CurrentUser = Depends(require_level(Level.OWNER))
) -> dict:
    """Zeigt, welche Rechte gesetzt wuerden - aendert nichts."""
    return await _run_setup(user.guild_id, apply=False, login=login, redo=redo)


@router.post("/roles/apply")
async def roles_apply(
    login: AdminLogin | None = None, redo: bool = False, user: CurrentUser = Depends(require_level(Level.OWNER))
) -> dict:
    """Legt die Gameserver-Rollen an und setzt die Rechte - mit den Zugangsdaten eines
    AMP-Super-Admins (einmalig) oder wenn der Bot-Benutzer gerade Super Admins hat."""
    return await _run_setup(user.guild_id, apply=True, login=login, redo=redo)


@router.post("/refresh-roles")
async def refresh_roles(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    roles, fresh = await available_roles(amp_client.core_call)
    return {
        "roles": [{"id": rid, "name": name} for name, rid in sorted(roles.items())],
        "fresh": fresh,
    }
