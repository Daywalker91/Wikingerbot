"""Zusatzrollen der Seite: Rechte = Rang + Zusatzrollen; ohne Tabelle nur der Rang."""

from sqlalchemy import insert, text

from bot.cogs.rangsync.sync import site_ranks
from bot.community import db as community_db
from bot.community.system_tickets import default_owner_id
from tests.test_community import site  # noqa: F401


async def add_heiler():
    async with community_db.session() as db:
        await db.execute(
            insert(community_db.roles).values(id=9, slug="heiler", name="Heiler", level=60, kind="extra", color="#d9534f")
        )
        await db.execute(insert(community_db.role_permissions).values(role_id=9, permission="ticket.manage"))
        await db.execute(insert(community_db.user_extra_roles).values(user_id=1, role_id=9))
        await db.commit()


async def test_extra_role_adds_permission(site):  # noqa: F811
    await add_heiler()
    assert await community_db.has_permission(1, "ticket.manage")
    assert not await community_db.has_permission(2, "ticket.manage")


async def test_extra_roles_are_not_ranks(site):  # noqa: F811
    await add_heiler()
    assert [r.slug for r in await site_ranks()] == ["karl"]


async def test_king_via_rank_only(site):  # noqa: F811
    async with community_db.session() as db:
        await db.execute(insert(community_db.roles).values(id=5, slug="konig", name="König", level=100, color="#fff"))
        await db.execute(insert(community_db.role_permissions).values(role_id=5, permission="*"))
        await db.execute(text("UPDATE users SET role_id = 5 WHERE id = 2"))
        await db.commit()
    assert await default_owner_id() == 2


async def test_without_extra_roles_table_only_rank_counts(site):  # noqa: F811
    await add_heiler()
    async with community_db.session() as db:
        await db.execute(text("DROP TABLE user_extra_roles"))
        await db.commit()
    community_db._extras = None  # neu pruefen, wie nach einem Neustart
    assert not await community_db.has_permission(1, "ticket.manage")  # Zusatzrolle nicht lesbar -> nur Rang
    assert not await community_db.extras_available()
