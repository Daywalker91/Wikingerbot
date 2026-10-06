"""FastAPI-Router fuer den Tab "Server-News": Einstellungen (Kanal, Ping, Vorlaufzeiten,
AMP-Zeitplan, Ausfaelle, Hinweis im Spiel je Server), Vorschau des AMP-Zeitplans,
angekuendigte Neustarts/Wartungen anlegen und absagen."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.middleware.auth import CurrentUser, require_capability, require_level
from api.types import Snowflake
from bot.cogs.servernews.notices import (
    Settings,
    create_notice,
    load_settings,
    local_now,
    open_notices,
    parse_leads,
    parse_start,
    save_settings,
    suggest_ingame,
    unix,
)
from bot.cogs.servernews.schedule import planned_runs
from bot.core import runtime
from bot.core.amp_client import amp_client
from bot.core.entities import ensure_guild
from db.models.role import Level
from db.models.server import Server
from db.session import get_db_session

router = APIRouter(prefix="/servernews", tags=["servernews"])


def _guild(guild_id: int):
    return runtime.bot.get_guild(guild_id) if runtime.bot else None


async def _servers(guild_id: int) -> list[Server]:
    async with get_db_session() as db:
        return list((await db.execute(select(Server).where(Server.guild_id == guild_id).order_by(Server.display_name))).scalars())


@router.get("/config")
async def get_config_(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    s = await load_settings(user.guild_id)
    guild = _guild(user.guild_id)
    return {
        "settings": {
            "channel_id": str(s.channel_id) if s.channel_id else None,
            "ping_role_id": str(s.ping_role_id) if s.ping_role_id else None,
            "leads": ", ".join(str(v) for v in s.leads),
            "amp_schedule": s.amp_schedule,
            "outages": s.outages,
        },
        "servers": [
            {
                "id": srv.id,
                "name": srv.display_name,
                "ingame": s.ingame.get(str(srv.id), ""),
                "suggestion": suggest_ingame(srv.display_name, srv.instance_name),
            }
            for srv in await _servers(user.guild_id)
        ],
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else [],
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default() and not r.managed] if guild else [],
        "cog_loaded": bool(runtime.bot and runtime.bot.get_cog("ServerNewsCog")),
    }


class SettingsIn(BaseModel):
    channel_id: Snowflake | None = None
    ping_role_id: Snowflake | None = None
    leads: str = Field("30, 10, 1", max_length=60)
    amp_schedule: bool = False
    outages: bool = True
    ingame: dict[str, str] = {}


@router.put("/config")
async def put_config_(body: SettingsIn, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = _guild(user.guild_id)
    name = guild.name if guild else str(user.guild_id)
    await ensure_guild(user.guild_id, name)
    ids = {str(srv.id) for srv in await _servers(user.guild_id)}
    await save_settings(
        user.guild_id,
        name,
        Settings(
            channel_id=body.channel_id, ping_role_id=body.ping_role_id, leads=parse_leads(body.leads),
            amp_schedule=body.amp_schedule, outages=body.outages,
            ingame={k: v for k, v in body.ingame.items() if k in ids and "{text}" in v},
        ),
    )
    return {"ok": True, "message": "Gespeichert."}


class TestIn(BaseModel):
    command: str = Field(min_length=1, max_length=200)


@router.post("/servers/{server_id}/test")
async def test_ingame(server_id: int, body: TestIn, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    """Schickt eine Testnachricht ins Spiel - im Spiel nachsehen, ob sie ankommt."""
    if "{text}" not in body.command:
        raise HTTPException(400, "Der Befehl braucht {text} als Platzhalter für die Nachricht.")
    async with get_db_session() as db:
        server = await db.get(Server, server_id)
    if server is None or server.guild_id != user.guild_id:
        raise HTTPException(404, "Server nicht gefunden.")
    try:
        await amp_client.send_console_message(server.amp_instance_id, body.command.replace("{text}", "[Server] Test vom WikingerBot"))
    except Exception as error:
        raise HTTPException(502, f"Nicht gesendet: {str(error).splitlines()[0][:200]}") from None
    return {"ok": True, "message": f"An {server.display_name} gesendet – schau im Spiel, ob „[Server] Test vom WikingerBot“ angekommen ist."}


@router.get("/amp-preview")
async def amp_preview(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    """Was der Bot aus den AMP-Zeitplaenen liest - zum Pruefen, bevor angekuendigt wird."""
    now_local = local_now()
    result = []
    for server in await _servers(user.guild_id):
        try:
            runs = await planned_runs(amp_client.instance_core_call, server.amp_instance_id, now_local)
            result.append({
                "server": server.display_name,
                "runs": [{"kind": r.kind, "label": r.label, "at": r.at.strftime("%a %d.%m. %H:%M")} for r in runs],
                "error": None,
            })
        except Exception as error:
            text = str(error).splitlines()[0][:200]
            if "Instance Unavailable" in text:
                text = "Instanz läuft nicht"
            result.append({"server": server.display_name, "runs": [], "error": text})
    return {"now": now_local.strftime("%a %d.%m. %H:%M"), "servers": result}


@router.get("/notices")
async def list_notices(user: CurrentUser = Depends(require_capability("server.control"))) -> list[dict]:
    return [
        {
            "id": n.id, "server": s.display_name, "kind": n.kind, "origin": n.origin, "status": n.status,
            "at": unix(n.at), "duration_min": n.duration_min, "reason": n.reason,
        }
        for n, s in await open_notices(user.guild_id)
    ]


class NoticeIn(BaseModel):
    server_id: int
    kind: str = Field(pattern="^(restart|maintenance)$")
    start: str = Field(min_length=1, max_length=10)  # Minuten ab jetzt oder HH:MM
    duration_min: int | None = Field(None, ge=1, le=1440)
    reason: str | None = Field(None, max_length=200)


@router.post("/notices")
async def add_notice(body: NoticeIn, user: CurrentUser = Depends(require_capability("server.control"))) -> dict:
    async with get_db_session() as db:
        server = await db.get(Server, body.server_id)
    if server is None or server.guild_id != user.guild_id:
        raise HTTPException(404, "Server nicht gefunden.")
    at = parse_start(body.start)
    if at is None:
        raise HTTPException(400, "Startzeit bitte als Minuten (z.B. 15) oder Uhrzeit (z.B. 20:00).")
    notice = await create_notice(
        user.guild_id, server.id, body.kind, at, duration_min=body.duration_min,
        reason=(body.reason or "").strip() or None, created_by=user.user_id,
    )
    return {"ok": True, "message": f"Angekündigt (Nr. {notice.id}) – die erste Meldung geht beim nächsten Takt raus (bis 30 Sekunden)."}


@router.post("/notices/{notice_id}/cancel")
async def cancel_notice(notice_id: int, user: CurrentUser = Depends(require_capability("server.control"))) -> dict:
    cog = runtime.bot.get_cog("ServerNewsCog") if runtime.bot else None
    guild = _guild(user.guild_id)
    if cog is None or guild is None:
        raise HTTPException(503, "Nur mit laufendem Bot und geladenem servernews-Cog.")
    return {"ok": True, "message": await cog.cancel(guild, notice_id)}
