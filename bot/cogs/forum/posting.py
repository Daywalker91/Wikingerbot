"""Neue Themen im Forum der Community-Seite in Discord ankuendigen.

Nur Kategorien, die jeder lesen darf (min_read_level 0) - interne Bereiche (z.B. nur
fuer das Team) erscheinen nie in Discord. Pro Thema eine kurze Karte mit Titel,
Verfasser, Kategorie, Anfang des Texts und einem Knopf "Hier lesen". Antworten werden
nicht angekuendigt.
"""

import re
from dataclasses import dataclass
from datetime import datetime

import discord
from sqlalchemy import select

from bot.community import db as community_db
from bot.community.announce import publish_if_announcement
from bot.core.entities import ensure_guild
from bot.core.guild_config import get_config
from db.models.community_post import CommunityPost
from db.session import get_db_session

KIND = "forum"
COLOR = 0xC9A35C
EXCERPT_LENGTH = 220


@dataclass
class ForumThread:
    id: int
    title: str
    author: str | None
    category: str
    public: bool
    body: str
    created_at: datetime | None


def excerpt(body: str, length: int = EXCERPT_LENGTH) -> str:
    """Anfang des Beitrags ohne Formatierung (Code, Zitate, Ueberschriften, Wiki-Links)."""
    text = re.sub(r"```.*?```", " ", body or "", flags=re.S)
    text = re.sub(r"^\s*(>|#{1,3})\s?", "", text, flags=re.M)
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
    text = re.sub(r"[*_~`]", "", text)
    text = " ".join(text.split())
    return text if len(text) <= length else text[: length - 1].rstrip() + "…"


async def fetch_thread(thread_id: int) -> ForumThread | None:
    t, c, p, u = community_db.forum_threads, community_db.forum_categories, community_db.forum_posts, community_db.users
    async with community_db.session() as db:
        row = (
            await db.execute(
                select(t.c.id, t.c.title, u.c.username, c.c.name, c.c.min_read_level, t.c.created_at)
                .select_from(t.join(c, c.c.id == t.c.category_id).outerjoin(u, u.c.id == t.c.user_id))
                .where(t.c.id == thread_id)
            )
        ).first()
        if row is None:
            return None
        body = (
            await db.execute(select(p.c.body).where(p.c.thread_id == thread_id).order_by(p.c.id).limit(1))
        ).scalar_one_or_none()
    return ForumThread(row[0], row[1], row[2], row[3], int(row[4] or 0) == 0, body or "", row[5])


async def recent_threads(limit: int = 10) -> list[ForumThread]:
    """Neueste Themen aus Kategorien, die jeder lesen darf."""
    t, c = community_db.forum_threads, community_db.forum_categories
    async with community_db.session() as db:
        ids = (
            await db.execute(
                select(t.c.id).select_from(t.join(c, c.c.id == t.c.category_id))
                .where(c.c.min_read_level == 0).order_by(t.c.id.desc()).limit(limit)
            )
        ).scalars().all()
    return [thread for thread in [await fetch_thread(i) for i in ids] if thread is not None]


def build_embed(thread: ForumThread) -> discord.Embed:
    embed = discord.Embed(
        title=f"📝 {thread.title}"[:256],
        url=community_db.site_link("forum.thread", id=thread.id),
        description=excerpt(thread.body) or None,
        color=COLOR,
    )
    embed.set_author(name="Neuer Beitrag im Forum")
    embed.set_footer(text=f"von {thread.author or 'Gelöschter Nutzer'} · {thread.category}")
    if thread.created_at:
        embed.timestamp = thread.created_at
    return embed


def read_button(thread_id: int) -> discord.ui.View | None:
    link = community_db.site_link("forum.thread", id=thread_id)
    if not link:
        return None
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Hier lesen", url=link, emoji="📖"))
    return view


async def announce_thread(bot: discord.Client, thread_id: int) -> list[str]:
    """Kuendigt ein neues Thema an (einmal pro Discord-Server). Was passiert ist, fuer Log/Tab."""
    thread = await fetch_thread(thread_id)
    if thread is None or not thread.public:
        return []
    done = []
    for guild in bot.guilds:
        channel_id = await get_config(guild.id, "forum_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if channel is None:
            continue
        async with get_db_session() as db:
            if await db.get(CommunityPost, (KIND, thread_id, guild.id)) is not None:
                continue  # schon angekuendigt
        role_id = await get_config(guild.id, "forum_ping_role_id")
        role = guild.get_role(int(role_id)) if role_id else None
        kwargs = {"view": view} if (view := read_button(thread_id)) else {}
        message = await channel.send(
            content=role.mention if role else None,
            embed=build_embed(thread),
            allowed_mentions=discord.AllowedMentions(roles=[role] if role else False, everyone=False, users=False),
            **kwargs,
        )
        await publish_if_announcement(message)
        await ensure_guild(guild.id, guild.name)
        async with get_db_session() as db:
            db.add(CommunityPost(kind=KIND, item_id=thread_id, guild_id=guild.id, channel_id=message.channel.id, message_id=message.id))
            await db.commit()
        done.append(f"{guild.name}: angekündigt")
    return done
