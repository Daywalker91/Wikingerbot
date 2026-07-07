from datetime import timedelta

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands
from sqlalchemy import func, select

from bot.core.base_cog import BaseCog
from bot.core.entities import ensure_guild, ensure_user
from bot.core.guild_config import get_config, set_config
from bot.core.permissions import Level, check_level_interaction, require_role
from db.models.modlog import ModAction, ModLogEntry, Warning
from db.session import get_db_session


async def _dm(member: discord.Member, message: str) -> None:
    try:
        await member.send(message)
    except discord.HTTPException:
        pass


async def _add_modlog(
    guild_id: int,
    user_id: int,
    mod_id: int,
    action: ModAction,
    reason: str | None,
    *,
    duration: int | None = None,
    escalation_reviewed: bool = True,
) -> ModLogEntry:
    async with get_db_session() as db:
        entry = ModLogEntry(
            guild_id=guild_id,
            user_id=user_id,
            mod_id=mod_id,
            action=action,
            reason=reason,
            duration=duration,
            escalation_reviewed=escalation_reviewed,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry


class EscalationReviewView(discord.ui.View):
    """Bestaetigen/Aufheben fuer automatisch ausgefuehrte Timeout-/Ban-Eskalationen."""

    def __init__(self, entry_id: int, action: str, guild_id: int, user_id: int) -> None:
        super().__init__(timeout=None)
        self.entry_id = entry_id
        self.action = action
        self.guild_id = guild_id
        self.user_id = user_id
        self.confirm_button.custom_id = f"modesc_confirm:{entry_id}"
        self.revert_button.custom_id = f"modesc_revert:{entry_id}"

    def _disable_all(self) -> None:
        for item in self.children:
            item.disabled = True

    @discord.ui.button(label="Bestaetigen", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await check_level_interaction(interaction, self.guild_id, Level.MOD):
            return
        async with get_db_session() as db:
            entry = await db.get(ModLogEntry, self.entry_id)
            if entry is not None:
                entry.escalation_reviewed = True
                await db.commit()
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("Bestaetigt.", ephemeral=True)

    @discord.ui.button(label="Aufheben", style=discord.ButtonStyle.danger)
    async def revert_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await check_level_interaction(interaction, self.guild_id, Level.MOD):
            return
        guild = interaction.guild
        try:
            if self.action == "ban":
                await guild.unban(discord.Object(id=self.user_id), reason="Eskalation aufgehoben")
            else:
                member = guild.get_member(self.user_id)
                if member is not None:
                    await member.timeout(None, reason="Eskalation aufgehoben")
        except discord.HTTPException:
            pass
        async with get_db_session() as db:
            entry = await db.get(ModLogEntry, self.entry_id)
            if entry is not None:
                entry.escalation_reviewed = True
                await db.commit()
        self._disable_all()
        await interaction.response.edit_message(view=self)
        await interaction.followup.send("Aufgehoben.", ephemeral=True)


class KickProposalView(discord.ui.View):
    """Vorschlag fuer eine Kick-Eskalation - muss aktiv ausgefuehrt werden.

    Bewusst nicht neustart-sicher (kein DB-Eintrag vor Ausfuehrung).
    """

    def __init__(self, guild_id: int, user_id: int, reason: str) -> None:
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.user_id = user_id
        self.reason = reason

    @discord.ui.button(label="Ausfuehren", style=discord.ButtonStyle.danger)
    async def execute_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await check_level_interaction(interaction, self.guild_id, Level.MOD):
            return
        member = interaction.guild.get_member(self.user_id)
        if member is None:
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content="Nutzer ist nicht mehr auf dem Server.", view=self
            )
            return

        await member.kick(reason=self.reason)
        await _add_modlog(self.guild_id, self.user_id, interaction.user.id, ModAction.KICK, self.reason)
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"{member.mention} wurde gekickt.", ephemeral=True)


class ModerationCog(BaseCog):
    """Kick/Ban/Timeout/Warn mit ModLog und automatischer Warn-Eskalation."""

    __cog_name__ = "moderation"
    __version__ = "1.0.0"
    __description__ = "Discord-Moderation: Kick/Ban/Timeout/Warn, ModLog"
    __author__ = "Daywalker91"

    modconfig_group = app_commands.Group(name="modconfig", description="Moderations-Konfiguration")

    async def cog_load(self) -> None:
        async with get_db_session() as db:
            result = await db.execute(
                select(ModLogEntry).where(
                    ModLogEntry.escalation_reviewed.is_(False),
                    ModLogEntry.review_message_id.is_not(None),
                )
            )
            pending = result.scalars().all()

        for entry in pending:
            action = "ban" if entry.action == ModAction.BAN else "timeout"
            view = EscalationReviewView(
                entry_id=entry.id, action=action, guild_id=entry.guild_id, user_id=entry.user_id
            )
            self.bot.add_view(view)

    @app_commands.command(name="kick", description="Kickt ein Mitglied vom Server")
    @app_commands.describe(user="Mitglied", reason="Begruendung")
    @require_role(Level.MOD)
    async def kick_cmd(self, interaction: discord.Interaction, user: discord.Member, reason: str) -> None:
        await interaction.response.defer(ephemeral=True)
        await ensure_guild(interaction.guild_id, interaction.guild.name)
        await ensure_user(user.id, str(user))

        await _dm(user, f"Du wurdest von **{interaction.guild.name}** gekickt.\nGrund: {reason}")
        await user.kick(reason=reason)
        await _add_modlog(interaction.guild_id, user.id, interaction.user.id, ModAction.KICK, reason)
        await interaction.followup.send(f"{user.mention} wurde gekickt. Grund: {reason}")

    @app_commands.command(name="ban", description="Bannt ein Mitglied vom Server")
    @app_commands.describe(
        user="Mitglied",
        reason="Begruendung",
        delete_message_days="Nachrichten der letzten X Tage loeschen (0-7)",
    )
    @require_role(Level.MOD)
    async def ban_cmd(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str,
        delete_message_days: app_commands.Range[int, 0, 7] = 0,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await ensure_guild(interaction.guild_id, interaction.guild.name)
        await ensure_user(user.id, str(user))

        await _dm(user, f"Du wurdest von **{interaction.guild.name}** gebannt.\nGrund: {reason}")
        await user.ban(reason=reason, delete_message_seconds=delete_message_days * 86400)
        await _add_modlog(interaction.guild_id, user.id, interaction.user.id, ModAction.BAN, reason)
        await interaction.followup.send(f"{user.mention} wurde gebannt. Grund: {reason}")

    @app_commands.command(name="unban", description="Hebt einen Bann auf")
    @app_commands.describe(user_id="Discord User-ID des gebannten Nutzers", reason="Begruendung")
    @require_role(Level.MOD)
    async def unban_cmd(self, interaction: discord.Interaction, user_id: str, reason: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.followup.send("Ungueltige User-ID.")
            return

        await interaction.guild.unban(discord.Object(id=uid), reason=reason)
        await _add_modlog(interaction.guild_id, uid, interaction.user.id, ModAction.UNBAN, reason)
        await interaction.followup.send(f"Bann fuer <@{uid}> aufgehoben. Grund: {reason}")

    @app_commands.command(name="timeout", description="Timeoutet ein Mitglied")
    @app_commands.describe(
        user="Mitglied", duration_minutes="Dauer in Minuten (max. 40320 = 28 Tage)", reason="Begruendung"
    )
    @require_role(Level.MOD)
    async def timeout_cmd(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        duration_minutes: app_commands.Range[int, 1, 40320],
        reason: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await ensure_guild(interaction.guild_id, interaction.guild.name)
        await ensure_user(user.id, str(user))

        await user.timeout(timedelta(minutes=duration_minutes), reason=reason)
        await _add_modlog(
            interaction.guild_id,
            user.id,
            interaction.user.id,
            ModAction.TIMEOUT,
            reason,
            duration=duration_minutes * 60,
        )
        await _dm(
            user,
            f"Du wurdest in **{interaction.guild.name}** fuer {duration_minutes} Minuten getimeoutet.\nGrund: {reason}",
        )
        await interaction.followup.send(
            f"{user.mention} wurde fuer {duration_minutes} Minuten getimeoutet. Grund: {reason}"
        )

    @app_commands.command(name="warn", description="Verwarnt ein Mitglied")
    @app_commands.describe(user="Mitglied", reason="Begruendung", points="Punkte (Default 1)")
    @require_role(Level.MOD)
    async def warn_cmd(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str,
        points: app_commands.Range[int, 1, 100] = 1,
    ) -> None:
        await interaction.response.defer()
        guild_id = interaction.guild_id

        await ensure_guild(guild_id, interaction.guild.name)
        await ensure_user(user.id, str(user))

        async with get_db_session() as db:
            db.add(
                Warning(guild_id=guild_id, user_id=user.id, mod_id=interaction.user.id, reason=reason, points=points)
            )
            await db.commit()

            result = await db.execute(
                select(func.sum(Warning.points)).where(
                    Warning.guild_id == guild_id, Warning.user_id == user.id, Warning.expired.is_(False)
                )
            )
            total_points = result.scalar_one() or 0

        await _dm(
            user,
            f"Du wurdest in **{interaction.guild.name}** verwarnt.\n"
            f"Grund: {reason}\nPunkte: {points} (Gesamt: {total_points})",
        )

        threshold = int(await get_config(guild_id, "warn_threshold", "3"))
        if total_points < threshold:
            await interaction.followup.send(
                f"{user.mention} verwarnt ({total_points}/{threshold} Punkten). Grund: {reason}"
            )
            return

        await interaction.followup.send(
            f"{user.mention} hat die Warn-Schwelle erreicht ({total_points}/{threshold})."
        )
        await self._trigger_escalation(interaction.channel, interaction.guild, user, total_points)

    async def _trigger_escalation(
        self, channel: discord.abc.Messageable, guild: discord.Guild, user: discord.Member, total_points: int
    ) -> None:
        action = await get_config(guild.id, "warn_action", "timeout")
        reason = f"Automatische Eskalation ({total_points} Warn-Punkte)"

        if action == "kick":
            embed = discord.Embed(
                title="Warn-Eskalation: Kick vorgeschlagen",
                description=f"{user.mention} hat {total_points} Warn-Punkte erreicht.\nVorschlag: **Kick**",
            )
            view = KickProposalView(guild_id=guild.id, user_id=user.id, reason=reason)
            await channel.send(embed=embed, view=view)
            return

        if action == "ban":
            await user.ban(reason=reason)
            duration = None
            title = "Automatische Eskalation: Bann"
            description = f"{user.mention} wurde automatisch gebannt ({total_points} Warn-Punkte)."
        else:
            timeout_minutes = int(await get_config(guild.id, "warn_timeout_minutes", "60"))
            await user.timeout(timedelta(minutes=timeout_minutes), reason=reason)
            duration = timeout_minutes * 60
            action = "timeout"
            title = "Automatische Eskalation: Timeout"
            description = (
                f"{user.mention} wurde automatisch fuer {timeout_minutes} Minuten getimeoutet "
                f"({total_points} Warn-Punkte)."
            )

        entry = await _add_modlog(
            guild.id,
            user.id,
            self.bot.user.id,
            ModAction.BAN if action == "ban" else ModAction.TIMEOUT,
            reason,
            duration=duration,
            escalation_reviewed=False,
        )

        view = EscalationReviewView(entry_id=entry.id, action=action, guild_id=guild.id, user_id=user.id)
        message = await channel.send(embed=discord.Embed(title=title, description=description), view=view)

        async with get_db_session() as db:
            db_entry = await db.get(ModLogEntry, entry.id)
            db_entry.review_message_id = message.id
            await db.commit()

    @app_commands.command(name="warnings", description="Zeigt aktive Verwarnungen eines Mitglieds")
    @app_commands.describe(user="Mitglied")
    @require_role(Level.MOD)
    async def warnings_cmd(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        async with get_db_session() as db:
            result = await db.execute(
                select(Warning)
                .where(
                    Warning.guild_id == interaction.guild_id,
                    Warning.user_id == user.id,
                    Warning.expired.is_(False),
                )
                .order_by(Warning.created_at.desc())
            )
            warnings = result.scalars().all()

        if not warnings:
            await interaction.followup.send(f"{user.mention} hat keine aktiven Verwarnungen.")
            return

        total = sum(w.points for w in warnings)
        lines = [f"`{w.created_at:%Y-%m-%d %H:%M}` — {w.points} Punkt(e): {w.reason or '-'}" for w in warnings]
        await interaction.followup.send(f"**{user.mention}** — {total} Punkte gesamt:\n" + "\n".join(lines))

    @app_commands.command(name="modlog", description="Zeigt die Moderations-Historie eines Mitglieds")
    @app_commands.describe(user="Mitglied")
    @require_role(Level.MOD)
    async def modlog_cmd(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await interaction.response.defer(ephemeral=True)
        async with get_db_session() as db:
            result = await db.execute(
                select(ModLogEntry)
                .where(ModLogEntry.guild_id == interaction.guild_id, ModLogEntry.user_id == user.id)
                .order_by(ModLogEntry.created_at.desc())
            )
            entries = result.scalars().all()

        if not entries:
            await interaction.followup.send(f"Keine Eintraege fuer {user.mention}.")
            return

        lines = [
            f"`{e.created_at:%Y-%m-%d %H:%M}` — **{e.action.value}** von <@{e.mod_id}>: {e.reason or '-'}"
            for e in entries
        ]
        await interaction.followup.send(f"**Modlog fuer {user.mention}**:\n" + "\n".join(lines))

    @modconfig_group.command(name="threshold", description="Setzt die Warn-Punkte-Schwelle")
    @app_commands.describe(value="Ab wie vielen aktiven Punkten eskaliert wird")
    @require_role(Level.OWNER)
    async def modconfig_threshold(
        self, interaction: discord.Interaction, value: app_commands.Range[int, 1, 100]
    ) -> None:
        await set_config(interaction.guild_id, "warn_threshold", str(value), interaction.guild.name)
        await interaction.response.send_message(
            f"Warn-Schwelle auf {value} gesetzt.", ephemeral=True, delete_after=20
        )

    @modconfig_group.command(name="action", description="Setzt die automatische Eskalations-Aktion")
    @app_commands.choices(
        action=[
            Choice(name="Timeout", value="timeout"),
            Choice(name="Ban", value="ban"),
            Choice(name="Kick (nur Vorschlag, keine Automatik)", value="kick"),
        ]
    )
    @require_role(Level.OWNER)
    async def modconfig_action(self, interaction: discord.Interaction, action: Choice[str]) -> None:
        await set_config(interaction.guild_id, "warn_action", action.value, interaction.guild.name)
        await interaction.response.send_message(
            f"Eskalations-Aktion auf `{action.name}` gesetzt.", ephemeral=True, delete_after=20
        )

    @modconfig_group.command(name="timeout", description="Setzt die Timeout-Dauer fuer Eskalationen")
    @app_commands.describe(minutes="Dauer in Minuten")
    @require_role(Level.OWNER)
    async def modconfig_timeout(
        self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 40320]
    ) -> None:
        await set_config(interaction.guild_id, "warn_timeout_minutes", str(minutes), interaction.guild.name)
        await interaction.response.send_message(
            f"Eskalations-Timeout auf {minutes} Minuten gesetzt.", ephemeral=True, delete_after=20
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
