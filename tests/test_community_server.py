"""Community-Server-Funktionen von Discord: Ankuendigungskanaele, Mitgliedschaftspruefung
und Tags im Ticket-Forum."""

from types import SimpleNamespace

import discord
from sqlalchemy import insert

from bot.cogs.tickets.cog import TicketsCog
from bot.cogs.tickets.site import change_status, create_ticket
from bot.cogs.welcome.cog import WelcomeCog
from bot.community import db as community_db
from bot.community.announce import publish_if_announcement
from bot.core.guild_config import set_config
from db.models.guild import Guild
from tests.test_community import site  # noqa: F401
from tests.test_tickets import MEMBER, STAFF, setup_site

# --- Ankuendigungskanal ---------------------------------------------------------------


class Published:
    def __init__(self, channel_type, fail=False):
        self.id, self.channel = 1, SimpleNamespace(type=channel_type)
        self.fail, self.published = fail, False

    async def publish(self):
        if self.fail:
            raise discord.HTTPException(SimpleNamespace(status=429, reason="Too Many Requests"), "rate limited")
        self.published = True


async def test_publish_only_in_announcement_channels():
    news = Published(discord.ChannelType.news)
    assert await publish_if_announcement(news) and news.published
    text = Published(discord.ChannelType.text)
    assert not await publish_if_announcement(text) and not text.published


async def test_publish_failure_is_not_fatal():
    assert not await publish_if_announcement(Published(discord.ChannelType.news, fail=True))


# --- Begruessung nach der Mitgliedschaftspruefung ----------------------------------------


async def test_welcome_waits_for_rules_screening():
    cog = WelcomeCog(SimpleNamespace())
    greeted = []

    async def greet(member):
        greeted.append(member.id)

    cog._greet = greet
    pending = SimpleNamespace(id=1, bot=False, pending=True)
    await cog.on_member_join(pending)
    assert greeted == []  # Regeln noch nicht akzeptiert

    accepted = SimpleNamespace(id=1, bot=False, pending=False)
    await cog.on_member_update(pending, accepted)
    assert greeted == [1]

    await cog.on_member_update(accepted, accepted)  # andere Aenderung (z.B. Nickname) -> nicht nochmal
    await cog.on_member_join(SimpleNamespace(id=2, bot=False, pending=False))  # Server ohne Pruefung
    await cog.on_member_join(SimpleNamespace(id=3, bot=True, pending=False))
    assert greeted == [1, 2]


# --- Tags im Ticket-Forum ----------------------------------------------------------------


class ForumThread:
    def __init__(self, thread_id, parent, name, tags):
        self.id, self.parent, self.name = thread_id, parent, name
        self.guild = parent.guild
        self.archived = False
        self.applied_tags = list(tags)
        self.sent = []
        self.edits = []

    async def send(self, text, allowed_mentions=None):
        self.sent.append(text)

    async def edit(self, archived=None, name=None, applied_tags=None):
        self.edits.append({"archived": archived, "applied_tags": applied_tags})
        if self.archived and archived is None:
            raise discord.HTTPException(SimpleNamespace(status=400, reason="Bad Request"), "Thread is archived")
        if archived is not None:
            self.archived = archived
        if name is not None:
            self.name = name
        if applied_tags is not None:
            self.applied_tags = list(applied_tags)

    async def fetch_message(self, message_id):
        return self.starter


class Forum:
    def __init__(self, guild, channel_id=600, may_manage=True, tags=()):
        self.guild, self.id, self.name = guild, channel_id, "tickets"
        self.available_tags = list(tags)
        self.may_manage = may_manage
        self._next = 5000

    async def edit(self, available_tags):
        if not self.may_manage:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
        for tag in available_tags:
            if not tag.id:
                self._next += 1
                tag.id = self._next
        self.available_tags = list(available_tags)
        return self

    async def create_thread(self, name, content=None, embed=None, view=None, allowed_mentions=None, applied_tags=()):
        self._next += 1
        thread = ForumThread(self._next, self, name, applied_tags)
        thread.starter = SimpleNamespace(edit=_noop_edit)
        self.guild.threads[thread.id] = thread
        return SimpleNamespace(thread=thread, message=thread.starter)


async def _noop_edit(**kwargs):
    return None


class ForumGuild:
    def __init__(self, **forum_options):
        self.id, self.name, self.threads = 1, "Wikinger", {}
        self.forum = Forum(self, **forum_options)

    def get_channel(self, cid):
        return self.forum if cid == self.forum.id else None

    def get_thread(self, tid):
        return self.threads.get(tid)

    def get_role(self, rid):
        return None


async def _forum_cog(db_session, monkeypatch, **forum_options):
    monkeypatch.setattr(discord, "ForumChannel", Forum)
    monkeypatch.setattr(discord, "Thread", ForumThread)
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await setup_site()
    await set_config(1, "tickets_channel_id", "600")
    guild = ForumGuild(**forum_options)
    dm_user = SimpleNamespace(send=_noop_edit)
    bot = SimpleNamespace(guilds=[guild], get_user=lambda uid: dm_user)
    return TicketsCog(bot), guild


def names(tags):
    return sorted(tag.name for tag in tags)


async def test_forum_tags_created_and_follow_status(site, db_session, monkeypatch):  # noqa: F811
    team_tag = discord.ForumTag(name="Dringend")
    team_tag.id = 42
    cog, guild = await _forum_cog(db_session, monkeypatch, tags=[team_tag])
    async with community_db.session() as db:  # Gameserver-Tickets bearbeitet, wer ticket.server hat
        await db.execute(insert(community_db.role_permissions).values(role_id=5, permission="ticket.server"))
        await db.commit()

    tid = await create_ticket(MEMBER, "Server down", "server", "Valheim startet nicht")
    await cog.sync_ticket(tid)
    [thread] = guild.threads.values()
    assert names(thread.applied_tags) == ["Gameserver", "Offen"]
    assert names(guild.forum.available_tags) == ["Dringend", "Gameserver", "Offen"]

    # Team setzt selbst einen Tag dazu - der bleibt beim Statuswechsel stehen
    thread.applied_tags.append(team_tag)
    await change_status(tid, STAFF, "Lagertha", "claim")
    await cog.sync_ticket(tid)
    assert names(thread.applied_tags) == ["Dringend", "Gameserver", "In Bearbeitung"]

    # Schliessen: Tag und Archivierung in einem Aufruf
    await change_status(tid, STAFF, "Lagertha", "close")
    await cog.sync_ticket(tid)
    assert thread.archived and names(thread.applied_tags) == ["Dringend", "Gameserver", "Geschlossen"]
    assert thread.edits[-1]["archived"] is True and thread.edits[-1]["applied_tags"] is not None

    # Wieder oeffnen geht trotz Archiv, weil beides zusammen geschickt wird
    await change_status(tid, STAFF, "Lagertha", "reopen")
    await cog.sync_ticket(tid)
    assert not thread.archived and "Geschlossen" not in names(thread.applied_tags)


async def test_forum_without_manage_channels_still_works(site, db_session, monkeypatch):  # noqa: F811
    open_tag = discord.ForumTag(name="Offen")  # vom Team selbst angelegt
    open_tag.id = 7
    cog, guild = await _forum_cog(db_session, monkeypatch, may_manage=False, tags=[open_tag])

    tid = await create_ticket(MEMBER, "Frage", "allgemein", "Wie komme ich auf den Server?")
    assert (await cog.sync_ticket(tid))[0] == "Wikinger: Thread angelegt"
    [thread] = guild.threads.values()
    assert names(thread.applied_tags) == ["Offen"]  # nur der vorhandene, ohne Fehler
    assert guild.forum.id in cog._tags_denied

    await change_status(tid, STAFF, "Lagertha", "close")
    await cog.sync_ticket(tid)
    assert thread.archived and thread.applied_tags == []  # "Geschlossen" fehlt - Status-Tag faellt weg
