"""News der Community-Seite als Discord-Nachricht - ohne Discord-Cog-Abhaengigkeit,
damit testbar. Die Nachricht gehoert zur News: Bearbeiten aktualisiert sie,
Loeschen/Entwurf/Haken weg entfernt sie (Zuordnung in community_posts)."""

import logging
from dataclasses import dataclass

import discord
from sqlalchemy import select

from bot.community import db as community_db
from bot.community.announce import publish_if_announcement
from bot.community.text import plain_excerpt
from bot.core.entities import ensure_guild
from bot.core.guild_config import get_config
from db.models.community_post import CommunityPost
from db.session import get_db_session

log = logging.getLogger("wikingerbot.news")

KIND = "news"
EXCERPT_LENGTH = 350
COLOR = 0xC9A35C  # Gold wie auf der Seite


@dataclass
class NewsItem:
    id: int
    title: str
    body: str
    image: str | None
    is_pinned: bool
    is_published: bool
    announce: bool
    author: str


async def fetch_news(news_id: int) -> NewsItem | None:
    n, u = community_db.news, community_db.users
    async with community_db.session() as db:
        row = (
            await db.execute(
                select(n.c.id, n.c.title, n.c.body, n.c.image, n.c.is_pinned, n.c.is_published, n.c.announce_discord, u.c.username)
                .select_from(n.join(u, u.c.id == n.c.user_id))
                .where(n.c.id == news_id)
            )
        ).first()
    if row is None:
        return None
    return NewsItem(row[0], row[1], row[2] or "", row[3], bool(row[4]), bool(row[5]), bool(row[6]), row[7])


async def recent_news(limit: int = 15) -> list[NewsItem]:
    n, u = community_db.news, community_db.users
    async with community_db.session() as db:
        rows = (
            await db.execute(
                select(n.c.id, n.c.title, n.c.body, n.c.image, n.c.is_pinned, n.c.is_published, n.c.announce_discord, u.c.username)
                .select_from(n.join(u, u.c.id == n.c.user_id))
                .order_by(n.c.id.desc())
                .limit(limit)
            )
        ).all()
    return [NewsItem(r[0], r[1], r[2] or "", r[3], bool(r[4]), bool(r[5]), bool(r[6]), r[7]) for r in rows]


def image_url(image: str | None) -> str | None:
    if not image:
        return None
    if image.startswith("https://"):
        return image
    base = community_db.current_config()["site_url"]
    return f"{base}/{image.lstrip('/')}" if base and image.startswith("assets/") else None


def build_embed(item: NewsItem) -> discord.Embed:
    link = community_db.site_link("news.view", id=item.id)
    title = ("📌 " if item.is_pinned else "📰 ") + item.title
    embed = discord.Embed(title=title[:256], url=link, description=plain_excerpt(item.body), color=COLOR)
    if link:
        embed.add_field(name="​", value=f"[Ganze News lesen]({link})", inline=False)
    if url := image_url(item.image):
        embed.set_image(url=url)
    embed.set_footer(text=f"von {item.author}")
    return embed


def should_post(item: NewsItem | None) -> bool:
    return item is not None and item.is_published and item.announce


async def _mapping(guild_id: int, news_id: int) -> CommunityPost | None:
    async with get_db_session() as db:
        return await db.get(CommunityPost, (KIND, news_id, guild_id))


async def _forget(guild_id: int, news_id: int) -> None:
    async with get_db_session() as db:
        row = await db.get(CommunityPost, (KIND, news_id, guild_id))
        if row is not None:
            await db.delete(row)
            await db.commit()


async def news_channel(guild: discord.Guild) -> discord.abc.Messageable | None:
    channel_id = await get_config(guild.id, "news_channel_id")
    return guild.get_channel(int(channel_id)) if channel_id else None


async def sync_news(bot: discord.Client, news_id: int) -> list[str]:
    """Bringt die Discord-Nachricht(en) zur News auf den aktuellen Stand.
    Gibt zurueck, was passiert ist (fuer Log und Oberflaeche)."""
    item = await fetch_news(news_id)
    done = []
    for guild in bot.guilds:
        channel = await news_channel(guild)
        mapping = await _mapping(guild.id, news_id)

        if not should_post(item):
            if mapping is not None:
                await _delete_message(guild, mapping)
                await _forget(guild.id, news_id)
                done.append(f"{guild.name}: entfernt")
            continue
        if channel is None:
            continue  # Server ohne News-Kanal

        embed = build_embed(item)
        if mapping is not None:
            message = await _fetch_message(guild, mapping)
            if message is not None:
                await message.edit(embed=embed)
                done.append(f"{guild.name}: aktualisiert")
                continue
            await _forget(guild.id, news_id)  # Nachricht wurde in Discord geloescht -> neu posten

        role_id = await get_config(guild.id, "news_ping_role_id")
        role = guild.get_role(int(role_id)) if role_id else None
        message = await channel.send(
            content=role.mention if role else None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=[role] if role else False, everyone=False, users=False),
        )
        await publish_if_announcement(message)
        await ensure_guild(guild.id, guild.name)
        async with get_db_session() as db:
            db.add(CommunityPost(kind=KIND, item_id=news_id, guild_id=guild.id, channel_id=message.channel.id, message_id=message.id))
            await db.commit()
        done.append(f"{guild.name}: gepostet")
    return done


async def remove_news(bot: discord.Client, news_id: int) -> None:
    for guild in bot.guilds:
        mapping = await _mapping(guild.id, news_id)
        if mapping is not None:
            await _delete_message(guild, mapping)
            await _forget(guild.id, news_id)


async def _fetch_message(guild: discord.Guild, mapping: CommunityPost) -> discord.Message | None:
    channel = guild.get_channel(mapping.channel_id)
    if channel is None:
        return None
    try:
        return await channel.fetch_message(mapping.message_id)
    except discord.NotFound:
        return None


async def _delete_message(guild: discord.Guild, mapping: CommunityPost) -> None:
    message = await _fetch_message(guild, mapping)
    if message is not None:
        try:
            await message.delete()
        except discord.NotFound:
            pass


async def posted_ids(guild_id: int) -> set[int]:
    async with get_db_session() as db:
        rows = await db.execute(
            select(CommunityPost.item_id).where(CommunityPost.kind == KIND, CommunityPost.guild_id == guild_id)
        )
        return {r[0] for r in rows.all()}
