"""FastAPI-Router fuer den Banner-Tab (bot/cogs/banner/web/BannerPage.tsx).

Dasselbe wie /banner und /bannergroup in Discord: Banner pro Server, Banner-Gruppen,
Hintergrund (eigenes Bild, Steam-Artwork, Theme, eigene Farben), Schriftfarbe,
Unschaerfe - mit Live-Vorschau des Bildes. Posten/Aktualisieren in Discord macht der
laufende Banner-Cog; ohne ihn wird nur gespeichert. Discord-IDs als Text.
"""

import asyncio
import io
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from api.middleware.auth import CurrentUser, require_capability, require_level
from api.types import Snowflake
from bot.cogs.banner.cog import (
    ALLOWED_CONTENT_TYPES,
    BACKGROUND_DIR,
    MAX_GROUP_MEMBERS,
    MAX_UPLOAD_BYTES,
    _delete_message,
    _save_background,
)
from bot.cogs.banner.image import render_banner, render_banner_group
from bot.cogs.banner.themes import BANNER_THEMES, BLUR_LEVELS, DEFAULT_THEME, PRESET_COLORS
from bot.core import runtime
from bot.core.entities import ensure_guild
from bot.core.server_address import connect_address
from bot.core.steam_art import fetch_header_image
from db.models.banner_group import BannerGroup, BannerGroupLayout
from db.models.role import Level
from db.models.server import BannerType, Server
from db.session import get_db_session

router = APIRouter(prefix="/banner", tags=["banner"])

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
Background = Literal["image", "steam", "theme", "colors"]

# Beispielwerte fuer die Vorschau - kein AMP-Aufruf noetig
_SAMPLE_STATUS = SimpleNamespace(
    State=SimpleNamespace(name="Ready"),
    Uptime="1h 23m",
    Metrics={"Active Users": SimpleNamespace(RawValue=3, MaxValue=10)},
)


def _cog():
    return runtime.bot.get_cog("BannerCog") if runtime.bot else None


def _hex(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if not HEX.match(value):
        raise ValueError("Farbe als #rrggbb angeben")
    return value.lower()


# --- Lesen ----------------------------------------------------------------------------


def _background_mode(obj, steam_available: bool) -> str:
    if obj.banner_background_path:
        return "image"
    if steam_available:
        return "steam"
    if obj.banner_color_start and obj.banner_color_end:
        return "colors"
    return "theme"


def _style(obj, steam_available: bool = False) -> dict:
    return {
        "type": obj.banner_type.value,
        "background": _background_mode(obj, steam_available),
        "theme": obj.banner_theme if obj.banner_theme in BANNER_THEMES else DEFAULT_THEME,
        "color_start": obj.banner_color_start,
        "color_end": obj.banner_color_end,
        "text_color": obj.banner_text_color,
        "blur": obj.banner_blur or 0,
        "has_image": bool(obj.banner_background_path),
    }


@router.get("/config")
async def get_banner(user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    gid = user.guild_id
    guild = runtime.bot.get_guild(gid) if runtime.bot else None
    async with get_db_session() as db:
        servers = (await db.execute(select(Server).where(Server.guild_id == gid).order_by(Server.display_name))).scalars().all()
        groups = (await db.execute(select(BannerGroup).where(BannerGroup.guild_id == gid).order_by(BannerGroup.name))).scalars().all()
    return {
        "cog_loaded": _cog() is not None,
        "text_channels": [{"id": str(c.id), "name": c.name} for c in guild.text_channels] if guild else [],
        "themes": BANNER_THEMES,
        "presets": PRESET_COLORS,
        "blur_levels": BLUR_LEVELS,
        "max_group_members": MAX_GROUP_MEMBERS,
        "servers": [
            {
                "id": s.id,
                "name": s.display_name,
                "instance_name": s.instance_name,
                "enabled": s.banner_enabled,
                "channel_id": str(s.banner_channel) if s.banner_channel else None,
                "group_id": s.banner_group_id,
                "steam_art": bool(s.steam_app_id),
                **_style(s, bool(s.steam_app_id) and s.banner_steam_art),
            }
            for s in servers
        ],
        "groups": [
            {
                "id": g.id,
                "name": g.name,
                "channel_id": str(g.channel) if g.channel else None,
                "layout": g.layout.value,
                "member_ids": [s.id for s in servers if s.banner_group_id == g.id],
                **_style(g),
            }
            for g in groups
        ],
    }


# --- Gemeinsames: Stil -------------------------------------------------------------------


class Style(BaseModel):
    type: Literal["embed", "image"] = "embed"
    background: Background = "theme"
    theme: str = DEFAULT_THEME
    color_start: str | None = None
    color_end: str | None = None
    text_color: str | None = None
    blur: int = Field(0, ge=0, le=20)

    @field_validator("color_start", "color_end", "text_color")
    @classmethod
    def _check_hex(cls, value: str | None) -> str | None:
        return _hex(value)

    @field_validator("theme")
    @classmethod
    def _check_theme(cls, value: str) -> str:
        if value not in BANNER_THEMES:
            raise ValueError("unbekanntes Theme")
        return value


def _apply_style(obj, style: Style, *, steam_available: bool = False) -> None:
    """Uebernimmt den Stil in Server/Gruppe. Ein eigenes Bild bleibt nur bei 'image'."""
    if style.background == "image" and not obj.banner_background_path:
        raise HTTPException(400, "Erst ein Hintergrundbild hochladen.")
    if style.background == "steam" and not steam_available:
        raise HTTPException(400, "Fuer diesen Server gibt es kein Steam-Artwork.")
    if style.background == "colors" and not (style.color_start and style.color_end):
        raise HTTPException(400, "Fuer einen eigenen Verlauf Start- und Endfarbe waehlen.")
    if style.background != "image" and obj.banner_background_path:
        Path(obj.banner_background_path).unlink(missing_ok=True)
        obj.banner_background_path = None
    obj.banner_type = BannerType(style.type)
    obj.banner_theme = style.theme if style.background == "theme" else None
    obj.banner_color_start = style.color_start if style.background == "colors" else None
    obj.banner_color_end = style.color_end if style.background == "colors" else None
    obj.banner_text_color = style.text_color
    obj.banner_blur = style.blur
    if hasattr(obj, "banner_steam_art"):
        obj.banner_steam_art = style.background == "steam"


# --- Server ------------------------------------------------------------------------------


class ServerBanner(Style):
    enabled: bool = False
    channel_id: Snowflake | None = None


async def _own_server(db, guild_id: int, server_id: int) -> Server:
    server = await db.get(Server, server_id)
    if server is None or server.guild_id != guild_id:
        raise HTTPException(404, "Server nicht gefunden.")
    return server


@router.put("/servers/{server_id}")
async def put_server(server_id: int, body: ServerBanner, user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    if body.enabled and not body.channel_id:
        raise HTTPException(400, "Zum Aktivieren einen Kanal waehlen.")
    async with get_db_session() as db:
        server = await _own_server(db, user.guild_id, server_id)
        if body.enabled and server.banner_group_id is not None:
            raise HTTPException(400, "Der Server gehoert zu einer Banner-Gruppe - erst dort entfernen.")
        old = (server.banner_channel, server.banner_message_id, server.banner_type)
        _apply_style(server, body, steam_available=bool(server.steam_app_id))
        server.banner_enabled = body.enabled
        server.banner_channel = body.channel_id
        # Aus, anderer Kanal oder andere Darstellung: alte Nachricht weg, neu posten
        stale = old[1] and (not body.enabled or old[0] != body.channel_id or old[2] != server.banner_type)
        if stale:
            server.banner_message_id = None
        await db.commit()
    return await _after_save(old if stale else None, "server", server_id, body.enabled)


async def _after_save(stale: tuple | None, kind: str, target_id: int, post: bool) -> dict:
    cog = _cog()
    if cog is None:
        return {"ok": True, "message": "Gespeichert. Der Banner-Cog ist nicht geladen - in Discord passiert erst etwas, wenn er laeuft."}
    if stale:
        await _delete_message(runtime.bot, stale[0], stale[1])
    if not post:
        return {"ok": True, "message": "Gespeichert."}
    try:
        if kind == "server":
            await cog._post_or_refresh_server(target_id)
        else:
            await cog._post_or_refresh_group(target_id)
    except Exception as error:
        return {"ok": True, "message": f"Gespeichert, aber in Discord nicht aktualisiert: {str(error)[:200]}"}
    return {"ok": True, "message": "Gespeichert und in Discord aktualisiert."}


@router.post("/servers/{server_id}/refresh")
async def refresh_server(server_id: int, user: CurrentUser = Depends(require_capability("banner.refresh"))) -> dict:
    async with get_db_session() as db:
        server = await _own_server(db, user.guild_id, server_id)
        enabled = server.banner_enabled and server.banner_group_id is None
    if not enabled:
        raise HTTPException(400, "Fuer diesen Server ist kein eigener Banner aktiv.")
    return await _after_save(None, "server", server_id, True)


# --- Gruppen -----------------------------------------------------------------------------


class GroupBanner(Style):
    name: str = Field(min_length=1, max_length=100)
    channel_id: Snowflake
    layout: Literal["combined", "separate"] = "combined"
    member_ids: list[int] = Field(default_factory=list)


async def _own_group(db, guild_id: int, group_id: int) -> BannerGroup:
    group = await db.get(BannerGroup, group_id)
    if group is None or group.guild_id != guild_id:
        raise HTTPException(404, "Gruppe nicht gefunden.")
    return group


async def _set_members(db, guild_id: int, group: BannerGroup, member_ids: list[int]) -> list[tuple]:
    """Setzt die Mitglieder; gibt eigene Banner-Nachrichten neu aufgenommener Server zurueck (zum Loeschen)."""
    wanted = list(dict.fromkeys(member_ids))
    if len(wanted) > MAX_GROUP_MEMBERS:
        raise HTTPException(400, f"Hoechstens {MAX_GROUP_MEMBERS} Server pro Gruppe.")
    servers = (await db.execute(select(Server).where(Server.guild_id == guild_id))).scalars().all()
    by_id = {s.id: s for s in servers}
    if any(i not in by_id for i in wanted):
        raise HTTPException(400, "Unbekannter Server in der Auswahl.")
    stale = []
    for server in servers:
        if server.id in wanted:
            if server.banner_group_id not in (None, group.id):
                raise HTTPException(400, f"`{server.display_name}` gehoert schon zu einer anderen Gruppe.")
            if server.banner_enabled and server.banner_message_id:
                stale.append((server.banner_channel, server.banner_message_id))
            server.banner_group_id = group.id
            server.banner_enabled = False  # eigener Banner geht in der Gruppe auf
            server.banner_message_id = None
        elif server.banner_group_id == group.id:
            server.banner_group_id = None
    return stale


@router.post("/groups")
async def create_group(body: GroupBanner, user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    await ensure_guild(user.guild_id, guild.name if guild else str(user.guild_id))
    async with get_db_session() as db:
        exists = await db.execute(select(BannerGroup).where(BannerGroup.guild_id == user.guild_id, BannerGroup.name == body.name))
        if exists.scalar_one_or_none() is not None:
            raise HTTPException(400, f"Gruppe `{body.name}` gibt es schon.")
        group = BannerGroup(guild_id=user.guild_id, name=body.name, channel=body.channel_id, layout=BannerGroupLayout(body.layout))
        db.add(group)
        await db.flush()
        _apply_style(group, body)
        stale = await _set_members(db, user.guild_id, group, body.member_ids)
        await db.commit()
        group_id = group.id
    for channel_id, message_id in stale:
        await _delete_message(runtime.bot, channel_id, message_id)
    result = await _after_save(None, "group", group_id, True)
    return {**result, "id": group_id}


@router.put("/groups/{group_id}")
async def put_group(group_id: int, body: GroupBanner, user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    async with get_db_session() as db:
        group = await _own_group(db, user.guild_id, group_id)
        clash = await db.execute(
            select(BannerGroup).where(BannerGroup.guild_id == user.guild_id, BannerGroup.name == body.name, BannerGroup.id != group_id)
        )
        if clash.scalar_one_or_none() is not None:
            raise HTTPException(400, f"Gruppe `{body.name}` gibt es schon.")
        old = (group.channel, group.message_id, group.banner_type, group.layout)
        group.name = body.name
        group.channel = body.channel_id
        group.layout = BannerGroupLayout(body.layout)
        _apply_style(group, body)
        stale_members = await _set_members(db, user.guild_id, group, body.member_ids)
        stale = old[1] and (old[0] != group.channel or old[2] != group.banner_type or old[3] != group.layout)
        if stale:
            group.message_id = None
        await db.commit()
    for channel_id, message_id in stale_members:
        await _delete_message(runtime.bot, channel_id, message_id)
    return await _after_save(old if stale else None, "group", group_id, True)


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int, user: CurrentUser = Depends(require_level(Level.OWNER))) -> dict:
    async with get_db_session() as db:
        group = await _own_group(db, user.guild_id, group_id)
        members = (await db.execute(select(Server).where(Server.banner_group_id == group_id))).scalars().all()
        for member in members:
            member.banner_group_id = None
        channel_id, message_id, path = group.channel, group.message_id, group.banner_background_path
        await db.delete(group)
        await db.commit()
    if path:
        Path(path).unlink(missing_ok=True)
    if runtime.bot:
        await _delete_message(runtime.bot, channel_id, message_id)
    return {"ok": True, "message": "Gruppe aufgeloest, ihre Server sind wieder frei."}


@router.post("/groups/{group_id}/refresh")
async def refresh_group(group_id: int, user: CurrentUser = Depends(require_capability("banner.refresh"))) -> dict:
    async with get_db_session() as db:
        await _own_group(db, user.guild_id, group_id)
    return await _after_save(None, "group", group_id, True)


# --- Hintergrundbild ---------------------------------------------------------------------


async def _read_upload(request: Request) -> bytes:
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, "Nur PNG-, JPEG- oder WebP-Bilder.")
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "Bild ist zu gross (max. 8 MB).")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception:
        raise HTTPException(400, "Die Datei ist kein lesbares Bild.") from None
    return data


@router.post("/{kind}/{target_id}/background")
async def upload_background(
    kind: Literal["servers", "groups"], target_id: int, request: Request, user: CurrentUser = Depends(require_level(Level.OWNER))
) -> dict:
    data = await _read_upload(request)
    async with get_db_session() as db:
        obj = await (_own_server if kind == "servers" else _own_group)(db, user.guild_id, target_id)
        path = BACKGROUND_DIR / f"{'server' if kind == 'servers' else 'group'}_{obj.id}.png"
        await _save_background(data, path)
        obj.banner_background_path = str(path)
        await db.commit()
    return {"ok": True, "message": "Bild gespeichert und als Hintergrund gesetzt - der Banner zeigt es beim naechsten Update."}


# --- Vorschau ----------------------------------------------------------------------------


def _png(buffer: io.BytesIO) -> Response:
    return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


async def _preview_background(obj, background: str, *, steam_app_id: int | None = None) -> str | None:
    if background == "image":
        return obj.banner_background_path
    if background == "steam" and steam_app_id:
        cached = await fetch_header_image(steam_app_id)
        return str(cached) if cached else None
    return None


def _preview_style(background, theme, color_start, color_end, text_color, blur) -> dict:
    try:
        return {
            "theme": theme if background == "theme" and theme in BANNER_THEMES else None,
            "color_start": _hex(color_start) if background == "colors" else None,
            "color_end": _hex(color_end) if background == "colors" else None,
            "text_color": _hex(text_color),
            "blur": max(0, min(20, blur)),
        }
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@router.get("/servers/{server_id}/preview")
async def preview_server(
    server_id: int,
    background: Background = "theme",
    theme: str = DEFAULT_THEME,
    color_start: str | None = None,
    color_end: str | None = None,
    text_color: str | None = None,
    blur: int = Query(0),
    user: CurrentUser = Depends(require_level(Level.OWNER)),
) -> Response:
    async with get_db_session() as db:
        server = await _own_server(db, user.guild_id, server_id)
    style = _preview_style(background, theme, color_start, color_end, text_color, blur)
    path = await _preview_background(server, background, steam_app_id=server.steam_app_id)
    address = await connect_address(server)
    buffer = await asyncio.to_thread(
        render_banner, server.display_name, address, _SAMPLE_STATUS, (3, 10), background_path=path, **style
    )
    return _png(buffer)


@router.get("/groups/{group_id}/preview")
async def preview_group(
    group_id: int,
    members: str = "",
    background: Background = "theme",
    theme: str = DEFAULT_THEME,
    color_start: str | None = None,
    color_end: str | None = None,
    text_color: str | None = None,
    blur: int = Query(0),
    user: CurrentUser = Depends(require_level(Level.OWNER)),
) -> Response:
    """Kombiniertes Gruppenbild mit Beispielwerten; `members` = Server-IDs (kommagetrennt)."""
    wanted = [int(x) for x in members.split(",") if x.strip().isdigit()][:MAX_GROUP_MEMBERS]
    async with get_db_session() as db:
        group = await _own_group(db, user.guild_id, group_id) if group_id else SimpleNamespace(banner_background_path=None)
        servers = (await db.execute(select(Server).where(Server.guild_id == user.guild_id, Server.id.in_(wanted or [0])))).scalars().all()
    names = {s.id: s.display_name for s in servers}
    entries = [(names[i], "", _SAMPLE_STATUS, (3, 10), None, False) for i in wanted if i in names] or [
        ("Beispiel-Server", "", _SAMPLE_STATUS, (3, 10), None, False)
    ]
    style = _preview_style(background, theme, color_start, color_end, text_color, blur)
    path = await _preview_background(group, background)
    buffer = await asyncio.to_thread(render_banner_group, entries, background_path=path, **style)
    return _png(buffer)
