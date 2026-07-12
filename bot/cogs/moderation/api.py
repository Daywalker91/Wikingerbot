"""FastAPI-Router fuer die Moderation-Seite (bot/cogs/moderation/web/ModerationPage.tsx).

Zeigt die ModLog-/Warnungs-Historie Guild-weit an - im Gegensatz zu den
Discord-Commands /modlog und /warnings, die je einen einzelnen Nutzer
abfragen (dort per Autocomplete komfortabel waehlbar, hier auf einer
Uebersichtsseite ist eine Guild-weite Liste sinnvoller).

Unban/Ban laufen hier direkt per Discord-REST-Call mit dem Bot-Token, da der
API-Prozess keine Gateway-Verbindung (kein guild.unban()/guild.ban()) hat -
dieselbe Bot-Token-REST-Technik wie bot/core/permissions.py's
has_owner_level_bypass.

Mod-Konfiguration (Warn-Schwelle/-Aktion/-Timeout) liegt bewusst hier statt im
admin-Cog - das ist Moderations-Fachlogik, die Discord-seitigen
modconfig_group-Befehle leben ebenfalls in bot/cogs/moderation/cog.py.
"""

from datetime import datetime
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import CurrentUser, require_level
from bot.core.config import settings
from bot.core.guild_config import get_config, set_config
from db.models.modlog import ModAction, ModLogEntry, Warning
from db.models.role import Level
from db.session import get_db

router = APIRouter(prefix="/moderation", tags=["moderation"])

DISCORD_API = "https://discord.com/api"


class ModLogEntryOut(BaseModel):
    id: int
    user_id: int
    mod_id: int
    action: str
    reason: str | None
    duration: int | None
    created_at: datetime


class WarningOut(BaseModel):
    id: int
    user_id: int
    mod_id: int
    reason: str | None
    points: int
    created_at: datetime


class UnbanBody(BaseModel):
    user_id: int
    reason: str


class BanBody(BaseModel):
    user_id: int
    reason: str
    delete_message_days: int = 0


class ActionResult(BaseModel):
    ok: bool
    message: str


class ModConfigOut(BaseModel):
    warn_threshold: int
    warn_action: Literal["timeout", "ban", "kick"]
    warn_timeout_minutes: int


class MemberSearchResult(BaseModel):
    id: int
    username: str
    display_name: str


@router.get("/mod-config", response_model=ModConfigOut)
async def get_mod_config(user: CurrentUser = Depends(require_level(Level.OWNER))) -> ModConfigOut:
    return ModConfigOut(
        warn_threshold=int(await get_config(user.guild_id, "warn_threshold", "3")),
        warn_action=await get_config(user.guild_id, "warn_action", "timeout"),
        warn_timeout_minutes=int(await get_config(user.guild_id, "warn_timeout_minutes", "60")),
    )


@router.put("/mod-config", response_model=ModConfigOut)
async def update_mod_config(
    body: ModConfigOut, user: CurrentUser = Depends(require_level(Level.OWNER))
) -> ModConfigOut:
    await set_config(user.guild_id, "warn_threshold", str(body.warn_threshold))
    await set_config(user.guild_id, "warn_action", body.warn_action)
    await set_config(user.guild_id, "warn_timeout_minutes", str(body.warn_timeout_minutes))
    return body


@router.get("/member-search", response_model=list[MemberSearchResult])
async def search_members(
    query: str,
    user: CurrentUser = Depends(require_level(Level.MOD)),
) -> list[MemberSearchResult]:
    """Autocomplete-Unterstuetzung fuers Ban/Unban-Formular (ModerationPage.tsx) -
    Suche per Name ODER direkt eingetippter ID soll beides funktionieren."""
    if not query:
        return []
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API}/guilds/{user.guild_id}/members/search",
            headers={"Authorization": f"Bot {settings.discord_token}"},
            params={"query": query, "limit": 10},
        )
    if response.status_code != 200:
        return []

    results = []
    for member in response.json():
        discord_user = member["user"]
        display_name = member.get("nick") or discord_user.get("global_name") or discord_user["username"]
        results.append(
            MemberSearchResult(
                id=int(discord_user["id"]), username=discord_user["username"], display_name=display_name
            )
        )
    return results


@router.get("/modlog", response_model=list[ModLogEntryOut])
async def list_modlog(
    limit: int = 50,
    user: CurrentUser = Depends(require_level(Level.MOD)),
    db: AsyncSession = Depends(get_db),
) -> list[ModLogEntryOut]:
    result = await db.execute(
        select(ModLogEntry)
        .where(ModLogEntry.guild_id == user.guild_id)
        .order_by(ModLogEntry.created_at.desc())
        .limit(limit)
    )
    return [
        ModLogEntryOut(
            id=entry.id,
            user_id=entry.user_id,
            mod_id=entry.mod_id,
            action=entry.action.value,
            reason=entry.reason,
            duration=entry.duration,
            created_at=entry.created_at,
        )
        for entry in result.scalars().all()
    ]


@router.get("/warnings", response_model=list[WarningOut])
async def list_warnings(
    active_only: bool = True,
    user: CurrentUser = Depends(require_level(Level.MOD)),
    db: AsyncSession = Depends(get_db),
) -> list[WarningOut]:
    query = select(Warning).where(Warning.guild_id == user.guild_id)
    if active_only:
        query = query.where(Warning.expired.is_(False))
    result = await db.execute(query.order_by(Warning.created_at.desc()))
    return [
        WarningOut(
            id=warning.id,
            user_id=warning.user_id,
            mod_id=warning.mod_id,
            reason=warning.reason,
            points=warning.points,
            created_at=warning.created_at,
        )
        for warning in result.scalars().all()
    ]


@router.post("/ban", response_model=ActionResult)
async def ban(
    body: BanBody,
    user: CurrentUser = Depends(require_level(Level.MOD)),
    db: AsyncSession = Depends(get_db),
) -> ActionResult:
    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{DISCORD_API}/guilds/{user.guild_id}/bans/{body.user_id}",
            headers={
                "Authorization": f"Bot {settings.discord_token}",
                "X-Audit-Log-Reason": quote(body.reason),
            },
            json={"delete_message_seconds": body.delete_message_days * 86400},
        )
    if response.status_code != 204:
        raise HTTPException(status_code=502, detail="Discord-Bann fehlgeschlagen")

    db.add(
        ModLogEntry(
            guild_id=user.guild_id,
            user_id=body.user_id,
            mod_id=user.user_id,
            action=ModAction.BAN,
            reason=body.reason,
        )
    )
    await db.commit()
    return ActionResult(ok=True, message="Gebannt")


@router.post("/unban", response_model=ActionResult)
async def unban(
    body: UnbanBody,
    user: CurrentUser = Depends(require_level(Level.MOD)),
    db: AsyncSession = Depends(get_db),
) -> ActionResult:
    async with httpx.AsyncClient() as client:
        response = await client.delete(
            f"{DISCORD_API}/guilds/{user.guild_id}/bans/{body.user_id}",
            headers={
                "Authorization": f"Bot {settings.discord_token}",
                "X-Audit-Log-Reason": quote(body.reason),
            },
        )
    if response.status_code not in (204, 404):
        raise HTTPException(status_code=502, detail="Discord-Unban fehlgeschlagen")

    db.add(
        ModLogEntry(
            guild_id=user.guild_id,
            user_id=body.user_id,
            mod_id=user.user_id,
            action=ModAction.UNBAN,
            reason=body.reason,
        )
    )
    await db.commit()
    return ActionResult(ok=True, message="Bann aufgehoben")
