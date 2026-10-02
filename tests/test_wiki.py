"""wiki-Cog: Suche und Leserechte gegen eine nachgebaute Seite."""

from sqlalchemy import insert, update

from bot.cogs.wiki.cog import page_by_slug, page_link, reader_level, search
from bot.community import db as community_db
from tests.test_community import site  # noqa: F401


async def seed():
    async with community_db.session() as db:
        await db.execute(
            insert(community_db.wiki_pages),
            [
                {"id": 1, "slug": "valheim", "title": "Valheim-Server", "category": "Server", "body": "So kommst du auf **Valheim**.", "min_read_level": 0},
                {"id": 2, "slug": "regeln", "title": "Regeln", "category": "", "body": "Kein Spam auf dem Valheim-Server.", "min_read_level": 0},
                {"id": 3, "slug": "mod-handbuch", "title": "Mod-Handbuch", "category": "Intern", "body": "Valheim-Bans gehen so.", "min_read_level": 50},
                {"id": 4, "slug": "prozent", "title": "100% Uptime", "category": "", "body": "x", "min_read_level": 0},
            ],
        )
        await db.execute(update(community_db.users).where(community_db.users.c.id == 1).values(discord_id=4242))
        await db.commit()


async def test_search_respects_read_level_and_ranks_title_hits(site):  # noqa: F811
    await seed()
    assert [r[0] for r in await search("valheim", 0)] == ["valheim", "regeln"]  # Titel-Treffer zuerst
    assert [r[0] for r in await search("valheim", 50)] == ["valheim", "mod-handbuch", "regeln"]  # dann alphabetisch
    assert [r[0] for r in await search("%", 0)] == ["prozent"]  # % ist kein Platzhalter
    assert await page_by_slug("mod-handbuch", 20) is None
    assert page_link("valheim") == "https://wikinger.example/index.php?p=wiki.page&seite=valheim"


async def test_reader_level(site):  # noqa: F811
    await seed()
    assert await reader_level(4242) == 20  # Karl
    assert await reader_level(999) == 0  # nicht verknuepft
