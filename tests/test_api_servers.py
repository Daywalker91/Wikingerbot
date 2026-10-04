from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from api.main import app
from api.middleware.auth import create_access_token
from bot.core.amp_client import DiscoveredInstance, amp_client
from db.models.guild import Guild
from db.models.role import Level
from db.models.server import Server


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _cookie_for(user_id: int, guild_id: int, level: Level) -> str:
    return create_access_token(user_id, guild_id, level)


async def test_list_servers_without_cookie_is_unauthorized():
    async with await _client() as client:
        response = await client.get("/servers")

    assert response.status_code == 401


async def test_list_servers_returns_empty_list_when_no_servers(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.get("/servers")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_servers_reports_reachable_server_with_status(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    db_session.add(
        Server(
            guild_id=1,
            instance_name="valheim",
            amp_instance_id="abc-123",
            display_name="Valheim",
            host="play.example.com",
        )
    )
    await db_session.commit()

    fake_status = SimpleNamespace(
        State=SimpleNamespace(name="Ready"),
        Uptime="1h 23m",
        Metrics={"Active Users": SimpleNamespace(RawValue=3, MaxValue=10)},
    )
    monkeypatch.setattr(amp_client, "get_status", AsyncMock(return_value=fake_status))

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.get("/servers")

    assert response.status_code == 200
    [server] = response.json()
    assert server["display_name"] == "Valheim"
    assert server["reachable"] is True
    assert server["state"] == "Ready"
    assert server["uptime"] == "1h 23m"
    assert server["players"] == [3, 10]


async def test_list_servers_marks_unreachable_server_without_crashing(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    db_session.add(
        Server(
            guild_id=1,
            instance_name="valheim",
            amp_instance_id="abc-123",
            display_name="Valheim",
            host="play.example.com",
        )
    )
    await db_session.commit()

    monkeypatch.setattr(amp_client, "get_status", AsyncMock(side_effect=TimeoutError("kein Netz")))

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.get("/servers")

    assert response.status_code == 200
    [server] = response.json()
    assert server["reachable"] is False
    assert server["state"] is None


async def test_list_servers_scopes_to_the_logged_in_guild(db_session):
    db_session.add_all([Guild(id=1, name="Guild A"), Guild(id=2, name="Guild B")])
    db_session.add(
        Server(
            guild_id=1,
            instance_name="server-a",
            amp_instance_id="a-1",
            display_name="Server A",
            host="a.example.com",
        )
    )
    db_session.add(
        Server(
            guild_id=2,
            instance_name="server-b",
            amp_instance_id="b-1",
            display_name="Server B",
            host="b.example.com",
        )
    )
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.get("/servers")

    [server] = response.json()
    assert server["display_name"] == "Server A"


async def test_list_servers_hides_hidden_servers(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    db_session.add(
        Server(
            guild_id=1,
            instance_name="hidden-server",
            amp_instance_id="hidden-1",
            display_name="Hidden",
            host="hidden.example.com",
            hidden=True,
        )
    )
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.get("/servers")

    assert response.json() == []


async def test_me_returns_current_user_without_cookie_is_unauthorized():
    async with await _client() as client:
        response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_me_returns_current_user_with_valid_cookie():
    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "100",
        "guild_id": "1",
        "level": "mod",
        "capabilities": ["server.control", "whitelist.review", "banner.refresh"],  # Mod hat alle Standard-Faehigkeiten
    }


async def _seed_server(db_session, *, guild_id: int = 1) -> Server:
    db_session.add(Guild(id=guild_id, name="Wikinger"))
    server = Server(
        guild_id=guild_id,
        instance_name="valheim",
        amp_instance_id="abc-123",
        display_name="Valheim",
        host="play.example.com",
    )
    db_session.add(server)
    await db_session.commit()
    await db_session.refresh(server)
    return server


async def test_start_server_requires_at_least_mod(db_session):
    server = await _seed_server(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.post(f"/servers/{server.id}/start")

    assert response.status_code == 403


async def test_start_server_calls_amp_client(db_session, monkeypatch):
    server = await _seed_server(db_session)
    mock_start = AsyncMock()
    monkeypatch.setattr(amp_client, "start", mock_start)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(f"/servers/{server.id}/start")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_start.assert_awaited_once_with("abc-123")


async def test_start_server_reports_failure_without_500(db_session, monkeypatch):
    server = await _seed_server(db_session)
    monkeypatch.setattr(amp_client, "start", AsyncMock(side_effect=TimeoutError("kein Netz")))

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(f"/servers/{server.id}/start")

    assert response.status_code == 200
    assert response.json()["ok"] is False


async def test_stop_server_calls_amp_client(db_session, monkeypatch):
    server = await _seed_server(db_session)
    mock_stop = AsyncMock()
    monkeypatch.setattr(amp_client, "stop", mock_stop)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(f"/servers/{server.id}/stop")

    assert response.status_code == 200
    mock_stop.assert_awaited_once_with("abc-123")


async def test_server_actions_are_scoped_to_the_logged_in_guild(db_session):
    server = await _seed_server(db_session, guild_id=1)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 2, Level.MOD))
        response = await client.post(f"/servers/{server.id}/start")

    assert response.status_code == 404


async def test_get_console_returns_lines(db_session, monkeypatch):
    server = await _seed_server(db_session)
    fake_line = SimpleNamespace(contents="Server started", source="stdout", type="log")
    monkeypatch.setattr(amp_client, "poll_console", AsyncMock(return_value=[fake_line]))

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get(f"/servers/{server.id}/console")

    assert response.status_code == 200
    [line] = response.json()
    assert line["contents"] == "Server started"


async def test_get_console_returns_empty_list_on_error(db_session, monkeypatch):
    server = await _seed_server(db_session)
    monkeypatch.setattr(amp_client, "poll_console", AsyncMock(side_effect=TimeoutError("kein Netz")))

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get(f"/servers/{server.id}/console")

    assert response.status_code == 200
    assert response.json() == []


async def test_send_console_command_calls_amp_client(db_session, monkeypatch):
    server = await _seed_server(db_session)
    mock_send = AsyncMock()
    monkeypatch.setattr(amp_client, "send_console_message", mock_send)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(f"/servers/{server.id}/console", json={"command": "say hi"})

    assert response.status_code == 200
    mock_send.assert_awaited_once_with("abc-123", "say hi")


class _FakeGuildResponse:
    def __init__(self, name: str) -> None:
        self._name = name

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"name": self._name}


class _FakeDiscordClient:
    def __init__(self, guild_name: str = "Wikinger") -> None:
        self.guild_name = guild_name

    async def __aenter__(self) -> "_FakeDiscordClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url: str, headers: dict) -> _FakeGuildResponse:
        return _FakeGuildResponse(self.guild_name)


async def test_list_discoverable_requires_owner(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    monkeypatch.setattr(amp_client, "list_instances", AsyncMock(return_value=[]))

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/servers/discoverable")

    assert response.status_code == 403


async def test_list_discoverable_excludes_already_added_instances(db_session, monkeypatch):
    await _seed_server(db_session)
    monkeypatch.setattr(
        amp_client,
        "list_instances",
        AsyncMock(
            return_value=[
                DiscoveredInstance("abc-123", "Valheim", "GenericModule", True, ""),
                DiscoveredInstance("new-id", "Factorio", "GenericModule", False, "steam:427520"),
            ]
        ),
    )

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/servers/discoverable")

    assert response.status_code == 200
    [instance] = response.json()
    assert instance["instance_id"] == "new-id"


async def test_create_server_requires_owner(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(
            "/servers",
            json={
                "instance_name": "factorio",
                "amp_instance_id": "new-id",
                "display_name": "Factorio",
                "host": "play.example.com",
            },
        )

    assert response.status_code == 403


async def test_create_server_adds_row_with_steam_appid(db_session, monkeypatch):
    test_client = await _client()
    monkeypatch.setattr("bot.cogs.amp.api.httpx.AsyncClient", lambda: _FakeDiscordClient("Wikinger"))
    monkeypatch.setattr(
        amp_client,
        "list_instances",
        AsyncMock(
            return_value=[DiscoveredInstance("new-id", "Factorio", "GenericModule", False, "steam:427520")]
        ),
    )
    monkeypatch.setattr(amp_client, "get_status", AsyncMock(side_effect=TimeoutError("noch nicht bereit")))

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.post(
            "/servers",
            json={
                "instance_name": "factorio",
                "amp_instance_id": "new-id",
                "display_name": "Factorio",
                "host": "play.example.com",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Factorio"
    assert body["reachable"] is False


async def test_create_server_without_host_uses_game_host_and_amp_port(db_session, monkeypatch):
    from bot.core import server_address

    test_client = await _client()
    monkeypatch.setattr("bot.cogs.amp.api.httpx.AsyncClient", lambda: _FakeDiscordClient("Wikinger"))
    endpoints = [{"DisplayName": "Application Address", "Endpoint": "0.0.0.0:7777"}]
    monkeypatch.setattr(
        amp_client,
        "list_instances",
        AsyncMock(return_value=[DiscoveredInstance("new-id", "Valguero", "GenericModule", False, "", endpoints)]),
    )
    monkeypatch.setattr(amp_client, "get_status", AsyncMock(side_effect=TimeoutError("gestoppt")))
    server_address.clear_cache()

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        assert (await client.get("/servers/discoverable")).json()[0]["port"] == 7777
        saved = await client.put("/servers/address-settings", json={"game_host": "https://spiel.example.org:1234/"})
        assert saved.json()["game_host"] == "spiel.example.org"  # nur der Host
        response = await client.post(
            "/servers", json={"instance_name": "valguero", "amp_instance_id": "new-id", "display_name": "Valguero"}
        )
        again = await client.post(
            "/servers", json={"instance_name": "valguero2", "amp_instance_id": "new-id", "display_name": "Valguero"}
        )

    assert response.status_code == 200 and response.json()["host"] == "spiel.example.org:7777"
    assert again.status_code == 409 and "schon als `valguero`" in again.json()["detail"]


async def test_delete_server_requires_owner_and_guild(db_session):
    db_session.add_all([Guild(id=1, name="Wikinger"), Guild(id=2, name="Andere")])
    await db_session.commit()
    db_session.add(Server(guild_id=1, instance_name="v", amp_instance_id="v-id", display_name="Valguero", host=""))
    await db_session.commit()
    server_id = (await db_session.execute(Server.__table__.select())).first().id

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.ADMIN))
        assert (await client.delete(f"/servers/{server_id}")).status_code == 403
        client.cookies.set("session", _cookie_for(100, 2, Level.OWNER))
        assert (await client.delete(f"/servers/{server_id}")).status_code == 404  # anderer Discord-Server
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.delete(f"/servers/{server_id}")

    assert response.status_code == 200 and "Valguero" in response.json()["message"]
    db_session.expire_all()
    assert await db_session.get(Server, server_id) is None
