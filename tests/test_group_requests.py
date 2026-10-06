"""Gruppen-Rollen mit Bestaetigung (Panel-Knopf "wb:role:<id>:c") - wie eine Whitelist-Anfrage."""

from types import SimpleNamespace

import discord
import pytest

from bot.cogs.roles import requests as group
from bot.cogs.roles.cog import RoleToggleButton, panel_buttons, parse_custom_id, role_id_from_custom_id
from bot.core.guild_config import set_config
from db.models.guild import Guild

WARDOGS, REVIEW_CHANNEL = 77, 900


class FakeRole:
    def __init__(self, role_id, name, position=3):
        self.id, self.name, self.position, self.managed = role_id, name, position, False
        self.permissions = discord.Permissions.none()
        self.mention = f"<@&{role_id}>"

    def is_default(self):
        return False


class FakeMember:
    def __init__(self, member_id):
        self.id, self.display_name, self.roles, self.dms = member_id, f"m{member_id}", [], []

    async def add_roles(self, role, reason=None):
        self.roles.append(role)

    async def remove_roles(self, role, reason=None):
        self.roles.remove(role)

    async def send(self, text):
        self.dms.append(text)


class FakeChannel:
    def __init__(self):
        self.id, self.sent, self.messages = REVIEW_CHANNEL, [], {}

    async def send(self, embed=None, view=None, allowed_mentions=None):
        message = SimpleNamespace(id=1000 + len(self.sent), embed=embed, view=view)

        async def edit(embed=None, view=None):
            message.embed, message.view = embed, view

        message.edit = edit
        self.sent.append(message)
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        return self.messages[message_id]


@pytest.fixture
async def guild(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, group.REVIEW_CHANNEL_KEY, str(REVIEW_CHANNEL), "Wikinger")
    role, channel = FakeRole(WARDOGS, "WARDOGS"), FakeChannel()
    members = {10: FakeMember(10), 20: FakeMember(20)}
    return SimpleNamespace(
        id=1, name="Wikinger", channel=channel, role=role, members=members,
        me=SimpleNamespace(top_role=SimpleNamespace(position=10)),
        get_channel=lambda cid: channel if cid == REVIEW_CHANNEL else None,
        get_role=lambda rid: role if rid == WARDOGS else None,
        get_member=lambda uid: members.get(uid),
    )


def test_custom_id_with_and_without_confirmation():
    assert parse_custom_id("wb:role:77") == (77, False)
    assert parse_custom_id("wb:role:77:c") == (77, True)
    assert parse_custom_id("wb:role:x:c") is None and role_id_from_custom_id("wb:role:77:c") == 77
    button = RoleToggleButton(77, "WARDOGS", confirm=True)
    assert button.item.custom_id == "wb:role:77:c"
    message = SimpleNamespace(components=[SimpleNamespace(children=[button.item, RoleToggleButton(5, "Valheim").item])])
    assert [(b.role_id, b.confirm) for b in panel_buttons(message)] == [(77, True), (5, False)]


async def test_request_approve_revoke(guild):
    member, mod = guild.members[10], guild.members[20]
    answer = await group.create_request(guild, member, guild.role)
    assert "gestellt" in answer and len(guild.channel.sent) == 1 and guild.channel.sent[0].view is not None
    assert "läuft schon" in await group.create_request(guild, member, guild.role)  # eine offene Anfrage je Rolle

    request_id = 1
    assert "eigene" in await group.decide(guild, member, request_id, True)  # nie die eigene
    assert "vergeben" in await group.decide(guild, mod, request_id, True)
    assert guild.role in member.roles and "angenommen" in member.dms[-1]
    assert guild.channel.sent[0].view is None  # Knoepfe weg
    assert "schon entschieden" in await group.decide(guild, mod, request_id, False)

    assert "entzogen" in await group.revoke(guild, member, guild.role, mod.id, "Griefing")
    assert guild.role not in member.roles and "Griefing" in member.dms[-1]


async def test_deny_then_cooldown(guild):
    member, mod = guild.members[10], guild.members[20]
    await group.create_request(guild, member, guild.role)
    assert "Abgelehnt" in await group.decide(guild, mod, 1, False, "Erst Probezeit")
    assert guild.role not in member.roles and "Probezeit" in member.dms[-1]
    assert "abgelehnt" in await group.create_request(guild, member, guild.role)  # 7 Tage Pause fuer diese Rolle


async def test_without_review_channel(guild):
    await set_config(1, group.REVIEW_CHANNEL_KEY, "", "Wikinger")
    assert "kein Whitelist-Kanal" in await group.create_request(guild, guild.members[10], guild.role)
