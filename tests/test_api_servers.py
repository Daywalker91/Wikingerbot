from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from api.main import app
from api.middleware.auth import create_access_token
from bot.core.amp_client import amp_client
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
    assert response.json() == {"user_id": 100, "guild_id": 1, "level": "mod"}
