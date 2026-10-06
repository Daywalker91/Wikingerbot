"""FastAPI-Router fuer den Rollen-Tab (bot/cogs/roles/web/RolesPage.tsx):
Autoroles und Selbstwahl-Panels. Dasselbe wie /rollen in Discord. Die Panels
liest der Bot direkt aus den Nachrichten (die Nachricht ist der Speicher),
welche Nachrichten Panels sind, steht in guild_config "role_panels".
Discord-IDs als Text."""

import discord
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import CurrentUser, require_level
from api.types import Snowflake
from bot.cogs.roles.cog import (
    MAX_BUTTONS,
    RoleToggleButton,
    build_view,
    forget_panel,
    get_autoroles,
    get_panels,
    panel_buttons,
    panel_embed,
    parse_message_ref,
    rank_role_ids,
    remember_panel,
    role_block_reason,
    set_autoroles,
)
from bot.core import runtime
from bot.core.whitelist_gate import gated_reason, gated_roles
from db.models.role import Level

router = APIRouter(prefix="/roles", tags=["roles"])


def _guild(guild_id: int) -> discord.Guild:
    guild = runtime.bot.get_guild(guild_id) if runtime.bot else None
    if guild is None:
        raise HTTPException(503, "Der Bot ist gerade nicht mit Discord verbunden.")
    return guild


async def _blocked(guild: discord.Guild) -> dict[int, str | None]:
    ranks = await rank_role_ids(guild.id)
    top = guild.me.top_role.position
    gated = await gated_roles(guild.id)
    return {
        r.id: role_block_reason(r, top, ranks) or (gated_reason(r.name, gated[r.id]) if r.id in gated else None)
        for r in guild.roles
    }


async def _read_panel(guild: discord.Guild, channel_id: int, message_id: int) -> dict:
    channel = guild.get_channel(channel_id)
    base = {"channel_id": str(channel_id), "message_id": str(message_id), "channel_name": channel.name if channel else None}
    try:
        message = await channel.fetch_message(message_id)
    except (discord.HTTPException, AttributeError):
        return {**base, "missing": True, "url": None, "title": "", "text": "", "buttons": []}
    embed = message.embeds[0] if message.embeds else None
    return {
        **base,
        "missing": False,
        "url": message.jump_url,
        "title": (embed.title or "") if embed else "",
        "text": (embed.description or "") if embed else "",
        "buttons": [
            {
                "role_id": str(b.role_id),
                "label": b.item.label or "",
                "emoji": str(b.item.emoji) if b.item.emoji else "",
                "confirm": b.confirm,
            }
            for b in panel_buttons(message)
        ],
    }


@router.get("/config")
async def get_roles(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = _guild(user.guild_id)
    blocked = await _blocked(guild)
    return {
        "cog_loaded": runtime.bot.get_cog("RolesCog") is not None,
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels],
        "roles": [
            {"id": str(r.id), "name": r.name, "color": str(r.color) if r.color.value else None, "blocked": blocked[r.id]}
            for r in sorted(guild.roles, key=lambda r: -r.position)
            if not r.is_default() and not r.managed
        ],
        "autoroles": [str(r) for r in await get_autoroles(guild.id)],
        "panels": [await _read_panel(guild, c, m) for c, m in await get_panels(guild.id)],
        "max_buttons": MAX_BUTTONS,
    }


class Autoroles(BaseModel):
    role_ids: list[Snowflake] = Field(default_factory=list)


@router.put("/autoroles")
async def put_autoroles(body: Autoroles, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = _guild(user.guild_id)
    blocked = await _blocked(guild)
    for role_id in body.role_ids:
        if role_id not in blocked:
            raise HTTPException(400, "Unbekannte Rolle.")
        if blocked[role_id]:
            raise HTTPException(400, blocked[role_id])
    await set_autoroles(guild, list(dict.fromkeys(body.role_ids)))
    return {"ok": True, "message": "Gespeichert – gilt für alle, die ab jetzt beitreten."}


class PanelButton(BaseModel):
    role_id: Snowflake
    label: str = Field("", max_length=80)
    emoji: str = Field("", max_length=64)
    confirm: bool = False  # Klick = Anfrage, das Team bestaetigt


class Panel(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    text: str = Field("", max_length=4000)
    buttons: list[PanelButton] = Field(default_factory=list)


class NewPanel(Panel):
    channel_id: Snowflake


async def _view(guild: discord.Guild, buttons: list[PanelButton]) -> discord.ui.View | None:
    if not buttons:  # ein Panel ohne Knoepfe kann niemand benutzen
        raise HTTPException(400, "Mindestens einen Knopf hinzufügen.")
    if len(buttons) > MAX_BUTTONS:
        raise HTTPException(400, f"Höchstens {MAX_BUTTONS} Knöpfe pro Panel.")
    if len({b.role_id for b in buttons}) != len(buttons):
        raise HTTPException(400, "Jede Rolle nur einmal pro Panel.")
    blocked = await _blocked(guild)
    items = []
    for b in buttons:
        role = guild.get_role(b.role_id)
        if role is None:
            raise HTTPException(400, "Unbekannte Rolle.")
        if blocked.get(role.id):
            raise HTTPException(400, blocked[role.id])
        items.append(RoleToggleButton(role.id, (b.label.strip() or role.name)[:80], b.emoji.strip() or None, confirm=b.confirm))
    return build_view(items) if items else None


def _text_channel(guild: discord.Guild, channel_id: int) -> discord.TextChannel:
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        raise HTTPException(400, "Bitte einen Textkanal wählen.")
    return channel


@router.post("/panels")
async def create_panel(body: NewPanel, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = _guild(user.guild_id)
    channel = _text_channel(guild, body.channel_id)
    view = await _view(guild, body.buttons)
    try:
        message = await channel.send(embed=panel_embed(body.title, body.text), view=view)
    except discord.HTTPException as error:
        raise HTTPException(400, f"Discord hat das Panel abgelehnt (ungültiges Emoji oder fehlende Rechte?): {error.text}") from None
    await remember_panel(guild, channel.id, message.id)
    return {"ok": True, "message": f"Panel in #{channel.name} erstellt."}


async def _own_panel(guild: discord.Guild, message_id: int) -> discord.Message:
    panels = dict((m, c) for c, m in await get_panels(guild.id))
    if message_id not in panels:
        raise HTTPException(404, "Panel nicht gefunden.")
    channel = guild.get_channel(panels[message_id])
    try:
        return await channel.fetch_message(message_id)
    except (discord.HTTPException, AttributeError):
        raise HTTPException(404, "Die Nachricht gibt es in Discord nicht mehr – Panel aus der Liste entfernen.") from None


@router.put("/panels/{message_id}")
async def put_panel(message_id: int, body: Panel, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = _guild(user.guild_id)
    message = await _own_panel(guild, message_id)
    view = await _view(guild, body.buttons)
    try:
        await message.edit(embed=panel_embed(body.title, body.text), view=view)
    except discord.HTTPException as error:
        raise HTTPException(400, f"Discord hat die Änderung abgelehnt (ungültiges Emoji?): {error.text}") from None
    return {"ok": True, "message": "Panel aktualisiert."}


@router.delete("/panels/{message_id}")
async def delete_panel(message_id: int, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    guild = _guild(user.guild_id)
    try:
        message = await _own_panel(guild, message_id)
        await message.delete()
    except HTTPException as error:
        if error.status_code != 404:
            raise
    except discord.HTTPException:
        pass
    await forget_panel(guild, message_id)
    return {"ok": True, "message": "Panel gelöscht."}


class AdoptPanel(BaseModel):
    link: str = Field(min_length=1, max_length=200)


@router.post("/panels/adopt")
async def adopt_panel(body: AdoptPanel, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    """Ein frueher (vor dem Tab) per /rollen panel erstelltes Panel in die Liste aufnehmen."""
    guild = _guild(user.guild_id)
    ref = parse_message_ref(body.link)
    if ref is None or ref[0] is None:
        raise HTTPException(400, "Bitte den Nachrichten-Link angeben (Rechtsklick auf die Nachricht → Link kopieren).")
    channel_id, message_id = ref
    channel = guild.get_channel(channel_id)
    try:
        message = await channel.fetch_message(message_id)
    except (discord.HTTPException, AttributeError):
        raise HTTPException(404, "Nachricht nicht gefunden.") from None
    if message.author.id != runtime.bot.user.id:
        raise HTTPException(400, "Das ist keine Nachricht des Bots.")
    await remember_panel(guild, channel_id, message_id)
    return {"ok": True, "message": "Panel übernommen."}
