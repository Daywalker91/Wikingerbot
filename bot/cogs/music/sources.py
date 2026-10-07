"""Quellen fuer den music-Cog: Radio-Streams (inkl. .m3u/.pls), Podcast-Feeds
(RSS) und lokale Dateien. Bewusst ohne YouTube/Spotify (siehe README).

Sicherheit: Der Bot laeuft in der DMZ. Eine frei eingegebene URL darf ihn
nicht ins interne Netz greifen lassen (SSRF) - check_public_url() laesst nur
oeffentliche Adressen zu. Radiosender legt ein Admin bewusst an, die werden
nicht geprueft (z.B. ein eigener Icecast im LAN).
"""

import asyncio
import ipaddress
import re
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


MAX_REDIRECTS = 5
STREAM_TIMEOUT = (10, 60)  # Verbinden, dann hoechstens 60 s ohne Daten


def check_public_url_sync(url: str) -> None:
    """Wie check_public_url, aber blockierend (fuer den Audio-Thread)."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SourceError("Nur http- und https-Adressen.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise SourceError(f"{parsed.hostname} ist nicht auffindbar.") from None
    if not infos or not all(is_public_ip(info[4][0]) for info in infos):
        raise SourceError("Adressen im internen Netz sind nicht erlaubt.")


def needs_ffmpeg_network(url: str) -> bool:
    """HLS (.m3u8) holt FFmpeg selbst (viele Teilstuecke) - alles andere laedt Python."""
    return urlparse(url).path.lower().endswith(".m3u8")


def open_stream(url: str):
    """Stream in Python oeffnen (blockierend, im Thread aufrufen) und den Response liefern;
    FFmpeg bekommt dann nur noch die Daten ueber eine Pipe. So muss FFmpeg weder Namen
    aufloesen noch TLS sprechen - statische FFmpeg-Builds stuerzen daran in manchen
    Containern ab - und jede Weiterleitung wird gegen interne Adressen geprueft."""
    import requests

    session = requests.Session()
    for _ in range(MAX_REDIRECTS + 1):
        check_public_url_sync(url)
        response = session.get(url, stream=True, allow_redirects=False, timeout=STREAM_TIMEOUT, headers={"User-Agent": USER_AGENT})
        if response.is_redirect and response.headers.get("location"):
            url = str(httpx.URL(url).join(response.headers["location"]))
            response.close()
            continue
        if response.status_code != 200:
            response.close()
            raise SourceError(f"Stream nicht abrufbar (HTTP {response.status_code}).")
        return response
    raise SourceError("Zu viele Weiterleitungen.")


async def fetch_limited(url: str, max_bytes: int, *, too_big: str | None = None) -> tuple[int, bytes]:
    """GET mit Groessengrenze; Weiterleitungen werden einzeln verfolgt und JEDES Ziel geprueft
    (sonst koennte eine oeffentliche Adresse ins interne Netz weiterleiten).
    too_big: Meldung bei Ueberschreitung - ohne wird einfach abgeschnitten."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await check_public_url(url)
            async with client.stream("GET", url) as response:
                if response.is_redirect and response.headers.get("location"):
                    url = str(response.url.join(response.headers["location"]))
                    continue
                body = b""
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        if too_big:
                            raise SourceError(too_big)
                        break
                return response.status_code, body
    raise SourceError("Zu viele Weiterleitungen.")


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
    await check_public_url(url)  # auch eingetragene Sender - nie ins interne Netz
    path = urlparse(url).path.lower()
    if not path.endswith((".m3u", ".pls")):
        return url
    status, body = await fetch_limited(url, MAX_PLAYLIST_BYTES)
    if status != 200:
        raise SourceError(f"Playlist des Senders nicht abrufbar (HTTP {status}).")
    stream = parse_playlist(body.decode("utf-8", errors="replace"))
    if stream is None:
        raise SourceError("In der Playlist des Senders steht keine Stream-Adresse.")
    await check_public_url(stream)
    return stream


# --- Ganze Playlisten (Sender-Sammlung importieren / als Warteschlange) -----------

MAX_LIST_BYTES = 1024 * 1024
MAX_LIST_ENTRIES = 200


def parse_playlist_entries(text: str) -> list[tuple[str, str]]:
    """Alle (Titel, Adresse) einer .m3u/.m3u8- oder .pls-Liste - Titel aus #EXTINF bzw.
    TitleN=, sonst der Dateiname. Nur http(s)-Adressen, ohne Doppelte, hoechstens MAX_LIST_ENTRIES."""
    entries, seen = [], set()
    pending_title = None
    pls_titles, pls_files = {}, {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("#EXTINF"):
            pending_title = line.split(",", 1)[1].strip() if "," in line else None
            continue
        match = re.match(r"(?i)^(file|title)(\d+)=(.*)$", line)
        if match:
            (pls_files if match[1].lower() == "file" else pls_titles)[match[2]] = match[3].strip()
            continue
        if line.startswith("#"):
            continue
        if line.startswith(("http://", "https://")) and line not in seen:
            seen.add(line)
            entries.append((_clean_title(pending_title) or _title_from_url(line), line))
        pending_title = None
    for key in sorted(pls_files, key=lambda k: int(k)):
        url = pls_files[key]
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            entries.append((_clean_title(pls_titles.get(key)) or _title_from_url(url), url))
    return entries[:MAX_LIST_ENTRIES]


def _clean_title(title: str | None) -> str:
    """"- RP MELLOW" -> "RP MELLOW" (Striche, Leerzeichen und Trenner am Rand weg)."""
    return (title or "").strip(" -–—|:·	")[:100]


def github_raw_url(url: str) -> str:
    """GitHub-Dateiseite -> Rohdatei: github.com/<user>/<repo>/blob/<zweig>/<pfad>
    -> raw.githubusercontent.com/<user>/<repo>/<zweig>/<pfad>. Andere Adressen bleiben."""
    match = re.match(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/(?:blob|raw)/(.+)$", url.strip())
    return f"https://raw.githubusercontent.com/{match[1]}/{match[2]}/{match[3]}" if match else url


def _title_from_url(url: str) -> str:
    name = urlparse(url).path.rsplit("/", 1)[-1]
    return (name.rsplit(".", 1)[0].replace("_", " ").replace("%20", " ") or urlparse(url).hostname or url)[:100]


async def fetch_playlist_entries(url: str) -> list[tuple[str, str]]:
    """Playlist abrufen (nie ins interne Netz) und alle Eintraege liefern.
    Die Adressen der Eintraege prueft, wer sie abspielt (check_public_url)."""
    url = github_raw_url(url)  # normale GitHub-Seite geht auch
    status, body = await fetch_limited(url, MAX_LIST_BYTES, too_big="Die Playlist ist zu groß (höchstens 1 MB).")
    if status != 200:
        raise SourceError(f"Playlist nicht abrufbar (HTTP {status}).")
    entries = parse_playlist_entries(body.decode("utf-8", errors="replace"))
    if not entries:
        raise SourceError("In der Datei stehen keine http(s)-Adressen – ist es wirklich eine .m3u/.pls?")
    return entries


async def check_public_urls(urls: list[str]) -> None:
    """Wie check_public_url fuer viele Adressen - jeden Host nur einmal aufloesen."""
    checked = set()
    for url in urls:
        key = (urlparse(url).scheme, urlparse(url).hostname, urlparse(url).port)
        if key not in checked:
            await check_public_url(url)
            checked.add(key)


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
    status, body = await fetch_limited(url, MAX_FEED_BYTES, too_big="Der Feed ist zu groß.")
    if status != 200:
        raise SourceError(f"Feed nicht abrufbar (HTTP {status}).")
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
