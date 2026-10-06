"""Gruppen-Rollen mit Bestaetigung - wie eine Whitelist-Anfrage, nur ohne Gameserver.

Ein Panel-Knopf mit Bestaetigung (custom_id "wb:role:<id>:c") gibt eine reine
Discord-Rolle (z.B. eine Spielgruppe) nicht sofort, sondern stellt eine Anfrage. Sie
erscheint im Whitelist-Kanal mit Annehmen / Ablehnen; entscheiden darf, wer die
Faehigkeit "whitelist.review" hat (Standard ab Mod, weitere Rollen im Tab
Einstellungen) - nie bei der eigenen Anfrage. Das Mitglied bekommt das Ergebnis per
DM. Wieder wegnehmen: /whitelist entziehen mitglied: rolle: oder im Tab Whitelist.

Zusatzrollen der Community-Seite laufen NICHT hierueber, sondern als Rollenanfrage auf
der Seite (rollenanfragen-Cog) - dort haengen ihre Regeln und z.B. das AMP-Konto.

Grenzen wie bei den Rollenanfragen der Seite: je Rolle eine offene Anfrage, eine
pro Tag, hoechstens vier pro Woche, nach einer Ablehnung dieselbe Rolle erst nach
sieben Tagen wieder.
"""

import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from sqlalchemy import func, select

from bot.core.capabilities import check_capability_interaction
from bot.core.entities import ensure_guild
from bot.core.guild_config import get_config
from db.models.panel_request import PanelRoleRequest
from db.session import get_db_session

log = logging.getLogger(__name__)

REVIEW_CHANNEL_KEY = "whitelist_channel"  # derselbe Kanal wie die Whitelist-Anfragen
PENDING, APPROVED, DENIED, REVOKED, CANCELLED = "pending", "approved", "denied", "revoked", "cancelled"
PER_DAY, PER_WEEK, DENIED_COOLDOWN_DAYS = 1, 4, 7
COLORS = {PENDING: 0xE0B96B, APPROVED: 0x3BA55C, DENIED: 0xD9534F, REVOKED: 0xD9534F, CANCELLED: 0x8A9296}


def _now() -> datetime:
    """UTC ohne Zeitzone - alle Zeitpunkte setzt der Bot selbst, damit die Grenzen nicht
    von der Zeitzone der Datenbank abhaengen."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def limit_error(guild_id: int, user_id: int, role_id: int) -> str | None:
    """Warum gerade keine neue Anfrage geht - oder None."""
    R = PanelRoleRequest
    mine = (R.guild_id == guild_id, R.user_id == user_id)
    async with get_db_session() as db:
        if (await db.execute(select(R.id).where(*mine, R.role_id == role_id, R.status == PENDING).limit(1))).first():
            return "Für diese Rolle läuft schon eine Anfrage – das Team entscheidet."
        denied_at = (
            await db.execute(
                select(func.max(R.decided_at)).where(
                    *mine, R.role_id == role_id, R.status == DENIED, R.decided_at > _now() - timedelta(days=DENIED_COOLDOWN_DAYS)
                )
            )
        ).scalar_one_or_none()
        if denied_at:
            again = (denied_at + timedelta(days=DENIED_COOLDOWN_DAYS)).replace(tzinfo=timezone.utc)
            return f"Diese Rolle wurde vor Kurzem abgelehnt – eine neue Anfrage geht ab <t:{int(again.timestamp())}:D>."
        day = (await db.execute(select(func.count()).where(*mine, R.created_at > _now() - timedelta(days=1)))).scalar_one()
        if day >= PER_DAY:
            return "Du kannst eine Rollen-Anfrage pro Tag stellen – versuch es morgen wieder."
        week = (await db.execute(select(func.count()).where(*mine, R.created_at > _now() - timedelta(days=7)))).scalar_one()
        if week >= PER_WEEK:
            return f"Du hast diese Woche schon {PER_WEEK} Rollen-Anfragen gestellt – bitte warte ein paar Tage."
    return None


def request_embed(request: PanelRoleRequest, role_name: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎭 Gruppen-Anfrage: {role_name}",
        description=f"<@{request.user_id}> möchte die Rolle <@&{request.role_id}>.",
        color=COLORS.get(request.status, COLORS[PENDING]),
    )
    decided = f"<@{request.decided_by}>" if request.decided_by else "?"
    note = f": {request.note}" if request.note else ""
    if request.status == APPROVED:
        embed.add_field(name="Ergebnis", value=f"✅ Angenommen von {decided}")
    elif request.status == DENIED:
        embed.add_field(name="Ergebnis", value=f"❌ Abgelehnt von {decided}{note}")
    elif request.status == REVOKED:
        embed.add_field(name="Ergebnis", value=f"⛔ Entzogen von {decided}{note}")
    elif request.status == CANCELLED:
        embed.add_field(name="Ergebnis", value="↩️ Erledigt – Mitglied weg oder Rolle nicht mehr vergebbar")
    else:
        embed.set_footer(text="Entscheiden: wer Whitelist-Anfragen bearbeiten darf – nie bei der eigenen Anfrage")
    return embed


def request_view(request: PanelRoleRequest) -> discord.ui.View | None:
    if request.status != PENDING:
        return None
    view = discord.ui.View(timeout=None)
    view.add_item(GroupRequestButton(request.id, "approve"))
    view.add_item(GroupRequestButton(request.id, "deny"))
    return view


async def review_channel(guild: discord.Guild):
    channel_id = await get_config(guild.id, REVIEW_CHANNEL_KEY)
    return guild.get_channel(int(channel_id)) if channel_id else None


async def create_request(guild: discord.Guild, member: discord.Member, role: discord.Role) -> str:
    """Stellt die Anfrage und postet sie im Whitelist-Kanal. Antwort fuer das Mitglied."""
    channel = await review_channel(guild)
    if channel is None:
        return "Für diese Rolle braucht es eine Bestätigung, aber dafür ist noch kein Whitelist-Kanal eingestellt – sag dem Team Bescheid."
    error = await limit_error(guild.id, member.id, role.id)
    if error:
        return error
    await ensure_guild(guild.id, guild.name)
    async with get_db_session() as db:
        request = PanelRoleRequest(guild_id=guild.id, user_id=member.id, role_id=role.id, status=PENDING, created_at=_now())
        db.add(request)
        await db.commit()
        await db.refresh(request)
    try:
        message = await channel.send(
            embed=request_embed(request, role.name), view=request_view(request), allowed_mentions=discord.AllowedMentions.none()
        )
    except discord.HTTPException as error:
        log.warning("Gruppen-Anfrage #%s nicht gepostet: %s", request.id, error)
        async with get_db_session() as db:
            await db.delete(await db.get(PanelRoleRequest, request.id))
            await db.commit()
        return "Die Anfrage ließ sich gerade nicht stellen – versuch es später noch einmal."
    async with get_db_session() as db:
        row = await db.get(PanelRoleRequest, request.id)
        row.channel_id, row.message_id = channel.id, message.id
        await db.commit()
    return f"Anfrage für **{role.name}** gestellt – das Team entscheidet, du bekommst Bescheid per DM."


async def decide(guild: discord.Guild, moderator: discord.abc.User, request_id: int, approve: bool, note: str = "") -> str:
    """Annehmen/Ablehnen eintragen und umsetzen. Rueckgabe: Antwort fuer den Entscheider."""
    from bot.cogs.roles.cog import block_reason  # erst hier - cog importiert dieses Modul

    async with get_db_session() as db:
        request = await db.get(PanelRoleRequest, request_id)
        if request is None or request.guild_id != guild.id:
            return "Diese Anfrage gibt es nicht mehr."
        if request.status != PENDING:
            return "Über diese Anfrage ist schon entschieden."
        if request.user_id == moderator.id:
            return "Über deine eigene Anfrage entscheidet jemand anderes."
        role = guild.get_role(request.role_id)
        member = guild.get_member(request.user_id)
        answer = None
        if approve and (member is None or role is None or await block_reason(role, guild)):
            request.status = CANCELLED
            answer = "Das Mitglied ist nicht mehr auf dem Server." if member is None else "Die Rolle ist nicht (mehr) vergebbar."
        else:
            request.status = APPROVED if approve else DENIED
        request.decided_by, request.note, request.decided_at = moderator.id, (note.strip()[:255] or None), _now()
        await db.commit()
        await db.refresh(request)
    if request.status == APPROVED:
        try:
            await member.add_roles(role, reason=f"Gruppen-Anfrage angenommen von {moderator}")
        except discord.HTTPException as error:
            log.warning("Gruppen-Anfrage #%s: Rolle nicht vergeben: %s", request.id, error)
            answer = "Angenommen, aber die Rolle ließ sich nicht vergeben – fehlt dem Bot „Rollen verwalten“ oder steht die Rolle über ihm?"
    await finish(guild, request, role.name if role else "?")
    return answer or ("Angenommen – die Rolle ist vergeben." if approve else "Abgelehnt – das Mitglied bekommt den Grund per DM.")


async def revoke(guild: discord.Guild, member: discord.Member, role: discord.Role, moderator_id: int, reason: str | None) -> str:
    """Rolle wieder wegnehmen (auch wenn sie von Hand vergeben wurde) und die Freigabe als entzogen markieren."""
    if role not in member.roles:
        return f"{member.display_name} hat die Rolle **{role.name}** nicht."
    try:
        await member.remove_roles(role, reason=f"Gruppe entzogen{': ' + reason if reason else ''}")
    except discord.HTTPException:
        return "Die Rolle ließ sich nicht entfernen – fehlt dem Bot „Rollen verwalten“ oder steht die Rolle über ihm?"
    R = PanelRoleRequest
    async with get_db_session() as db:
        request = (
            await db.execute(
                select(R).where(R.guild_id == guild.id, R.user_id == member.id, R.role_id == role.id, R.status == APPROVED)
                .order_by(R.id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if request is not None:
            request.status, request.decided_by, request.note, request.decided_at = REVOKED, moderator_id, (reason or None), _now()
            await db.commit()
            await db.refresh(request)
    if request is not None:
        await finish(guild, request, role.name, dm=False)
    try:
        await member.send(f"⛔ Dir wurde die Rolle **{role.name}** auf **{guild.name}** entzogen." + (f"\nGrund: {reason}" if reason else ""))
    except discord.HTTPException:
        pass
    return f"Rolle **{role.name}** bei {member.display_name} entzogen."


async def finish(guild: discord.Guild, request: PanelRoleRequest, role_name: str, *, dm: bool = True) -> None:
    """Nachricht im Whitelist-Kanal aktualisieren, Mitglied per DM informieren."""
    if request.channel_id and request.message_id:
        channel = guild.get_channel(request.channel_id)
        if channel is not None:
            try:
                message = await channel.fetch_message(request.message_id)
                await message.edit(embed=request_embed(request, role_name), view=None)
            except discord.HTTPException:
                pass
    member = guild.get_member(request.user_id)
    if not dm or member is None or request.status not in (APPROVED, DENIED):
        return
    if request.status == APPROVED:
        text = f"✅ Deine Anfrage für die Rolle **{role_name}** auf **{guild.name}** wurde angenommen – du hast sie jetzt."
    else:
        text = f"❌ Deine Anfrage für die Rolle **{role_name}** auf **{guild.name}** wurde abgelehnt." + (
            f"\nGrund: {request.note}" if request.note else ""
        )
    try:
        await member.send(text)
    except discord.HTTPException:
        pass  # DMs zu


class DenyModal(discord.ui.Modal, title="Gruppen-Anfrage ablehnen"):
    reason = discord.ui.TextInput(label="Grund (bekommt das Mitglied)", style=discord.TextStyle.paragraph, min_length=3, max_length=255)

    def __init__(self, request_id: int) -> None:
        super().__init__()
        self.request_id = request_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        answer = await decide(interaction.guild, interaction.user, self.request_id, False, str(self.reason))
        await interaction.followup.send(answer, ephemeral=True)


class GroupRequestButton(discord.ui.DynamicItem[discord.ui.Button], template=r"wb:grpreq:(?P<request_id>\d+):(?P<action>approve|deny)"):
    LABELS = {"approve": ("✅", "Annehmen", discord.ButtonStyle.success), "deny": ("❌", "Ablehnen", discord.ButtonStyle.danger)}

    def __init__(self, request_id: int, action: str) -> None:
        emoji, label, style = self.LABELS[action]
        super().__init__(discord.ui.Button(custom_id=f"wb:grpreq:{request_id}:{action}", emoji=emoji, label=label, style=style))
        self.request_id, self.action = request_id, action

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str]):
        return cls(int(match["request_id"]), match["action"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        if not await check_capability_interaction(interaction, interaction.guild.id, "whitelist.review"):
            return
        if self.action == "deny":
            await interaction.response.send_modal(DenyModal(self.request_id))
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await interaction.followup.send(await decide(interaction.guild, interaction.user, self.request_id, True), ephemeral=True)
