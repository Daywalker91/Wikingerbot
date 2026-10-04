"""Rang-Sync zwischen Community-Seite und Discord (Regeln siehe sync.py).

- Seite -> Discord: Auftrag user.role (Rang auf der Seite geaendert), neue Verknuepfung.
- Discord -> Seite: Rollenwechsel eines verknuepften Mitglieds.
- Konflikt beim Verknuepfen (Discord sagt anderes als die Seite) -> Ticket, nichts
  wird geaendert. Hat jemand in Discord noch gar keine Rang-Rolle, ist das kein
  Konflikt - dann bekommt er die Rolle von der Seite.
- Discord-Bann eines verknuepften Mitglieds -> Ticket (Sperre auf der Seite bleibt getrennt).

Fuer andere Cogs (AMP-Konten): Ereignis "community_rank_changed" (site_user_id),
wenn der Bot einen Rang auf der Seite aendert - solche Aenderungen kommen nicht
ueber die Auftraege der Seite.
"""

import asyncio
import logging

import discord
from discord.ext import commands

from bot.cogs.rangsync.sync import (
    has_any_rank_role,
    holds_king_role,
    linked_members,
    load_mapping,
    rank_from_discord,
    set_site_rank,
    site_rank_of,
    target_discord_roles,
)
from bot.community import db as community_db
from bot.community import outbox
from bot.community.linking import user_for_discord
from bot.community.system_tickets import default_owner_id, open_system_ticket
from bot.core.base_cog import BaseCog
from bot.core.guild_config import get_config

log = logging.getLogger("wikingerbot.rangsync")

JOIN_DELAY_SECONDS = 3  # nach dem Beitritt: Autorole zuerst, dann der Rang der Seite


class RangsyncCog(BaseCog):
    """Raenge der Seite <-> Discord-Rollen."""

    __cog_name__ = "rangsync"
    __version__ = "1.0.0"
    __description__ = "Rang-Sync zwischen Community-Seite und Discord"
    __author__ = "Daywalker91"

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self._own_changes: set[int] = set()  # Discord-IDs, deren Rollen gerade der Bot setzt

    async def cog_load(self) -> None:
        outbox.register("user.role", self._on_site_role)

    async def cog_unload(self) -> None:
        outbox.unregister("user.role", self._on_site_role)

    async def _enabled(self, guild: discord.Guild) -> bool:
        return community_db.enabled() and await get_config(guild.id, "rangsync_enabled", "false") == "true"

    # --- Seite -> Discord ----------------------------------------------------------

    async def apply_site_rank(self, guild: discord.Guild, member: discord.Member, rank_id: int) -> str:
        ranks = await load_mapping(guild.id)
        current = {r.id for r in member.roles}
        target = target_discord_roles(ranks, rank_id, current)
        if target is None or target == current:
            return "unverändert"
        roles = [r for r in (guild.get_role(i) for i in target) if r is not None and not r.is_default()]
        self._own_changes.add(member.id)
        try:
            await member.edit(roles=roles, reason="Rang-Sync: Rang auf der Community-Seite")
        except discord.HTTPException as error:
            self._own_changes.discard(member.id)
            log.warning("Rollen von %s nicht gesetzt (Bot-Rolle zu niedrig?): %s", member, error)
            return f"fehlgeschlagen: {error}"
        return "angepasst"

    async def _on_site_role(self, payload: dict) -> None:
        site_user_id = int(payload["user_id"])
        rank_id = await site_rank_of(site_user_id)
        discord_id = await self._discord_id(site_user_id)
        if rank_id is None or discord_id is None:
            return
        for guild in self.bot.guilds:
            if not await self._enabled(guild):
                continue
            member = guild.get_member(discord_id)
            if member is not None:
                await self.apply_site_rank(guild, member, rank_id)

    async def _discord_id(self, site_user_id: int) -> int | None:
        for user_id, discord_id, _ in await linked_members():
            if user_id == site_user_id:
                return discord_id
        return None

    async def sync_all(self, guild: discord.Guild) -> dict[str, int]:
        """Alle verknuepften Mitglieder einmal Seite -> Discord abgleichen (Tab-Knopf)."""
        result = {"angepasst": 0, "unverändert": 0, "fehlgeschlagen": 0, "nicht auf dem Server": 0}
        for _site_id, discord_id, rank_id in await linked_members():
            member = guild.get_member(discord_id)
            if member is None:
                result["nicht auf dem Server"] += 1
                continue
            outcome = await self.apply_site_rank(guild, member, rank_id)
            result["fehlgeschlagen" if outcome.startswith("fehlgeschlagen") else outcome] += 1
        return result

    # --- (Wieder-)Beitritt: Rang der Seite statt nur Autorole ------------------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot and not member.pending:
            await self._apply_on_join(member)

    async def _apply_on_join(self, member: discord.Member) -> None:
        """Wer schon verknuepft ist (z.B. nach Verlassen und Wiederkommen), bekommt
        seinen Rang von der Seite. Kurz warten, damit die Autorole (roles-Cog)
        vorher durch ist und hier nicht wieder dazukommt."""
        if not await self._enabled(member.guild):
            return
        site_user = await user_for_discord(member.id)
        if site_user is None:
            return
        await asyncio.sleep(JOIN_DELAY_SECONDS)
        fresh = member.guild.get_member(member.id)
        rank_id = await site_rank_of(site_user.id)
        if fresh is not None and rank_id is not None:
            result = await self.apply_site_rank(member.guild, fresh, rank_id)
            log.info("Rang-Sync beim Beitritt von %s: %s", site_user.username, result)

    # --- Discord -> Seite ----------------------------------------------------------

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.pending and not after.pending and not after.bot:
            await self._apply_on_join(after)  # Regeln gerade akzeptiert
            return
        if before.roles == after.roles or after.bot or not await self._enabled(after.guild):
            return
        if after.id in self._own_changes:  # unsere eigene Aenderung kommt hier wieder an
            self._own_changes.discard(after.id)
            return
        site_user = await user_for_discord(after.id)
        if site_user is None:
            return
        ranks = await load_mapping(after.guild.id)
        site_rank_id = await site_rank_of(site_user.id)
        site_rank = next((r for r in ranks if r.id == site_rank_id), None)
        role_ids = {r.id for r in after.roles}
        if (site_rank is not None and site_rank.is_king) or holds_king_role(ranks, role_ids):
            return  # Koenig (auf der Seite oder in Discord) nie automatisch aendern
        derived = rank_from_discord(ranks, role_ids)
        if derived is None or derived.id == site_rank_id:
            return
        await set_site_rank(site_user.id, derived.id)
        log.info("Rang-Sync: %s ist auf der Seite jetzt %s (Discord-Rollen geaendert)", site_user.username, derived.name)
        self.bot.dispatch("community_rank_changed", site_user.id)

    # --- Verknuepfung: Konflikt pruefen --------------------------------------------

    @commands.Cog.listener()
    async def on_community_link(self, member: discord.Member, site_user) -> None:
        if not await self._enabled(member.guild):
            return
        ranks = await load_mapping(member.guild.id)
        site_rank_id = await site_rank_of(site_user.id)
        site_rank = next((r for r in ranks if r.id == site_rank_id), None)
        role_ids = {r.id for r in member.roles}
        if site_rank is not None and not site_rank.is_king and holds_king_role(ranks, role_ids):
            king = next(r for r in ranks if r.is_king)
            await self._conflict_ticket(member, site_user, site_rank.name, king.name)
            return
        derived = rank_from_discord(ranks, role_ids)
        if site_rank is None or site_rank.is_king or derived is None or derived.id == site_rank_id:
            if site_rank is not None and not site_rank.is_king:
                await self.apply_site_rank(member.guild, member, site_rank_id)
            return
        if not has_any_rank_role(ranks, role_ids):
            # in Discord noch ohne Rang-Rolle: kein Widerspruch, Rolle von der Seite uebernehmen
            await self.apply_site_rank(member.guild, member, site_rank_id)
            return
        await self._conflict_ticket(member, site_user, site_rank.name, derived.name)

    async def _conflict_ticket(self, member: discord.Member, site_user, site_name: str, discord_name: str) -> None:
        body = (
            f"Beim Verknüpfen weichen die Ränge ab:\n"
            f"- Seite: {site_name}\n- Discord: {discord_name} ({member} / {member.id})\n\n"
            "Der Bot hat nichts geändert. Bitte den richtigen Rang auf der Seite setzen "
            "(dann zieht Discord nach) oder die Discord-Rolle anpassen (dann zieht die Seite nach)."
        )
        await open_system_ticket(self.bot, site_user.id, f"Rang-Konflikt: Seite {site_name}, Discord {discord_name}", body)

    # --- Discord-Bann -> Ticket ----------------------------------------------------

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        if not await self._enabled(guild):
            return
        site_user = await user_for_discord(user.id, include_banned=True)
        if site_user is None:
            return
        reason = None
        try:
            reason = (await guild.fetch_ban(user)).reason
        except discord.HTTPException:
            pass
        owner = await get_config(guild.id, "rangsync_ticket_owner")
        owner_id = int(owner) if owner else await default_owner_id()
        if owner_id is None:
            log.warning("Kein Ersteller fuer System-Tickets gefunden - Bann von %s nicht gemeldet", user)
            return
        body = (
            f"{site_user.username} wurde in Discord gebannt ({user} / {user.id}).\n"
            f"Grund: {reason or 'keiner angegeben'}\n\n"
            "Die Sperre auf der Seite bleibt davon unberührt – bei Bedarf unter Verwaltung → Mitglied sperren."
        )
        await open_system_ticket(self.bot, owner_id, f"Discord-Bann: {site_user.username}", body, category="melden")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RangsyncCog(bot))
