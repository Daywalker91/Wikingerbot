"""FastAPI-Router fuer Dashboard- (bot/cogs/amp/web/DashboardPage.tsx) und
Server-Seite (bot/cogs/amp/web/ServerPage.tsx).

Wird von api/cog_routers.py's discover_cog_routers() automatisch eingesammelt
und in api/main.py registriert - kein manuelles Eintragen noetig.
"""

import asyncio
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import CurrentUser, get_current_user, require_level
from bot.cogs.amp.registry import add_server, known_instance_ids
from bot.core import runtime
from bot.core.amp_client import amp_client
from bot.core.config import settings
from bot.core.entities import ensure_guild
from bot.core.guild_config import get_config, set_config
from bot.core.server_address import GAME_HOST_KEY, connect_address, default_host, game_port, public_host, split_port
from bot.core.steam_art import parse_steam_appid
from db.models.role import Level
from db.models.server import Server
from db.session import get_db

router = APIRouter(prefix="/servers", tags=["servers"])
logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api"


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
        logger.warning("get_status fehlgeschlagen fuer %s", server.instance_name, exc_info=True)
        return ServerStatusOut(
            id=server.id,
            instance_name=server.instance_name,
            display_name=server.display_name,
            host=await connect_address(server),
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
        host=await connect_address(server),
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


class DiscoverableInstanceOut(BaseModel):
    instance_id: str
    friendly_name: str
    module: str
    running: bool
    port: int | None = None  # Spiel-Port laut AMP


class ServerCreate(BaseModel):
    instance_name: str
    amp_instance_id: str
    display_name: str
    host: str = ""  # leer = Standard-Spieladresse; ohne Port = Spiel-Port aus AMP


class AddressSettings(BaseModel):
    game_host: str = Field("", max_length=255)


@router.get("/discoverable", response_model=list[DiscoverableInstanceOut])
async def list_discoverable_instances(
    user: CurrentUser = Depends(require_level(Level.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> list[DiscoverableInstanceOut]:
    """AMP-Instanzen, die noch nicht als Server angelegt sind - Pendant zu
    /server discover (bot/cogs/amp/cog.py:server_discover)."""
    instances = await amp_client.list_instances()
    known_ids = await known_instance_ids(_active_guild_ids())
    return [
        DiscoverableInstanceOut(
            instance_id=i.instance_id,
            friendly_name=i.friendly_name,
            module=i.module,
            running=i.running,
            port=game_port(i.endpoints),
        )
        for i in instances
        if i.instance_id not in known_ids
    ]


@router.get("/address-settings")
async def get_address_settings(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    """Standard-Spieladresse (Host ohne Port) fuer Server ohne eigene Adresse."""
    return {
        "game_host": await get_config(user.guild_id, GAME_HOST_KEY) or "",
        "effective_host": await default_host(user.guild_id),
        "public_host": public_host(),
    }


@router.put("/address-settings")
async def put_address_settings(body: AddressSettings, user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    host = split_port(body.game_host.strip().removeprefix("https://").removeprefix("http://").rstrip("/"))[0]
    await _ensure_guild_from_discord(user.guild_id)
    await set_config(user.guild_id, GAME_HOST_KEY, host)
    return {"ok": True, "game_host": host}


def _active_guild_ids() -> set[int] | None:
    """Discord-Server, auf denen der Bot gerade ist (None, wenn der Bot nicht laeuft)."""
    return {g.id for g in runtime.bot.guilds} if runtime.bot is not None else None


async def _ensure_guild_from_discord(guild_id: int) -> None:
    """Legt die Guild-Zeile an, falls noch nicht vorhanden - anders als die
    Discord-Cogs (interaction.guild.name direkt verfuegbar) muss der Name hier
    per REST mit dem Bot-Token nachgeladen werden (gleiche Technik wie
    bot/core/permissions.py's has_owner_level_bypass)."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API}/guilds/{guild_id}", headers={"Authorization": f"Bot {settings.discord_token}"}
        )
        response.raise_for_status()
    await ensure_guild(guild_id, response.json()["name"])


@router.post("", response_model=ServerStatusOut)
async def create_server(
    body: ServerCreate,
    user: CurrentUser = Depends(require_level(Level.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> ServerStatusOut:
    await _ensure_guild_from_discord(user.guild_id)

    # Uebernimmt AMPs DisplayImageSource ("steam:<appid>") automatisch als
    # steam_app_id, falls vorhanden - gleiche Logik wie /server add
    # (bot/cogs/amp/cog.py:server_add), treibt spaeter den Banner-Cog.
    steam_app_id = None
    instances = await amp_client.list_instances()
    for instance in instances:
        if instance.instance_id == body.amp_instance_id:
            steam_app_id = parse_steam_appid(instance.display_image_source)
            break

    result = await add_server(
        _active_guild_ids(),
        user.guild_id,
        name=body.instance_name,
        amp_instance_id=body.amp_instance_id,
        display_name=body.display_name,
        host=body.host,
        steam_app_id=steam_app_id,
    )
    if not result.ok:
        raise HTTPException(409, result.message)
    server = await db.get(Server, result.server_id)
    return await _status_for(server)


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
