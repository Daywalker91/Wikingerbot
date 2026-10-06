import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.cogs.whitelist.actions import grant, revoke
from bot.core.base_cog import BaseCog
from bot.core.capabilities import check_capability_interaction, require_capability
from bot.core.discord_utils import send_temp_followup
from bot.core.entities import ensure_guild, ensure_user
from bot.core.guild_config import get_config, set_config
from bot.core.permissions import Level, check_level_interaction, require_role
from db.models.server import Server
from db.models.user import User
from db.models.whitelist import WhitelistRequest, WhitelistStatus
from db.session import get_db_session

WHITELIST_CHANNEL_KEY = "whitelist_channel"


async def _dm(member: discord.Member, message: str) -> None:
    try:
        await member.send(message)
    except discord.HTTPException:
        pass


async def _server_choices(interaction: discord.Interaction, current: str, *, only_whitelist: bool) -> list[app_commands.Choice[str]]:
    query = select(Server.instance_name, Server.display_name).where(Server.guild_id == interaction.guild_id)
    if only_whitelist:
        query = query.where(Server.whitelist_enabled.is_(True))
    async with get_db_session() as db:
        rows = (await db.execute(query)).all()

    current_lower = current.lower()
    return [
        app_commands.Choice(name=f"{display_name} ({instance_name})", value=instance_name)
        for instance_name, display_name in rows
        if current_lower in instance_name.lower() or current_lower in display_name.lower()
    ][:25]


async def _autocomplete_server(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Fuer /whitelist request: nur Server mit eingeschalteter Whitelist."""
    return await _server_choices(interaction, current, only_whitelist=True)


async def _autocomplete_any_server(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    return await _server_choices(interaction, current, only_whitelist=False)


async def _autocomplete_pending_request(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    async with get_db_session() as db:
        result = await db.execute(
            select(WhitelistRequest.id, WhitelistRequest.ign, Server.display_name)
            .join(Server, Server.id == WhitelistRequest.server_id)
            .where(
                Server.guild_id == interaction.guild_id,
                WhitelistRequest.status == WhitelistStatus.PENDING,
            )
        )
        rows = result.all()

    current_lower = current.lower()
    choices = []
    for request_id, ign, display_name in rows:
        label = f"#{request_id} {ign} ({display_name})"
        if current_lower in label.lower():
            choices.append(app_commands.Choice(name=label, value=request_id))
    return choices[:25]


async def _resolve_request(
    request_id: int, approved: bool, moderator: discord.Member, reason: str | None = None
) -> tuple[bool, str]:
    """Fuehrt Freigabe/Ablehnung aus. Gibt (gefunden, ergebnis_text) zurueck."""
    async with get_db_session() as db:
        request = await db.get(WhitelistRequest, request_id)
        if request is None or request.status != WhitelistStatus.PENDING:
            return False, "Anfrage nicht gefunden oder bereits bearbeitet."

        server = await db.get(Server, request.server_id)
        request.status = WhitelistStatus.APPROVED if approved else WhitelistStatus.DENIED
        request.handled_by = moderator.id
        await db.commit()

    guild = moderator.guild
    member = guild.get_member(request.user_id)
    result_lines: list[str] = []

    if approved:
        result_lines = await grant(guild, request, server)
    elif member is not None:
        reason_text = f"\nGrund: {reason}" if reason else ""
        await _dm(
            member,
            f"Deine Whitelist-Anfrage fuer **{server.display_name}** wurde abgelehnt.{reason_text}",
        )

    status_word = "genehmigt" if approved else "abgelehnt"
    summary = f"Anfrage #{request_id} ({request.ign} / {server.display_name}) {status_word} von {moderator.mention}."
    if result_lines:
        summary += "\n" + "\n".join(result_lines)
    return True, summary


class WhitelistReviewView(discord.ui.View):
    """Accept/Deny-Buttons fuer eine einzelne Whitelist-Anfrage."""

    def __init__(self, request_id: int, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.request_id = request_id
        self.guild_id = guild_id
        self.accept_button.custom_id = f"whitelist_accept:{request_id}"
        self.deny_button.custom_id = f"whitelist_deny:{request_id}"

    async def _handle(self, interaction: discord.Interaction, approved: bool) -> None:
        if not await check_capability_interaction(interaction, self.guild_id, "whitelist.review"):
            return
        await interaction.response.defer()

        _, summary = await _resolve_request(self.request_id, approved, interaction.user)

        for item in self.children:
            item.disabled = True

        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.add_field(name="Ergebnis", value=summary, inline=False)
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Annehmen", style=discord.ButtonStyle.success)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle(interaction, True)

    @discord.ui.button(label="Ablehnen", style=discord.ButtonStyle.danger)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._handle(interaction, False)


class WhitelistCog(BaseCog):
    """Whitelist-Anfragen mit Mod-Freigabe (Accept/Deny-Buttons), AMP-Whitelist und Rollen-Vergabe."""

    __cog_name__ = "whitelist"
    __version__ = "1.0.0"
    __description__ = "Whitelist-Anfragen, Freigabe, Rollen-Vergabe"
    __author__ = "Daywalker91"

    whitelist_group = app_commands.Group(name="whitelist", description="Whitelist-Verwaltung")

    async def cog_load(self) -> None:
        async with get_db_session() as db:
            result = await db.execute(
                select(WhitelistRequest).where(
                    WhitelistRequest.status == WhitelistStatus.PENDING,
                    WhitelistRequest.review_message_id.is_not(None),
                )
            )
            pending = result.scalars().all()

        for request in pending:
            async with get_db_session() as db:
                server = await db.get(Server, request.server_id)
            if server is None:
                continue
            view = WhitelistReviewView(request_id=request.id, guild_id=server.guild_id)
            self.bot.add_view(view)

    @whitelist_group.command(name="channel", description="Setzt den Kanal fuer Whitelist-Anfragen (Mods/Admins)")
    @app_commands.describe(channel="Zielkanal")
    @require_role(Level.OWNER)
    async def whitelist_channel_cmd(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await set_config(interaction.guild_id, WHITELIST_CHANNEL_KEY, str(channel.id), interaction.guild.name)
        await interaction.response.send_message(
            f"Whitelist-Kanal auf {channel.mention} gesetzt.", ephemeral=True, delete_after=20
        )

    @whitelist_group.command(name="request", description="Beantragt Whitelist-Zugang zu einem Server")
    @app_commands.describe(
        server="Server (instance_name)",
        ign="Dein In-Game-Name (Spielername/Charaktername im jeweiligen Spiel, nicht dein Discord-Name)."
        " Weglassen, um deinen zuletzt genutzten IGN wiederzuverwenden.",
    )
    @app_commands.autocomplete(server=_autocomplete_server)
    @require_role(Level.MEMBER)
    async def whitelist_request_cmd(
        self, interaction: discord.Interaction, server: str, ign: app_commands.Range[str, 2, 64] | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if ign is not None:
            ign = " ".join(ign.split())  # keine Zeilenumbrueche/Tabs im Namen

        async with get_db_session() as db:
            result = await db.execute(
                select(Server).where(
                    Server.guild_id == interaction.guild_id, Server.instance_name == server
                )
            )
            server_row = result.scalar_one_or_none()

        if server_row is None:
            await send_temp_followup(interaction, f"Server `{server}` nicht gefunden.")
            return
        if not server_row.whitelist_enabled:
            await send_temp_followup(
                interaction, f"Für `{server_row.display_name}` gibt es keine Whitelist – der Zugang ist frei (z.B. über die Rollen)."
            )
            return
        async with get_db_session() as db:
            open_status = (
                await db.execute(
                    select(WhitelistRequest.status).where(
                        WhitelistRequest.user_id == interaction.user.id,
                        WhitelistRequest.server_id == server_row.id,
                        WhitelistRequest.status.in_([WhitelistStatus.PENDING, WhitelistStatus.APPROVED]),
                    )
                )
            ).scalars().first()
        if open_status is not None:
            text = "Du bist dort schon freigeschaltet." if open_status == WhitelistStatus.APPROVED else "Deine Anfrage läuft schon."
            await send_temp_followup(interaction, text)
            return

        channel_id_raw = await get_config(interaction.guild_id, WHITELIST_CHANNEL_KEY)
        channel = self.bot.get_channel(int(channel_id_raw)) if channel_id_raw else None
        if channel is None:
            await send_temp_followup(
                interaction, "Kein Whitelist-Kanal konfiguriert. Wende dich an einen Admin."
            )
            return

        await ensure_guild(interaction.guild_id, interaction.guild.name)
        await ensure_user(interaction.user.id, str(interaction.user))

        async with get_db_session() as db:
            user = await db.get(User, interaction.user.id)
            if ign is not None:
                user.ign = ign
            elif user.ign is not None:
                ign = user.ign
            else:
                await send_temp_followup(
                    interaction,
                    "Du hast noch keinen In-Game-Namen hinterlegt. Bitte gib `ign` beim ersten Mal an.",
                )
                return
            await db.commit()

        async with get_db_session() as db:
            request = WhitelistRequest(user_id=interaction.user.id, server_id=server_row.id, ign=ign)
            db.add(request)
            await db.commit()
            await db.refresh(request)

        embed = discord.Embed(title="Neue Whitelist-Anfrage")
        embed.add_field(name="Nutzer", value=interaction.user.mention)
        embed.add_field(name="Server", value=server_row.display_name)
        embed.add_field(name="IGN", value=ign)

        view = WhitelistReviewView(request_id=request.id, guild_id=interaction.guild_id)
        message = await channel.send(embed=embed, view=view)

        async with get_db_session() as db:
            db_request = await db.get(WhitelistRequest, request.id)
            db_request.review_message_id = message.id
            await db.commit()

        await send_temp_followup(interaction, "Anfrage gesendet.")

    @whitelist_group.command(name="list", description="Listet Whitelist-Anfragen")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Ausstehend", value="pending"),
            app_commands.Choice(name="Genehmigt", value="approved"),
            app_commands.Choice(name="Abgelehnt", value="denied"),
            app_commands.Choice(name="Entzogen", value="revoked"),
        ]
    )
    @require_capability("whitelist.review")
    async def whitelist_list_cmd(
        self, interaction: discord.Interaction, status: app_commands.Choice[str] | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        target_status = WhitelistStatus(status.value) if status is not None else WhitelistStatus.PENDING

        async with get_db_session() as db:
            result = await db.execute(
                select(WhitelistRequest, Server)
                .join(Server, Server.id == WhitelistRequest.server_id)
                .where(Server.guild_id == interaction.guild_id, WhitelistRequest.status == target_status)
                .order_by(WhitelistRequest.created_at.desc())
            )
            rows = result.all()

        if not rows:
            await interaction.followup.send(f"Keine Anfragen mit Status `{target_status.value}`.")
            return

        lines = [
            f"`#{req.id}` <@{req.user_id}> — {req.ign} ({srv.display_name}) — {req.created_at:%Y-%m-%d %H:%M}"
            for req, srv in rows
        ]
        await interaction.followup.send("\n".join(lines))

    @whitelist_group.command(name="approve", description="Genehmigt eine Whitelist-Anfrage")
    @app_commands.describe(request_id="Anfrage-ID")
    @app_commands.autocomplete(request_id=_autocomplete_pending_request)
    @require_capability("whitelist.review")
    async def whitelist_approve_cmd(self, interaction: discord.Interaction, request_id: int) -> None:
        await interaction.response.defer(ephemeral=True)
        _, summary = await _resolve_request(request_id, True, interaction.user)
        await send_temp_followup(interaction, summary)

    @whitelist_group.command(name="deny", description="Lehnt eine Whitelist-Anfrage ab")
    @app_commands.describe(request_id="Anfrage-ID", reason="Begruendung")
    @app_commands.autocomplete(request_id=_autocomplete_pending_request)
    @require_capability("whitelist.review")
    async def whitelist_deny_cmd(
        self, interaction: discord.Interaction, request_id: int, reason: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        _, summary = await _resolve_request(request_id, False, interaction.user, reason)
        await send_temp_followup(interaction, summary)

    @whitelist_group.command(name="entziehen", description="Entzieht eine Freigabe (Server oder Gruppen-Rolle) samt Discord-Rolle")
    @app_commands.describe(
        mitglied="Mitglied",
        server="Server (instance_name) - ODER:",
        rolle="Gruppen-Rolle ohne Server (z.B. eine Spielgruppe aus einem Panel mit Bestätigung)",
        grund="Begruendung (bekommt das Mitglied per DM)",
    )
    @app_commands.autocomplete(server=_autocomplete_any_server)
    @require_capability("whitelist.review")
    async def whitelist_revoke_cmd(
        self,
        interaction: discord.Interaction,
        mitglied: discord.Member,
        server: str | None = None,
        rolle: discord.Role | None = None,
        grund: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        if (server is None) == (rolle is None):
            await send_temp_followup(interaction, "Bitte genau eins angeben: `server` oder `rolle`.")
            return
        if rolle is not None:
            from bot.cogs.roles.requests import revoke as revoke_group

            await send_temp_followup(interaction, await revoke_group(interaction.guild, mitglied, rolle, interaction.user.id, grund))
            return
        async with get_db_session() as db:
            server_row = (
                await db.execute(select(Server).where(Server.guild_id == interaction.guild_id, Server.instance_name == server))
            ).scalar_one_or_none()
        if server_row is None:
            await send_temp_followup(interaction, f"Server `{server}` nicht gefunden.")
            return
        _, summary = await revoke(interaction.guild, mitglied.id, server_row, interaction.user.id, grund)
        await send_temp_followup(interaction, summary)

    @whitelist_group.command(name="donator", description="Setzt/entfernt den Donator-Status eines Nutzers")
    @app_commands.describe(user="Nutzer", enabled="Donator-Status")
    @require_role(Level.OWNER)
    async def whitelist_donator_cmd(
        self, interaction: discord.Interaction, user: discord.Member, enabled: bool
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await ensure_user(user.id, str(user))

        async with get_db_session() as db:
            db_user = await db.get(User, user.id)
            db_user.is_donator = enabled
            await db.commit()

        status_word = "gesetzt" if enabled else "entfernt"
        await send_temp_followup(interaction, f"Donator-Status fuer {user.mention} {status_word}.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WhitelistCog(bot))
