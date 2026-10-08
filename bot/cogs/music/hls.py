"""HLS-Radio (.m3u8) in Python laden und als fortlaufende Daten an FFmpeg reichen.

FFmpeg bekommt Streams ueber eine Pipe (siehe sources.open_stream) - so muss es
selbst nie ins Netz (statische FFmpeg-Builds stuerzen daran in manchen Containern
ab). Bei HLS heisst das: Playlist lesen, ggf. eine Variante waehlen, dann die
Teilstuecke der Reihe nach laden und die Playlist regelmaessig neu abrufen.

Laeuft blockierend im Schreib-Thread von discord.py (FFmpegAudio mit pipe=True,
read() wird dort aufgerufen). close() beendet es.

Nicht unterstuetzt: verschluesselte Streams (#EXT-X-KEY) und Byte-Bereiche.
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

MAX_PLAYLIST_BYTES = 1024 * 1024
MAX_SEGMENT_BYTES = 30 * 1024 * 1024
PREFERRED_MAX_BANDWIDTH = 400_000  # Varianten bis hierhin bevorzugen (FLAC & Co. sind viel groesser)
LIVE_START_SEGMENTS = 3  # bei Live-Streams so viele Teilstuecke vor dem Ende anfangen
CHUNK = 64 * 1024
MAX_FAILURES = 3


class HlsError(Exception):
    pass


@dataclass
class Variant:
    url: str
    bandwidth: int
    codecs: str = ""


@dataclass
class MediaPlaylist:
    sequence: int
    target_duration: float
    segments: list[str] = field(default_factory=list)  # absolute Adressen
    init: str | None = None  # #EXT-X-MAP (fMP4)
    ended: bool = False


def _attributes(text: str) -> dict[str, str]:
    return {k.upper(): v.strip('"') for k, v in re.findall(r'([A-Za-z0-9-]+)=("[^"]*"|[^,]*)', text)}


def parse_master(text: str, base: str) -> list[Variant]:
    """Varianten einer Master-Playlist ([] = es ist schon eine Media-Playlist)."""
    variants, pending = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.upper().startswith("#EXT-X-STREAM-INF:"):
            pending = _attributes(line.split(":", 1)[1])
        elif line and not line.startswith("#") and pending is not None:
            value = pending.get("BANDWIDTH", "")
            bandwidth = int(value) if value.isdigit() else 0
            variants.append(Variant(urljoin(base, line), bandwidth, pending.get("CODECS", "")))
            pending = None
    return variants


def choose_variant(variants: list[Variant]) -> Variant:
    """Die beste Variante bis PREFERRED_MAX_BANDWIDTH, sonst die kleinste."""
    fitting = [v for v in variants if 0 < v.bandwidth <= PREFERRED_MAX_BANDWIDTH and "flac" not in v.codecs.lower()]
    if fitting:
        return max(fitting, key=lambda v: v.bandwidth)
    return min(variants, key=lambda v: v.bandwidth or 10**12)


def parse_media(text: str, base: str) -> MediaPlaylist:
    playlist = MediaPlaylist(sequence=0, target_duration=6.0)
    for raw in text.splitlines():
        line = raw.strip()
        upper = line.upper()
        if upper.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            playlist.sequence = int(line.split(":", 1)[1] or 0)
        elif upper.startswith("#EXT-X-TARGETDURATION:"):
            playlist.target_duration = max(1.0, float(line.split(":", 1)[1] or 6))
        elif upper.startswith("#EXT-X-MAP:"):
            uri = _attributes(line.split(":", 1)[1]).get("URI")
            playlist.init = urljoin(base, uri) if uri else None
        elif upper.startswith("#EXT-X-KEY:"):
            method = _attributes(line.split(":", 1)[1]).get("METHOD", "NONE").upper()
            if method != "NONE":
                raise HlsError("Verschlüsselte HLS-Streams werden nicht unterstützt.")
        elif upper.startswith("#EXT-X-BYTERANGE"):
            raise HlsError("HLS mit Byte-Bereichen wird nicht unterstützt.")
        elif upper.startswith("#EXT-X-ENDLIST"):
            playlist.ended = True
        elif line and not line.startswith("#"):
            playlist.segments.append(urljoin(base, line))
    return playlist


def looks_like_hls(url: str, content_type: str) -> bool:
    content_type = content_type.split(";", 1)[0].strip().lower()
    return urlparse(url).path.lower().endswith(".m3u8") or content_type in {
        "application/vnd.apple.mpegurl",
        "application/x-mpegurl",
        "audio/mpegurl",
        "audio/x-mpegurl",
    }


class HlsReader:
    """Datei-artiges Objekt: read(n) liefert die Daten der Teilstuecke nacheinander.

    get_text(url) -> (Adresse nach Weiterleitungen, Text) und iter_bytes(url) -> Bytes-Stuecke
    machen die eigentlichen Abrufe (mit Pruefung gegen interne Adressen, siehe sources.py)."""

    def __init__(self, url: str, get_text, iter_bytes, wait=None) -> None:
        self._get_text, self._iter_bytes = get_text, iter_bytes
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait  # Tests: ohne echtes Warten
        self._buffer = bytearray()
        final_url, text = get_text(url)
        if "#EXTM3U" not in text[:1024].upper():
            raise HlsError("Das ist keine HLS-Playlist.")
        variants = parse_master(text, final_url)
        if variants:
            variant = choose_variant(variants)
            log.info("HLS: Variante %s (%s bit/s)", variant.url, variant.bandwidth or "?")
            final_url, text = get_text(variant.url)
        self.media_url = final_url
        self._first = parse_media(text, final_url)
        if not self._first.segments:
            raise HlsError("Die HLS-Playlist enthält keine Teilstücke.")
        self._chunks = self._run()

    @property
    def raw(self):  # wie requests.Response.raw - der Cog reicht .raw an FFmpeg
        return self

    def close(self) -> None:
        self._stop.set()

    def read(self, size: int = -1) -> bytes:
        size = CHUNK if size is None or size < 0 else size
        while len(self._buffer) < size and not self._stop.is_set():
            try:
                self._buffer += next(self._chunks)
            except StopIteration:
                break
            except Exception as error:  # Netzwerkfehler o.ae.: Ende des Streams
                log.warning("HLS beendet: %s", error)
                self._stop.set()
                break
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    def _run(self):
        playlist = self._first
        if playlist.ended:
            next_sequence = playlist.sequence
        else:
            next_sequence = playlist.sequence + max(0, len(playlist.segments) - LIVE_START_SEGMENTS)
        init_sent = None
        failures = 0
        while not self._stop.is_set():
            if playlist.init and playlist.init != init_sent:
                yield from self._iter_bytes(playlist.init)
                init_sent = playlist.init
            if next_sequence < playlist.sequence:  # zu langsam - Teilstuecke sind schon weg
                next_sequence = playlist.sequence
            for index, segment in enumerate(playlist.segments):
                if self._stop.is_set():
                    return
                if playlist.sequence + index < next_sequence:
                    continue
                next_sequence = playlist.sequence + index + 1
                try:
                    yield from self._iter_bytes(segment)
                    failures = 0
                except HlsError:
                    raise
                except Exception as error:  # ein Teilstueck fehlt: auslassen, bei mehreren aufgeben
                    failures += 1
                    if failures >= MAX_FAILURES:
                        raise
                    log.info("HLS-Teilstück übersprungen (%s)", error)
            if playlist.ended:
                return
            self._wait(playlist.target_duration / 2)
            if self._stop.is_set():
                return
            try:
                _, text = self._get_text(self.media_url)
                playlist = parse_media(text, self.media_url)
                failures = 0
            except HlsError:
                raise
            except Exception as error:
                failures += 1
                if failures >= MAX_FAILURES:
                    raise
                log.info("HLS-Playlist nicht abrufbar (%s), neuer Versuch", error)
