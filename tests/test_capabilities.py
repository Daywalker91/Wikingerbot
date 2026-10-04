"""Faehigkeiten: Standard-Stufe oder zugeordnete Discord-Rolle - im Kern und in der API."""

from types import SimpleNamespace

import httpx

from api.main import app
from api.middleware.auth import create_access_token
from bot.core import runtime
from bot.core.capabilities import allowed, member_capabilities, save_capability_roles
from db.models.guild import Guild
from db.models.role import Level

SCHMIED = 77


async def seed(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await save_capability_roles(1, "Wikinger", {"server.control": [SCHMIED]})


async def test_allowed_by_level_or_role(db_session):
    await seed(db_session)
    assert await allowed(1, "server.control", Level.MOD, [])  # Standard-Stufe
    assert await allowed(1, "server.control", Level.MEMBER, [SCHMIED])  # zugeordnete Rolle
    assert not await allowed(1, "server.control", Level.MEMBER, [5])
    assert not await allowed(1, "whitelist.review", Level.MEMBER, [SCHMIED])  # nur fuer die eine Faehigkeit
    assert await member_capabilities(1, Level.MEMBER, [SCHMIED]) == ["server.control"]


async def test_api_uses_discord_roles_of_the_member(db_session, monkeypatch):
    await seed(db_session)
    member = SimpleNamespace(roles=[SimpleNamespace(id=SCHMIED)])
    guild = SimpleNamespace(get_member=lambda uid: member if uid == 100 else None)
    monkeypatch.setattr(runtime, "bot", SimpleNamespace(get_guild=lambda gid: guild if gid == 1 else None))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", create_access_token(100, 1, Level.MEMBER))
        me = (await client.get("/auth/me")).json()
        assert me["capabilities"] == ["server.control"]
        # Whitelist hat der Schmied nicht -> 403; Server-Start schon (404, weil es den Server nicht gibt)
        assert (await client.get("/whitelist/requests")).status_code == 403
        assert (await client.post("/servers/12345/start")).status_code == 404

        client.cookies.set("session", create_access_token(200, 1, Level.MEMBER))  # ohne Rolle
        assert (await client.post("/servers/12345/start")).status_code == 403


async def test_settings_api(db_session):
    await seed(db_session)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", create_access_token(100, 1, Level.OWNER))
        caps = {c["key"]: c for c in (await client.get("/admin/capabilities")).json()}
        assert caps["server.control"]["role_ids"] == [str(SCHMIED)] and caps["server.control"]["default"] == "mod"
        assert (await client.put("/admin/capabilities", json={"roles": {"gibtsnicht": []}})).status_code == 400
        assert (await client.put("/admin/capabilities", json={"roles": {"whitelist.review": ["88"]}})).status_code == 200
        caps = {c["key"]: c for c in (await client.get("/admin/capabilities")).json()}
        assert caps["whitelist.review"]["role_ids"] == ["88"] and caps["server.control"]["role_ids"] == []
