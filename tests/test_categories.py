"""Kategorien der Seite (News/Events) -> Rollen anpingen."""

from types import SimpleNamespace

from sqlalchemy import insert, text

from bot.cogs.news.posting import sync_news
from bot.community import categories
from bot.community import db as community_db
from bot.core.guild_config import set_config
from db.models.guild import Guild
from tests.test_community import site  # noqa: F401  (Fixture: nachgebaute Seiten-DB)
from tests.test_news import FakeChannel, add_news


class Role(SimpleNamespace):
    @property
    def mention(self):
        return f"<@&{self.id}>"


ROLES = {77: Role(id=77), 88: Role(id=88), 99: Role(id=99)}


def bot_with(channel):
    guild = SimpleNamespace(
        id=1,
        name="Wikinger",
        get_channel=lambda cid: channel if cid == channel.id else None,
        get_role=ROLES.get,
    )
    return SimpleNamespace(guilds=[guild])


async def _setup(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, "news_channel_id", "500")
    await set_config(1, "news_ping_role_id", "77")
    async with community_db.session() as db:
        await db.execute(insert(community_db.announce_categories), [{"id": 1, "name": "Server"}, {"id": 2, "name": "Valheim"}])
        await db.commit()


async def _assign(news_id, *category_ids):
    async with community_db.session() as db:
        await db.execute(insert(community_db.news_categories), [{"news_id": news_id, "category_id": c} for c in category_ids])
        await db.commit()


async def test_category_roles_are_pinged(site, db_session):  # noqa: F811
    await _setup(db_session)
    await categories.save_role_map(1, "Wikinger", {1: [88], 2: [99, 88], 5: []})
    await add_news()
    await _assign(1, 1, 2)
    channel = FakeChannel()
    assert await sync_news(bot_with(channel), 1) == ["Wikinger: gepostet"]
    [message] = channel.messages.values()
    assert message.content == "<@&88> <@&99>"  # jede Rolle einmal, ohne die allgemeine Ping-Rolle


async def test_without_mapped_category_the_general_role_is_pinged(site, db_session):  # noqa: F811
    await _setup(db_session)
    await categories.save_role_map(1, "Wikinger", {2: [99]})
    await add_news()
    await _assign(1, 1)  # "Server" hat keine Rollen
    channel = FakeChannel()
    await sync_news(bot_with(channel), 1)
    [message] = channel.messages.values()
    assert message.content == "<@&77>"


async def test_deleted_roles_are_skipped(site, db_session):  # noqa: F811
    await _setup(db_session)
    await categories.save_role_map(1, "Wikinger", {1: [12345, 99]})
    await add_news()
    await _assign(1, 1)
    channel = FakeChannel()
    await sync_news(bot_with(channel), 1)
    assert next(iter(channel.messages.values())).content == "<@&99>"


async def test_site_without_category_tables_still_posts(site, db_session):  # noqa: F811
    await _setup(db_session)
    async with community_db.session() as db:
        await db.execute(text("DROP TABLE news_categories"))
        await db.commit()
    await add_news()
    channel = FakeChannel()
    assert await sync_news(bot_with(channel), 1) == ["Wikinger: gepostet"]
    assert next(iter(channel.messages.values())).content == "<@&77>"


async def test_ui_lists_categories_with_roles(site, db_session):  # noqa: F811
    await _setup(db_session)
    await categories.save_role_map(1, "Wikinger", {2: [99]})
    data = await categories.categories_for_ui(1)
    assert data == {
        "categories": [{"id": 1, "name": "Server", "role_ids": []}, {"id": 2, "name": "Valheim", "role_ids": ["99"]}],
        "categories_error": None,
    }
    async with community_db.session() as db:
        await db.execute(text("DROP TABLE announce_categories"))
        await db.commit()
    data = await categories.categories_for_ui(1)
    assert data["categories"] == [] and data["categories_error"].startswith("Kategorien nicht lesbar")
