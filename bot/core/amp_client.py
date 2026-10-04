import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, TypeVar

from ampapi.auth import BasicAuthProviderAsync, RefreshingAuthProviderAsync
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


async def _raw_call(module, endpoint: str, args: dict) -> None:
    """Ruft einen AMP-Endpunkt direkt per api_call() auf, ohne die Antwort in ein
    generisches ActionResult zu deserialisieren.

    ampapi/dataclass_wizard kann Optional[T] ohne konkreten Typparameter nicht
    auflösen und wirft dabei einen TypeError ("issubclass() arg 1 must be a
    class"), obwohl der Aufruf serverseitig laengst durchgelaufen ist - live
    beobachtet bei ADSModule.StartInstance/StopInstance und Core.Start, die
    alle drei ein bares (nicht generisch parametrisiertes) ActionResult
    zurueckgeben. Die Antwort wird hier nicht ausgewertet (keiner unserer
    Aufrufer braucht sie), api_call() umgeht die kaputte Deserialisierung."""
    await module.api_call(endpoint, args)


def instance_name_from_path(path: Path) -> str | None:
    """AMP legt jede Instanz unter .../instances/<InstanzName>/ an - laeuft der Bot
    selbst in AMP, steckt sein eigener Instanzname also in seinem Pfad."""
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part.lower() == "instances":
            return parts[index + 1]
    return None


def own_instance_ids() -> set[str]:
    """Name/ID der AMP-Instanz, in der der Bot selbst laeuft (wird ueberall
    ausgeblendet, damit er sich nicht selbst stoppen kann). AMP_OWN_INSTANCE
    hat Vorrang - noetig im Docker-Modus, wo der Pfad den Namen nicht enthaelt."""
    if settings.amp_own_instance:
        return {settings.amp_own_instance.lower()}
    name = instance_name_from_path(Path(__file__).resolve())
    return {name.lower()} if name else set()


def web_url_from_endpoints(endpoints: list[dict]) -> str | None:
    """Erste brauchbare http-Adresse aus AMPs ApplicationEndpoints."""
    for endpoint in endpoints:
        uri = str(endpoint.get("Uri") or "")
        address = str(endpoint.get("Endpoint") or "")
        if uri.startswith(("http://", "https://")):
            candidate = uri
        elif address:
            candidate = f"http://{address}"
        else:
            continue
        host = candidate.split("://", 1)[1].split(":", 1)[0].split("/", 1)[0]
        if host and host not in {"0.0.0.0", "127.0.0.1", "localhost", "::"}:
            return candidate.rstrip("/")
    return None


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
    # AMPs ApplicationEndpoints (DisplayName/Endpoint/Uri) - liefert den Spiel-Port
    # fuer die Verbindungsadresse (bot/core/server_address.py)
    endpoints: list = field(default_factory=list)


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
        """Listet alle am Controller bekannten Spiele-Instanzen (fuer /server discover).

        Instanzen mit Module "ADS" sind der Controller selbst bzw. dessen
        verwaltete ADS-Knoten, keine Spiele-Server - die sollen sich nirgends
        (weder Discord-Autocomplete/-discover noch WebUI) versehentlich
        anlegen/starten/stoppen lassen, deshalb hier zentral herausgefiltert.
        Aus demselben Grund fehlt die Instanz, in der der Bot selbst laeuft.
        """
        controller = self._controller_client()
        nodes = await _with_timeout(
            controller.ADSModule.GetInstances(ForceIncludeSelf=False), DEFAULT_TIMEOUT
        )
        own = own_instance_ids()
        discovered = []
        for node in nodes:
            for instance in node.AvailableInstances:
                if instance.Module == "ADS":
                    continue
                if own & {str(getattr(instance, "InstanceName", "")).lower(), str(instance.InstanceID).lower()}:
                    continue
                discovered.append(
                    DiscoveredInstance(
                        instance_id=instance.InstanceID,
                        friendly_name=instance.FriendlyName,
                        module=instance.Module,
                        running=instance.Running,
                        display_image_source=instance.DisplayImageSource,
                        endpoints=list(getattr(instance, "ApplicationEndpoints", None) or []),
                    )
                )
        return discovered

    async def own_web_url(self) -> str | None:
        """Adresse der eigenen Instanz laut AMP (Vorlage: Meta.EndpointURIFormat
        http://{ip}:{port}) - fuer /bot web, wenn PUBLIC_URL fehlt. None, wenn AMP
        keine brauchbare Adresse kennt (z.B. nur 0.0.0.0)."""
        own = own_instance_ids()
        if not own:
            return None
        controller = self._controller_client()
        nodes = await _with_timeout(controller.api_call("ADSModule/GetInstances", {"ForceIncludeSelf": True}), DEFAULT_TIMEOUT)
        if isinstance(nodes, dict) and "result" in nodes:
            nodes = nodes["result"]
        for node in nodes or []:
            for instance in node.get("AvailableInstances", []):
                ids = {str(instance.get("InstanceName", "")).lower(), str(instance.get("InstanceID", "")).lower()}
                if not own & ids:
                    continue
                return web_url_from_endpoints(instance.get("ApplicationEndpoints") or [])
        return None

    async def controller_instance_ids(self) -> list[str]:
        """Instanz-ID(s) des Controllers selbst (Module "ADS") - "Manage" darauf ist in AMP
        das Recht, sich am Panel anzumelden (fuer bot/cogs/ampkonten/role_setup.py)."""
        controller = self._controller_client()
        nodes = await _with_timeout(controller.api_call("ADSModule/GetInstances", {"ForceIncludeSelf": True}), DEFAULT_TIMEOUT)
        if isinstance(nodes, dict) and "result" in nodes:
            nodes = nodes["result"]
        nodes = nodes or []
        # Bei Controller/Target-Setups hat jedes Target ein eigenes ADS - angemeldet
        # wird aber nur am Controller, also nur dessen lokalen Knoten nehmen.
        local = [node for node in nodes if not node.get("IsRemote")]
        return [
            str(instance.get("InstanceID"))
            for node in local or nodes
            for instance in node.get("AvailableInstances", [])
            if instance.get("Module") == "ADS" and instance.get("InstanceID")
        ]

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
            await _with_timeout(
                _raw_call(self._instance_client(instance_id).Core, "Core/Start", {}), DEFAULT_TIMEOUT
            )
            return

        await _with_timeout(
            _raw_call(
                self._controller_client().ADSModule,
                "ADSModule/StartInstance",
                {"InstanceName": instance_id},
            ),
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

    async def stop(self, instance_id: str) -> None:
        await _with_timeout(
            _raw_call(
                self._controller_client().ADSModule,
                "ADSModule/StopInstance",
                {"InstanceName": instance_id},
            ),
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

    async def remove_whitelist(self, instance_id: str, ign: str) -> None:
        """Gegenstueck zu add_whitelist (nur Minecraft-Instanzen, best-effort)."""
        await _with_timeout(
            self._instance_client(instance_id).MinecraftModule.RemoveWhitelistEntry(UserOrUUID=ign),
            DEFAULT_TIMEOUT,
        )

    # --- Rollen und Rechte am Controller (fuer bot/core/amp_role.py) ---------------
    # Bewusst roh per api_call: ampapis Deserialisierung ist bei diesen Typen
    # unzuverlaessig (siehe _raw_call), und wir brauchen nur einfache JSON-Werte.

    async def core_call(self, endpoint: str, args: dict | None = None):
        """Ruft einen Core-Endpunkt am Controller auf und gibt das rohe JSON zurueck.
        Aeltere AMP-Versionen verpacken das Ergebnis in {"result": ...} - das wird
        hier einheitlich ausgepackt."""
        result = await _with_timeout(
            self._controller_client().Core.api_call(f"Core/{endpoint}", args or {}), DEFAULT_TIMEOUT
        )
        if isinstance(result, dict) and set(result) == {"result"}:
            return result["result"]
        return result

    def fresh_calls(self, username: str = "", password: str = "", token: str = ""):
        """(controller_call, instance_call) mit FRISCHER Anmeldung - fuer Aufgaben mit mehr
        Rechten als der Bot sonst hat (z.B. Rollen einrichten).

        Ohne Zugangsdaten: der Bot-Benutzer (gerade vergebene Super Admins gelten so sofort -
        AMP legt die Rechte einer Sitzung beim Anmelden fest). Mit Zugangsdaten: ein Konto
        eines Admins, einmalig fuer diese Aufgabe - nichts davon wird gespeichert oder
        geloggt, keine "angemeldet bleiben"-Sitzung. Die laufenden Sitzungen des Bots
        (Konsole, Status) bleiben in beiden Faellen unberuehrt."""

        def auth(panel_url: str):
            if not username:
                return self._auth(panel_url)
            return BasicAuthProviderAsync(panelUrl=panel_url, username=username, password=password, token=token, rememberMe=False)

        controller = ADSAsync(auth(settings.amp_url))
        instances: dict[str, MinecraftAsync] = {}

        def unwrap(result):
            if isinstance(result, dict) and set(result) == {"result"}:
                return result["result"]
            return result

        async def controller_call(endpoint: str, args: dict | None = None):
            return unwrap(await _with_timeout(controller.Core.api_call(f"Core/{endpoint}", args or {}), DEFAULT_TIMEOUT))

        async def instance_call(instance_id: str, endpoint: str, args: dict | None = None):
            if instance_id not in instances:
                instances[instance_id] = MinecraftAsync(auth(f"{settings.amp_url}/API/ADSModule/Servers/{instance_id}"))
            client = instances[instance_id]
            return unwrap(await _with_timeout(client.Core.api_call(f"Core/{endpoint}", args or {}), DEFAULT_TIMEOUT))

        return controller_call, instance_call

    async def instance_core_call(self, instance_id: str, endpoint: str, args: dict | None = None):
        """Wie core_call, aber in einer Instanz (z.B. Rollen-Rechte dieser Instanz)."""
        result = await _with_timeout(
            self._instance_client(instance_id).Core.api_call(f"Core/{endpoint}", args or {}), DEFAULT_TIMEOUT
        )
        if isinstance(result, dict) and set(result) == {"result"}:
            return result["result"]
        return result

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
