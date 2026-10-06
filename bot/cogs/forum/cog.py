"""Forum der Community-Seite in Discord: neue Themen werden kurz angekuendigt
("Neuer Beitrag im Forum ... [Hier lesen]"), /forum zeigt die neuesten Themen.

Gelesen und geschrieben wird auf der Seite - Discord bekommt nur den Hinweis. Nur
Kategorien, die jeder lesen darf. Braucht die Anbindung an die Seite (community-Cog);
Kanal und Ping-Rolle im Tab "Forum".
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.forum.posting import announce_thread, recent_threads
from bot.community import db as community_db
from bot.community import outbox
from bot.core.base_cog import BaseCog

log = logging.getLogger("wikingerbot.forum")


class ForumCog(BaseCog):
    """Ankuendigungen neuer Forum-Themen der Seite."""

    __cog_name__ = "forum"
    __version__ = "1.0.0"
    __description__ = "Neue Themen im Forum der Community-Seite in Discord ankuendigen"
    __author__ = "Daywalker91"

    async def cog_load(self) -> None:
        outbox.register("forum.thread", self._on_thread)

    async def cog_unload(self) -> None:
        outbox.unregister("forum.thread", self._on_thread)

    async def _on_thread(self, payload: dict) -> None:
        done = await announce_thread(self.bot, int(payload["thread_id"]))
        if done:
            log.info("Forum-Thema #%s: %s", payload["thread_id"], ", ".join(done))

    @app_commands.command(name="forum", description="Die neuesten Themen im Forum der Community-Seite")
    async def forum(self, interaction: discord.Interaction) -> None:
        if not community_db.enabled():
            await interaction.response.send_message("Die Community-Seite ist nicht angebunden.", ephemeral=True)
            return
        try:
            threads = await recent_threads(8)
        except Exception:
            await interaction.response.send_message("Die Seite ist gerade nicht erreichbar.", ephemeral=True)
            return
        if not threads:
            await interaction.response.send_message("Noch keine Themen im Forum.", ephemeral=True)
            return
        lines = []
        for thread in threads:
            link = community_db.site_link("forum.thread", id=thread.id)
            label = f"{thread.title} · {thread.category}"
            lines.append(f"- [{label}]({link})" if link else f"- {label}")
        await interaction.response.send_message("**Neueste Themen im Forum**\n" + "\n".join(lines), ephemeral=True, suppress_embeds=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ForumCog(bot))
