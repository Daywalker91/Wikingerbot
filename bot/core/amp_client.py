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
    # AMPs Klassifikator fuer das Instanz-Artwork, z.B. "steam:1326470" fuer
    # Steam-basierte Spiele-Server - treibt den automatischen Steam-Artwork-Abruf
    # im banner-Cog (siehe bot/core/steam_art.py).
    display_image_source: str


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
                        display_image_source=instance.DisplayImageSource,
                    )
                )
        return discovered

    async def get_status(self, instance_id: str):
        return await _with_timeout(
            self._instance_client(instance_id).Core.GetStatus(), DEFAULT_TIMEOUT
        )

    async def start(self, instance_id: str) -> None:
        """Startet eine Instanz - welcher Weg noetig ist, haengt vom ADS-Status ab.

        Ist die Instanz komplett aus, ist ihre eigene Mini-API (fuer Core.Start
        ueber die Pro-Instanz-Session) nicht erreichbar - der Start muss dann
        ueber ADSModule.StartInstance am Controller laufen, was ueblicherweise
        Huelle und Anwendung zusammen hochfaehrt. Laeuft die ADS-Instanz aber
        schon (z.B. nach einem zuvor abgebrochenen Start), wuerde ein erneuter
        ADSModule.StartInstance-Aufruf nur die bereits laufende Huelle nochmal
        antriggern, ohne die Anwendung darin zu starten - dann reicht/braucht
        es direkt Core.Start() auf der Instanz-Session.
        """
        if await self._is_instance_running(instance_id):
            await self._core_start(instance_id)
            return

        await _with_timeout(
            self._controller_client().ADSModule.StartInstance(InstanceName=instance_id),
            START_STOP_TIMEOUT,
        )

    async def _is_instance_running(self, instance_id: str) -> bool:
        """Ob die ADS-Instanz selbst (nicht die Anwendung darin) laut Controller laeuft.

        Nutzt list_instances() statt get_status(), da Letzteres genau dann nicht
        erreichbar ist, wenn die Instanz komplett aus ist - der Fall, den wir
        hier gerade unterscheiden muessen. Schlaegt die Abfrage fehl, gilt die
        Instanz sicherheitshalber als nicht laufend (fuehrt zum bekannten,
        langsameren aber verlaesslicheren ADSModule.StartInstance-Pfad)."""
        try:
            instances = await self.list_instances()
        except Exception:
            return False
        return any(i.instance_id == instance_id and i.running for i in instances)

    async def _core_start(self, instance_id: str) -> None:
        """Ruft Core.Start() auf der Instanz-Session auf - direkt per api_call statt
        ueber den generierten Core.Start()-Wrapper, da dieser die Antwort in ein
        generisches ActionResult zu deserialisieren versucht (ampapi/dataclass_wizard
        kann Optional[T] ohne konkreten Typparameter nicht auflösen und wirft dabei
        einen TypeError, obwohl der Aufruf serverseitig durchlaeuft). Die Antwort
        wird hier nicht ausgewertet, api_call() umgeht die kaputte Deserialisierung."""
        core = self._instance_client(instance_id).Core
        await _with_timeout(core.api_call("Core/Start", {}), DEFAULT_TIMEOUT)

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
