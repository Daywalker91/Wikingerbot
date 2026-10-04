"""Strafrolle: geben/aufheben, Merken beim Verlassen, Wiederbeitritt, Eskalationsstufe."""

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from bot.cogs.moderation.cog import ModerationCog, _trigger_escalation
from bot.cogs.roles.cog import RolesCog
from bot.core import punishment
from bot.core.guild_config import set_config
from db.models.guild import Guild
from db.models.modlog import ModAction, ModLogEntry
from db.models.user import User

KARL, THRALL, GAME, EVERYONE = 11, 12, 13, 1


class FakeRole:
    def __init__(self, role_id, position=1):
        self.id, self.position, self.name = role_id, position, f"r{role_id}"
        self.managed = False
        import discord

        self.permissions = discord.Permissions.none()
        self.mention = f"<@&{role_id}>"

    def is_default(self):
        return self.id == EVERYONE

    def __ge__(self, other):
        return self.position >= other.position


class FakeGuild:
    def __init__(self):
        self.id, self.name, self.owner_id = 1, "Wikinger", 1
        self.roles = {i: FakeRole(i) for i in (KARL, THRALL, GAME, EVERYONE)}
        self.me = SimpleNamespace(id=999, top_role=FakeRole(900, position=50))
        self.members = {}

    def get_role(self, role_id):
        return self.roles.get(role_id)

    def get_member(self, member_id):
        return self.members.get(member_id)


class FakeMember:
    def __init__(self, guild, member_id, role_ids, pending=False):
        self.guild, self.id, self.bot, self.pending = guild, member_id, False, pending
        self.roles = [guild.roles[EVERYONE], *(guild.roles[i] for i in role_ids)]
        self.top_role = max(self.roles, key=lambda r: r.position)
        self.mention = f"<@{member_id}>"
        self.dms = []
        guild.members[member_id] = self

    def ids(self):
        return sorted(r.id for r in self.roles if not r.is_default())

    async def edit(self, roles, reason=None):
        assert all(not r.is_default() for r in roles)
        self.roles = [self.guild.roles[EVERYONE], *roles]

    async def add_roles(self, *roles, reason=None):
        self.roles += [r for r in roles if r not in self.roles]

    async def send(self, text):
        self.dms.append(text)


@pytest.fixture
async def guild(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, "autorole_ids", json.dumps([str(KARL)]))
    await set_config(1, "punish_role_id", str(THRALL))
    return FakeGuild()


async def test_apply_and_lift(guild):
    member = FakeMember(guild, 42, [KARL, GAME])
    assert await punishment.apply(member, "Spam") is None
    assert member.ids() == [THRALL, GAME]  # Spiel-Rolle bleibt, Autorole weg
    assert await punishment.is_remembered(1, 42)
    assert "schon" in await punishment.apply(member, "nochmal")

    assert await punishment.lift(member, "gut jetzt") is None
    assert member.ids() == [KARL, GAME]
    assert not await punishment.is_remembered(1, 42)


async def test_without_punish_role_configured(guild):
    await set_config(1, "punish_role_id", "")
    assert "keine Strafrolle" in await punishment.apply(FakeMember(guild, 42, [KARL]), "x")


async def test_rejoin_gets_punish_role_instead_of_autorole(guild):
    cog = RolesCog(SimpleNamespace())
    await punishment.remember(SimpleNamespace(id=1, name="Wikinger"), 42)
    returning = FakeMember(guild, 42, [])
    await cog._give_autoroles(returning)
    assert returning.ids() == [THRALL]

    newcomer = FakeMember(guild, 43, [])
    await cog._give_autoroles(newcomer)
    assert newcomer.ids() == [KARL]


async def test_role_change_by_hand_is_remembered_and_forgotten(guild):
    cog = ModerationCog(SimpleNamespace())
    before = FakeMember(guild, 42, [KARL])
    after = FakeMember(guild, 42, [THRALL])
    await cog.on_member_update(before, after)
    assert await punishment.is_remembered(1, 42)
    await cog.on_member_update(after, FakeMember(guild, 42, [KARL]))
    assert not await punishment.is_remembered(1, 42)


async def test_escalation_ladder_step(guild, db_session):
    await set_config(1, "warn_ladder", json.dumps(["strafrolle", "ban"]))
    db_session.add(User(id=42, username="ragnar"))
    await db_session.commit()
    sent = []

    async def send(*args, **kwargs):
        sent.append(kwargs.get("embed") or args[0])

    member = FakeMember(guild, 42, [KARL])
    await _trigger_escalation(999, SimpleNamespace(send=send), guild, member, 3)
    assert member.ids() == [THRALL]
    assert "Strafrolle" in sent[0].title
    entry = (await db_session.execute(select(ModLogEntry))).scalar_one()
    assert entry.action == ModAction.PUNISH and member.dms
