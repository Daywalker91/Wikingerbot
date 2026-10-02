"""Quellen fuer den music-Cog: Radio-Streams (inkl. .m3u/.pls), Podcast-Feeds
(RSS) und lokale Dateien. Bewusst ohne YouTube/Spotify (siehe README).

Sicherheit: Der Bot laeuft in der DMZ. Eine frei eingegebene URL darf ihn
nicht ins interne Netz greifen lassen (SSRF) - check_public_url() laesst nur
oeffentliche Adressen zu. Radiosender legt ein Admin bewusst an, die werden
nicht geprueft (z.B. ein eigener Icecast im LAN).
"""

import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree

ROOT = Path(__file__).resolve().parents[3]
MUSIC_DIR = ROOT / "data" / "music"
AUDIO_EXTENSIONS = {".mp3", ".ogg", ".opus", ".flac", ".wav", ".m4a", ".aac"}

HTTP_TIMEOUT = 10.0
MAX_PLAYLIST_BYTES = 64 * 1024
MAX_FEED_BYTES = 5 * 1024 * 1024
FEED_CACHE_SECONDS = 600
USER_AGENT = "WikingerBot (Discord-Bot; https://github.com/Daywalker91/Wikingerbot)"


class SourceError(Exception):
    """Fehler mit einer Meldung, die so an den Discord-Nutzer gehen kann."""


# --- URL-Pruefung ---------------------------------------------------------------


def is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


async def check_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceError("Nur http- und https-Adressen.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise SourceError(f"{parsed.hostname} ist nicht auffindbar.") from None
    if not infos or not all(is_public_ip(info[4][0]) for info in infos):
        raise SourceError("Adressen im internen Netz sind nicht erlaubt.")


# --- Radio: Playlisten aufloesen -------------------------------------------------


def parse_playlist(text: str) -> str | None:
    """Erste Stream-Adresse aus einer .m3u- oder .pls-Datei."""
    for raw in text.splitlines():
        line = raw.strip()
        if line.lower().startswith("file") and "=" in line:  # .pls: File1=http://...
            line = line.split("=", 1)[1].strip()
        if line.startswith(("http://", "https://")):
            return line
    return None


async def resolve_stream_url(url: str) -> str:
    """Radiosender verweisen oft auf eine .m3u/.pls-Liste statt direkt auf den
    Stream - die wird hier aufgeloest. HLS (.m3u8) kann FFmpeg selbst."""
    path = urlparse(url).path.lower()
    if not path.endswith((".m3u", ".pls")):
        return url
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_PLAYLIST_BYTES:
                    break
    stream = parse_playlist(body.decode("utf-8", errors="replace"))
    if stream is None:
        raise SourceError("In der Playlist des Senders steht keine Stream-Adresse.")
    return stream


# --- Podcasts ---------------------------------------------------------------------


@dataclass
class Episode:
    title: str
    url: str
    guid: str
    published: str  # fuer die Anzeige, z.B. "02.10.2026"


@dataclass
class Feed:
    title: str
    episodes: list[Episode]


def _text(element, tag: str) -> str:
    found = element.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def _date(value: str) -> str:
    try:
        return parsedate_to_datetime(value).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return ""


def parse_feed(xml: bytes) -> Feed:
    """RSS-Feed eines Podcasts -> Titel und Folgen mit Audio-Datei (neueste zuerst,
    so wie Feeds sie ueblicherweise liefern)."""
    try:
        root = ElementTree.fromstring(xml)
    except Exception as error:  # defusedxml wirft bei boesartigem XML eigene Fehler
        raise SourceError("Das ist kein gültiger Podcast-Feed.") from error
    channel = root.find("channel")
    if channel is None:
        raise SourceError("Das ist kein RSS-Podcast-Feed.")
    episodes = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        url = enclosure.get("url") if enclosure is not None else None
        if not url:
            continue
        episodes.append(
            Episode(
                title=_text(item, "title") or "(ohne Titel)",
                url=url.strip(),
                guid=_text(item, "guid") or url.strip(),
                published=_date(_text(item, "pubDate")),
            )
        )
    return Feed(title=_text(channel, "title") or "Podcast", episodes=episodes)


_feed_cache: dict[str, tuple[float, Feed]] = {}


async def fetch_feed(url: str, *, use_cache: bool = True) -> Feed:
    cached = _feed_cache.get(url)
    if use_cache and cached and time.monotonic() - cached[0] < FEED_CACHE_SECONDS:
        return cached[1]
    await check_public_url(url)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise SourceError(f"Feed nicht abrufbar (HTTP {response.status_code}).")
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > MAX_FEED_BYTES:
                    raise SourceError("Der Feed ist zu groß.")
    feed = parse_feed(body)
    _feed_cache[url] = (time.monotonic(), feed)
    return feed


# --- Lokale Dateien ---------------------------------------------------------------


def list_audio_files(root: Path = MUSIC_DIR) -> list[str]:
    """Alle Audiodateien unter data/music, als Pfade relativ dazu (mit /)."""
    if not root.is_dir():
        return []
    return sorted(
        p.relative_to(root).as_posix()
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )


def list_folders(root: Path = MUSIC_DIR) -> list[str]:
    files = list_audio_files(root)
    return sorted({f.rsplit("/", 1)[0] for f in files if "/" in f} | ({"."} if any("/" not in f for f in files) else set()))


def safe_music_path(relative: str, root: Path = MUSIC_DIR) -> Path:
    """Pfad unterhalb von data/music - ".." oder absolute Pfade fuehren nicht hinaus."""
    candidate = (root / relative).resolve()
    if candidate != root.resolve() and root.resolve() not in candidate.parents:
        raise SourceError("Ungültiger Pfad.")
    return candidate


def files_in_folder(folder: str, root: Path = MUSIC_DIR) -> list[str]:
    files = list_audio_files(root)
    if folder in {".", ""}:
        return [f for f in files if "/" not in f]
    prefix = folder.rstrip("/") + "/"
    return [f for f in files if f.startswith(prefix)]


def title_from_path(relative: str) -> str:
    return Path(relative).stem.replace("_", " ")
