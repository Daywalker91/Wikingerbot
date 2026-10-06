"""tickets-Cog: Regeln wie auf der Seite und die Spiegelung Seite <-> Staff-Thread
<-> DM, gegen eine nachgebaute Seite und ein nachgebautes Discord."""

from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select, update

from bot.cogs.tickets.cog import TicketsCog
from bot.cogs.tickets.site import TicketError, add_reply, change_status, create_ticket, fetch_ticket
from bot.community import db as community_db
from bot.core.guild_config import set_config
from db.models.guild import Guild
from tests.test_community import site  # noqa: F401

MEMBER, STAFF = 1, 2  # Ragnar (Karl), Lagertha (Support)


async def setup_site():
    async with community_db.session() as db:
        await db.execute(insert(community_db.roles).values(id=5, slug="support", name="Support", level=30, color="#fff"))
        await db.execute(
            insert(community_db.role_permissions),
            [{"role_id": 2, "permission": "ticket.create"}, {"role_id": 5, "permission": "ticket.manage"}, {"role_id": 5, "permission": "ticket.create"}],
        )
        await db.execute(update(community_db.users).where(community_db.users.c.id == STAFF).values(role_id=5, discord_id=777))
        await db.execute(update(community_db.users).where(community_db.users.c.id == MEMBER).values(discord_id=4242))
        await db.commit()


async def bodies(ticket_id):
    m = community_db.ticket_messages
    async with community_db.session() as db:
        return (await db.execute(select(m.c.user_id, m.c.body, m.c.is_internal).where(m.c.ticket_id == ticket_id).order_by(m.c.id))).all()


async def test_create_validation(site):  # noqa: F811
    await setup_site()
    with pytest.raises(TicketError, match="Betreff"):
        await create_ticket(MEMBER, "Hi", "allgemein", "lange genug beschrieben")
    with pytest.raises(TicketError, match="genauer"):
        await create_ticket(MEMBER, "Server down", "allgemein", "kurz")
    with pytest.raises(TicketError, match="Kategorie"):
        await create_ticket(MEMBER, "Server down", "quatsch", "lange genug beschrieben")
    async with community_db.session() as db:  # Rang ohne ticket.create
        await db.execute(update(community_db.users).where(community_db.users.c.id == 3).values(role_id=99))
        await db.commit()
    with pytest.raises(TicketError, match="Rang"):
        await create_ticket(3, "Server down", "server", "Loki darf keine Tickets")


async def test_status_rules_like_the_site(site):  # noqa: F811
    await setup_site()
    tid = await create_ticket(MEMBER, "Server down", "technik", "Valheim startet nicht mehr")
    assert (await fetch_ticket(tid)).status == "open"

    await add_reply(tid, STAFF, "Schau ich mir an")
    ticket = await fetch_ticket(tid)
    assert ticket.status == "waiting" and ticket.assigned_to == STAFF  # wer zuerst antwortet, uebernimmt

    await add_reply(tid, MEMBER, "Danke!")
    assert (await fetch_ticket(tid)).status == "open"  # Mitglied antwortet -> wieder offen

    await add_reply(tid, STAFF, "Notiz: Mod kaputt", internal=True)
    assert (await fetch_ticket(tid)).status == "open"  # interne Notiz aendert nichts
    with pytest.raises(TicketError, match="Interne Notizen"):
        await add_reply(tid, MEMBER, "geheim", internal=True)
    with pytest.raises(TicketError, match="gehört dir nicht"):
        await add_reply(tid, 3, "Ich misch mich ein")

    await change_status(tid, STAFF, "Lagertha", "close")
    with pytest.raises(TicketError, match="geschlossen"):
        await add_reply(tid, MEMBER, "Noch was")
    await change_status(tid, MEMBER, "Ragnar", "reopen")  # eigenes Ticket wieder oeffnen darf das Mitglied
    with pytest.raises(TicketError, match="nur der Support"):
        await change_status(tid, MEMBER, "Ragnar", "claim")
    assert (await bodies(tid))[-1] == (None, "Ragnar hat das Ticket wieder geöffnet.", 0)


# --- nachgebautes Discord ------------------------------------------------------------


class FakeThread:
    def __init__(self, guild, thread_id, parent, name):
        self.guild, self.id, self.parent, self.name = guild, thread_id, parent, name
        self.archived = False
        self.sent = []

    async def send(self, text, allowed_mentions=None):
        self.sent.append(text)

    async def edit(self, archived=None, name=None):
        if archived is not None:
            self.archived = archived
        if name is not None:
            self.name = name

    async def fetch_message(self, message_id):
        raise AttributeError  # Startnachricht liegt im Elternkanal


class FakeStarter:
    def __init__(self, channel, message_id, embed, view):
        self.channel, self.id, self.embed, self.view = channel, message_id, embed, view

    async def create_thread(self, name, auto_archive_duration=None):
        thread = FakeThread(self.channel.guild, self.id, self.channel, name)
        self.channel.guild.threads[thread.id] = thread
        return thread

    async def edit(self, embed=None, view=None):
        self.embed, self.view = embed, view


class FakeText:
    def __init__(self, guild, channel_id=600):
        self.guild, self.id, self.messages = guild, channel_id, {}
        self._next = 5000

    async def send(self, content=None, embed=None, view=None, allowed_mentions=None):
        self._next += 1
        message = FakeStarter(self, self._next, embed, view)
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id):
        return self.messages[message_id]


class FakeGuild:
    def __init__(self):
        self.id, self.name, self.threads = 1, "Wikinger", {}
        self.channel = FakeText(self)

    def get_channel(self, cid):
        return self.channel if cid == self.channel.id else None

    def get_thread(self, tid):
        return self.threads.get(tid)

    def get_role(self, rid):
        return None


class FakeUser:
    def __init__(self):
        self.dms = []

    async def send(self, embed=None, view=None):
        self.dms.append((embed, view))


def make_cog():
    guild = FakeGuild()
    member_user = FakeUser()
    bot = SimpleNamespace(guilds=[guild], get_user=lambda uid: member_user if uid == 4242 else None)
    return TicketsCog(bot), guild, member_user


async def test_mirror_site_thread_dm(site, db_session, monkeypatch):  # noqa: F811
    import discord as d

    monkeypatch.setattr(d, "Thread", FakeThread)  # die nachgebauten Threads gelten als Threads
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await setup_site()
    await set_config(1, "tickets_channel_id", "600")
    cog, guild, member = make_cog()

    tid = await create_ticket(MEMBER, "Server down", "technik", "Valheim startet nicht")
    assert await cog.sync_ticket(tid) == ["Wikinger: Thread angelegt", "Wikinger: 1 Nachricht(en) gespiegelt"]
    [thread] = guild.threads.values()
    assert thread.name == "#1 Server down"
    assert thread.sent == ["**Ragnar** (Seite): Valheim startet nicht"]
    assert member.dms == []  # eigene Nachricht -> keine DM

    # Support antwortet auf der Seite -> Thread + DM mit Antworten-Knopf
    await add_reply(tid, STAFF, "Starte ihn neu")
    await add_reply(tid, STAFF, "intern: Mod pruefen", internal=True)
    await cog.sync_ticket(tid)
    assert thread.sent[-2:] == ["**Lagertha** (Seite): Starte ihn neu", "🔒 **Lagertha** (intern, Seite): intern: Mod pruefen"]
    assert len(member.dms) == 1  # interne Notiz geht nicht per DM
    embed, view = member.dms[0]
    assert "Starte ihn neu" in embed.description and view.children[0].item.custom_id == f"wb:ticketreply:{tid}"

    # Support schreibt im Thread -> landet auf der Seite, nicht doppelt im Thread, Mitglied bekommt DM
    discord_message = SimpleNamespace(
        author=SimpleNamespace(bot=False, id=777), channel=thread, content="Jetzt laeuft er wieder",
        reply=None, add_reaction=lambda e: _noop(),
    )
    sent_before = len(thread.sent)
    await cog.on_message(discord_message)
    assert (await bodies(tid))[-1] == (STAFF, "Jetzt laeuft er wieder", 0)
    assert len(thread.sent) == sent_before  # nicht zurueckgespiegelt
    assert len(member.dms) == 2

    # Schliessen ueber den Knopf -> Systemzeile im Thread, DM, Thread archiviert
    await change_status(tid, STAFF, "Lagertha", "close")
    await cog.sync_ticket(tid)
    assert thread.sent[-1] == "ℹ️ *Lagertha hat das Ticket geschlossen.*"
    assert thread.archived and "geschlossen" in member.dms[-1][0].title
    starter = guild.channel.messages[thread.id]
    assert [i.item.custom_id for i in starter.view.children] == [f"wb:ticket:{tid}:reopen"]


async def _noop():
    return None


async def test_dms_without_staff_channel(site, db_session):  # noqa: F811
    """Ohne Staff-Kanal gibt es keine Threads - die DMs an das Mitglied kommen trotzdem."""
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await setup_site()
    cog, guild, member = make_cog()
    tid = await create_ticket(MEMBER, "Frage zum Rang", "konto", "Warum bin ich noch Thrall?")
    await cog.sync_ticket(tid)
    await add_reply(tid, STAFF, "Weil du neu bist")
    assert await cog.sync_ticket(tid) == []
    assert guild.threads == {} and len(member.dms) == 1
