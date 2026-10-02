"""FastAPI-Router fuer die Begruessungs-Seite (bot/cogs/welcome/web/WelcomePage.tsx).
Discord-IDs als Text - JavaScript wuerde sie runden."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.middleware.auth import CurrentUser, require_level
from bot.cogs.welcome.cog import DEFAULT_GOODBYE, DEFAULT_WELCOME
from bot.core import runtime
from bot.core.guild_config import get_config, set_config
from db.models.role import Level

router = APIRouter(prefix="/welcome", tags=["welcome"])

ID = r"^\d{1,20}$"


class WelcomeConfig(BaseModel):
    channel_id: str | None = Field(default=None, pattern=ID)
    message: str = Field(default=DEFAULT_WELCOME, max_length=2000)
    dm_message: str = Field(default="", max_length=2000)
    goodbye_enabled: bool = False
    goodbye_message: str = Field(default=DEFAULT_GOODBYE, max_length=2000)
    goodbye_channel_id: str | None = Field(default=None, pattern=ID)


def _guild(guild_id: int):
    return runtime.bot.get_guild(guild_id) if runtime.bot else None


@router.get("")
async def get_welcome(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    gid = user.guild_id
    config = WelcomeConfig(
        channel_id=await get_config(gid, "welcome_channel_id") or None,
        message=await get_config(gid, "welcome_message", DEFAULT_WELCOME),
        dm_message=await get_config(gid, "welcome_dm_message", "") or "",
        goodbye_enabled=await get_config(gid, "goodbye_enabled", "false") == "true",
        goodbye_message=await get_config(gid, "goodbye_message", DEFAULT_GOODBYE),
        goodbye_channel_id=await get_config(gid, "goodbye_channel_id") or None,
    )
    guild = _guild(gid)
    return {
        "config": config.model_dump(),
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else [],
        "server_name": guild.name if guild else "",
        "member_count": guild.member_count if guild else 0,
    }


@router.put("")
async def put_welcome(body: WelcomeConfig, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    gid = user.guild_id
    guild = _guild(gid)
    name = guild.name if guild else str(gid)
    values = {
        "welcome_channel_id": body.channel_id or "",
        "welcome_message": body.message,
        "welcome_dm_message": body.dm_message,
        "goodbye_enabled": "true" if body.goodbye_enabled else "false",
        "goodbye_message": body.goodbye_message,
        "goodbye_channel_id": body.goodbye_channel_id or "",
    }
    for key, value in values.items():
        await set_config(gid, key, value, name)
    return {"ok": True}
