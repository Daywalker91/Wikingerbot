"""Forum-Ankuendigungen (nur oeffentliche Kategorien) und Tickets je Kategorie (Forum, Ping, Rechte)."""

import json
from types import SimpleNamespace

from sqlalchemy import insert

from bot.cogs.forum.posting import announce_thread, excerpt, fetch_thread
from bot.cogs.tickets.cog import ROUTES_KEY, route_for
from bot.cogs.tickets.site import category_permission, is_staff
from bot.community import db as community_db
from bot.core.guild_config import set_config
from db.models.guild import Guild
from tests.test_community import site  # noqa: F401


def test_excerpt_strips_formatting():
    text = "## Plan\n**Wichtig:** wir bauen `hier`\n> Zitat\n[[Basis|unsere Basis]]\n```code```"
    assert excerpt(text) == "Plan Wichtig: wir bauen hier Zitat unsere Basis"
    assert excerpt("x" * 500).endswith("…") and len(excerpt("x" * 500)) == 220


async def seed_forum():
    async with community_db.session() as db:
        await db.execute(insert(community_db.forum_categories), [
            {"id": 1, "name": "Die Methalle", "min_read_level": 0},
            {"id": 2, "name": "Halle der Huskarle", "min_read_level": 50},
        ])
        await db.execute(insert(community_db.forum_threads), [
            {"id": 10, "category_id": 1, "user_id": 1, "title": "Basis auf Fjordur"},
            {"id": 11, "category_id": 2, "user_id": 1, "title": "Intern: Bannliste"},
        ])
        await db.execute(insert(community_db.forum_posts), [
            {"id": 100, "thread_id": 10, "user_id": 1, "body": "**Plan** für die neue Basis"},
            {"id": 101, "thread_id": 11, "user_id": 1, "body": "geheim"},
        ])
        await db.commit()


class FakeChannel:
    def __init__(self):
        self.id, self.sent = 300, []

    async def send(self, content=None, embed=None, allowed_mentions=None, view=None):
        message = SimpleNamespace(id=900 + len(self.sent), channel=self, embed=embed, view=view, content=content)
        self.sent.append(message)
        return message


async def test_only_public_threads_announced_once(site, db_session):  # noqa: F811
    await seed_forum()
    thread = await fetch_thread(10)
    assert (thread.title, thread.author, thread.category, thread.public) == ("Basis auf Fjordur", "Ragnar", "Die Methalle", True)
    assert not (await fetch_thread(11)).public

    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, "forum_channel_id", "300", "Wikinger")
    channel = FakeChannel()
    guild = SimpleNamespace(id=1, name="Wikinger", get_channel=lambda cid: channel if cid == 300 else None, get_role=lambda rid: None)
    bot = SimpleNamespace(guilds=[guild])

    assert await announce_thread(bot, 11) == []  # interner Bereich: nie in Discord
    assert await announce_thread(bot, 10) == ["Wikinger: angekündigt"]
    embed = channel.sent[0].embed
    assert "Basis auf Fjordur" in embed.title and embed.url.endswith("forum.thread&id=10") and "Plan für die neue Basis" in embed.description
    assert channel.sent[0].view.children[0].label == "Hier lesen"
    assert await announce_thread(bot, 10) == []  # nur einmal


async def test_ticket_routes_per_category(db_session):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, "tickets_channel_id", "100", "Wikinger")
    await set_config(1, "tickets_ping_role_id", "5", "Wikinger")
    await set_config(1, ROUTES_KEY, json.dumps({"melden": {"channel_id": "200", "ping_role_id": "7"}, "server": {"channel_id": "300"}}), "Wikinger")
    assert await route_for(1, "allgemein") == (100, 5)  # Standard
    assert await route_for(1, "melden") == (200, 7)  # eigenes Forum + Ping
    assert await route_for(1, "server") == (300, None)  # eigenes Forum ohne Ping - nicht den Support anpingen


async def test_staff_per_category(site):  # noqa: F811
    assert category_permission("melden") == "ticket.reports" and category_permission("technik") == "ticket.manage"
    async with community_db.session() as db:
        await db.execute(insert(community_db.role_permissions).values(role_id=2, permission="ticket.reports"))
        await db.commit()
    # Karl (Rolle 2) hat hier testweise nur "Meldungen bearbeiten"
    assert await is_staff(1, "melden") and not await is_staff(1, "allgemein") and not await is_staff(1, "server")
    assert await is_staff(1)  # irgendeine Kategorie
