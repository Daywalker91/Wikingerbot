import asyncio
from dataclasses import dataclass
from typing import Awaitable, TypeVar

from ampapi.auth import RefreshingAuthProviderAsync
from ampapi.modules import ADSAsync, MinecraftAsync

from bot.core.config import settings

T = TypeVar("T")

# ampapi nutzt aiohttp ohne eigenes Timeout (Standard waere 5 Minuten). Damit ein
# langsamer/nicht erreichbarer AMP-Node den Bot nicht so lange blockiert, wird
# hier ein eigenes, kurzes Timeout erzwungen.
DEFAULT_TIMEOUT = 10.0
START_STOP_TIMEOUT = 30.0  # Start/Stop kann laut AMP-Logs legitim >15s dauern


async def _with_timeout(awaitable: Awaitable[T], timeout: float) -> T:
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(f"AMP hat nach {timeout:.0f}s nicht geantwortet") from None


@dataclass
class DiscoveredInstance:
    instance_id: str
    friendly_name: str
    module: str
    running: bool


@dataclass
class ConsoleLine:
    contents: str
    source: str
    type: str


class AMPClient:
    """Verwaltet die AMP-Controller- und Pro-Instanz-Sessions.

    Alle Instanzen haengen an einem einzigen AMP-Controller (AMP_URL) und werden
    ueber ihre amp_instance_id per Pfad-Praefix adressiert
    (/API/ADSModule/Servers/{id}/API/), nicht ueber eigene Host/Ports. Core.GetUpdates
    liefert serverseitig inkrementell nur neue Eintraege seit dem letzten Aufruf
    derselben Session - deshalb wird pro Instanz dieselbe Session wiederverwendet.
    """

    def __init__(self) -> None:
        self._controller: ADSAsync | None = None
        self._instances: dict[str, MinecraftAsync] = {}

    def _auth(self, panel_url: str) -> RefreshingAuthProviderAsync:
        return RefreshingAuthProviderAsync(
            panelUrl=panel_url,
            username=settings.amp_user,
            password=settings.amp_password,
        )

    def _controller_client(self) -> ADSAsync:
        if self._controller is None:
            self._controller = ADSAsync(self._auth(settings.amp_url))
        return self._controller

    def _instance_client(self, instance_id: str) -> MinecraftAsync:
        """Gibt einen Pro-Instanz-Client zurueck.

        MinecraftAsync statt CommonAPIAsync, damit MinecraftModule (fuer
        add_whitelist) verfuegbar ist. Core bleibt identisch nutzbar - fuer
        Nicht-Minecraft-Instanzen bleibt MinecraftModule einfach ungenutzt.
        """
        if instance_id not in self._instances:
            panel_url = f"{settings.amp_url}/API/ADSModule/Servers/{instance_id}"
            self._instances[instance_id] = MinecraftAsync(self._auth(panel_url))
        return self._instances[instance_id]

    async def list_instances(self) -> list[DiscoveredInstance]:
        """Listet alle am Controller bekannten Instanzen (fuer /server discover)."""
        controller = self._controller_client()
        nodes = await _with_timeout(
            controller.ADSModule.GetInstances(ForceIncludeSelf=False), DEFAULT_TIMEOUT
        )
        discovered = []
        for node in nodes:
            for instance in node.AvailableInstances:
                discovered.append(
                    DiscoveredInstance(
                        instance_id=instance.InstanceID,
                        friendly_name=instance.FriendlyName,
                        module=instance.Module,
                        running=instance.Running,
                    )
                )
        return discovered

    async def get_status(self, instance_id: str):
        return await _with_timeout(
            self._instance_client(instance_id).Core.GetStatus(), DEFAULT_TIMEOUT
        )

    async def start(self, instance_id: str) -> None:
        """Startet eine Instanz ueber den Controller.

        Waehrend eine Instanz komplett gestoppt ist, ist ihre eigene Mini-API
        (fuer Core.Start ueber die Pro-Instanz-Session) nicht erreichbar - der
        Start muss deshalb ueber ADSModule.StartInstance am Controller laufen.
        """
        await _with_timeout(
            self._controller_client().ADSModule.StartInstance(InstanceName=instance_id),
            START_STOP_TIMEOUT,
        )

    async def stop(self, instance_id: str) -> None:
        await _with_timeout(
            self._controller_client().ADSModule.StopInstance(InstanceName=instance_id),
            START_STOP_TIMEOUT,
        )

    async def send_console_message(self, instance_id: str, message: str) -> None:
        await _with_timeout(
            self._instance_client(instance_id).Core.SendConsoleMessage(message), DEFAULT_TIMEOUT
        )

    async def add_whitelist(self, instance_id: str, ign: str) -> None:
        """Fuegt einen Spieler zur AMP-Whitelist hinzu (nur Minecraft-Instanzen).

        Best-effort: bei anderen Spiel-Modulen (GenericModule etc.) schlaegt
        der Aufruf fehl, die Rufer-Seite (whitelist-Cog) faengt das ab.
        """
        await _with_timeout(
            self._instance_client(instance_id).MinecraftModule.AddToWhitelist(UserOrUUID=ign),
            DEFAULT_TIMEOUT,
        )

    async def poll_console(self, instance_id: str) -> list[ConsoleLine]:
        """Neue Konsolenzeilen seit dem letzten Poll dieser Instanz-Session."""
        updates = await _with_timeout(
            self._instance_client(instance_id).Core.GetUpdates(), DEFAULT_TIMEOUT
        )
        return [
            ConsoleLine(contents=entry.Contents, source=entry.Source, type=entry.Type)
            for entry in updates.ConsoleEntries
        ]


amp_client = AMPClient()
