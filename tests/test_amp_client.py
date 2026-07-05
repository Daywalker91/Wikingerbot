from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.core.amp_client import AMPClient
from bot.core.config import settings


def _fake_client(core: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(Core=core)


async def test_poll_console_returns_entries():
    entry = SimpleNamespace(Contents="Hello", Source="Server", Type="Console")
    core = SimpleNamespace(GetUpdates=AsyncMock(return_value=SimpleNamespace(ConsoleEntries=[entry])))
    client = AMPClient()
    client._instance_client = lambda instance_id: _fake_client(core)

    lines = await client.poll_console("abc")

    assert len(lines) == 1
    assert lines[0].contents == "Hello"
    assert lines[0].source == "Server"


async def test_start_stop_calls_core():
    core = SimpleNamespace(Start=AsyncMock(), Stop=AsyncMock())
    client = AMPClient()
    client._instance_client = lambda instance_id: _fake_client(core)

    await client.start("abc")
    await client.stop("abc")

    core.Start.assert_awaited_once()
    core.Stop.assert_awaited_once()


async def test_send_console_message_forwards_to_core():
    core = SimpleNamespace(SendConsoleMessage=AsyncMock())
    client = AMPClient()
    client._instance_client = lambda instance_id: _fake_client(core)

    await client.send_console_message("abc", "say hello")

    core.SendConsoleMessage.assert_awaited_once_with("say hello")


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
