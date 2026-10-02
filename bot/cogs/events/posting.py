"""Events der Community-Seite in Discord: Embed mit Zusage-Knoepfen und optional
ein natives Discord-Event (nur zur Anzeige). Ohne Discord-Cog-Abhaengigkeit,
damit testbar.

Zusagen gelten pro Konto auf der Seite (event_participants) - aus Discord nur
fuer verknuepfte Mitglieder mit dem Recht events.join, mit denselben Regeln wie
auf der Seite (Limit zaehlt nur feste Zusagen, keine Zusagen fuer abgesagte oder
vergangene Events).

Zeiten: Die Seite speichert Event-Zeiten ohne Zeitzone in Europe/Berlin.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from sqlalchemy import delete, func, insert, select, update

from bot.community import db as community_db
from bot.community.text import plain_excerpt
from bot.core.entities import ensure_guild
from bot.core.guild_config import get_config
from db.models.community_post import CommunityPost
from db.session import get_db_session

log = logging.getLogger("wikingerbot.events")

KIND = "event"
NATIVE_KIND = "event_native"  # message_id = ID des nativen Discord-Events
SITE_TZ = ZoneInfo("Europe/Berlin")
DEFAULT_DURATION = timedelta(hours=3)  # wie auf der Seite, wenn kein Ende angegeben ist
COLOR = 0x5FA8A0
ANSWERS = {"yes": ("✅", "Dabei"), "maybe": ("❔", "Vielleicht"), "no": ("❌", "Nicht dabei")}
MAX_NAMES = 20


@dataclass
class EventItem:
    id: int
    title: str
    description: str
    location: str
    starts_at: datetime  # mit Zeitzone
    ends_at: datetime | None
    max_participants: int | None
    cancelled: bool
    announce: bool
    author: str

    @property
    def end(self) -> datetime:
        return self.ends_at or self.starts_at + DEFAULT_DURATION

    def is_past(self, now: datetime | None = None) -> bool:
        return self.end < (now or datetime.now(timezone.utc))


@dataclass
class Participants:
    by_status: dict[str, list[str]] = field(default_factory=lambda: {"yes": [], "maybe": [], "no": []})

    def count(self, status: str) -> int:
        return len(self.by_status[status])


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=SITE_TZ)


def _event_query():
    e, u = community_db.events, community_db.users
    return select(
        e.c.id, e.c.title, e.c.description, e.c.location, e.c.starts_at, e.c.ends_at,
        e.c.max_participants, e.c.is_cancelled, e.c.announce_discord, u.c.username,
    ).select_from(e.join(u, u.c.id == e.c.user_id))


def _to_event(row) -> EventItem:
    return EventItem(
        id=row[0], title=row[1], description=row[2] or "", location=row[3] or "",
        starts_at=_aware(row[4]), ends_at=_aware(row[5]), max_participants=row[6],
        cancelled=bool(row[7]), announce=bool(row[8]), author=row[9],
    )


async def fetch_event(event_id: int) -> EventItem | None:
    async with community_db.session() as db:
        row = (await db.execute(_event_query().where(community_db.events.c.id == event_id))).first()
    return _to_event(row) if row else None


async def upcoming_events(limit: int = 10) -> list[EventItem]:
    """Kommende und laufende Events (Ende frühestens jetzt), naechste zuerst."""
    e = community_db.events
    cutoff = datetime.now(SITE_TZ).replace(tzinfo=None) - DEFAULT_DURATION
    async with community_db.session() as db:
        rows = (await db.execute(_event_query().where(e.c.starts_at >= cutoff).order_by(e.c.starts_at).limit(limit * 2))).all()
    items = [_to_event(r) for r in rows]
    return [i for i in items if not i.is_past()][:limit]


async def fetch_participants(event_id: int) -> Participants:
    p, u = community_db.event_participants, community_db.users
    async with community_db.session() as db:
        rows = (
            await db.execute(
                select(p.c.status, u.c.username)
                .select_from(p.join(u, u.c.id == p.c.user_id))
                .where(p.c.event_id == event_id)
                .order_by(p.c.updated_at)
            )
        ).all()
    result = Participants()
    for status, name in rows:
        if status in result.by_status:
            result.by_status[status].append(name)
    return result


async def can_join(site_user_id: int) -> bool:
    u, rp = community_db.users, community_db.role_permissions
    async with community_db.session() as db:
        row = (
            await db.execute(
                select(rp.c.permission)
                .select_from(u.join(rp, rp.c.role_id == u.c.role_id))
                .where(u.c.id == site_user_id, rp.c.permission.in_(["events.join", "*"]))
                .limit(1)
            )
        ).first()
    return row is not None


async def set_participation(event_id: int, site_user_id: int, answer: str) -> str:
    """Zusage aus Discord. Ergebnis: ok | removed | full | closed | missing | forbidden.
    Dieselbe Antwort nochmal klicken nimmt sie zurueck."""
    if answer not in ANSWERS:
        raise ValueError(answer)
    if not await can_join(site_user_id):
        return "forbidden"
    e, p = community_db.events, community_db.event_participants
    async with community_db.session() as db:
        async with db.begin():
            # sperrt die Event-Zeile wie die Seite, damit zwei nicht gleichzeitig den letzten Platz bekommen
            event = (
                await db.execute(
                    select(e.c.max_participants, e.c.is_cancelled, e.c.starts_at, e.c.ends_at)
                    .where(e.c.id == event_id)
                    .with_for_update()
                )
            ).first()
            if event is None:
                return "missing"
            end = _aware(event.ends_at) or _aware(event.starts_at) + DEFAULT_DURATION
            if event.is_cancelled or end < datetime.now(timezone.utc):
                return "closed"
            current = (
                await db.execute(select(p.c.status).where(p.c.event_id == event_id, p.c.user_id == site_user_id))
            ).scalar_one_or_none()
            if current == answer:
                await db.execute(delete(p).where(p.c.event_id == event_id, p.c.user_id == site_user_id))
                return "removed"
            if answer == "yes" and current != "yes" and event.max_participants is not None:
                yes = (
                    await db.execute(select(func.count()).where(p.c.event_id == event_id, p.c.status == "yes"))
                ).scalar_one()
                if yes >= event.max_participants:
                    return "full"
            if current is None:
                await db.execute(insert(p).values(event_id=event_id, user_id=site_user_id, status=answer, updated_at=func.now()))
            else:
                await db.execute(
                    update(p).where(p.c.event_id == event_id, p.c.user_id == site_user_id).values(status=answer, updated_at=func.now())
                )
    return "ok"


def _ts(value: datetime, style: str) -> str:
    return f"<t:{int(value.timestamp())}:{style}>"


def build_embed(item: EventItem, parts: Participants) -> discord.Embed:
    link = community_db.site_link("events.view", id=item.id)
    prefix = "❌ ABGESAGT: " if item.cancelled else "📅 "
    embed = discord.Embed(title=(prefix + item.title)[:256], url=link, description=plain_excerpt(item.description, 500), color=COLOR)
    when = f"{_ts(item.starts_at, 'F')} ({_ts(item.starts_at, 'R')})"
    if item.ends_at:
        when += f"\nbis {_ts(item.ends_at, 't' if item.ends_at.date() == item.starts_at.date() else 'f')}"
    embed.add_field(name="Wann", value=when, inline=False)
    if item.location:
        embed.add_field(name="Wo", value=item.location[:1024], inline=False)
    yes = parts.count("yes")
    limit = f"/{item.max_participants}" if item.max_participants else ""
    full = " · **voll**" if item.max_participants and yes >= item.max_participants else ""
    embed.add_field(
        name="Teilnehmer",
        value=f"✅ {yes}{limit} · ❔ {parts.count('maybe')} · ❌ {parts.count('no')}{full}",
        inline=False,
    )
    if parts.by_status["yes"]:
        names = parts.by_status["yes"][:MAX_NAMES]
        more = len(parts.by_status["yes"]) - len(names)
        embed.add_field(name="Dabei", value=", ".join(names) + (f" und {more} weitere" if more else ""), inline=False)
    footer = f"von {item.author}"
    if item.cancelled:
        footer += " · abgesagt"
    elif item.is_past():
        footer += " · vorbei"
    else:
        footer += " · Zusagen nur mit verknüpftem Konto (/verknuepfen)"
    embed.set_footer(text=footer)
    return embed


def should_post(item: EventItem | None) -> bool:
    return item is not None and item.announce


async def _mapping(kind: str, guild_id: int, event_id: int) -> CommunityPost | None:
    async with get_db_session() as db:
        return await db.get(CommunityPost, (kind, event_id, guild_id))


async def _remember(kind: str, guild: discord.Guild, event_id: int, channel_id: int, message_id: int) -> None:
    await ensure_guild(guild.id, guild.name)
    async with get_db_session() as db:
        db.add(CommunityPost(kind=kind, item_id=event_id, guild_id=guild.id, channel_id=channel_id, message_id=message_id))
        await db.commit()


async def _forget(kind: str, guild_id: int, event_id: int) -> None:
    async with get_db_session() as db:
        row = await db.get(CommunityPost, (kind, event_id, guild_id))
        if row is not None:
            await db.delete(row)
            await db.commit()


async def _message(guild: discord.Guild, mapping: CommunityPost) -> discord.Message | None:
    channel = guild.get_channel(mapping.channel_id)
    if channel is None:
        return None
    try:
        return await channel.fetch_message(mapping.message_id)
    except discord.NotFound:
        return None


async def sync_event(bot: discord.Client, event_id: int, view_factory=None) -> list[str]:
    """Embed (und natives Event) auf den aktuellen Stand bringen.
    view_factory(event_id, disabled) liefert die Knoepfe (vom Cog, wegen DynamicItem)."""
    item = await fetch_event(event_id)
    parts = await fetch_participants(event_id) if item else Participants()
    done = []
    for guild in bot.guilds:
        channel_id = await get_config(guild.id, "events_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        mapping = await _mapping(KIND, guild.id, event_id)

        if not should_post(item):
            if mapping is not None:
                message = await _message(guild, mapping)
                if message is not None:
                    await message.delete()
                await _forget(KIND, guild.id, event_id)
                done.append(f"{guild.name}: entfernt")
            await _sync_native(guild, event_id, None, done)
            continue
        if channel is None and mapping is None:
            continue

        embed = build_embed(item, parts)
        closed = item.cancelled or item.is_past()
        view = view_factory(event_id, closed) if view_factory else None
        message = await _message(guild, mapping) if mapping else None
        if message is not None:
            await message.edit(embed=embed, view=view)
            done.append(f"{guild.name}: aktualisiert")
        elif channel is not None:
            if mapping is not None:
                await _forget(KIND, guild.id, event_id)  # in Discord geloescht -> neu posten
            role_id = await get_config(guild.id, "events_ping_role_id")
            role = guild.get_role(int(role_id)) if role_id else None
            sent = await channel.send(
                content=role.mention if role else None,
                embed=embed,
                view=view,
                allowed_mentions=discord.AllowedMentions(roles=[role] if role else False, everyone=False, users=False),
            )
            await _remember(KIND, guild, event_id, sent.channel.id, sent.id)
            done.append(f"{guild.name}: gepostet")
        if await get_config(guild.id, "events_native", "true") == "true":
            await _sync_native(guild, event_id, item, done)
    return done


async def _sync_native(guild: discord.Guild, event_id: int, item: EventItem | None, done: list[str]) -> None:
    """Natives Discord-Event - braucht das Recht 'Events verwalten'. Fehler hier
    duerfen das Embed nicht verhindern, sie landen nur im Log."""
    mapping = await _mapping(NATIVE_KIND, guild.id, event_id)
    try:
        native = None
        if mapping is not None:
            try:
                native = await guild.fetch_scheduled_event(mapping.message_id)
            except discord.NotFound:
                await _forget(NATIVE_KIND, guild.id, event_id)
                mapping = None
        active = native is not None and native.status in (discord.EventStatus.scheduled, discord.EventStatus.active)

        if item is None:  # geloescht oder nicht mehr ankuendigen
            if active:
                await native.delete()
            if mapping is not None:
                await _forget(NATIVE_KIND, guild.id, event_id)
            return
        if item.cancelled:
            if active and native.status == discord.EventStatus.scheduled:
                await native.cancel()
                done.append(f"{guild.name}: Discord-Event abgesagt")
            return
        if item.is_past() or item.starts_at <= datetime.now(timezone.utc):
            return  # vergangene/laufende Events kann Discord nicht mehr anlegen oder verschieben

        fields = dict(
            name=item.title[:100],
            description=plain_excerpt(item.description, 900) + (f"\n{community_db.site_link('events.view', id=item.id)}" if community_db.site_link("events.view", id=item.id) else ""),
            start_time=item.starts_at,
            end_time=item.end,
            location=(item.location or "Community")[:100],
        )
        if active:
            await native.edit(**fields)
        else:
            if mapping is not None:
                await _forget(NATIVE_KIND, guild.id, event_id)
            created = await guild.create_scheduled_event(
                entity_type=discord.EntityType.external, privacy_level=discord.PrivacyLevel.guild_only, **fields
            )
            await _remember(NATIVE_KIND, guild, event_id, 0, created.id)
            done.append(f"{guild.name}: Discord-Event angelegt")
    except discord.Forbidden:
        log.warning("Discord-Event fuer Event #%s nicht moeglich - der Bot braucht das Recht 'Events verwalten'", event_id)
    except discord.HTTPException as error:
        log.warning("Discord-Event fuer Event #%s fehlgeschlagen: %s", event_id, error)


async def remove_event(bot: discord.Client, event_id: int) -> None:
    for guild in bot.guilds:
        mapping = await _mapping(KIND, guild.id, event_id)
        if mapping is not None:
            message = await _message(guild, mapping)
            if message is not None:
                await message.delete()
            await _forget(KIND, guild.id, event_id)
        await _sync_native(guild, event_id, None, [])


async def posted_ids(guild_id: int) -> set[int]:
    async with get_db_session() as db:
        rows = await db.execute(select(CommunityPost.item_id).where(CommunityPost.kind == KIND, CommunityPost.guild_id == guild_id))
        return {r[0] for r in rows.all()}
