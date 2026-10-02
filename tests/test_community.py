"""Anbindung an die Community-Seite: Verknuepfen und Outbox - gegen eine
SQLite-Nachbildung der Seiten-Tabellen (die echten legt die Seite an)."""

import json
from datetime import UTC, datetime, timedelta

import discord
import pytest
import pytest_asyncio
from discord.ext import commands
from sqlalchemy import insert, select

from bot.community import db as community_db
from bot.community import outbox
from bot.community.db import bot_outbox, discord_link_codes, roles, users
from bot.community.linking import LinkError, link_with_code, normalize_code, unlink_discord, user_for_discord
from bot.core.config import settings


@pytest_asyncio.fixture
async def site(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "community_database_url", f"sqlite+aiosqlite:///{(tmp_path / 'site.db').as_posix()}")
    monkeypatch.setattr(settings, "community_site_url", "https://wikinger.example")
    await community_db.dispose()
    async with community_db.engine().begin() as conn:
        await conn.run_sync(community_db.metadata.create_all)
        await conn.execute(insert(roles), [{"id": 2, "slug": "karl", "name": "Karl", "level": 20, "color": "#c9a35c"}])
        await conn.execute(
            insert(users),
            [
                {"id": 1, "username": "Ragnar", "role_id": 2, "is_banned": 0},
                {"id": 2, "username": "Lagertha", "role_id": 2, "is_banned": 0},
                {"id": 3, "username": "Loki", "role_id": 2, "is_banned": 1},
            ],
        )
    yield
    for kind in outbox.registered():
        outbox.unregister(kind)
    await community_db.dispose()


async def add_code(user_id: int, code: str, minutes: int = 15) -> None:
    # SQLite: CURRENT_TIMESTAMP ist UTC - die Seite nutzt NOW() der MariaDB, beides dieselbe Uhr
    async with community_db.session() as db:
        await db.execute(
            insert(discord_link_codes).values(user_id=user_id, code=code, expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=minutes))
        )
        await db.commit()


def test_normalize_code():
    assert normalize_code(" abcd-efgh ") == "ABCDEFGH"


async def test_link_success(site):
    await add_code(1, "ABCDEFGH")
    user = await link_with_code("abcd efgh", 4242, "ragnar")
    assert (user.id, user.username, user.role_name) == (1, "Ragnar", "Karl")

    async with community_db.session() as db:
        row = (await db.execute(select(users.c.discord_id, users.c.discord_name).where(users.c.id == 1))).first()
        codes = (await db.execute(select(discord_link_codes))).all()
    assert row == (4242, "ragnar") and codes == []  # Code nur einmal nutzbar
    assert (await user_for_discord(4242)).username == "Ragnar"


@pytest.mark.parametrize("code", ["KURZ", "ABCDEFG1", "ABCDEFGI"])  # zu kurz, 1 und I gibt es im Alphabet nicht
async def test_invalid_code_format(site, code):
    with pytest.raises(LinkError, match="kein gültiger Code"):
        await link_with_code(code, 1, "x")


async def test_expired_or_unknown_code(site):
    await add_code(1, "ABCDEFGH", minutes=-1)
    with pytest.raises(LinkError, match="abgelaufen"):
        await link_with_code("ABCDEFGH", 4242, "ragnar")
    with pytest.raises(LinkError, match="abgelaufen"):
        await link_with_code("ZZZZZZZZ", 4242, "ragnar")


async def test_banned_account_cannot_link(site):
    await add_code(3, "LKLKLKLK")
    with pytest.raises(LinkError, match="gesperrt"):
        await link_with_code("LKLKLKLK", 666, "loki")


async def test_discord_account_already_linked_elsewhere(site):
    await add_code(1, "AAAAAAAA")
    await link_with_code("AAAAAAAA", 4242, "ragnar")
    await add_code(2, "BBBBBBBB")
    with pytest.raises(LinkError, match="schon mit \\*\\*Ragnar\\*\\*"):
        await link_with_code("BBBBBBBB", 4242, "ragnar")


async def test_unlink(site):
    await add_code(1, "AAAAAAAA")
    await link_with_code("AAAAAAAA", 4242, "ragnar")
    assert (await unlink_discord(4242)).username == "Ragnar"
    assert await user_for_discord(4242) is None
    assert await unlink_discord(4242) is None


async def test_outbox_dispatch_retry_and_untouched_types(site):
    async with community_db.session() as db:
        await db.execute(
            insert(bot_outbox),
            [
                {"type": "news.saved", "payload": json.dumps({"news_id": 1}), "attempts": 0},
                {"type": "ticket.created", "payload": json.dumps({"ticket_id": 7}), "attempts": 0},
                {"type": "event.saved", "payload": json.dumps({"event_id": 3}), "attempts": 0},
            ],
        )
        await db.commit()

    seen = []

    async def news(payload):
        seen.append(payload)

    async def broken(payload):
        raise RuntimeError("Kanal fehlt")

    outbox.register("news.saved", news)
    outbox.register("ticket.created", broken)
    # event.saved hat keinen Zustaendigen -> bleibt unberuehrt

    assert await outbox.process_pending() == 1
    assert seen == [{"news_id": 1}]

    async with community_db.session() as db:
        rows = {r.type: r for r in (await db.execute(select(bot_outbox))).all()}
    assert rows["news.saved"].processed_at is not None
    assert rows["ticket.created"].processed_at is None and rows["ticket.created"].attempts == 1
    assert rows["ticket.created"].last_error == "Kanal fehlt"
    assert rows["event.saved"].attempts == 0

    for _ in range(outbox.MAX_ATTEMPTS):
        await outbox.process_pending()
    assert await outbox.counts() == {"pending": 1, "failed": 1}  # event.saved offen, ticket aufgegeben


async def test_site_link(site):
    assert community_db.site_link("user", id=5) == "https://wikinger.example/index.php?p=user&id=5"


async def test_cog_skipped_without_community_db(monkeypatch):
    monkeypatch.setattr(settings, "community_database_url", "")
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    await bot.load_extension("bot.cogs.community.cog")
    assert bot.get_cog("CommunityCog") is None and not bot.tree.get_commands()


async def test_cog_loads_with_community_db(site):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    await bot.load_extension("bot.cogs.community.cog")
    names = sorted(c.name for c in bot.tree.get_commands())
    assert names == ["community", "profil", "verknuepfen", "verknuepfung_loesen"]
    for command in bot.tree.get_commands():
        command.to_dict(bot.tree)
    assert "user.unlinked" in outbox.registered()
    await bot.remove_cog("CommunityCog")
    assert "user.unlinked" not in outbox.registered()


def test_community_url_from_db_name():
    from bot.core.config import Settings

    s = Settings(_env_file=None, db_host="10.0.0.107", db_user="wikingerbot", db_password="p#w", community_db_name="php")
    assert s.community_database_url == "mysql+asyncmy://wikingerbot:p%23w@10.0.0.107:3306/php"
    assert Settings(_env_file=None, community_db_name="php").community_database_url == ""  # ohne DB_HOST keine Anbindung
