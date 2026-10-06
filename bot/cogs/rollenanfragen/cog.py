"""Rollenanfragen der Community-Seite in Discord.

Ein Mitglied beantragt auf der Seite (Einstellungen -> Rolle beantragen) die naechste
Rangstufe oder eine Zusatzrolle; die Seite legt dazu ein Ticket der Kategorie
"Rollenanfrage" an. Der Bot postet die Anfrage mit den Knoepfen Zustimmen / Ablehnen
in den Mod-Log-Kanal und in den Ticket-Thread. Wer entscheiden darf, steht in
requests.py. Zustimmen vergibt die Rolle auf der Seite (Rang-Sync und AMP-Konten
ziehen nach), Ablehnen fragt nach einem Grund; beides beantwortet und schliesst das
Ticket - das Mitglied bekommt es per DM.

Braucht die Anbindung an die Seite; Kanal = Mod-Log (Tab Moderation).
"""

import logging
import re

import discord
from discord.ext import commands

from bot.cogs.rollenanfragen.requests import APPROVED, CANCELLED, DENIED, PENDING, Approver, RoleRequest, approver_for, decide, decision_error, load
from bot.community import db as community_db
from bot.community import outbox
from bot.community.linking import user_for_discord
from bot.core.base_cog import BaseCog
from bot.core.entities import ensure_guild
from bot.core.guild_config import get_config
from bot.core.permissions import resolve_level
from db.models.community_post import CommunityPost
from db.session import get_db_session

log = logging.getLogger("wikingerbot.rollenanfragen")

MODLOG_KIND = "rolereq"  # Nachricht im Mod-Log
THREAD_KIND = "rolereq_thread"  # Nachricht im Ticket-Thread
COLORS = {PENDING: 0xE0B96B, APPROVED: 0x3BA55C, DENIED: 0xD9534F, CANCELLED: 0x8A9296}


def request_embed(request: RoleRequest) -> discord.Embed:
    what = "die Zusatzrolle" if request.role_kind == "extra" else "den Rang"
    who = f"<@{request.discord_id}>" if request.discord_id else request.username
    embed = discord.Embed(
        title=f"📨 Rollenanfrage: {request.role_name}",
        description=f"{who} ({request.username}, {request.requester_rank_name}) beantragt {what} **{request.role_name}**.",
        color=COLORS.get(request.status, COLORS[PENDING]),
    )
    embed.add_field(name="Begründung", value=(request.reason or "–")[:1000], inline=False)
    if request.ticket_id:
        link = community_db.site_link("tickets.view", id=request.ticket_id)
        embed.add_field(name="Ticket", value=f"[#{request.ticket_id}]({link})" if link else f"#{request.ticket_id}")
    if request.status == APPROVED:
        embed.add_field(name="Entscheidung", value=f"✅ Zugestimmt von {request.decided_name or '?'}", inline=False)
    elif request.status == DENIED:
        text = f"❌ Abgelehnt von {request.decided_name or '?'}" + (f": {request.decision_note}" if request.decision_note else "")
        embed.add_field(name="Entscheidung", value=text[:1000], inline=False)
    elif request.status == CANCELLED:
        embed.add_field(name="Entscheidung", value="↩️ Vom Mitglied zurückgezogen (Ticket geschlossen)", inline=False)
    else:
        rule = "wer die Rolle selbst hat (ab Mod)" if request.role_kind == "extra" else "wer über dem Rang steht (ab Mod)"
        embed.set_footer(text=f"Entscheiden: König oder {rule} – nie bei der eigenen Anfrage")
    return embed


def request_view(request: RoleRequest) -> discord.ui.View | None:
    if request.status != PENDING:
        return None
    view = discord.ui.View(timeout=None)
    view.add_item(RoleRequestButton(request.id, "approve"))
    view.add_item(RoleRequestButton(request.id, "deny"))
    return view


async def _approver(interaction: discord.Interaction) -> Approver | str:
    """Wer klickt - als Entscheider, oder ein Hinweis, warum nicht."""
    if not community_db.enabled():
        return "Die Community-Seite ist gerade nicht angebunden."
    site_user = await user_for_discord(interaction.user.id)
    if site_user is None:
        return "Verknüpfe dich zuerst mit der Seite (/verknuepfen)."
    member = interaction.user if isinstance(interaction.user, discord.Member) else None
    level = await resolve_level(interaction.guild_id or 0, [r.id for r in member.roles] if member else [])
    admin = bool(member and member.guild_permissions.administrator)
    return await approver_for(site_user.id, site_user.username, level, admin)


class DenyModal(discord.ui.Modal, title="Rollenanfrage ablehnen"):
    reason = discord.ui.TextInput(label="Grund (bekommt das Mitglied)", style=discord.TextStyle.paragraph, min_length=3, max_length=255)

    def __init__(self, request_id: int) -> None:
        super().__init__()
        self.request_id = request_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        cog: "RollenanfragenCog | None" = interaction.client.get_cog("RollenanfragenCog")
        message = await cog.run_decision(interaction, self.request_id, False, str(self.reason)) if cog else "Rollenanfragen sind gerade nicht verfügbar."
        await interaction.followup.send(message, ephemeral=True)


class RoleRequestButton(discord.ui.DynamicItem[discord.ui.Button], template=r"wb:rolereq:(?P<request_id>\d+):(?P<action>approve|deny)"):
    LABELS = {"approve": ("✅", "Zustimmen", discord.ButtonStyle.success), "deny": ("❌", "Ablehnen", discord.ButtonStyle.danger)}

    def __init__(self, request_id: int, action: str) -> None:
        emoji, label, style = self.LABELS[action]
        super().__init__(discord.ui.Button(custom_id=f"wb:rolereq:{request_id}:{action}", emoji=emoji, label=label, style=style))
        self.request_id, self.action = request_id, action

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["request_id"]), match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        cog: "RollenanfragenCog | None" = interaction.client.get_cog("RollenanfragenCog")
        if cog is None:
            await interaction.response.send_message("Rollenanfragen sind gerade nicht verfügbar.", ephemeral=True)
            return
        if self.action == "deny":
            # vorher pruefen, damit niemand umsonst einen Grund tippt
            error = await cog.check(interaction, self.request_id)
            if error:
                await interaction.response.send_message(error, ephemeral=True)
                return
            await interaction.response.send_modal(DenyModal(self.request_id))
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(await cog.run_decision(interaction, self.request_id, True), ephemeral=True)


class RollenanfragenCog(BaseCog):
    """Rollenanfragen der Seite: im Mod-Log zustimmen oder ablehnen."""

    __cog_name__ = "rollenanfragen"
    __version__ = "1.0.0"
    __description__ = "Rollenanfragen der Community-Seite (Zustimmen/Ablehnen in Discord)"
    __author__ = "Daywalker91"

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(RoleRequestButton)
        outbox.register("role.request", self._on_request)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(RoleRequestButton)
        outbox.unregister("role.request", self._on_request)

    # --- Neue Anfrage -----------------------------------------------------------------

    async def _on_request(self, payload: dict) -> None:
        request = await load(int(payload["request_id"]))
        if request is None:
            return
        if request.status != PENDING:  # z.B. zurueckgezogen: Knoepfe weg, Stand zeigen
            await self._refresh_messages(request)
            return
        await self.post_request(request)

    async def post_request(self, request: RoleRequest) -> None:
        embed, view = request_embed(request), request_view(request)
        tickets = self.bot.get_cog("TicketsCog")
        if tickets is not None and request.ticket_id:
            try:
                await tickets.sync_ticket(request.ticket_id)  # Thread sicher anlegen (Reihenfolge der Auftraege egal)
            except Exception as error:
                log.warning("Ticket-Thread fuer Rollenanfrage #%s: %s", request.id, error)
        for guild in self.bot.guilds:
            channel = await self._modlog(guild)
            if channel is not None and await self._get(MODLOG_KIND, guild.id, request.id) is None:
                try:
                    message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                    await self._set(MODLOG_KIND, guild, request.id, channel.id, message.id)
                except discord.HTTPException as error:
                    log.warning("Rollenanfrage #%s nicht im Mod-Log gepostet: %s", request.id, error)
            if tickets is not None and request.ticket_id and await self._get(THREAD_KIND, guild.id, request.id) is None:
                thread = await tickets._thread(guild, request.ticket_id)
                if thread is not None:
                    try:
                        message = await thread.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                        await self._set(THREAD_KIND, guild, request.id, thread.id, message.id)
                    except discord.HTTPException as error:
                        log.warning("Rollenanfrage #%s nicht im Ticket-Thread gepostet: %s", request.id, error)

    # --- Entscheiden ------------------------------------------------------------------

    async def check(self, interaction: discord.Interaction, request_id: int) -> str | None:
        approver = await _approver(interaction)
        if isinstance(approver, str):
            return approver
        request = await load(request_id)
        if request is None:
            return "Diese Anfrage gibt es nicht mehr."
        return decision_error(request, approver)

    async def run_decision(self, interaction: discord.Interaction, request_id: int, approve: bool, note: str = "") -> str:
        approver = await _approver(interaction)
        if isinstance(approver, str):
            return approver
        request = await load(request_id)
        if request is None:
            return "Diese Anfrage gibt es nicht mehr."
        error = decision_error(request, approver)
        if error:
            return error
        if not await decide(request, approver, approve, note):
            return "Inzwischen hat schon jemand anderes entschieden."
        log.info("Rollenanfrage #%s (%s fuer %s) %s von %s", request.id, request.role_name, request.username,
                 "genehmigt" if approve else "abgelehnt", approver.username)
        await self._after_decision(request.id, interaction.user)
        return "Zugestimmt – die Rolle ist vergeben." if approve else "Abgelehnt – das Mitglied bekommt den Grund per DM."

    async def _after_decision(self, request_id: int, actor: discord.abc.User) -> None:
        request = await load(request_id)
        if request is None:
            return
        # Seite -> Discord: Rang-Sync und AMP-Konten ziehen nach wie bei einer Aenderung auf der Seite
        if request.status == APPROVED:
            kind = "user.extra_roles" if request.role_kind == "extra" else "user.role"
            await outbox.dispatch_local(kind, {"user_id": request.user_id})
        tickets = self.bot.get_cog("TicketsCog")
        if tickets is not None and request.ticket_id:
            try:
                await tickets.sync_ticket(request.ticket_id)  # Antwort + Schliessen spiegeln, DM ans Mitglied
            except Exception as error:
                log.warning("Ticket #%s nach Entscheidung nicht abgeglichen: %s", request.ticket_id, error)
        await self._refresh_messages(request)
        for guild in self.bot.guilds:
            channel = await self._modlog(guild)
            if channel is not None:
                icon, verb = ("✅", "zugestimmt") if request.status == APPROVED else ("❌", "abgelehnt")
                who = f"<@{request.discord_id}>" if request.discord_id else request.username
                text = f"{icon} Rollenanfrage **{request.role_name}** für {who} – {verb} von {actor.mention}"
                if request.status == DENIED and request.decision_note:
                    text += f": {request.decision_note}"
                try:
                    await channel.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    pass

    async def _refresh_messages(self, request: RoleRequest) -> None:
        """Gepostete Anfrage (Mod-Log, Ticket-Thread) auf den aktuellen Stand bringen."""
        embed = request_embed(request)
        for guild in self.bot.guilds:
            for kind in (MODLOG_KIND, THREAD_KIND):
                mapping = await self._get(kind, guild.id, request.id)
                if mapping is None:
                    continue
                channel = guild.get_channel_or_thread(mapping.channel_id)
                if channel is None:
                    continue
                try:
                    message = await channel.fetch_message(mapping.message_id)
                    await message.edit(embed=embed, view=None)
                except discord.HTTPException:
                    pass

    # --- Hilfen ---------------------------------------------------------------------

    async def _modlog(self, guild: discord.Guild):
        channel_id = await get_config(guild.id, "modlog_channel_id")
        return guild.get_channel(int(channel_id)) if channel_id else None

    async def _get(self, kind: str, guild_id: int, request_id: int) -> CommunityPost | None:
        async with get_db_session() as db:
            return await db.get(CommunityPost, (kind, request_id, guild_id))

    async def _set(self, kind: str, guild: discord.Guild, request_id: int, channel_id: int, message_id: int) -> None:
        await ensure_guild(guild.id, guild.name)
        async with get_db_session() as db:
            row = await db.get(CommunityPost, (kind, request_id, guild.id))
            if row is None:
                db.add(CommunityPost(kind=kind, item_id=request_id, guild_id=guild.id, channel_id=channel_id, message_id=message_id))
            else:
                row.channel_id, row.message_id = channel_id, message_id
            await db.commit()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RollenanfragenCog(bot))
