"""news-Cog: News der Seite <-> Discord-Nachricht, gegen eine nachgebaute Seite
und einen nachgebauten Discord-Kanal."""

from types import SimpleNamespace

import discord
from sqlalchemy import insert, update

from bot.cogs.news.posting import image_url, plain_excerpt, remove_news, sync_news
from bot.community import db as community_db
from bot.core.guild_config import set_config
from db.models.guild import Guild
from tests.test_community import site  # noqa: F401  (Fixture: nachgebaute Seiten-DB)


class FakeMessage:
    def __init__(self, channel, message_id, content, embed, view=None):
        self.channel, self.id, self.content, self.embed, self.view = channel, message_id, content, embed, view

    async def edit(self, embed, view=None):
        self.embed, self.view = embed, view
        self.channel.log.append(("edit", self.id))

    async def delete(self):
        self.channel.messages.pop(self.id, None)
        self.channel.log.append(("delete", self.id))


class FakeChannel:
    def __init__(self, channel_id=500):
        self.id = channel_id
        self.messages: dict[int, FakeMessage] = {}
        self.log = []
        self._next = 1000

    async def send(self, content=None, embed=None, view=None, allowed_mentions=None):
        self._next += 1
        message = FakeMessage(self, self._next, content, embed, view)
        self.messages[message.id] = message
        self.log.append(("send", message.id))
        return message

    async def fetch_message(self, message_id):
        if message_id not in self.messages:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
        return self.messages[message_id]


def fake_bot(channel, role=None):
    guild = SimpleNamespace(
        id=1,
        name="Wikinger",
        get_channel=lambda cid: channel if cid == channel.id else None,
        get_role=lambda rid: role if role and rid == role.id else None,
    )
    return SimpleNamespace(guilds=[guild])


async def add_news(news_id=1, published=1, announce=1, image=None):
    async with community_db.session() as db:
        await db.execute(
            insert(community_db.news).values(
                id=news_id, user_id=1, title="Met-Abend", body="**Kommt** alle!\n[[Taverne|in die Taverne]]",
                image=image, is_pinned=0, is_published=published, announce_discord=announce,
            )
        )
        await db.commit()


async def set_news(news_id=1, **values):
    async with community_db.session() as db:
        await db.execute(update(community_db.news).where(community_db.news.c.id == news_id).values(**values))
        await db.commit()


def test_plain_excerpt():
    assert plain_excerpt("**Kommt** alle!\n[[Taverne|in die Taverne]] `x`") == "Kommt alle! in die Taverne x"
    assert plain_excerpt("a" * 500, 10) == "a" * 9 + "…"


async def test_image_url(site):  # noqa: F811
    assert image_url("https://cdn.example/x.png") == "https://cdn.example/x.png"
    assert image_url("assets/img/wald.jpg") == "https://wikinger.example/assets/img/wald.jpg"
    assert image_url("http://unsicher/x.png") is None
    assert image_url(None) is None


async def test_post_update_retract_repost_delete(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, "news_channel_id", "500")
    role = SimpleNamespace(id=77, mention="<@&77>")
    await set_config(1, "news_ping_role_id", "77")
    channel = FakeChannel()
    bot = fake_bot(channel, role)
    await add_news(image="assets/img/met.jpg")

    # 1. veroeffentlicht + Haken -> gepostet, Rolle angepingt
    assert await sync_news(bot, 1) == ["Wikinger: gepostet"]
    [message] = channel.messages.values()
    assert message.content == "<@&77>"
    assert message.embed.title == "📰 Met-Abend"
    assert message.embed.url == "https://wikinger.example/index.php?p=news.view&id=1"
    assert message.embed.image.url == "https://wikinger.example/assets/img/met.jpg"
    assert message.embed.footer.text == "von Ragnar"

    # 2. bearbeitet -> dieselbe Nachricht aktualisiert, kein zweiter Ping
    await set_news(title="Met-Abend (verschoben)", is_pinned=1)
    assert await sync_news(bot, 1) == ["Wikinger: aktualisiert"]
    assert len(channel.messages) == 1 and message.embed.title == "📌 Met-Abend (verschoben)"

    # 3. Haken weg -> Nachricht entfernt
    await set_news(announce_discord=0)
    assert await sync_news(bot, 1) == ["Wikinger: entfernt"]
    assert channel.messages == {}

    # 4. wieder an -> neu gepostet
    await set_news(announce_discord=1)
    assert await sync_news(bot, 1) == ["Wikinger: gepostet"]

    # 5. jemand loescht die Nachricht in Discord -> beim naechsten Speichern neu gepostet
    channel.messages.clear()
    assert await sync_news(bot, 1) == ["Wikinger: gepostet"]
    assert len(channel.messages) == 1

    # 6. News auf der Seite geloescht -> Nachricht weg
    await remove_news(bot, 1)
    assert channel.messages == {}


async def test_drafts_and_servers_without_channel_are_skipped(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    channel = FakeChannel()
    await add_news(news_id=1)
    assert await sync_news(fake_bot(channel), 1) == []  # kein News-Kanal eingestellt

    await set_config(1, "news_channel_id", "500")
    await add_news(news_id=2, published=0)
    assert await sync_news(fake_bot(channel), 2) == []  # Entwurf
    assert channel.messages == {}
