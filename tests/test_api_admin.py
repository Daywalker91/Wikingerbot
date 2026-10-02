import httpx

from api.main import app
from api.middleware.auth import create_access_token
from db.models.guild import Guild
from db.models.role import GuildRole, Level
from db.session import get_db_session


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _cookie_for(user_id: int, guild_id: int, level: Level) -> str:
    return create_access_token(user_id, guild_id, level)


class _FakeResponse:
    def __init__(self, status_code: int, json_body) -> None:
        self.status_code = status_code
        self._json_body = json_body

    def json(self):
        return self._json_body


class _FakeAsyncClient:
    def __init__(self, status_code: int = 200, json_body=None) -> None:
        self.status_code = status_code
        self.json_body = json_body if json_body is not None else []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args) -> None:
        return None

    async def get(self, url: str, headers: dict) -> _FakeResponse:
        return _FakeResponse(self.status_code, self.json_body)


async def test_list_discord_roles_requires_owner(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/admin/discord-roles")

    assert response.status_code == 403


async def test_list_discord_roles_returns_roles(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    test_client = await _client()
    fake = _FakeAsyncClient(status_code=200, json_body=[{"id": "42", "name": "Moderator"}])
    monkeypatch.setattr("bot.cogs.admin.api.httpx.AsyncClient", lambda: fake)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/admin/discord-roles")

    assert response.status_code == 200
    assert response.json() == [{"id": "42", "name": "Moderator"}]


async def test_list_discord_roles_fails_on_discord_error(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    test_client = await _client()
    fake = _FakeAsyncClient(status_code=500)
    monkeypatch.setattr("bot.cogs.admin.api.httpx.AsyncClient", lambda: fake)

    async with test_client as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/admin/discord-roles")

    assert response.status_code == 502


async def test_list_guild_roles_empty(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/admin/roles")

    assert response.status_code == 200
    assert response.json() == []


async def test_add_guild_role_requires_owner(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.post("/admin/roles", json={"discord_role_id": 42, "level": "mod"})

    assert response.status_code == 403


async def test_add_guild_role_creates_row(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.post("/admin/roles", json={"discord_role_id": 42, "level": "mod"})

    assert response.status_code == 200
    body = response.json()
    assert body["discord_role_id"] == "42"
    assert body["level"] == "mod"

    async with get_db_session() as db:
        role = await db.get(GuildRole, body["id"])
        assert role is not None
        assert role.guild_id == 1


async def test_remove_guild_role(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    role = GuildRole(guild_id=1, discord_role_id=42, level=Level.MOD)
    db_session.add(role)
    await db_session.commit()
    await db_session.refresh(role)

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.delete(f"/admin/roles/{role.id}")

    assert response.status_code == 200
    assert response.json()["ok"] is True


async def test_remove_guild_role_not_found(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.delete("/admin/roles/999")

    assert response.status_code == 404


async def test_guild_roles_are_scoped_to_the_logged_in_guild(db_session):
    db_session.add_all([Guild(id=1, name="Guild A"), Guild(id=2, name="Guild B")])
    db_session.add(GuildRole(guild_id=1, discord_role_id=1, level=Level.MOD))
    db_session.add(GuildRole(guild_id=2, discord_role_id=2, level=Level.ADMIN))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/admin/roles")

    [role] = response.json()
    assert role["discord_role_id"] == "1"


async def test_list_cogs_requires_owner(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.MOD))
        response = await client.get("/admin/cogs")

    assert response.status_code == 403


async def test_list_cogs_returns_available_and_loaded(db_session):
    from bot.core.bot import discover_cog_names
    from bot.core.bot_settings import set_bot_setting

    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_bot_setting("loaded_cogs", '["moderation", "amp"]')

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/admin/cogs")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] == discover_cog_names()
    assert body["loaded"] == ["moderation", "amp"]


async def test_list_cogs_defaults_to_empty_loaded_list(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.get("/admin/cogs")

    assert response.status_code == 200
    assert response.json()["loaded"] == []


async def test_long_discord_ids_survive_as_text(db_session):
    """19-stellige Discord-IDs: JavaScript wuerde sie als Zahl runden - darum
    kommen sie als Text rein und gehen als Text raus (api/types.py)."""
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client() as client:
        client.cookies.set("session", _cookie_for(100, 1, Level.OWNER))
        response = await client.post("/admin/roles", json={"discord_role_id": "1523404561895784448", "level": "mod"})

    assert response.json()["discord_role_id"] == "1523404561895784448"
    async with get_db_session() as db:
        role = await db.get(GuildRole, response.json()["id"])
    assert role.discord_role_id == 1523404561895784448
