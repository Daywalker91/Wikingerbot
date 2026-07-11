"""FastAPI-Router fuer die Dashboard-Seite (bot/cogs/amp/web/DashboardPage.tsx).

Wird von api/cog_routers.py's discover_cog_routers() automatisch eingesammelt
und in api/main.py registriert - kein manuelles Eintragen noetig.
"""

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import CurrentUser, get_current_user
from bot.core.amp_client import amp_client
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
