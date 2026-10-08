"""FastAPI-Router fuer die Musik-Seite (bot/cogs/music/web/MusicPage.tsx).

Steuert die laufende Wiedergabe direkt ueber den Bot - geht deshalb nur, wenn
die Web-Oberflaeche im Bot-Prozess laeuft (api/server.py, z.B. in AMP), nicht
bei getrennt gestarteter API. Discord-IDs gehen als Text raus: JavaScript kann
Zahlen dieser Groesse nicht exakt darstellen.
"""

import json

import discord
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import CurrentUser, get_current_user, require_level
from bot.cogs.music import stations as station_store
from bot.cogs.music.stations import CATEGORIES_KEY, STATIONS_KEY
from bot.cogs.music.sources import (
    MUSIC_DIR,
    SourceError,
    fetch_feed,
    list_audio_files,
    list_folders,
)
from bot.core import runtime
from bot.core.guild_config import get_config, set_config
from db.models.role import Level, level_at_least

router = APIRouter(prefix="/music", tags=["music"])


def _guild_and_cog(user: CurrentUser):
    if runtime.bot is None:
        raise HTTPException(503, "Nur verfügbar, wenn die Oberfläche im Bot läuft.")
    cog = runtime.bot.get_cog("MusicCog")
    guild = runtime.bot.get_guild(user.guild_id)
    if cog is None or guild is None:
        raise HTTPException(503, "Der Musik-Cog ist nicht geladen.")
    return guild, cog


async def _json(guild_id: int, key: str) -> dict:
    try:
        return json.loads(await get_config(guild_id, key, "{}") or "{}")
    except json.JSONDecodeError:
        return {}


async def _save_json(guild_id: int, key: str, value: dict) -> None:
    guild = runtime.bot.get_guild(guild_id) if runtime.bot else None
    await set_config(guild_id, key, json.dumps(value), guild.name if guild else str(guild_id))


async def _stations(guild_id: int) -> tuple[dict, dict]:
    return await _json(guild_id, STATIONS_KEY), await _json(guild_id, CATEGORIES_KEY)


async def _save_stations(guild_id: int, stations: dict, categories: dict) -> None:
    await _save_json(guild_id, STATIONS_KEY, stations)
    await _save_json(guild_id, CATEGORIES_KEY, station_store.prune_categories(stations, categories))


def _station_rows(stations: dict, categories: dict, with_url: bool) -> list[dict]:
    rows = []
    for name in sorted(stations, key=str.casefold):
        row = {"name": name, "category": station_store.category_of(categories, name)}
        if with_url:
            row["url"] = stations[name]
        rows.append(row)
    return rows


# --- Wiedergabe ---------------------------------------------------------------------


@router.get("/state")
async def state(user: CurrentUser = Depends(get_current_user)) -> dict:
    guild, cog = _guild_and_cog(user)
    member = guild.get_member(user.user_id)
    data = cog.state(guild)
    data["my_channel_name"] = member.voice.channel.name if member and member.voice and member.voice.channel else None
    data["can_control"] = _can_control(user, guild)
    return data


def _can_control(user: CurrentUser, guild) -> bool:
    if level_at_least(user.level, Level.MOD):
        return True
    voice = guild.voice_client
    member = guild.get_member(user.user_id)
    return bool(voice and member and member.voice and member.voice.channel == voice.channel)


@router.get("/library")
async def library(user: CurrentUser = Depends(get_current_user)) -> dict:
    stations, categories = await _stations(user.guild_id)
    podcasts = await _json(user.guild_id, "podcast_feeds")
    return {
        "stations": _station_rows(stations, categories, with_url=False),
        "files": list_audio_files(),
        "folders": list_folders(),
        "podcasts": sorted(podcasts),
    }


@router.get("/podcasts/{name}/episodes")
async def episodes(name: str, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    feeds = await _json(user.guild_id, "podcast_feeds")
    if name not in feeds:
        raise HTTPException(404, "Diesen Podcast gibt es nicht.")
    try:
        feed = await fetch_feed(feeds[name]["url"])
    except Exception as error:
        raise HTTPException(502, f"Podcast nicht abrufbar: {error}") from error
    return [{"index": i, "title": e.title, "published": e.published} for i, e in enumerate(feed.episodes[:100])]


class PlayIn(BaseModel):
    kind: str = Field(pattern="^(radio|file|folder|podcast)$")
    name: str
    episode: int = 0
    shuffle: bool = False


@router.post("/play")
async def play(body: PlayIn, user: CurrentUser = Depends(get_current_user)) -> dict:
    guild, cog = _guild_and_cog(user)
    member = guild.get_member(user.user_id)
    channel = member.voice.channel if member and member.voice else None
    if channel is None:
        raise HTTPException(400, "Geh zuerst in Discord in einen Voice-Kanal – dorthin kommt die Musik.")
    voice = guild.voice_client
    if voice and voice.channel != channel and voice.is_playing() and not level_at_least(user.level, Level.MOD):
        raise HTTPException(409, f"Ich spiele gerade in {voice.channel.name}.")
    try:
        tracks = await cog.resolve_tracks(guild.id, body.kind, body.name, user.user_id, episode=body.episode, shuffle=body.shuffle)
        added = await cog.start_tracks(guild, channel, tracks)
    except SourceError as error:
        raise HTTPException(400, str(error)) from error
    except (TimeoutError, discord.ClientException) as error:  # Sprachverbindung kam nicht zustande
        from bot.cogs.music.cog import voice_error_text

        raise HTTPException(502, voice_error_text(error)) from error
    except Exception as error:
        raise HTTPException(502, f"Abspielen fehlgeschlagen: {error}") from error
    return {"added": added}


class ControlIn(BaseModel):
    action: str = Field(pattern="^(pause|resume|skip|stop|shuffle|volume)$")
    value: int | None = Field(default=None, ge=0, le=100)


@router.post("/control")
async def control(body: ControlIn, user: CurrentUser = Depends(get_current_user)) -> dict:
    guild, cog = _guild_and_cog(user)
    if not _can_control(user, guild):
        raise HTTPException(403, "Steuern darf, wer im selben Voice-Kanal ist – oder ein Mod.")
    try:
        await cog.control(guild, body.action, body.value)
    except SourceError as error:
        raise HTTPException(400, str(error)) from error
    return {"ok": True}


# --- Einstellungen (Admin) ------------------------------------------------------------


@router.get("/config")
async def config(user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    stations, categories = await _stations(user.guild_id)
    podcasts = await _json(user.guild_id, "podcast_feeds")
    channels = []
    if runtime.bot is not None and (guild := runtime.bot.get_guild(user.guild_id)):
        channels = [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
    return {
        "stations": _station_rows(stations, categories, with_url=True),
        "podcasts": [
            {"name": n, "url": d["url"], "channel_id": str(d["channel_id"]) if d.get("channel_id") else None}
            for n, d in sorted(podcasts.items())
        ],
        "text_channels": channels,
        "music_dir": str(MUSIC_DIR),
        "file_count": len(list_audio_files()),
    }


class StationIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(pattern="^https?://")
    category: str = Field(default="", max_length=100)


@router.post("/stations")
async def add_station(body: StationIn, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    stations, categories = await _stations(user.guild_id)
    conflict = station_store.station_conflict(stations, body.name, body.url)
    if conflict:
        raise HTTPException(409, conflict.replace("**", ""))
    name = body.name.strip()
    stations[name] = body.url.strip()
    station_store.set_category(stations, categories, [name], body.category)
    await _save_stations(user.guild_id, stations, categories)
    return {"ok": True}


class StationImport(BaseModel):
    url: str = Field(pattern="^https?://", max_length=500)
    category: str = Field(default="", max_length=100)  # leer = Genre aus der Liste


@router.post("/stations/import")
async def import_station_list(body: StationImport, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    """Alle Sender einer .m3u/.pls-Liste eintragen (gleiche Adressen werden uebersprungen)."""
    from bot.cogs.music.sources import SourceError, fetch_playlist_entries

    try:
        entries = await fetch_playlist_entries(body.url)
    except SourceError as error:
        raise HTTPException(400, str(error)) from None
    except Exception as error:
        raise HTTPException(502, f"Liste nicht abrufbar: {str(error).splitlines()[0][:200]}") from None
    stations, categories = await _stations(user.guild_id)
    added, known = station_store.import_stations(stations, entries, categories, body.category)
    await _save_stations(user.guild_id, stations, categories)
    return {"ok": True, "message": f"{added} Sender eingetragen" + (f", {known} waren schon da" if known else "") + "."}


@router.delete("/stations/{name}")
async def remove_station(name: str, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    stations, categories = await _stations(user.guild_id)
    station_store.remove_stations(stations, categories, [name])
    await _save_stations(user.guild_id, stations, categories)
    return {"ok": True}


class StationBulk(BaseModel):
    names: list[str] = Field(min_length=1, max_length=5000)
    action: str = Field(pattern="^(category|delete)$")
    category: str = Field(default="", max_length=100)  # "" = Kategorie entfernen


@router.post("/stations/bulk")
async def bulk_stations(body: StationBulk, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    """Mehrere Sender auf einmal: Kategorie setzen/entfernen oder loeschen."""
    stations, categories = await _stations(user.guild_id)
    if body.action == "delete":
        count = station_store.remove_stations(stations, categories, body.names)
        message = f"{count} Sender entfernt."
    else:
        count = station_store.set_category(stations, categories, body.names, body.category)
        chosen = station_store.find_category(categories, body.category)
        message = f"{count} Sender " + (f"in „{chosen}“ verschoben." if chosen else "ohne Kategorie.")
    await _save_stations(user.guild_id, stations, categories)
    return {"ok": True, "message": message}


class PodcastIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(pattern="^https?://")


@router.post("/podcasts")
async def add_podcast(body: PodcastIn, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    try:
        feed = await fetch_feed(body.url, use_cache=False)
    except SourceError as error:
        raise HTTPException(400, str(error)) from error
    except Exception as error:
        raise HTTPException(400, f"Feed nicht nutzbar: {error}") from error
    feeds = await _json(user.guild_id, "podcast_feeds")
    feeds[body.name] = {"url": body.url, "channel_id": None, "last_guid": feed.episodes[0].guid if feed.episodes else None}
    await _save_json(user.guild_id, "podcast_feeds", feeds)
    return {"title": feed.title, "episodes": len(feed.episodes)}


@router.delete("/podcasts/{name}")
async def remove_podcast(name: str, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    feeds = await _json(user.guild_id, "podcast_feeds")
    feeds.pop(name, None)
    await _save_json(user.guild_id, "podcast_feeds", feeds)
    return {"ok": True}


class AnnounceIn(BaseModel):
    channel_id: str | None = Field(default=None, pattern=r"^\d+$")


@router.put("/podcasts/{name}/announce")
async def announce(name: str, body: AnnounceIn, user: CurrentUser = Depends(require_level(Level.ADMIN))) -> dict:
    feeds = await _json(user.guild_id, "podcast_feeds")
    if name not in feeds:
        raise HTTPException(404, "Diesen Podcast gibt es nicht.")
    feeds[name]["channel_id"] = int(body.channel_id) if body.channel_id else None
    await _save_json(user.guild_id, "podcast_feeds", feeds)
    return {"ok": True}
