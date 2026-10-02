"""AMP-Konten fuer Mitglieder der Community-Seite (Logik in accounts.py).

- amp.request (Antrag auf der Seite): Konto anlegen bzw. reaktivieren, Rolle nach
  Rang, Startpasswort per DM (muss beim ersten Login geaendert werden).
- amp.reset (Passwort vergessen): neues Startpasswort per DM.
- amp.disable (Konto auf der Seite geloescht): AMP-Konto sperren.
- Rang geaendert (user.role von der Seite, community_rank_changed vom Rang-Sync):
  Rolle anpassen, ohne AMP-Zugang sperren.

Den Stand schreibt der Bot in die Seite zurueck (users.amp_*), damit das Mitglied
ihn unter Einstellungen -> AMP-Zugang sieht. Einstellungen im Tab "AMP-Konten".
"""

import logging

import discord
from discord.ext import commands

from bot.cogs.ampkonten.accounts import (
    URL_KEY,
    AmpError,
    Outcome,
    apply_rank,
    handle_disable,
    handle_request,
    handle_reset,
    site_member,
    write_site_status,
)
from bot.community import outbox
from bot.core.amp_client import amp_client
from bot.core.base_cog import BaseCog
from bot.core.bot_settings import get_bot_setting

log = logging.getLogger("wikingerbot.ampkonten")
COLOR = 0x5FA8A0


class AmpKontenCog(BaseCog):
    """AMP-Konten fuer die Community."""

    __cog_name__ = "ampkonten"
    __version__ = "1.0.0"
    __description__ = "AMP-Konten fuer Mitglieder der Community-Seite"
    __author__ = "Daywalker91"

    def __init__(self, bot: commands.Bot, core_call=None) -> None:
        super().__init__(bot)
        self.core_call = core_call or amp_client.core_call

    async def cog_load(self) -> None:
        outbox.register("amp.request", self._on_request)
        outbox.register("amp.reset", self._on_reset)
        outbox.register("amp.disable", self._on_disable)
        outbox.register("user.role", self._on_rank)

    async def cog_unload(self) -> None:
        outbox.unregister("amp.request", self._on_request)
        outbox.unregister("amp.reset", self._on_reset)
        outbox.unregister("amp.disable", self._on_disable)
        outbox.unregister("user.role", self._on_rank)

    # --- Auftraege ---------------------------------------------------------------

    async def _on_request(self, payload: dict) -> None:
        await self._run(int(payload["user_id"]), handle_request)

    async def _on_reset(self, payload: dict) -> None:
        await self._run(int(payload["user_id"]), handle_reset)

    async def _on_disable(self, payload: dict) -> None:
        outcome = await handle_disable(self.core_call, int(payload["user_id"]))
        if outcome is not None:
            await write_site_status(int(payload["user_id"]), outcome)

    async def _on_rank(self, payload: dict) -> None:
        await self.rank_changed(int(payload["user_id"]))

    @commands.Cog.listener()
    async def on_community_rank_changed(self, site_user_id: int) -> None:
        try:
            await self.rank_changed(site_user_id)
        except Exception as error:
            log.warning("AMP-Konto nach Rangwechsel nicht angepasst: %s", error)

    async def rank_changed(self, site_user_id: int) -> None:
        outcome = await apply_rank(self.core_call, site_user_id)
        if outcome is not None:
            await write_site_status(site_user_id, outcome)
            if outcome.status == "disabled":
                await self._dm(site_user_id, outcome)

    async def _run(self, site_user_id: int, action) -> None:
        """Antrag/Passwort: Fehler von AMP landen als Hinweis auf der Seite statt in der
        Wiederholungsschleife - ein abgelehnter Name wird beim naechsten Versuch nicht besser."""
        try:
            outcome = await action(self.core_call, site_user_id)
        except AmpError as error:
            outcome = Outcome("denied", str(error))
        if outcome.password and not await self._dm(site_user_id, outcome):
            # Zugangsdaten nicht zustellbar - nichts geht verloren, nur neu anfordern
            outcome.note = "Die Zugangsdaten konnten nicht per Discord-DM zugestellt werden – erlaube DMs vom Server und fordere ein neues Passwort an."
        await write_site_status(site_user_id, outcome)

    async def _dm(self, site_user_id: int, outcome: Outcome) -> bool:
        member = await site_member(site_user_id)
        if member is None or not member.discord_id:
            return False
        user = self.bot.get_user(member.discord_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(member.discord_id)
            except discord.HTTPException:
                return False
        url = await get_bot_setting(URL_KEY, "") or ""
        if outcome.password:
            embed = discord.Embed(
                title="🔑 Dein AMP-Zugang",
                description="Beim ersten Login musst du ein eigenes Passwort vergeben. Diese Nachricht danach am besten löschen.",
                color=COLOR,
            )
            if url:
                embed.add_field(name="Adresse", value=url, inline=False)
            embed.add_field(name="Benutzer", value=f"`{outcome.amp_username}`")
            embed.add_field(name="Startpasswort", value=f"||`{outcome.password}`||")
        else:
            embed = discord.Embed(title="🔒 AMP-Zugang gesperrt", description=outcome.note or "Dein AMP-Konto ist gesperrt.", color=COLOR)
        try:
            await user.send(embed=embed)
            return True
        except discord.HTTPException:
            return False


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AmpKontenCog(bot))
