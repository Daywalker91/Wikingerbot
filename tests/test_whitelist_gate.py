"""Whitelist pro Server: Rolle nur per Freigabe, Entziehen, gesperrte Selbstwahl."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest
from sqlalchemy import select

from bot.cogs.roles.cog import RolesCog, block_reason
from bot.cogs.whitelist.actions import grant, revoke
from bot.core.amp_client import amp_client
from bot.core.guild_config import set_config
from bot.core.whitelist_gate import gated_roles
from db.models.guild import Guild
from db.models.server import Server
from db.models.user import User
from db.models.whitelist import WhitelistRequest, WhitelistStatus

VEIN, ARK, KARL = 11, 12, 13


class FakeRole:
    def __init__(self, role_id, name):
        self.id, self.name, self.position, self.managed = role_id, name, 1, False
        self.permissions = discord.Permissions.none()

    def is_default(self):
        return False


class FakeMember:
    def __init__(self, guild, member_id, roles=()):
        self.guild, self.id, self.roles, self.dms, self.pending, self.bot = guild, member_id, list(roles), [], False, False

    async def add_roles(self, *roles, reason=None):
        self.roles += [r for r in roles if r not in self.roles]

    async def remove_roles(self, *roles, reason=None):
        self.roles = [r for r in self.roles if r not in roles]

    async def send(self, text):
        self.dms.append(text)


@pytest.fixture
async def world(db_session, monkeypatch):
    monkeypatch.setattr(amp_client, "add_whitelist", AsyncMock(side_effect=Exception("kein Minecraft")))
    monkeypatch.setattr(amp_client, "remove_whitelist", AsyncMock(side_effect=Exception("kein Minecraft")))
    db_session.add_all([Guild(id=1, name="Wikinger"), User(id=42, username="ragnar")])
    await db_session.commit()
    servers = [
        Server(guild_id=1, instance_name="vein", amp_instance_id="v", display_name="Vein", host="", discord_role_id=VEIN, whitelist_enabled=True),
        Server(guild_id=1, instance_name="ark1", amp_instance_id="a1", display_name="ARK Island", host="", discord_role_id=ARK, whitelist_enabled=True),
        Server(guild_id=1, instance_name="ark2", amp_instance_id="a2", display_name="ARK Ragnarok", host="", discord_role_id=ARK, whitelist_enabled=True),
    ]
    db_session.add_all(servers)
    await db_session.commit()
    roles = {VEIN: FakeRole(VEIN, "Vein"), ARK: FakeRole(ARK, "ARK"), KARL: FakeRole(KARL, "Karl")}
    guild = SimpleNamespace(id=1, name="Wikinger", members={}, me=SimpleNamespace(top_role=SimpleNamespace(position=50)))
    guild.get_role = roles.get
    guild.get_member = guild.members.get
    member = FakeMember(guild, 42)
    guild.members[42] = member
    return guild, member, {s.instance_name: s for s in servers}, roles


async def approve(db_session, server, ign="Ragnar"):
    request = WhitelistRequest(user_id=42, server_id=server.id, ign=ign, status=WhitelistStatus.APPROVED)
    db_session.add(request)
    await db_session.commit()
    return request


async def test_grant_gives_role_and_revoke_takes_it(world, db_session):
    guild, member, servers, roles = world
    request = await approve(db_session, servers["vein"])
    lines = await grant(guild, request, servers["vein"])
    assert roles[VEIN] in member.roles and any("Rolle Vein vergeben" in line for line in lines)

    ok, summary = await revoke(guild, 42, servers["vein"], 7, "Griefing")
    assert ok and roles[VEIN] not in member.roles and "Griefing" in member.dms[-1]
    status = (await db_session.execute(select(WhitelistRequest.status))).scalar_one()
    assert status == WhitelistStatus.REVOKED
    assert not (await revoke(guild, 42, servers["vein"], 7, None))[0]  # nichts mehr zu entziehen


async def test_shared_role_stays_while_another_approval_covers_it(world, db_session):
    guild, member, servers, roles = world
    for name in ("ark1", "ark2"):
        await grant(guild, await approve(db_session, servers[name]), servers[name])
    ok, summary = await revoke(guild, 42, servers["ark1"], 7, None)
    assert ok and roles[ARK] in member.roles and "bleibt" in summary
    await revoke(guild, 42, servers["ark2"], 7, None)
    assert roles[ARK] not in member.roles


async def test_gated_roles_block_self_service(world, db_session):
    guild, member, servers, roles = world
    assert set(await gated_roles(1)) == {VEIN, ARK}
    assert "Whitelist" in await block_reason(roles[VEIN], guild)
    assert await block_reason(roles[KARL], guild) is None

    # Whitelist aus -> Rolle wieder frei waehlbar
    server = servers["vein"]
    server.whitelist_enabled = False
    db_session.add(server)
    await db_session.commit()
    assert await block_reason(roles[VEIN], guild) is None


async def test_autorole_skips_gated_roles(world):
    guild, member, servers, roles = world
    await set_config(1, "autorole_ids", f'["{KARL}", "{VEIN}"]')
    newcomer = FakeMember(guild, 43)
    await RolesCog(SimpleNamespace())._give_autoroles(newcomer)
    assert newcomer.roles == [roles[KARL]]
