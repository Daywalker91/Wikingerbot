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
from bot.cogs.whitelist.actions import grant, revoke
from bot.core import runtime
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
    status: Literal["pending", "approved", "denied", "revoked"]
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
    status: Literal["pending", "approved", "denied", "revoked"] = "pending",
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

    # wie der Knopf in Discord: AMP-Whitelist, Rolle des Servers, DM
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    lines = await grant(guild, request, server)
    return ActionResult(ok=True, message="Genehmigt. " + " · ".join(lines))


@router.post("/requests/{request_id}/revoke", response_model=ActionResult)
async def revoke_request(
    request_id: int,
    body: DenyBody,
    user: CurrentUser = Depends(require_capability("whitelist.review")),
    db: AsyncSession = Depends(get_db),
) -> ActionResult:
    """Freigabe entziehen - wie /whitelist entziehen."""
    request, server = await _get_scoped_request(db, request_id, user.guild_id)
    if request.status != WhitelistStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Nur genehmigte Anfragen lassen sich entziehen")
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    if guild is None:
        raise HTTPException(status_code=503, detail="Der Bot ist gerade nicht mit Discord verbunden.")
    _, summary = await revoke(guild, request.user_id, server, user.user_id, body.reason)
    return ActionResult(ok=True, message=summary)


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


# --- Gruppen-Rollen (Panel-Knopf mit Bestaetigung, bot/cogs/roles/requests.py) -------------


class GroupRequestOut(BaseModel):
    id: int
    user_id: Snowflake
    user_name: str | None
    role_id: Snowflake
    role_name: str
    status: Literal["pending", "approved", "denied", "revoked", "cancelled"]
    note: str | None = None
    decided_by: Snowflake | None = None
    created_at: datetime


def _guild_or_503(guild_id: int):
    guild = runtime.bot.get_guild(guild_id) if runtime.bot else None
    if guild is None:
        raise HTTPException(status_code=503, detail="Der Bot ist gerade nicht mit Discord verbunden.")
    return guild


@router.get("/groups", response_model=list[GroupRequestOut])
async def list_group_requests(
    status: Literal["pending", "approved", "denied", "revoked"] = "pending",
    user: CurrentUser = Depends(require_capability("whitelist.review")),
    db: AsyncSession = Depends(get_db),
) -> list[GroupRequestOut]:
    from db.models.panel_request import PanelRoleRequest as R

    rows = (
        await db.execute(select(R).where(R.guild_id == user.guild_id, R.status == status).order_by(R.created_at.desc()).limit(200))
    ).scalars().all()
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    out = []
    for r in rows:
        role = guild.get_role(r.role_id) if guild else None
        member = guild.get_member(r.user_id) if guild else None
        out.append(
            GroupRequestOut(
                id=r.id, user_id=r.user_id, user_name=member.display_name if member else None, role_id=r.role_id,
                role_name=role.name if role else str(r.role_id), status=r.status, note=r.note, decided_by=r.decided_by,
                created_at=r.created_at,
            )
        )
    return out


class _Moderator:
    """Wer im Web entscheidet - fuer requests.decide (braucht .id und einen Namen)."""

    def __init__(self, guild, user_id: int) -> None:
        member = guild.get_member(user_id)
        self.id, self._name = user_id, member.display_name if member else str(user_id)

    def __str__(self) -> str:
        return self._name


@router.post("/groups/{request_id}/approve", response_model=ActionResult)
async def approve_group_request(
    request_id: int, user: CurrentUser = Depends(require_capability("whitelist.review"))
) -> ActionResult:
    from bot.cogs.roles.requests import decide

    guild = _guild_or_503(user.guild_id)
    return ActionResult(ok=True, message=await decide(guild, _Moderator(guild, user.user_id), request_id, True))


@router.post("/groups/{request_id}/deny", response_model=ActionResult)
async def deny_group_request(
    request_id: int, body: DenyBody, user: CurrentUser = Depends(require_capability("whitelist.review"))
) -> ActionResult:
    from bot.cogs.roles.requests import decide

    guild = _guild_or_503(user.guild_id)
    return ActionResult(ok=True, message=await decide(guild, _Moderator(guild, user.user_id), request_id, False, body.reason or ""))


@router.post("/groups/{request_id}/revoke", response_model=ActionResult)
async def revoke_group_request(
    request_id: int,
    body: DenyBody,
    user: CurrentUser = Depends(require_capability("whitelist.review")),
    db: AsyncSession = Depends(get_db),
) -> ActionResult:
    """Gruppen-Rolle wieder wegnehmen - wie /whitelist entziehen mitglied: rolle:."""
    from bot.cogs.roles.requests import APPROVED, revoke as revoke_group
    from db.models.panel_request import PanelRoleRequest

    request = await db.get(PanelRoleRequest, request_id)
    if request is None or request.guild_id != user.guild_id:
        raise HTTPException(status_code=404, detail="Anfrage nicht gefunden")
    if request.status != APPROVED:
        raise HTTPException(status_code=409, detail="Nur angenommene Anfragen lassen sich entziehen")
    guild = _guild_or_503(user.guild_id)
    member, role = guild.get_member(request.user_id), guild.get_role(request.role_id)
    if member is None or role is None:
        raise HTTPException(status_code=409, detail="Mitglied oder Rolle gibt es nicht mehr.")
    return ActionResult(ok=True, message=await revoke_group(guild, member, role, user.user_id, body.reason))

