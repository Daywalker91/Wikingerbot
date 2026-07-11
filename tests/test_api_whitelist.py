from unittest.mock import AsyncMock

import httpx

from api.main import app
from api.middleware.auth import create_access_token
from bot.core.amp_client import amp_client
from db.models.guild import Guild
from db.models.role import Level
from db.models.server import Server
from db.models.user import User
from db.models.whitelist import WhitelistRequest, WhitelistStatus


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _cookie_for(user_id: int, guild_id: int, level: Level) -> str:
    return create_access_token(user_id, guild_id, level)


async def _seed_request(db_session, *, guild_id: int = 1, status: WhitelistStatus = WhitelistStatus.PENDING):
    db_session.add(Guild(id=guild_id, name="Wikinger"))
    db_session.add(User(id=200, username="Antragsteller"))
    db_session.add(
        Server(
            guild_id=guild_id,
            instance_name="valheim",
            amp_instance_id="abc-123",
            display_name="Valheim",
            host="play.example.com",
        )
    )
    await db_session.flush()
    request = WhitelistRequest(user_id=200, server_id=1, ign="Steve123", status=status)
    db_session.add(request)
    await db_session.commit()
    await db_session.refresh(request)
    return request


async def test_list_requests_without_cookie_is_unauthorized():
    async with await _client() as client:
        response = await client.get("/whitelist/requests")

    assert response.status_code == 401


async def test_list_requests_requires_at_least_mod():
    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.get("/whitelist/requests")

    assert response.status_code == 403


async def test_list_requests_returns_pending_by_default(db_session):
    await _seed_request(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/whitelist/requests")

    assert response.status_code == 200
    [request] = response.json()
    assert request["ign"] == "Steve123"
    assert request["server_name"] == "Valheim"
    assert request["status"] == "pending"


async def test_list_requests_filters_by_status(db_session):
    await _seed_request(db_session, status=WhitelistStatus.APPROVED)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        pending = await client.get("/whitelist/requests", params={"status": "pending"})
        approved = await client.get("/whitelist/requests", params={"status": "approved"})

    assert pending.json() == []
    assert len(approved.json()) == 1


async def test_approve_request_marks_approved_and_calls_amp_whitelist(db_session, monkeypatch):
    request = await _seed_request(db_session)
    mock_add_whitelist = AsyncMock()
    monkeypatch.setattr(amp_client, "add_whitelist", mock_add_whitelist)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(f"/whitelist/requests/{request.id}/approve")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    mock_add_whitelist.assert_awaited_once_with("abc-123", "Steve123")

    await db_session.refresh(request)
    assert request.status == WhitelistStatus.APPROVED
    assert request.handled_by == 100


async def test_approve_request_survives_amp_failure(db_session, monkeypatch):
    request = await _seed_request(db_session)
    monkeypatch.setattr(amp_client, "add_whitelist", AsyncMock(side_effect=Exception("kein Minecraft")))

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(f"/whitelist/requests/{request.id}/approve")

    assert response.status_code == 200
    assert "fehlgeschlagen" in response.json()["message"]

    await db_session.refresh(request)
    assert request.status == WhitelistStatus.APPROVED


async def test_deny_request_marks_denied(db_session):
    request = await _seed_request(db_session)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(f"/whitelist/requests/{request.id}/deny", json={"reason": "Nope"})

    assert response.status_code == 200
    await db_session.refresh(request)
    assert request.status == WhitelistStatus.DENIED
    assert request.handled_by == 100


async def test_approve_already_handled_request_returns_conflict(db_session):
    request = await _seed_request(db_session, status=WhitelistStatus.APPROVED)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(f"/whitelist/requests/{request.id}/approve")

    assert response.status_code == 409


async def test_requests_are_scoped_to_the_logged_in_guild(db_session):
    request = await _seed_request(db_session, guild_id=1)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 2, Level.MOD))
        list_response = await client.get("/whitelist/requests")
        approve_response = await client.post(f"/whitelist/requests/{request.id}/approve")

    assert list_response.json() == []
    assert approve_response.status_code == 404
