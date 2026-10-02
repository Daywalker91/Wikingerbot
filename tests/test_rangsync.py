"""rangsync-Cog: Raenge der Seite <-> Discord-Rollen, gegen eine nachgebaute
Seite und nachgebaute Discord-Mitglieder."""

import json
from types import SimpleNamespace

from sqlalchemy import insert, select, update

from bot.cogs.rangsync.cog import RangsyncCog
from bot.cogs.rangsync.sync import Rank, load_mapping, rank_from_discord, target_discord_roles
from bot.community import db as community_db
from bot.core.guild_config import set_config
from db.models.guild import Guild
from tests.test_community import site  # noqa: F401

# Discord-Rollen-IDs
MEMBER, MOD, ADMIN, OWNER, GAME = 101, 102, 103, 104, 200


def ranks():
    return [
        Rank(1, "thrall", "Thrall", 10, None, "both"),
        Rank(2, "karl", "Karl", 20, MEMBER, "both"),
        Rank(3, "huskarl", "Huskarl", 50, MOD, "both"),
        Rank(4, "jarl", "Jarl", 80, ADMIN, "to_site"),
        Rank(5, "konig", "König", 100, OWNER, "off"),
    ]


def test_site_to_discord_targets():
    r = ranks()
    assert target_discord_roles(r, 3, {MEMBER, GAME}) == {MOD, GAME}  # Karl -> Huskarl, Spiele-Rolle bleibt
    assert target_discord_roles(r, 1, {MEMBER, MOD, GAME}) == {GAME}  # Thrall = keine Rang-Rolle
    assert target_discord_roles(r, 4, {MEMBER, ADMIN}) is None  # Jarl nur Discord -> Seite: nicht anfassen
    assert target_discord_roles(r, 5, {MEMBER}) is None  # Koenig nie


def test_discord_to_site_rank():
    r = ranks()
    assert rank_from_discord(r, {MEMBER, MOD}).slug == "huskarl"  # hoechster gewinnt
    assert rank_from_discord(r, {ADMIN, MEMBER}).slug == "jarl"
    assert rank_from_discord(r, {GAME}).slug == "thrall"  # keine Rang-Rolle
    assert rank_from_discord(r, {OWNER}).slug == "thrall"  # Koenig nie automatisch


async def seed_site(guild_id=1):
    async with community_db.session() as db:
        await db.execute(
            insert(community_db.roles),
            [
                {"id": 1, "slug": "thrall", "name": "Thrall", "level": 10, "color": "#000"},
                {"id": 3, "slug": "huskarl", "name": "Huskarl", "level": 50, "color": "#000"},
                {"id": 4, "slug": "jarl", "name": "Jarl", "level": 80, "color": "#000"},
                {"id": 5, "slug": "konig", "name": "König", "level": 100, "color": "#000"},
            ],
        )
        await db.execute(insert(community_db.role_permissions).values(role_id=5, permission="*"))
        await db.execute(update(community_db.users).where(community_db.users.c.id == 1).values(discord_id=4242))
        await db.execute(update(community_db.users).where(community_db.users.c.id == 2).values(discord_id=777, role_id=5))
        await db.commit()
    mapping = {
        "karl": {"role_id": MEMBER, "direction": "both"},
        "huskarl": {"role_id": MOD, "direction": "both"},
        "jarl": {"role_id": ADMIN, "direction": "to_site"},
        "konig": {"role_id": OWNER, "direction": "both"},  # wird trotzdem "off"
    }
    await set_config(guild_id, "rangsync_map", json.dumps(mapping))
    await set_config(guild_id, "rangsync_enabled", "true")


class FakeRole(SimpleNamespace):
    def is_default(self):
        return False


class FakeMember:
    def __init__(self, guild, member_id, role_ids):
        self.guild, self.id, self.bot = guild, member_id, False
        self.roles = [FakeRole(id=i) for i in role_ids]
        self.edits = []

    async def edit(self, roles, reason=None):
        self.roles = list(roles)
        self.edits.append({r.id for r in roles})


def make(members):
    guild = SimpleNamespace(id=1, name="Wikinger", get_role=lambda rid: FakeRole(id=rid), get_member=lambda mid: members.get(mid))
    dispatched = []
    bot = SimpleNamespace(guilds=[guild], dispatch=lambda *a: dispatched.append(a), get_cog=lambda name: None)
    return RangsyncCog(bot), guild, dispatched


async def site_rank(user_id):
    async with community_db.session() as db:
        return (await db.execute(select(community_db.users.c.role_id).where(community_db.users.c.id == user_id))).scalar_one()


async def test_mapping_king_always_off(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await seed_site()
    king = next(r for r in await load_mapping(1) if r.slug == "konig")
    assert king.direction == "off"


async def test_site_role_change_updates_discord_roles(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await seed_site()
    members = {}
    cog, guild, _ = make(members)
    members[4242] = FakeMember(guild, 4242, [MEMBER, GAME])

    async with community_db.session() as db:  # auf der Seite zum Huskarl befoerdert
        await db.execute(update(community_db.users).where(community_db.users.c.id == 1).values(role_id=3))
        await db.commit()
    await cog._on_site_role({"user_id": 1})
    assert members[4242].edits == [{MOD, GAME}]


async def test_discord_role_change_updates_site_and_ignores_own_changes(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await seed_site()
    cog, guild, dispatched = make({})
    before = FakeMember(guild, 4242, [MEMBER])
    after = FakeMember(guild, 4242, [MEMBER, MOD])
    await cog.on_member_update(before, after)
    assert await site_rank(1) == 3 and dispatched == [("community_rank_changed", 1)]

    # eigene Aenderung des Bots kommt als Ereignis zurueck -> nichts tun
    cog._own_changes.add(4242)
    await cog.on_member_update(after, FakeMember(guild, 4242, [MEMBER]))
    assert await site_rank(1) == 3


async def test_king_on_site_is_never_changed(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await seed_site()
    cog, guild, _ = make({})
    await cog.on_member_update(FakeMember(guild, 777, [OWNER]), FakeMember(guild, 777, [MEMBER]))
    assert await site_rank(2) == 5


async def tickets():
    t = community_db.tickets
    async with community_db.session() as db:
        return (await db.execute(select(t.c.user_id, t.c.subject, t.c.category))).all()


async def test_link_conflict_opens_ticket_and_changes_nothing(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await seed_site()
    cog, guild, _ = make({})
    member = FakeMember(guild, 4242, [MOD])  # Discord: Huskarl, Seite: Karl
    site_user = SimpleNamespace(id=1, username="Ragnar")
    await cog.on_community_link(member, site_user)
    assert await tickets() == [(1, "Rang-Konflikt: Seite Karl, Discord Huskarl", "konto")]
    assert member.edits == [] and await site_rank(1) == 2


async def test_link_without_rank_roles_takes_site_rank(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await seed_site()
    cog, guild, _ = make({})
    member = FakeMember(guild, 4242, [GAME])
    await cog.on_community_link(member, SimpleNamespace(id=1, username="Ragnar"))
    assert member.edits == [{MEMBER, GAME}] and await tickets() == []


async def test_discord_ban_opens_ticket_for_king(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await seed_site()
    cog, _, _ = make({})

    async def fetch_ban(user):
        return SimpleNamespace(reason="Spam")

    guild = SimpleNamespace(id=1, name="Wikinger", fetch_ban=fetch_ban)
    await cog.on_member_ban(guild, SimpleNamespace(id=4242, __str__=lambda self: "ragnar"))
    [(owner, subject, category)] = await tickets()
    assert owner == 2 and subject == "Discord-Bann: Ragnar" and category == "melden"  # Lagertha ist hier Koenig
