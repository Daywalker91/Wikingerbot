import re
from typing import Literal

BUILTIN_FILTER_PATTERNS: dict[str, str] = {
    "map_points_saved": r"Saved \d+ map points to disk",
    "zdos_connections": r"^Connections \d+ \S+\s+sent:\d+ recv:\d+",
}

BUILTIN_EVENT_PATTERNS: dict[str, str] = {
    "joined": r"\bjoined\b",
    "connected": r"\bconnected\b",
    "entered": r"\bhas entered\b",
    "left": r"\bleft the game\b",
    "disconnected": r"\bdisconnected\b",
    "has_left": r"\bhas left\b",
    "logged_in": r"\blogged in\b",
    "logged_out": r"\blogged out\b",
}

ClassifyResult = Literal["console", "event", "suppress"]


def _any_match(contents: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, contents, re.IGNORECASE) for pattern in patterns)


def active_builtin_patterns(builtins: dict[str, str], disabled_keys: set[str]) -> list[str]:
    """Eingebaute Muster, deren Key nicht in disabled_keys steht (per-Server Override)."""
    return [pattern for key, pattern in builtins.items() if key not in disabled_keys]


def classify(
    contents: str,
    *,
    filter_mode: str,
    active_builtin_filters: list[str],
    custom_filter_patterns: list[str],
    active_builtin_events: list[str],
    custom_event_patterns: list[str],
) -> ClassifyResult:
    """Entscheidet, wohin eine Konsolenzeile geht: Event-Kanal, Konsolen-Kanal oder gar nicht.

    Event-Muster haben immer Vorrang vor der Filter-Unterdrueckung - eine
    Zeile, die wie ein Join/Leave-Event aussieht, geht auch dann in den
    Event-Kanal, wenn sie zufaellig auch ein Filter-Muster trifft.
    """
    event_patterns = active_builtin_events + custom_event_patterns
    if event_patterns and _any_match(contents, event_patterns):
        return "event"

    if filter_mode == "blacklist":
        blacklist_patterns = active_builtin_filters + custom_filter_patterns
        if blacklist_patterns and _any_match(contents, blacklist_patterns):
            return "suppress"
    elif filter_mode == "whitelist":
        # Eingebaute Muster sind Rausch-Definitionen (Blacklist-Semantik) und
        # ergeben als Allow-Liste keinen Sinn - nur eigene Muster gelten hier.
        if not custom_filter_patterns or not _any_match(contents, custom_filter_patterns):
            return "suppress"

    return "console"
