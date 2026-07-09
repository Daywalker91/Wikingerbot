"""Steam-Store-Artwork fuer Banner-Hintergruende.

AMPs ADSModule.GetInstances() liefert pro Instanz ein DisplayImageSource-Feld
(z.B. "steam:1326470" fuer Steam-basierte Spiele-Server). Steams CDN stellt
das Store-Header-Bild oeffentlich ohne API-Key bereit - damit lassen sich
Banner-Hintergruende automatisch mit echtem Spiel-Artwork befuellen, ganz
ohne mitgelieferte Assets oder manuelle Konfiguration.
"""

import re
from pathlib import Path

import httpx

STEAM_APPID_PATTERN = re.compile(r"^steam:(\d+)$")
STEAM_HEADER_URL = "https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"
CACHE_DIR = Path("data/banner_backgrounds/steam_cache")
FETCH_TIMEOUT = 5.0


def parse_steam_appid(display_image_source: str) -> int | None:
    """Extrahiert die Steam-App-ID aus AMPs DisplayImageSource, falls vorhanden."""
    match = STEAM_APPID_PATTERN.match(display_image_source)
    return int(match.group(1)) if match else None


async def fetch_header_image(appid: int) -> Path | None:
    """Liefert den lokalen Pfad zum Steam-Header-Bild einer App-ID, laedt bei Bedarf herunter.

    Store-Artwork aendert sich praktisch nie, daher kein Cache-Refresh - einmal
    heruntergeladen wird die Datei dauerhaft wiederverwendet. Bei jedem Fehler
    (ungueltige AppID, kein Netz, Nicht-200) wird None zurueckgegeben statt zu
    werfen, damit der Banner auf die naechste Hintergrund-Prioritaet zurueckfaellt.
    """
    cached = CACHE_DIR / f"{appid}.jpg"
    if cached.exists():
        return cached

    try:
        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT) as client:
            response = await client.get(STEAM_HEADER_URL.format(appid=appid))
    except httpx.HTTPError:
        return None

    if response.status_code != 200:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(response.content)
    return cached
