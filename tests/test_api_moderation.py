import httpx
from sqlalchemy import select

from api.main import app
from api.middleware.auth import create_access_token
from db.models.guild import Guild
from db.models.modlog import ModAction, ModLogEntry, Warning
from db.models.role import Level
from db.models.user import User


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _cookie_for(user_id: int, guild_id: int, level: Level) -> str:
    return create_access_token(user_id, guild_id, level)


async def _seed_guild_and_user(db_session, *, guild_id: int = 1, user_id: int = 200):
    db_session.add(Guild(id=guild_id, name="Wikinger"))
    db_session.add(User(id=user_id, username="Bösewicht"))
    await db_session.commit()


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    def __init__(self, delete_status: int = 204) -> None:
        self.delete_status = delete_status
        self.delete_calls: list[tuple[str, dict]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def delete(self, url: str, headers: dict) -> _FakeResponse:
        self.delete_calls.append((url, headers))
        return _FakeResponse(self.delete_status)


async def test_list_modlog_without_cookie_is_unauthorized():
    async with await _client() as client:
        response = await client.get("/moderation/modlog")

    assert response.status_code == 401


async def test_list_modlog_requires_at_least_mod():
    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MEMBER))
        response = await client.get("/moderation/modlog")

    assert response.status_code == 403


async def test_list_modlog_returns_entries_for_own_guild(db_session):
    await _seed_guild_and_user(db_session)
    db_session.add(
        ModLogEntry(guild_id=1, user_id=200, mod_id=100, action=ModAction.KICK, reason="Stoerung")
    )
    db_session.add(
        ModLogEntry(guild_id=2, user_id=200, mod_id=100, action=ModAction.KICK, reason="Andere Guild")
    )
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/moderation/modlog")

    assert response.status_code == 200
    [entry] = response.json()
    assert entry["action"] == "kick"
    assert entry["reason"] == "Stoerung"


async def test_list_warnings_filters_expired_by_default(db_session):
    await _seed_guild_and_user(db_session)
    db_session.add(Warning(guild_id=1, user_id=200, mod_id=100, reason="aktiv", points=1, expired=False))
    db_session.add(Warning(guild_id=1, user_id=200, mod_id=100, reason="abgelaufen", points=1, expired=True))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        active = await client.get("/moderation/warnings")
        all_warnings = await client.get("/moderation/warnings", params={"active_only": "false"})

    assert len(active.json()) == 1
    assert active.json()[0]["reason"] == "aktiv"
    assert len(all_warnings.json()) == 2


async def test_unban_calls_discord_and_writes_modlog(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    # httpx.AsyncClient() muss erst NACH dem Erzeugen des Test-Clients gepatcht
    # werden - "bot.cogs.moderation.api.httpx" ist dasselbe Modulobjekt wie das
    # global importierte httpx, ein frueheres Patchen wuerde auch den ASGI-
    # Testclient-Konstruktor oben treffen.
    test_client = await _client()
    fake_client = _FakeAsyncClient(delete_status=204)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake_client)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(
            "/moderation/unban", json={"user_id": 200, "reason": "Bewaehrung"}
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert fake_client.delete_calls[0][0] == "https://discord.com/api/guilds/1/bans/200"

    result = await db_session.execute(
        select(ModLogEntry).where(ModLogEntry.action == ModAction.UNBAN)
    )
    [entry] = result.scalars().all()
    assert entry.user_id == 200
    assert entry.mod_id == 100


async def test_unban_treats_not_banned_as_success(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    fake_client = _FakeAsyncClient(delete_status=404)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake_client)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(
            "/moderation/unban", json={"user_id": 200, "reason": "War nie gebannt"}
        )

    assert response.status_code == 200


async def test_unban_fails_on_discord_error(db_session, monkeypatch):
    await _seed_guild_and_user(db_session)
    test_client = await _client()
    fake_client = _FakeAsyncClient(delete_status=500)
    monkeypatch.setattr("bot.cogs.moderation.api.httpx.AsyncClient", lambda: fake_client)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post(
            "/moderation/unban", json={"user_id": 200, "reason": "Egal"}
        )

    assert response.status_code == 502
