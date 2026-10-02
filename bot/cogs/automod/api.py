"""FastAPI-Router fuer den AutoMod-Tab (bot/cogs/automod/web/AutoModPage.tsx).

Alles zu AutoMod an einer Stelle: Warn-Punkte aus Discords eigenem AutoMod,
die eigenen Regeln, Folgen, Ausnahmen und der Alarmkanal. Discord-IDs als Text.
"""

import json
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.middleware.auth import CurrentUser, require_level
from api.types import Snowflake
from bot.cogs.automod.cog import AUTOMOD_TRIGGER_LABELS, CONFIG_KEY, automod_points
from bot.cogs.automod.rules import merged_config
from bot.core import runtime
from bot.core.guild_config import get_config, set_config
from db.models.role import Level

router = APIRouter(prefix="/automod", tags=["automod"])

DOMAIN = r"^[a-z0-9.-]{1,253}$"


class Flood(BaseModel):
    on: bool
    messages: int = Field(ge=2, le=50)
    seconds: int = Field(ge=2, le=120)


class Duplicates(BaseModel):
    on: bool
    count: int = Field(ge=2, le=20)
    seconds: int = Field(ge=5, le=600)


class Caps(BaseModel):
    on: bool
    percent: int = Field(ge=50, le=100)
    min_length: int = Field(ge=5, le=200)


class Emojis(BaseModel):
    on: bool
    max: int = Field(ge=1, le=100)


class Links(BaseModel):
    mode: Literal["off", "allowlist", "block"]
    allow: list[str] = Field(default_factory=list, max_length=200)


class Action(BaseModel):
    delete: bool
    points: int = Field(ge=0, le=10)
    timeout_minutes: int = Field(ge=0, le=1440)


class Rules(BaseModel):
    enabled: bool
    flood: Flood
    duplicates: Duplicates
    caps: Caps
    emojis: Emojis
    links: Links
    new_accounts_days: int = Field(ge=0, le=365)
    action: Action
    exempt_channels: list[Snowflake] = Field(default_factory=list)
    exempt_roles: list[Snowflake] = Field(default_factory=list)


class DiscordAutoMod(BaseModel):
    enabled: bool
    points: dict[str, int]


class AutoModConfig(BaseModel):
    discord: DiscordAutoMod
    rules: Rules
    alert_channel_id: Snowflake | None = None


def _guild(guild_id: int):
    return runtime.bot.get_guild(guild_id) if runtime.bot else None


@router.get("/config")
async def get_automod(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    gid = user.guild_id
    try:
        stored = json.loads(await get_config(gid, CONFIG_KEY, "{}") or "{}")
    except json.JSONDecodeError:
        stored = {}
    alert = await get_config(gid, "automod_alert_channel_id")
    config = AutoModConfig(
        discord=DiscordAutoMod(
            enabled=await get_config(gid, "automod_warn_enabled", "false") == "true",
            points=await automod_points(gid),
        ),
        rules=Rules(**merged_config(stored)),
        alert_channel_id=int(alert) if alert else None,
    )
    guild = _guild(gid)
    return {
        "config": config.model_dump(mode="json"),
        "trigger_labels": AUTOMOD_TRIGGER_LABELS,
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else [],
        "roles": [{"id": str(r.id), "name": r.name} for r in guild.roles if not r.is_default()] if guild else [],
        # Warn-Punkte gibt es nur mit dem moderation-Cog (Verwarnsystem)
        "moderation_loaded": bool(runtime.bot and runtime.bot.get_cog("ModerationCog")),
    }


@router.put("/config")
async def put_automod(body: AutoModConfig, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    gid = user.guild_id
    guild = _guild(gid)
    name = guild.name if guild else str(gid)
    points = {k: max(0, min(int(v), 100)) for k, v in body.discord.points.items() if k in AUTOMOD_TRIGGER_LABELS}
    rules = body.rules.model_dump()
    rules["links"]["allow"] = sorted({d.strip().lower().removeprefix("www.") for d in rules["links"]["allow"] if d.strip()})

    await set_config(gid, "automod_warn_enabled", "true" if body.discord.enabled else "false", name)
    await set_config(gid, "automod_warn_points", json.dumps(points), name)
    await set_config(gid, CONFIG_KEY, json.dumps(rules), name)
    await set_config(gid, "automod_alert_channel_id", str(body.alert_channel_id) if body.alert_channel_id else "", name)

    # Der Cog haelt die Regeln 60 s zwischengespeichert - Aenderung sofort wirksam machen
    cog = runtime.bot.get_cog("AutomodCog") if runtime.bot else None
    if cog is not None:
        cog._config_cache.pop(gid, None)
    return {"ok": True}
