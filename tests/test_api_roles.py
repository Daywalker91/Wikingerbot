"""Rollen-Tab: Autoroles und Selbstwahl-Panels gegen ein nachgebautes Discord."""

from types import SimpleNamespace

import discord
import httpx
import pytest

from api.main import app
from api.middleware.auth import create_access_token
from bot.cogs.roles.cog import get_autoroles, get_panels
from bot.core import runtime
from db.models.guild import Guild
from db.models.role import GuildRole, Level

KARL, VEIN, ARK, MOD, ADMINROLE, ABOVE = 11, 12, 13, 14, 15, 16


class FakeRole:
    def __init__(self, role_id, name, position, permissions=None):
        self.id, self.name, self.position = role_id, name, position
        self.permissions = permissions or discord.Permissions.none()
        self.managed = False
        self.color = discord.Color.default()

    def is_default(self):
        return False


class FakeMessage:
    def __init__(self, channel, message_id, embed, view):
        self.channel, self.id, self.author = channel, message_id, SimpleNamespace(id=999)
        self.jump_url = f"https://discord.com/channels/1/{channel.id}/{message_id}"
        self._set(embed, view)

    def _set(self, embed, view):
        self.embeds = [embed] if embed else []
        items = view.children if view else []
        self.components = [
            SimpleNamespace(children=[SimpleNamespace(custom_id=i.item.custom_id, label=i.item.label, emoji=i.item.emoji, style=i.item.style) for i in items])
        ]

    async def edit(self, embed=None, view=None):
        self._set(embed, view)

    async def delete(self):
        self.channel.messages.pop(self.id, None)


class FakeChannel:
    def __init__(self, channel_id, name):
        self.id, self.name, self.messages, self._next = channel_id, name, {}, 500

    async def send(self, embed=None, view=None):
        self._next += 1
        message = FakeMessage(self, self._next, embed, view)
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return self.messages[message_id]


@pytest.fixture
def discord_guild(monkeypatch):
    monkeypatch.setattr(discord, "TextChannel", FakeChannel)
    roles = [
        FakeRole(KARL, "Karl", 2),
        FakeRole(VEIN, "Vein", 3),
        FakeRole(ARK, "ARK", 4),
        FakeRole(MOD, "Huskarl", 5),
        FakeRole(ADMINROLE, "Gefährlich", 6, discord.Permissions(ban_members=True)),
        FakeRole(ABOVE, "König", 20),
    ]
    channel = FakeChannel(100, "rollen")
    guild = SimpleNamespace(
        id=1,
        name="Wikinger",
        roles=roles,
        text_channels=[channel],
        me=SimpleNamespace(top_role=SimpleNamespace(position=10)),
        get_role=lambda rid: next((r for r in roles if r.id == rid), None),
        get_channel=lambda cid: channel if cid == channel.id else None,
    )
    bot = SimpleNamespace(get_guild=lambda gid: guild if gid == 1 else None, get_cog=lambda name: object(), user=SimpleNamespace(id=999))
    monkeypatch.setattr(runtime, "bot", bot)
    return guild, channel


async def _client(level=Level.ADMIN):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client.cookies.set("session", create_access_token(100, 1, level))
    return client


async def seed(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    db_session.add(GuildRole(guild_id=1, discord_role_id=MOD, level=Level.MOD))
    db_session.add(GuildRole(guild_id=1, discord_role_id=KARL, level=Level.MEMBER))  # Grundstufe: bleibt vergebbar
    await db_session.commit()


async def test_config_marks_blocked_roles_and_admin_only(db_session, discord_guild):
    await seed(db_session)
    async with await _client(Level.MOD) as client:
        assert (await client.get("/roles/config")).status_code == 403
    async with await _client() as client:
        data = (await client.get("/roles/config")).json()
    blocked = {r["name"]: r["blocked"] for r in data["roles"]}
    assert blocked["Karl"] is None and blocked["Vein"] is None
    assert "Berechtigungsrolle" in blocked["Huskarl"]
    assert "Verwaltungsrechte" in blocked["Gefährlich"]
    assert "über der Rolle des Bots" in blocked["König"]


async def test_autoroles(db_session, discord_guild):
    await seed(db_session)
    async with await _client() as client:
        assert (await client.put("/roles/autoroles", json={"role_ids": [str(MOD)]})).status_code == 400
        assert (await client.put("/roles/autoroles", json={"role_ids": [str(KARL)]})).status_code == 200
    assert await get_autoroles(1) == [KARL]


async def test_panel_create_edit_adopt_delete(db_session, discord_guild):
    _, channel = discord_guild
    await seed(db_session)
    async with await _client() as client:
        bad = await client.post("/roles/panels", json={"channel_id": "100", "title": "Spiele", "buttons": [{"role_id": str(ADMINROLE)}]})
        assert bad.status_code == 400
        twice = [{"role_id": str(VEIN)}, {"role_id": str(VEIN)}]
        assert (await client.post("/roles/panels", json={"channel_id": "100", "title": "Spiele", "buttons": twice})).status_code == 400

        created = await client.post(
            "/roles/panels",
            json={"channel_id": "100", "title": "Spiele", "text": "Klick!", "buttons": [{"role_id": str(VEIN), "emoji": "🧟"}]},
        )
        assert created.status_code == 200
        [(channel_id, message_id)] = await get_panels(1)
        assert channel_id == 100

        panel = (await client.get("/roles/config")).json()["panels"][0]
        assert panel["title"] == "Spiele" and panel["buttons"][0]["label"] == "Vein" and panel["buttons"][0]["emoji"] == "🧟"

        edited = await client.put(
            f"/roles/panels/{message_id}",
            json={"title": "Deine Spiele", "text": "Neu", "buttons": [{"role_id": str(ARK), "label": "Ark"}, {"role_id": str(VEIN)}]},
        )
        assert edited.status_code == 200
        panel = (await client.get("/roles/config")).json()["panels"][0]
        assert panel["title"] == "Deine Spiele" and [b["label"] for b in panel["buttons"]] == ["Ark", "Vein"]

        # frueher per Slash-Befehl erstelltes Panel uebernehmen
        old = await channel.send(embed=discord.Embed(title="Alt"))
        link = f"https://discord.com/channels/1/100/{old.id}"
        assert (await client.post("/roles/panels/adopt", json={"link": link})).status_code == 200
        assert len(await get_panels(1)) == 2

        assert (await client.delete(f"/roles/panels/{message_id}")).status_code == 200
    assert message_id not in channel.messages
    assert [m for _, m in await get_panels(1)] == [old.id]
