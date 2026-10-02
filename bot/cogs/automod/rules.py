"""Regeln des automod-Cogs - nur, was Discords eingebauter AutoMod nicht kann
(Stichwoerter, Erwaehnungs-Spam und verdaechtige Inhalte macht Discord selbst,
deren Treffer verarbeitet schon der moderation-Cog).

Ohne Discord-Abhaengigkeit, damit testbar.
"""

import copy
import re
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

DEFAULT_CONFIG: dict = {
    "enabled": False,
    "flood": {"on": True, "messages": 6, "seconds": 8},
    "duplicates": {"on": True, "count": 3, "seconds": 60},
    "caps": {"on": True, "percent": 70, "min_length": 12},
    "emojis": {"on": True, "max": 10},
    "links": {"mode": "off", "allow": []},  # off | allowlist | block
    "new_accounts_days": 0,  # 0 = aus; sonst Hinweis bei Beitritt juengerer Konten
    "action": {"delete": True, "points": 0, "timeout_minutes": 0},
    "exempt_channels": [],
    "exempt_roles": [],
}

URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
INVITE = re.compile(r"(?:discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.IGNORECASE)
CUSTOM_EMOJI = re.compile(r"<a?:\w+:\d+>")
UNICODE_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿]")


def merged_config(stored: dict | None) -> dict:
    """Gespeicherte Werte ueber die Standardwerte legen - neue Regeln in spaeteren
    Versionen bekommen so automatisch ihren Standard."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    for key, value in (stored or {}).items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def caps_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def count_emojis(text: str) -> int:
    without_custom = CUSTOM_EMOJI.sub("", text)
    return len(CUSTOM_EMOJI.findall(text)) + len(UNICODE_EMOJI.findall(without_custom))


def extract_domains(text: str) -> list[str]:
    domains = []
    for url in URL.findall(text):
        host = urlparse(url).hostname
        if host:
            domains.append(host.lower().removeprefix("www."))
    if INVITE.search(text):
        domains.append("discord.gg")
    return domains


def domain_allowed(domain: str, allowlist: list[str]) -> bool:
    """example.org erlaubt auch sub.example.org."""
    domain = domain.lower()
    for allowed in allowlist:
        allowed = allowed.lower().strip().removeprefix("www.")
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


class MessageHistory:
    """Letzte Nachrichten pro (Server, Mitglied) fuer Flut- und Wiederholungs-Erkennung."""

    def __init__(self, keep_seconds: int = 300) -> None:
        self.keep_seconds = keep_seconds
        self._items: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(deque)

    def add(self, key: tuple[int, int], text: str, at: float | None = None) -> deque[tuple[float, str]]:
        at = time.monotonic() if at is None else at
        items = self._items[key]
        items.append((at, normalize(text)))
        while items and at - items[0][0] > self.keep_seconds:
            items.popleft()
        return items


def check_message(config: dict, text: str, recent: deque[tuple[float, str]], at: float) -> str | None:
    """Grund des Verstosses oder None. `recent` enthaelt die Nachricht schon."""
    flood = config["flood"]
    if flood["on"] and sum(1 for t, _ in recent if at - t <= flood["seconds"]) > flood["messages"]:
        return f"Zu viele Nachrichten in kurzer Zeit (mehr als {flood['messages']} in {flood['seconds']} s)"

    duplicates = config["duplicates"]
    current = normalize(text)
    if duplicates["on"] and current:
        same = sum(1 for t, body in recent if body == current and at - t <= duplicates["seconds"])
        if same >= duplicates["count"]:
            return f"Gleiche Nachricht {same}× wiederholt"

    caps = config["caps"]
    letters = sum(1 for c in text if c.isalpha())
    if caps["on"] and letters >= caps["min_length"] and caps_ratio(text) * 100 >= caps["percent"]:
        return "Zu viele Großbuchstaben"

    emojis = config["emojis"]
    if emojis["on"] and count_emojis(text) > emojis["max"]:
        return f"Zu viele Emojis (mehr als {emojis['max']})"

    links = config["links"]
    if links["mode"] != "off":
        domains = extract_domains(text)
        if links["mode"] == "block" and domains:
            return "Links sind hier nicht erlaubt"
        if links["mode"] == "allowlist":
            blocked = [d for d in domains if not domain_allowed(d, links["allow"])]
            if blocked:
                return f"Link nicht erlaubt ({blocked[0]})"
    return None
