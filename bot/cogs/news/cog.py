"""News der Community-Seite in Discord: veroeffentlichte News mit Haken
"In Discord ankuendigen" landen als Embed im News-Kanal, Aenderungen werden
nachgezogen, geloeschte/zurueckgezogene News verschwinden wieder.

Braucht die Anbindung an die Seite (community-Cog). Einstellungen (Kanal,
Ping-Rolle) im Tab "News" der Oberflaeche.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.news.posting import recent_news, remove_news, sync_news
from bot.community import db as community_db
from bot.community import outbox
from bot.core.base_cog import BaseCog

log = logging.getLogger("wikingerbot.news")


class NewsCog(BaseCog):
    """News der Seite in Discord."""

    __cog_name__ = "news"
    __version__ = "1.0.0"
    __description__ = "News der Community-Seite in Discord"
    __author__ = "Daywalker91"

    async def cog_load(self) -> None:
        outbox.register("news.saved", self._on_saved)
        outbox.register("news.deleted", self._on_deleted)

    async def cog_unload(self) -> None:
        outbox.unregister("news.saved")
        outbox.unregister("news.deleted")

    async def _on_saved(self, payload: dict) -> None:
        done = await sync_news(self.bot, int(payload["news_id"]))
        if done:
            log.info("News #%s: %s", payload["news_id"], ", ".join(done))

    async def _on_deleted(self, payload: dict) -> None:
        await remove_news(self.bot, int(payload["news_id"]))

    @app_commands.command(name="news", description="Die neuesten News der Community-Seite")
    async def news(self, interaction: discord.Interaction) -> None:
        if not community_db.enabled():
            await interaction.response.send_message("Die Community-Seite ist nicht angebunden.", ephemeral=True)
            return
        try:
            items = [i for i in await recent_news(20) if i.is_published][:5]
        except Exception:
            await interaction.response.send_message("Die Seite ist gerade nicht erreichbar.", ephemeral=True)
            return
        if not items:
            await interaction.response.send_message("Noch keine News.", ephemeral=True)
            return
        lines = []
        for item in items:
            link = community_db.site_link("news.view", id=item.id)
            title = ("📌 " if item.is_pinned else "") + item.title
            lines.append(f"- [{title}]({link})" if link else f"- {title}")
        await interaction.response.send_message("**Neueste News**\n" + "\n".join(lines), ephemeral=True, suppress_embeds=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NewsCog(bot))

