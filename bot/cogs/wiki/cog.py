"""Wiki der Community-Seite in Discord: /wiki sucht in Titel und Text, mit
Vorschlaegen beim Tippen. Nur lesend.

Sichtbar ist, was man auf der Seite lesen duerfte: min_read_level der Seite <=
Level des eigenen Rangs (verknuepft), sonst nur oeffentliche Seiten (Level 0).
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import or_, select

from bot.community import db as community_db
from bot.community.linking import user_for_discord
from bot.community.text import plain_excerpt
from bot.core.base_cog import BaseCog

log = logging.getLogger("wikingerbot.wiki")

COLOR = 0xC9A35C
MAX_RESULTS = 5


async def reader_level(discord_id: int) -> int:
    site_user = await user_for_discord(discord_id)
    if site_user is None:
        return 0
    u, r = community_db.users, community_db.roles
    async with community_db.session() as db:
        level = (
            await db.execute(select(r.c.level).select_from(u.join(r, r.c.id == u.c.role_id)).where(u.c.id == site_user.id))
        ).scalar_one_or_none()
    return int(level or 0)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search(text: str, level: int, limit: int = MAX_RESULTS) -> list[tuple]:
    w = community_db.wiki_pages
    pattern = f"%{_escape_like(text.strip())}%"
    async with community_db.session() as db:
        rows = (
            await db.execute(
                select(w.c.slug, w.c.title, w.c.category, w.c.body)
                .where(w.c.min_read_level <= level, or_(w.c.title.ilike(pattern, escape="\\"), w.c.body.ilike(pattern, escape="\\")))
                # Treffer im Titel zuerst
                .order_by(~w.c.title.ilike(pattern, escape="\\"), w.c.title)
                .limit(limit)
            )
        ).all()
    return [tuple(r) for r in rows]


async def page_by_slug(slug: str, level: int):
    w = community_db.wiki_pages
    async with community_db.session() as db:
        return (
            await db.execute(select(w.c.slug, w.c.title, w.c.category, w.c.body).where(w.c.slug == slug, w.c.min_read_level <= level))
        ).first()


def page_link(slug: str) -> str | None:
    return community_db.site_link("wiki.page", seite=slug)


class WikiCog(BaseCog):
    """Wiki der Seite durchsuchen."""

    __cog_name__ = "wiki"
    __version__ = "1.0.0"
    __description__ = "Wiki der Community-Seite durchsuchen"
    __author__ = "Daywalker91"

    async def _ac_pages(self, interaction: discord.Interaction, current: str):
        if not community_db.enabled() or len(current.strip()) < 2:
            return []
        try:
            results = await search(current, await reader_level(interaction.user.id), limit=25)
        except Exception:
            return []
        return [app_commands.Choice(name=title[:100], value=f"slug:{slug}"[:100]) for slug, title, _, _ in results]

    @app_commands.command(name="wiki", description="Sucht im Wiki der Community-Seite")
    @app_commands.describe(suche="Suchbegriff oder Seite aus der Liste", zeigen="Antwort fuer alle im Kanal sichtbar")
    @app_commands.autocomplete(suche=_ac_pages)
    async def wiki(self, interaction: discord.Interaction, suche: str, zeigen: bool = False) -> None:
        if not community_db.enabled():
            await interaction.response.send_message("Die Community-Seite ist nicht angebunden.", ephemeral=True)
            return
        try:
            level = await reader_level(interaction.user.id)
            if suche.startswith("slug:"):
                page = await page_by_slug(suche[5:], level)
                results = [tuple(page)] if page else []
            else:
                results = await search(suche, level)
        except Exception as error:
            log.warning("Wiki-Suche fehlgeschlagen: %s", error)
            await interaction.response.send_message("Die Seite ist gerade nicht erreichbar.", ephemeral=True)
            return
        if not results:
            await interaction.response.send_message(f"Im Wiki nichts zu „{suche}“ gefunden.", ephemeral=True)
            return
        if len(results) == 1:
            slug, title, category, body = results[0]
            embed = discord.Embed(title=f"📜 {title}"[:256], url=page_link(slug), description=plain_excerpt(body, 700), color=COLOR)
            if category:
                embed.set_footer(text=category)
        else:
            embed = discord.Embed(title=f"📜 Wiki: „{suche}“"[:256], color=COLOR)
            for slug, title, category, body in results:
                link = page_link(slug)
                value = plain_excerpt(body, 160) + (f"\n[Lesen]({link})" if link else "")
                embed.add_field(name=(f"{title} · {category}" if category else title)[:256], value=value[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=not zeigen)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WikiCog(bot))
