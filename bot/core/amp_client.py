from dataclasses import dataclass

from ampapi.auth import RefreshingAuthProviderAsync
from ampapi.modules import ADSAsync, CommonAPIAsync

from bot.core.config import settings


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
        self._instances: dict[str, CommonAPIAsync] = {}

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

    def _instance_client(self, instance_id: str) -> CommonAPIAsync:
        if instance_id not in self._instances:
            panel_url = f"{settings.amp_url}/API/ADSModule/Servers/{instance_id}"
            self._instances[instance_id] = CommonAPIAsync(self._auth(panel_url))
        return self._instances[instance_id]

    async def list_instances(self) -> list[DiscoveredInstance]:
        """Listet alle am Controller bekannten Instanzen (fuer /server discover)."""
        controller = self._controller_client()
        nodes = await controller.ADSModule.GetInstances(ForceIncludeSelf=False)
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
        return await self._instance_client(instance_id).Core.GetStatus()

    async def start(self, instance_id: str) -> None:
        await self._instance_client(instance_id).Core.Start()

    async def stop(self, instance_id: str) -> None:
        await self._instance_client(instance_id).Core.Stop()

    async def send_console_message(self, instance_id: str, message: str) -> None:
        await self._instance_client(instance_id).Core.SendConsoleMessage(message)

    async def poll_console(self, instance_id: str) -> list[ConsoleLine]:
        """Neue Konsolenzeilen seit dem letzten Poll dieser Instanz-Session."""
        updates = await self._instance_client(instance_id).Core.GetUpdates()
        return [
            ConsoleLine(contents=entry.Contents, source=entry.Source, type=entry.Type)
            for entry in updates.ConsoleEntries
        ]


amp_client = AMPClient()
