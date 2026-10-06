"""Banner: nur neu posten, wenn die alte Nachricht wirklich geloescht ist - nicht, wenn
Discord gerade hakt (sonst bleiben zwei Banner stehen)."""

from types import SimpleNamespace

import discord

from bot.cogs.banner.cog import BannerCog
from db.models.guild import Guild
from db.models.server import Server
from db.session import get_db_session


class FakeChannel:
    def __init__(self, error=None):
        self.error, self.sent, self.edited = error, [], []

    async def fetch_message(self, message_id):
        if self.error:
            raise self.error
        message = SimpleNamespace(id=message_id)

        async def edit(**kwargs):
            self.edited.append(message_id)

        message.edit = edit
        return message

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(id=999)


async def _setup(db_session, channel):
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    db_session.add(Server(guild_id=1, instance_name="v", amp_instance_id="i", display_name="Valheim", host="",
                          banner_enabled=True, banner_channel=50, banner_message_id=123))
    await db_session.commit()
    cog = BannerCog(SimpleNamespace(get_channel=lambda cid: channel if cid == 50 else None))

    async def payload(server):
        return None, None, None

    cog._build_server_payload = payload
    async with get_db_session() as db:
        server_id = (await db.get(Server, 1)).id
    return cog, server_id


def _http_error(status: int, cls=discord.HTTPException):
    return cls(SimpleNamespace(status=status, reason="x"), "fehler")


async def test_discord_hiccup_does_not_repost(db_session):
    channel = FakeChannel(error=_http_error(503))
    cog, server_id = await _setup(db_session, channel)
    await cog._post_or_refresh_server(server_id)
    assert channel.sent == []  # kein zweiter Banner


async def test_deleted_message_is_reposted(db_session):
    channel = FakeChannel(error=_http_error(404, discord.NotFound))
    cog, server_id = await _setup(db_session, channel)
    await cog._post_or_refresh_server(server_id)
    assert len(channel.sent) == 1
    async with get_db_session() as db:
        assert (await db.get(Server, server_id)).banner_message_id == 999


async def test_existing_message_is_edited(db_session):
    channel = FakeChannel()
    cog, server_id = await _setup(db_session, channel)
    await cog._post_or_refresh_server(server_id)
    assert channel.edited == [123] and channel.sent == []
