"""Verbindungsadresse eines Spiele-Servers fuer Spieler (Anzeige in Status, Karte, Banner).

Zusammengesetzt aus Host und Port:
- Host: was beim Server eingetragen ist, sonst die Standard-Spieladresse des
  Discord-Servers (Tab Server), sonst der Hostname aus PUBLIC_URL.
- Port: steht einer im Eintrag, gilt der; sonst der Spiel-Port, den AMP fuer die
  Instanz meldet ("Application Address"). Er wird bei jeder Anzeige frisch gelesen
  (kurz zwischengespeichert), damit eine Port-Aenderung in AMP von selbst mitkommt.

Mit AMP selbst spricht der Bot nie ueber diese Adresse, sondern ueber die Instanz-ID.
"""

import logging
import time
from urllib.parse import urlparse

from bot.core.config import settings
from bot.core.guild_config import get_config

log = logging.getLogger(__name__)

GAME_HOST_KEY = "game_host"  # guild_config: Standard-Spieladresse (Host ohne Port)
CACHE_SECONDS = 60
# Endpunkte, die nicht der Spiel-Port sind
_NOT_GAME = ("sftp", "query", "rcon", "web", "http", "ftp", "telnet")

_ports: dict[str, int] = {}
_ports_at = 0.0


def split_port(address: str) -> tuple[str, int | None]:
    """'host:2456' -> ('host', 2456); 'host' -> ('host', None); '[::1]:5' -> ('[::1]', 5)."""
    address = (address or "").strip()
    head, sep, tail = address.rpartition(":")
    if sep and tail.isdigit() and head and (head.count(":") == 0 or head.endswith("]")):
        return head, int(tail)
    return address, None


def _field(endpoint, name: str) -> str:
    value = endpoint.get(name) if isinstance(endpoint, dict) else getattr(endpoint, name, None)
    return str(value or "")


def game_port(endpoints) -> int | None:
    """Spiel-Port aus AMPs ApplicationEndpoints: bevorzugt 'Application Address',
    sonst der erste Endpunkt, der nicht SFTP/Query/RCON/Web ist."""
    endpoints = list(endpoints or [])

    def port_of(endpoint) -> int | None:
        return split_port(_field(endpoint, "Endpoint"))[1]

    for endpoint in endpoints:
        name = _field(endpoint, "DisplayName").lower()
        if ("application" in name or "game" in name) and port_of(endpoint):
            return port_of(endpoint)
    for endpoint in endpoints:
        name = _field(endpoint, "DisplayName").lower()
        if not any(word in name for word in _NOT_GAME) and port_of(endpoint):
            return port_of(endpoint)
    return None


def public_host() -> str | None:
    """Hostname aus PUBLIC_URL (letzte Rueckfallstufe fuer den Host)."""
    if not settings.public_url:
        return None
    return urlparse(settings.public_url if "://" in settings.public_url else f"//{settings.public_url}").hostname


async def instance_ports() -> dict[str, int]:
    """Instanz-ID -> Spiel-Port laut AMP, zwischengespeichert."""
    global _ports, _ports_at
    if time.monotonic() - _ports_at < CACHE_SECONDS:
        return _ports
    from bot.core.amp_client import amp_client  # spaet, damit der Import billig bleibt

    try:
        instances = await amp_client.list_instances()
        _ports = {i.instance_id: port for i in instances if (port := game_port(i.endpoints))}
    except Exception as error:  # AMP nicht erreichbar: alte Werte behalten
        log.debug("Spiel-Ports nicht lesbar: %s", error)
    _ports_at = time.monotonic()
    return _ports


def clear_cache() -> None:
    global _ports, _ports_at
    _ports, _ports_at = {}, 0.0


async def default_host(guild_id: int) -> str | None:
    host = split_port(await get_config(guild_id, GAME_HOST_KEY) or "")[0]
    return host or public_host()


async def connect_address(server) -> str:
    """Adresse fuer Spieler, z.B. 'spiel.example.org:2456' - leer, wenn kein Host bekannt ist."""
    host, port = split_port(server.host or "")
    if not host:
        host = await default_host(server.guild_id) or ""
    if not host:
        return ""
    if port is None:
        port = (await instance_ports()).get(server.amp_instance_id)
    return f"{host}:{port}" if port else host
