"""Warteschlange pro Server - ohne Discord-Abhaengigkeit, damit testbar.
Das eigentliche Abspielen (FFmpeg, VoiceClient) macht der Cog."""

import random
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

MAX_QUEUE = 200


@dataclass
class Track:
    title: str
    source: str  # URL oder absoluter Dateipfad
    kind: Literal["stream", "file"]
    requester_id: int
    label: str = ""  # z.B. "Radio", "Podcast", "Datei" - fuer die Anzeige


@dataclass
class GuildPlayer:
    guild_id: int
    volume: float = 0.5
    queue: deque[Track] = field(default_factory=deque)
    current: Track | None = None
    idle_since: float = field(default_factory=time.monotonic)

    def add(self, *tracks: Track) -> int:
        """Haengt Titel an; gibt zurueck, wie viele tatsaechlich Platz hatten."""
        room = max(0, MAX_QUEUE - len(self.queue))
        added = list(tracks)[:room]
        self.queue.extend(added)
        return len(added)

    def next(self) -> Track | None:
        self.current = self.queue.popleft() if self.queue else None
        if self.current is None:
            self.idle_since = time.monotonic()
        return self.current

    def clear(self) -> None:
        self.queue.clear()
        self.current = None
        self.idle_since = time.monotonic()

    def shuffle(self) -> None:
        items = list(self.queue)
        random.shuffle(items)
        self.queue = deque(items)

    def set_volume(self, percent: int) -> float:
        self.volume = max(0, min(percent, 100)) / 100
        return self.volume

    def idle_seconds(self) -> float:
        return 0.0 if self.current else time.monotonic() - self.idle_since
