"""FastAPI-Router fuer Dashboard- (bot/cogs/amp/web/DashboardPage.tsx) und
Server-Seite (bot/cogs/amp/web/ServerPage.tsx).

Wird von api/cog_routers.py's discover_cog_routers() automatisch eingesammelt
und in api/main.py registriert - kein manuelles Eintragen noetig.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import CurrentUser, get_current_user, require_level
from bot.core.amp_client import amp_client
from db.models.role import Level
from db.models.server import Server
from db.session import get_db

router = APIRouter(prefix="/servers", tags=["servers"])


class ServerStatusOut(BaseModel):
    id: int
    instance_name: str
    display_name: str
    host: str
    reachable: bool
    state: str | None = None
    uptime: str | None = None
    players: tuple[int, int] | None = None


async def _status_for(server: Server) -> ServerStatusOut:
    try:
        status = await amp_client.get_status(server.amp_instance_id)
    except Exception:
        return ServerStatusOut(
            id=server.id,
            instance_name=server.instance_name,
            display_name=server.display_name,
            host=server.host,
            reachable=False,
        )

    # Gleiche Feld-Extraktion wie bot/cogs/banner/image.py:extract_players und
    # der amp-Cog (/server status) - bewusst hier dupliziert statt cross-cog
    # importiert, passend zum bestehenden Muster kleiner, pro Verwender
    # duplizierter Helfer (z.B. _autocomplete_instance_name).
    metric = status.Metrics.get("Active Users") if status.Metrics else None
    players = (metric.RawValue, metric.MaxValue) if metric else None

    return ServerStatusOut(
        id=server.id,
        instance_name=server.instance_name,
        display_name=server.display_name,
        host=server.host,
        reachable=True,
        state=status.State.name,
        uptime=status.Uptime,
        players=players,
    )


@router.get("", response_model=list[ServerStatusOut])
async def list_servers(
    user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ServerStatusOut]:
    result = await db.execute(
        select(Server).where(Server.guild_id == user.guild_id, Server.hidden.is_(False))
    )
    servers = result.scalars().all()
    return list(await asyncio.gather(*(_status_for(s) for s in servers)))


class ServerActionResult(BaseModel):
    ok: bool
    message: str


class ConsoleCommandBody(BaseModel):
    command: str


class ConsoleLineOut(BaseModel):
    contents: str
    source: str
    type: str


async def _get_scoped_server(db: AsyncSession, server_id: int, guild_id: int) -> Server:
    result = await db.execute(
        select(Server).where(Server.id == server_id, Server.guild_id == guild_id)
    )
    server = result.scalar_one_or_none()
    if server is None:
        raise HTTPException(status_code=404, detail="Server nicht gefunden")
    return server


@router.post("/{server_id}/start", response_model=ServerActionResult)
async def start_server(
    server_id: int,
    user: CurrentUser = Depends(require_level(Level.MOD)),
    db: AsyncSession = Depends(get_db),
) -> ServerActionResult:
    server = await _get_scoped_server(db, server_id, user.guild_id)
    try:
        await amp_client.start(server.amp_instance_id)
    except Exception as exc:
        return ServerActionResult(ok=False, message=f"Start fehlgeschlagen: {exc}")
    return ServerActionResult(ok=True, message=f"Starte {server.display_name} ...")


@router.post("/{server_id}/stop", response_model=ServerActionResult)
async def stop_server(
    server_id: int,
    user: CurrentUser = Depends(require_level(Level.MOD)),
    db: AsyncSession = Depends(get_db),
) -> ServerActionResult:
    server = await _get_scoped_server(db, server_id, user.guild_id)
    try:
        await amp_client.stop(server.amp_instance_id)
    except Exception as exc:
        return ServerActionResult(ok=False, message=f"Stop fehlgeschlagen: {exc}")
    return ServerActionResult(ok=True, message=f"Stoppe {server.display_name} ...")


@router.get("/{server_id}/console", response_model=list[ConsoleLineOut])
async def get_console(
    server_id: int,
    user: CurrentUser = Depends(require_level(Level.MOD)),
    db: AsyncSession = Depends(get_db),
) -> list[ConsoleLineOut]:
    """Liefert neue Konsolenzeilen seit dem letzten Poll dieser AMP-Instanz-Session.

    Achtung: dieselbe Pro-Instanz-Session wird auch vom Discord-seitigen
    console_bridge-Task (bot/cogs/amp/cog.py) alle 2s abgefragt - beide
    Verbraucher teilen sich denselben "seit dem letzten Aufruf"-Zustand bei
    AMP, Zeilen werden also zwischen Discord-Kanal und dieser Seite aufgeteilt
    statt dupliziert. Fuer den beabsichtigten Zweck (kurzer Blick/Befehle
    schicken, ohne Discord zu oeffnen) akzeptabel.
    """
    server = await _get_scoped_server(db, server_id, user.guild_id)
    try:
        lines = await amp_client.poll_console(server.amp_instance_id)
    except Exception:
        return []
    return [ConsoleLineOut(contents=line.contents, source=line.source, type=line.type) for line in lines]


@router.post("/{server_id}/console", response_model=ServerActionResult)
async def send_console_command(
    server_id: int,
    body: ConsoleCommandBody,
    user: CurrentUser = Depends(require_level(Level.MOD)),
    db: AsyncSession = Depends(get_db),
) -> ServerActionResult:
    server = await _get_scoped_server(db, server_id, user.guild_id)
    try:
        await amp_client.send_console_message(server.amp_instance_id, body.command)
    except Exception as exc:
        return ServerActionResult(ok=False, message=f"Befehl fehlgeschlagen: {exc}")
    return ServerActionResult(ok=True, message="Befehl gesendet")
