"""Zeitzone der Community (Einstellung TIMEZONE, Standard Europe/Berlin)."""

import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot.core.config import settings

log = logging.getLogger("wikingerbot")


def community_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("Unbekannte Zeitzone %r - nehme UTC", settings.timezone)
        return ZoneInfo("UTC")
