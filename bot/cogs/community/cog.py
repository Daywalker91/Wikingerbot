"""Grundlage der Anbindung an die Community-Seite: Konto-Verknuepfung und das
Abholen der Auftraege, die die Seite in bot_outbox schreibt.

Eingestellt wird die Anbindung in der Web-Oberflaeche (Seite "Community").
Ohne Anbindung tut der Cog nichts und die Befehle verweisen dorthin - der Bot
bleibt ohne Seite lauffaehig. Die weiteren Community-Cogs (news,
events, tickets, ...) melden ihre Auftragsarten selbst bei bot.community.outbox an.

Ereignisse fuer andere Cogs: "community_link" (member, site_user) nach einer
Verknuepfung, "community_unlink" (discord_id, site_user_id) nach dem Loesen.
"""

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.community import db as community_db
from bot.community import outbox
from bot.community.linking import LinkError, link_with_code, linked_count, unlink_discord, user_for_discord
from bot.core.base_cog import BaseCog
from bot.core.permissions import Level, require_role

log = logging.getLogger("wikingerbot.community")

POLL_SECONDS = 5
LINK_ATTEMPTS = 5  # Fehlversuche pro 10 Minuten und Discord-Konto
LINK_WINDOW = 600


class CommunityCog(BaseCog):
    """Verknuepfung mit der Community-Seite und Auftraege der Seite."""

    __cog_name__ = "community"
    __version__ = "1.0.0"
    __description__ = "Anbindung an die Community-Seite"
    __author__ = "Daywalker91"

    community_group = app_commands.Group(name="community", description="Anbindung an die Community-Seite")

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self._failed_links: dict[int, list[float]] = {}
        self._poll_error_logged = False

    async def cog_load(self) -> None:
        config = await community_db.load_config()
        if not config["enabled"]:
            log.info("Community-Seite nicht angebunden - einstellbar in der Web-Oberflaeche (Community).")
        outbox.register("user.unlinked", self._on_site_unlinked)
        self.poll.start()

    async def cog_unload(self) -> None:
        self.poll.cancel()
        outbox.unregister("user.unlinked", self._on_site_unlinked)

    # --- Auftraege der Seite --------------------------------------------------------

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll(self) -> None:
        if not community_db.enabled():
            return
        try:
            await outbox.process_pending()
            if self._poll_error_logged:
                log.info("Community-Datenbank wieder erreichbar.")
                self._poll_error_logged = False
        except Exception as error:
            # nur einmal melden, sonst alle 5 Sekunden dieselbe Zeile im Log
            if not self._poll_error_logged:
                log.warning("Community-Datenbank nicht erreichbar: %s", str(error).splitlines()[0][:300])
                self._poll_error_logged = True

    @poll.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    async def _on_site_unlinked(self, payload: dict) -> None:
        # Rollen bleiben bewusst, wie sie sind (abgestimmt) - nur fuer andere Cogs melden
        discord_id = int(payload.get("discord_id") or 0)
        if discord_id:
            self.bot.dispatch("community_unlink", discord_id, int(payload.get("user_id") or 0))

    # --- Befehle --------------------------------------------------------------------

    async def _not_connected(self, interaction: discord.Interaction) -> bool:
        if community_db.enabled():
            return False
        await interaction.response.send_message(
            "Die Community-Seite ist noch nicht angebunden (Bot-Oberfläche → Community).", ephemeral=True
        )
        return True

    def _too_many_attempts(self, user_id: int) -> bool:
        now = time.monotonic()
        recent = [t for t in self._failed_links.get(user_id, []) if now - t < LINK_WINDOW]
        self._failed_links[user_id] = recent
        return len(recent) >= LINK_ATTEMPTS

    @app_commands.command(name="verknuepfen", description="Verknuepft dein Discord-Konto mit deinem Konto auf der Seite")
    @app_commands.describe(code="Der Code aus Einstellungen -> Discord auf der Seite")
    async def link(self, interaction: discord.Interaction, code: str) -> None:
        if await self._not_connected(interaction):
            return
        if self._too_many_attempts(interaction.user.id):
            await interaction.response.send_message("Zu viele Versuche – probier es in ein paar Minuten noch mal.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            site_user = await link_with_code(code, interaction.user.id, interaction.user.name)
        except LinkError as error:
            self._failed_links.setdefault(interaction.user.id, []).append(time.monotonic())
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception as error:
            log.warning("Verknuepfung fehlgeschlagen: %s", error)
            await interaction.followup.send("Die Seite ist gerade nicht erreichbar. Versuch es später noch mal.", ephemeral=True)
            return
        log.info("Discord %s mit Seiten-Konto %s (#%d) verknuepft", interaction.user, site_user.username, site_user.id)
        if isinstance(interaction.user, discord.Member):
            self.bot.dispatch("community_link", interaction.user, site_user)
        await interaction.followup.send(
            f"✅ Verknüpft mit **{site_user.username}** ({site_user.role_name}) auf der Seite. Skål!", ephemeral=True
        )

    @app_commands.command(name="verknuepfung_loesen", description="Loest die Verknuepfung mit der Seite")
    async def unlink(self, interaction: discord.Interaction) -> None:
        if await self._not_connected(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            site_user = await unlink_discord(interaction.user.id)
        except Exception as error:
            log.warning("Loesen fehlgeschlagen: %s", error)
            await interaction.followup.send("Die Seite ist gerade nicht erreichbar.", ephemeral=True)
            return
        if site_user is None:
            await interaction.followup.send("Dein Discord-Konto ist mit keinem Konto auf der Seite verknüpft.", ephemeral=True)
            return
        self.bot.dispatch("community_unlink", interaction.user.id, site_user.id)
        await interaction.followup.send(
            f"Die Verknüpfung mit **{site_user.username}** ist gelöst. Deine Discord-Rollen bleiben, wie sie sind.",
            ephemeral=True,
        )

    @app_commands.command(name="profil", description="Link zum Profil auf der Seite")
    @app_commands.describe(mitglied="Wessen Profil (ohne Angabe: deins)")
    async def profile(self, interaction: discord.Interaction, mitglied: discord.Member | None = None) -> None:
        if await self._not_connected(interaction):
            return
        member = mitglied or interaction.user
        try:
            site_user = await user_for_discord(member.id, include_banned=True)
        except Exception:
            await interaction.response.send_message("Die Seite ist gerade nicht erreichbar.", ephemeral=True)
            return
        if site_user is None:
            if member == interaction.user:
                link = community_db.site_link("settings", tab="discord")
                text = "Du bist noch nicht mit der Seite verknüpft." + (
                    f" So geht's: auf der Seite unter [Einstellungen → Discord]({link}) einen Code erzeugen, dann `/verknuepfen CODE`."
                    if link
                    else " Erzeug auf der Seite unter Einstellungen → Discord einen Code, dann `/verknuepfen CODE`."
                )
            else:
                text = f"{member.display_name} ist nicht mit der Seite verknüpft."
            await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        link = community_db.site_link("user", id=site_user.id)
        name = f"[{site_user.username}]({link})" if link else f"**{site_user.username}**"
        await interaction.response.send_message(
            f"{member.display_name} ist auf der Seite {name} – {site_user.role_name}.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @community_group.command(name="status", description="Zustand der Anbindung an die Seite")
    @require_role(Level.ADMIN)
    async def status(self, interaction: discord.Interaction) -> None:
        if await self._not_connected(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            counts = await outbox.counts()
            linked = await linked_count()
        except Exception as error:
            await interaction.followup.send(f"❌ Datenbank der Seite nicht erreichbar: {str(error).splitlines()[0][:300]}", ephemeral=True)
            return
        lines = [
            "✅ Datenbank der Seite erreichbar",
            f"🔗 Verknüpfte Mitglieder: {linked}",
            f"📬 Offene Aufträge: {counts['pending']}" + (f" · ⚠️ endgültig fehlgeschlagen: {counts['failed']}" if counts["failed"] else ""),
            f"🧩 Zuständig für: {', '.join(outbox.registered()) or '–'}",
            f"🌐 Seite: {community_db.site_link('home') or 'COMMUNITY_SITE_URL nicht gesetzt'}",
        ]
        await interaction.followup.send("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommunityCog(bot))
