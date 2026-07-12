"""FastAPI-Router fuer die Einstellungen-Seite (bot/cogs/admin/web/SettingsPage.tsx).

GuildRole-Verwaltung (Discord-Rolle -> Berechtigungslevel) hatte bisher gar
keine Bedienoberflaeche - weder Discord-Befehl noch WebUI. Die Tabelle blieb
leer, nur der Owner/Administrator-Bypass in bot/core/permissions.py hat das
bislang kompensiert (siehe has_owner_level_bypass). Diese Seite ist die erste
Moeglichkeit, GuildRole-Eintraege tatsaechlich zu pflegen.

Moderations-Konfiguration (Warn-Schwelle/-Aktion/-Timeout) liegt bewusst NICHT
hier, sondern in bot/cogs/moderation/api.py - das ist Moderations-Fachlogik
(modconfig_group-Befehle leben ebenfalls im moderation-Cog), nicht Admin.
"""

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.auth import CurrentUser, require_level
from bot.core.config import settings
from db.models.role import GuildRole, Level
from db.session import get_db

router = APIRouter(prefix="/admin", tags=["admin"])

DISCORD_API = "https://discord.com/api"


class DiscordRoleOut(BaseModel):
    id: int
    name: str


class GuildRoleOut(BaseModel):
    id: int
    discord_role_id: int
    level: Literal["member", "mod", "admin", "owner"]


class GuildRoleCreate(BaseModel):
    discord_role_id: int
    level: Literal["member", "mod", "admin", "owner"]


@router.get("/discord-roles", response_model=list[DiscordRoleOut])
async def list_discord_roles(
    user: CurrentUser = Depends(require_level(Level.OWNER)),
) -> list[DiscordRoleOut]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{DISCORD_API}/guilds/{user.guild_id}/roles",
            headers={"Authorization": f"Bot {settings.discord_token}"},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Discord-Rollen konnten nicht geladen werden")
    return [DiscordRoleOut(id=int(role["id"]), name=role["name"]) for role in response.json()]


@router.get("/roles", response_model=list[GuildRoleOut])
async def list_guild_roles(
    user: CurrentUser = Depends(require_level(Level.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> list[GuildRoleOut]:
    result = await db.execute(select(GuildRole).where(GuildRole.guild_id == user.guild_id))
    return [
        GuildRoleOut(id=role.id, discord_role_id=role.discord_role_id, level=role.level.value)
        for role in result.scalars().all()
    ]


@router.post("/roles", response_model=GuildRoleOut)
async def add_guild_role(
    body: GuildRoleCreate,
    user: CurrentUser = Depends(require_level(Level.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> GuildRoleOut:
    role = GuildRole(
        guild_id=user.guild_id, discord_role_id=body.discord_role_id, level=Level(body.level)
    )
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return GuildRoleOut(id=role.id, discord_role_id=role.discord_role_id, level=role.level.value)


@router.delete("/roles/{role_id}")
async def remove_guild_role(
    role_id: int,
    user: CurrentUser = Depends(require_level(Level.OWNER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(GuildRole).where(GuildRole.id == role_id, GuildRole.guild_id == user.guild_id)
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Rollen-Zuordnung nicht gefunden")
    await db.delete(role)
    await db.commit()
    return {"ok": True}
