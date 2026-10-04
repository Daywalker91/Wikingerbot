"""FastAPI-Router fuer die Whitelist-Seite (bot/cogs/whitelist/web/WhitelistPage.tsx).

Wichtige Einschraenkung: die API laeuft in einem eigenen Prozess ohne
Discord-Gateway-Verbindung. Genehmigen/Ablehnen aktualisiert deshalb nur die
DB (+ best-effort AMP-Whitelist-Aufruf) - Rollen-Vergabe, DM an den
Antragsteller und das Aktualisieren der Discord-Review-Nachricht bleiben
dem Discord-Cog vorbehalten (siehe bot/cogs/whitelist/cog.py:_resolve_request).
Wird eine Anfrage ueber die WebUI entschieden, zeigt die urspruengliche
Discord-Nachricht das nicht sofort an - klickt jemand dort trotzdem auf
Annehmen/Ablehnen, verhindert der bestehende Status-Check ein doppeltes
Verarbeiten (siehe _resolve_request: "bereits bearbeitet").
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.types import Snowflake
from api.middleware.auth import CurrentUser, require_capability, require_level
from bot.core.amp_client import amp_client
from db.models.role import Level
from db.models.server import Server
from db.models.whitelist import WhitelistRequest, WhitelistStatus
from db.session import get_db

router = APIRouter(prefix="/whitelist", tags=["whitelist"])


class WhitelistRequestOut(BaseModel):
    id: int
    user_id: Snowflake
    server_id: int
    server_name: str
    ign: str
    status: Literal["pending", "approved", "denied"]
    created_at: datetime
    handled_by: Snowflake | None = None


class DenyBody(BaseModel):
    reason: str | None = None


class ActionResult(BaseModel):
    ok: bool
    message: str


async def _get_scoped_request(
    db: AsyncSession, request_id: int, guild_id: int
) -> tuple[WhitelistRequest, Server]:
    result = await db.execute(
        select(WhitelistRequest, Server)
        .join(Server, Server.id == WhitelistRequest.server_id)
        .where(WhitelistRequest.id == request_id, Server.guild_id == guild_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Anfrage nicht gefunden")
    return row


@router.get("/requests", response_model=list[WhitelistRequestOut])
async def list_requests(
    status: Literal["pending", "approved", "denied"] = "pending",
    user: CurrentUser = Depends(require_capability("whitelist.review")),
    db: AsyncSession = Depends(get_db),
) -> list[WhitelistRequestOut]:
    result = await db.execute(
        select(WhitelistRequest, Server)
        .join(Server, Server.id == WhitelistRequest.server_id)
        .where(Server.guild_id == user.guild_id, WhitelistRequest.status == WhitelistStatus(status))
        .order_by(WhitelistRequest.created_at.desc())
    )
    return [
        WhitelistRequestOut(
            id=req.id,
            user_id=req.user_id,
            server_id=req.server_id,
            server_name=server.display_name,
            ign=req.ign,
            status=req.status.value,
            created_at=req.created_at,
            handled_by=req.handled_by,
        )
        for req, server in result.all()
    ]


@router.post("/requests/{request_id}/approve", response_model=ActionResult)
async def approve_request(
    request_id: int,
    user: CurrentUser = Depends(require_capability("whitelist.review")),
    db: AsyncSession = Depends(get_db),
) -> ActionResult:
    request, server = await _get_scoped_request(db, request_id, user.guild_id)
    if request.status != WhitelistStatus.PENDING:
        raise HTTPException(status_code=409, detail="Anfrage bereits bearbeitet")

    request.status = WhitelistStatus.APPROVED
    request.handled_by = user.user_id
    await db.commit()

    try:
        await amp_client.add_whitelist(server.amp_instance_id, request.ign)
        return ActionResult(ok=True, message="Genehmigt, AMP-Whitelist: OK")
    except Exception as exc:
        return ActionResult(ok=True, message=f"Genehmigt, AMP-Whitelist fehlgeschlagen: {exc}")


@router.post("/requests/{request_id}/deny", response_model=ActionResult)
async def deny_request(
    request_id: int,
    body: DenyBody,
    user: CurrentUser = Depends(require_capability("whitelist.review")),
    db: AsyncSession = Depends(get_db),
) -> ActionResult:
    request, _server = await _get_scoped_request(db, request_id, user.guild_id)
    if request.status != WhitelistStatus.PENDING:
        raise HTTPException(status_code=409, detail="Anfrage bereits bearbeitet")

    request.status = WhitelistStatus.DENIED
    request.handled_by = user.user_id
    await db.commit()
    return ActionResult(ok=True, message="Abgelehnt")
