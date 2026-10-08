"""Events der Community-Seite in Discord: Embed mit Zusage-Knoepfen (Dabei /
Vielleicht / Nicht dabei), abgeglichen mit den Zusagen auf der Seite, und
optional ein natives Discord-Event zur Anzeige.

Braucht die Anbindung an die Seite (community-Cog). Einstellungen im Tab
"Events" der Oberflaeche. Die Knoepfe sind DynamicItems (Event und Antwort in der
custom_id) - sie funktionieren auch nach einem Neustart.
"""

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.events.posting import ANSWERS, remove_event, set_participation, sync_event, upcoming_events
from bot.community import db as community_db
from bot.community import outbox
from bot.community.linking import user_for_discord
from bot.core.base_cog import BaseCog

log = logging.getLogger("wikingerbot.events")

RESULT_TEXT = {
    "ok": "Eingetragen – steht auch auf der Seite.",
    "removed": "Deine Antwort ist zurückgenommen.",
    "full": "Das Event ist leider voll. „Vielleicht“ geht noch, falls ein Platz frei wird.",
    "closed": "Für dieses Event kann man nicht mehr zusagen (abgesagt oder vorbei).",
    "norsvp": "Das ist ein Info-Termin – dafür gibt es keine Zusagen.",
    "missing": "Dieses Event gibt es nicht mehr.",
    "forbidden": "Dein Rang auf der Seite darf bei Events nicht zusagen.",
}


class EventAnswerButton(discord.ui.DynamicItem[discord.ui.Button], template=r"wb:event:(?P<event_id>\d+):(?P<answer>yes|maybe|no)"):
    def __init__(self, event_id: int, answer: str, disabled: bool = False) -> None:
        emoji, label = ANSWERS[answer]
        style = {"yes": discord.ButtonStyle.success, "maybe": discord.ButtonStyle.secondary, "no": discord.ButtonStyle.danger}[answer]
        super().__init__(
            discord.ui.Button(custom_id=f"wb:event:{event_id}:{answer}", label=label, emoji=emoji, style=style, disabled=disabled)
        )
        self.event_id = event_id
        self.answer = answer

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str]):
        return cls(int(match["event_id"]), match["answer"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if not community_db.enabled():
            await interaction.response.send_message("Die Community-Seite ist gerade nicht angebunden.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            site_user = await user_for_discord(interaction.user.id)
            if site_user is None:
                link = community_db.site_link("settings", tab="discord")
                await interaction.followup.send(
                    "Zusagen zählen auf der Seite pro Konto – verknüpfe dafür einmal dein Discord-Konto: "
                    + (f"auf der Seite unter [Einstellungen → Discord]({link}) einen Code erzeugen, " if link else "auf der Seite unter Einstellungen → Discord einen Code erzeugen, ")
                    + "dann `/verknuepfen CODE`.",
                    ephemeral=True,
                )
                return
            result = await set_participation(self.event_id, site_user.id, self.answer)
        except Exception as error:
            log.warning("Zusage fehlgeschlagen: %s", error)
            await interaction.followup.send("Die Seite ist gerade nicht erreichbar. Versuch es später noch mal.", ephemeral=True)
            return
        await interaction.followup.send(RESULT_TEXT[result], ephemeral=True)
        if result in ("ok", "removed", "closed", "norsvp", "missing"):
            # Die Seite meldet Aenderungen aus Discord nicht zurueck - Embed selbst auffrischen
            try:
                await sync_event(interaction.client, self.event_id, event_view)
            except Exception as error:
                log.warning("Event-Embed nicht aktualisiert: %s", error)


def event_view(event_id: int, disabled: bool) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for answer in ANSWERS:
        view.add_item(EventAnswerButton(event_id, answer, disabled))
    return view


class EventsCog(BaseCog):
    """Events der Seite in Discord."""

    __cog_name__ = "events"
    __version__ = "1.0.0"
    __description__ = "Events der Community-Seite in Discord"
    __author__ = "Daywalker91"

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(EventAnswerButton)
        outbox.register("event.saved", self._on_saved)
        outbox.register("event.participants", self._on_saved)
        outbox.register("event.deleted", self._on_deleted)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(EventAnswerButton)
        outbox.unregister("event.saved", self._on_saved)
        outbox.unregister("event.participants", self._on_saved)
        outbox.unregister("event.deleted", self._on_deleted)

    async def _on_saved(self, payload: dict) -> None:
        done = await sync_event(self.bot, int(payload["event_id"]), event_view)
        if done:
            log.info("Event #%s: %s", payload["event_id"], ", ".join(done))

    async def _on_deleted(self, payload: dict) -> None:
        await remove_event(self.bot, int(payload["event_id"]))

    @app_commands.command(name="events", description="Die naechsten Events der Community")
    async def events(self, interaction: discord.Interaction) -> None:
        if not community_db.enabled():
            await interaction.response.send_message("Die Community-Seite ist nicht angebunden.", ephemeral=True)
            return
        try:
            items = await upcoming_events(5)
        except Exception:
            await interaction.response.send_message("Die Seite ist gerade nicht erreichbar.", ephemeral=True)
            return
        if not items:
            await interaction.response.send_message("Gerade sind keine Events geplant.", ephemeral=True)
            return
        lines = []
        for item in items:
            link = community_db.site_link("events.view", id=item.id)
            title = ("❌ " if item.cancelled else "") + item.title
            when = f"<t:{int(item.starts_at.timestamp())}:f>"
            lines.append(f"- {when} – " + (f"[{title}]({link})" if link else title))
        await interaction.response.send_message("**Nächste Events**\n" + "\n".join(lines), ephemeral=True, suppress_embeds=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventsCog(bot))
