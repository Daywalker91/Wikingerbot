"""events-Cog: Zusageregeln, Embed und Abgleich mit Discord (Nachricht + natives
Event) - gegen eine nachgebaute Seite und ein nachgebautes Discord."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import discord
from sqlalchemy import insert, select, update

from bot.cogs.events.cog import EventAnswerButton, event_view
from bot.cogs.events.posting import (
    SITE_TZ,
    Participants,
    build_embed,
    fetch_event,
    remove_event,
    set_participation,
    sync_event,
)
from bot.community import db as community_db
from bot.core.guild_config import set_config
from db.models.guild import Guild
from tests.test_community import site  # noqa: F401
from tests.test_news import FakeChannel


def local(days=2, hours=0):
    return (datetime.now(SITE_TZ) + timedelta(days=days, hours=hours)).replace(tzinfo=None, microsecond=0)


async def seed(event_id=1, **values):
    async with community_db.session() as db:
        await db.execute(insert(community_db.role_permissions).values(role_id=2, permission="events.join"))
        row = dict(
            id=event_id, user_id=1, title="Raid", description="Wir **raiden**!", location="Valheim",
            starts_at=local(), ends_at=None, max_participants=None, is_cancelled=0, announce_discord=1,
        )
        await db.execute(insert(community_db.events).values(**{**row, **values}))
        await db.commit()


async def set_event(event_id=1, **values):
    async with community_db.session() as db:
        await db.execute(update(community_db.events).where(community_db.events.c.id == event_id).values(**values))
        await db.commit()


async def statuses(event_id=1):
    p = community_db.event_participants
    async with community_db.session() as db:
        return dict((await db.execute(select(p.c.user_id, p.c.status).where(p.c.event_id == event_id))).all())


async def test_participation_rules(site):  # noqa: F811
    await seed(max_participants=1)
    assert await set_participation(1, 1, "yes") == "ok"
    assert await statuses() == {1: "yes"}
    assert await set_participation(1, 2, "yes") == "full"  # Limit zaehlt nur feste Zusagen
    assert await set_participation(1, 2, "maybe") == "ok"
    assert await set_participation(1, 1, "yes") == "removed"  # gleiche Antwort nochmal = zuruecknehmen
    assert await statuses() == {2: "maybe"}
    assert await set_participation(1, 2, "yes") == "ok"  # jetzt ist Platz
    assert await set_participation(99, 1, "yes") == "missing"

    await set_event(is_cancelled=1)
    assert await set_participation(1, 1, "no") == "closed"
    await set_event(is_cancelled=0, starts_at=local(days=-2))
    assert await set_participation(1, 1, "no") == "closed"  # vorbei


async def test_rank_without_events_join_cannot_answer(site):  # noqa: F811
    await seed()
    async with community_db.session() as db:
        await db.execute(community_db.role_permissions.delete())
        await db.commit()
    assert await set_participation(1, 1, "yes") == "forbidden"


async def test_embed(site):  # noqa: F811
    await seed(max_participants=2)
    item = await fetch_event(1)
    assert item.starts_at.tzinfo is not None  # Ortszeit der Seite als Europe/Berlin
    parts = Participants({"yes": ["Ragnar", "Lagertha"], "maybe": ["Loki"], "no": []})
    embed = build_embed(item, parts)
    assert embed.title == "📅 Raid"
    assert embed.url == "https://wikinger.example/index.php?p=events.view&id=1"
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Teilnehmer"] == "✅ 2/2 · ❔ 1 · ❌ 0 · **voll**"
    assert fields["Dabei"] == "Ragnar, Lagertha" and fields["Wo"] == "Valheim"
    assert f"<t:{int(item.starts_at.timestamp())}:F>" in fields["Wann"]

    item.cancelled = True
    assert build_embed(item, parts).title == "❌ ABGESAGT: Raid"


class FakeScheduled:
    def __init__(self, guild, event_id, **fields):
        self.guild, self.id, self.fields = guild, event_id, fields
        self.status = discord.EventStatus.scheduled

    async def edit(self, **fields):
        self.fields.update(fields)

    async def cancel(self):
        self.status = discord.EventStatus.cancelled

    async def delete(self):
        self.guild.scheduled.pop(self.id, None)


class FakeGuild:
    def __init__(self, channel, can_manage_events=True):
        self.id, self.name, self.channel = 1, "Wikinger", channel
        self.scheduled: dict[int, FakeScheduled] = {}
        self.can = can_manage_events
        self._next = 9000

    def get_channel(self, cid):
        return self.channel if cid == self.channel.id else None

    def get_role(self, rid):
        return None

    async def create_scheduled_event(self, **fields):
        if not self.can:
            raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
        self._next += 1
        event = FakeScheduled(self, self._next, **fields)
        self.scheduled[event.id] = event
        return event

    async def fetch_scheduled_event(self, event_id):
        if event_id not in self.scheduled:
            raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Event")
        return self.scheduled[event_id]


async def test_sync_post_change_cancel_delete(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, "events_channel_id", "500")
    channel = FakeChannel()
    guild = FakeGuild(channel)
    bot = SimpleNamespace(guilds=[guild])
    await seed()

    # posten: Nachricht mit drei Knoepfen + natives Event
    assert await sync_event(bot, 1, event_view) == ["Wikinger: gepostet", "Wikinger: Discord-Event angelegt"]
    [message] = channel.messages.values()
    [native] = guild.scheduled.values()
    assert native.fields["name"] == "Raid" and native.fields["location"] == "Valheim"
    assert native.fields["end_time"] - native.fields["start_time"] == timedelta(hours=3)

    # Zusage auf der Seite -> Zaehler im Embed
    await set_participation(1, 1, "yes")
    assert await sync_event(bot, 1, event_view) == ["Wikinger: aktualisiert"]
    assert "✅ 1" in {f.name: f.value for f in message.embed.fields}["Teilnehmer"]

    # Titel geaendert -> natives Event nachgezogen
    await set_event(title="Raid (verschoben)")
    await sync_event(bot, 1, event_view)
    assert native.fields["name"] == "Raid (verschoben)"

    # abgesagt -> Embed markiert, natives Event abgesagt
    await set_event(is_cancelled=1)
    done = await sync_event(bot, 1, event_view)
    assert "Wikinger: Discord-Event abgesagt" in done
    assert message.embed.title.startswith("❌ ABGESAGT") and native.status == discord.EventStatus.cancelled

    # geloescht -> Nachricht weg
    await remove_event(bot, 1)
    assert channel.messages == {}


async def test_missing_manage_events_still_posts_message(site, db_session):  # noqa: F811
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, "events_channel_id", "500")
    channel = FakeChannel()
    bot = SimpleNamespace(guilds=[FakeGuild(channel, can_manage_events=False)])
    await seed()
    assert await sync_event(bot, 1, event_view) == ["Wikinger: gepostet"]
    assert len(channel.messages) == 1


async def test_button_for_unlinked_member_explains_linking(site):  # noqa: F811
    await seed()
    sent = []

    class Followup:
        async def send(self, text, **kw):
            sent.append(text)

    class Response:
        async def defer(self, **kw):
            pass

    interaction = SimpleNamespace(user=SimpleNamespace(id=12345), response=Response(), followup=Followup())
    await EventAnswerButton(1, "yes").callback(interaction)
    assert "verknüpfe" in sent[0] and "/verknuepfen" in sent[0]
    assert await statuses() == {}


def test_view_has_three_buttons_and_can_be_disabled():
    view = event_view(7, disabled=True)
    ids = [item.item.custom_id for item in view.children]
    assert ids == ["wb:event:7:yes", "wb:event:7:maybe", "wb:event:7:no"]
    assert all(item.item.disabled for item in view.children)


async def test_info_event_without_rsvp(site, db_session):  # noqa: F811
    """Info-Termin (z.B. Server-Wartung): keine Knoepfe, keine Teilnehmer, keine Zusagen."""
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, "events_channel_id", "500")
    await set_config(1, "events_native", "false")
    channel = FakeChannel()
    bot = SimpleNamespace(guilds=[FakeGuild(channel)])
    await seed(rsvp_enabled=0)

    assert await set_participation(1, 1, "yes") == "norsvp"
    assert await sync_event(bot, 1, event_view) == ["Wikinger: gepostet"]
    [message] = channel.messages.values()
    assert message.view is None
    assert "Teilnehmer" not in {f.name for f in message.embed.fields}
    assert message.embed.footer.text.endswith("Info-Termin")

    # Zusagen wieder an -> Knoepfe kommen beim Aktualisieren dazu
    await set_event(rsvp_enabled=1)
    await sync_event(bot, 1, event_view)
    assert message.view is not None and "Teilnehmer" in {f.name for f in message.embed.fields}
