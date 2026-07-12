from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.core.amp_client import AMPClient
from bot.core.config import settings


def _fake_client(core: SimpleNamespace | None = None, minecraft_module: SimpleNamespace | None = None) -> SimpleNamespace:
    return SimpleNamespace(Core=core, MinecraftModule=minecraft_module)


async def test_poll_console_returns_entries():
    entry = SimpleNamespace(Contents="Hello", Source="Server", Type="Console")
    core = SimpleNamespace(GetUpdates=AsyncMock(return_value=SimpleNamespace(ConsoleEntries=[entry])))
    client = AMPClient()
    client._instance_client = lambda instance_id: _fake_client(core)

    lines = await client.poll_console("abc")

    assert len(lines) == 1
    assert lines[0].contents == "Hello"
    assert lines[0].source == "Server"


def _node(instances: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(AvailableInstances=instances)


def _instance(instance_id: str, running: bool, module: str = "Minecraft") -> SimpleNamespace:
    return SimpleNamespace(
        InstanceID=instance_id,
        FriendlyName=instance_id,
        Module=module,
        Running=running,
        DisplayImageSource="",
    )


async def test_list_instances_excludes_ads_module_entries():
    ads_module = SimpleNamespace(
        GetInstances=AsyncMock(
            return_value=[
                _node([_instance("game-1", True), _instance("ads-1", True, module="ADS")])
            ]
        )
    )
    controller = SimpleNamespace(ADSModule=ads_module)
    client = AMPClient()
    client._controller_client = lambda: controller

    instances = await client.list_instances()

    assert [i.instance_id for i in instances] == ["game-1"]


async def test_start_stop_calls_controller_ads_module_via_raw_api_call():
    # api_call() statt der generierten StartInstance/StopInstance-Wrapper, da
    # diese ein bares ActionResult deserialisieren wollen und dabei an einem
    # ampapi/dataclass_wizard-Bug scheitern (siehe _raw_call-Docstring).
    ads_module = SimpleNamespace(
        api_call=AsyncMock(return_value={}),
        GetInstances=AsyncMock(return_value=[_node([_instance("abc", False)])]),
    )
    controller = SimpleNamespace(ADSModule=ads_module)
    client = AMPClient()
    client._controller_client = lambda: controller

    await client.start("abc")
    await client.stop("abc")

    ads_module.api_call.assert_any_call("ADSModule/StartInstance", {"InstanceName": "abc"})
    ads_module.api_call.assert_any_call("ADSModule/StopInstance", {"InstanceName": "abc"})


async def test_start_calls_core_start_directly_when_instance_already_running():
    # Live beobachteter Randfall: ADS-Instanz lief schon (z.B. nach einem zuvor
    # abgebrochenen Start) - ein erneuter ADSModule.StartInstance-Aufruf wuerde
    # die Anwendung darin nicht mitstarten, Core.Start() auf der Instanz-
    # Session direkt ist dann der richtige Weg.
    ads_module = SimpleNamespace(
        api_call=AsyncMock(return_value={}),
        GetInstances=AsyncMock(return_value=[_node([_instance("abc", True)])]),
    )
    controller = SimpleNamespace(ADSModule=ads_module)
    core = SimpleNamespace(api_call=AsyncMock(return_value={}))
    client = AMPClient()
    client._controller_client = lambda: controller
    client._instance_client = lambda instance_id: _fake_client(core)

    await client.start("abc")

    core.api_call.assert_awaited_once_with("Core/Start", {})
    ads_module.api_call.assert_not_awaited()


async def test_start_uses_start_instance_when_list_instances_fails():
    ads_module = SimpleNamespace(
        api_call=AsyncMock(return_value={}),
        GetInstances=AsyncMock(side_effect=Exception("kein Netz")),
    )
    controller = SimpleNamespace(ADSModule=ads_module)
    client = AMPClient()
    client._controller_client = lambda: controller

    await client.start("abc")  # darf nicht werfen

    ads_module.api_call.assert_awaited_once_with("ADSModule/StartInstance", {"InstanceName": "abc"})


async def test_send_console_message_forwards_to_core():
    core = SimpleNamespace(SendConsoleMessage=AsyncMock())
    client = AMPClient()
    client._instance_client = lambda instance_id: _fake_client(core)

    await client.send_console_message("abc", "say hello")

    core.SendConsoleMessage.assert_awaited_once_with("say hello")


async def test_add_whitelist_forwards_to_minecraft_module():
    minecraft_module = SimpleNamespace(AddToWhitelist=AsyncMock())
    client = AMPClient()
    client._instance_client = lambda instance_id: _fake_client(minecraft_module=minecraft_module)

    await client.add_whitelist("abc", "Steve123")

    minecraft_module.AddToWhitelist.assert_awaited_once_with(UserOrUUID="Steve123")


def test_instance_client_is_cached_per_instance_id(monkeypatch):
    monkeypatch.setattr(settings, "amp_user", "botuser")
    monkeypatch.setattr(settings, "amp_password", "secret")
    monkeypatch.setattr(settings, "amp_url", "http://amp.example.com")

    client = AMPClient()

    first = client._instance_client("abc")
    second = client._instance_client("abc")
    third = client._instance_client("def")

    assert first is second
    assert first is not third
