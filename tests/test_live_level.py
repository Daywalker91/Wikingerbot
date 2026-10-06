"""Bot-Oberflaeche: die Stufe gilt live aus Discord, nicht die beim Login gemerkte."""

from types import SimpleNamespace

import httpx

from api.main import app
from api.middleware.auth import create_access_token
from bot.core import runtime
from db.models.guild import Guild
from db.models.role import GuildRole, Level

MOD_ROLE = 50


def fake_guild(members):
    return SimpleNamespace(id=1, chunked=True, get_member=lambda uid: members.get(uid))


def member(*role_ids, admin=False):
    return SimpleNamespace(
        roles=[SimpleNamespace(id=r) for r in role_ids], guild_permissions=SimpleNamespace(administrator=admin)
    )


async def me(level=Level.OWNER) -> httpx.Response:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    async with client:
        client.cookies.set("session", create_access_token(100, 1, level))
        return await client.get("/auth/me")


async def test_level_follows_discord_roles(db_session, monkeypatch):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    db_session.add(GuildRole(guild_id=1, discord_role_id=MOD_ROLE, level=Level.MOD))
    await db_session.commit()
    members = {100: member(MOD_ROLE)}
    monkeypatch.setattr(runtime, "bot", SimpleNamespace(get_guild=lambda gid: fake_guild(members)))

    assert (await me(Level.OWNER)).json()["level"] == "mod"  # Login als Owner, heute nur noch Mod

    members[100] = member()  # Rolle weg
    assert (await me(Level.OWNER)).json()["level"] == "member"

    members[100] = member(admin=True)  # Discord-Administrator / Server-Owner
    assert (await me(Level.MEMBER)).json()["level"] == "owner"

    members.pop(100)  # vom Server gegangen
    assert (await me()).status_code == 401


async def test_without_bot_login_level_counts(monkeypatch):
    monkeypatch.setattr(runtime, "bot", None)
    assert (await me(Level.ADMIN)).json()["level"] == "admin"
