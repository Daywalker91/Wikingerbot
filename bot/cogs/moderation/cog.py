import json
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands, tasks
from sqlalchemy import func, select, update

from bot.core.base_cog import BaseCog
from bot.core.entities import ensure_guild, ensure_user
from bot.core.guild_config import get_config, set_config
from bot.core.permissions import Level, check_level_interaction, require_role
from db.models.modlog import ModAction, ModLogEntry, Warning, WarnEscalationState
from db.session import get_db_session

DEFAULT_LADDER = ["timeout", "kick", "ban"]
ALLOWED_LADDER_ACTIONS = {"timeout", "kick", "ban"}


async def _get_ladder(guild_id: int) -> list[str]:
    raw = await get_config(guild_id, "warn_ladder", json.dumps(DEFAULT_LADDER))
    return json.loads(raw)


async def _consume_tier(guild_id: int, user_id: int) -> int:
    """Gibt den jetzt zu verwendenden Stufen-Index zurueck und erhoeht ihn
    fuer die naechste Eskalation. Getrennt von den Warn-Punkten (Warning),
    damit ein manueller Reset (reset_escalation_tier) moeglich ist, ohne die
    Warn-Historie zu loeschen."""
    async with get_db_session() as db:
        state = await db.get(WarnEscalationState, (guild_id, user_id))
        if state is None:
            state = WarnEscalationState(guild_id=guild_id, user_id=user_id, tier=0)
            db.add(state)
            await db.flush()
        current = state.tier
        state.tier += 1
        await db.commit()
        return current


async def reset_escalation_tier(guild_id: int, user_id: int) -> None:
    async with get_db_session() as db:
        state = await db.get(WarnEscalationState, (guild_id, user_id))
        if state is not None:
            state.tier = 0
            await db.commit()


async def _decay_warnings() -> None:
    """Laesst Warn-Punkte nach GuildConfig-Key "warn_decay_days" automatisch
    verfallen (expired=True) - betrifft nur, ob NEUE Verwarnungen wieder ueber
    die Schwelle fuehren. Ruehrt die Eskalationsstufe (WarnEscalationState)
    bewusst nicht an, Reset bleibt eine separate, manuelle Aktion. Frei
    stehende Funktion statt Cog-Methode, damit sie ohne lebende Cog-Instanz
    direkt testbar ist (siehe tests/test_moderation_escalation.py)."""
    async with get_db_session() as db:
        guild_ids = (await db.execute(select(Warning.guild_id).distinct())).scalars().all()

    for guild_id in guild_ids:
        decay_days = int(await get_config(guild_id, "warn_decay_days", "30"))
        # created_at ist naiv (SQLite/MariaDB DateTime ohne Zeitzone) - tz-aware
        # Wert erzeugen und wieder abstreifen, um datetime.utcnow() (deprecated)
        # zu vermeiden, aber vergleichbar mit der DB-Spalte zu bleiben.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=decay_days)).replace(tzinfo=None)
        async with get_db_session() as db:
            await db.execute(
                update(Warning)
                .where(
                    Warning.guild_id == guild_id,
                    Warning.expired.is_(False),
                    Warning.created_at < cutoff,
                )
                .values(expired=True)
            )
            await db.commit()


DEFAULT_AUTOMOD_POINTS = {
    "spam": 1,
    "keyword": 2,
    "keyword_preset": 2,
    "mention_spam": 2,
    "harmful_link": 3,
    "member_profile": 1,
}


async def _automod_points_for(guild_id: int, trigger_type: str) -> int:
    weights = json.loads(
        await get_config(guild_id, "automod_warn_points", json.dumps(DEFAULT_AUTOMOD_POINTS))
    )
    return weights.get(trigger_type, 1)


def _build_automod_reason(trigger_type: str, matched_keyword: str | None) -> str:
    reason = f"AutoMod: {trigger_type}"
    if matched_keyword:
        reason += f" (Treffer: '{matched_keyword}')"
    return reason


async def _resolve_automod_channel(bot: discord.Client, guild_id: int, fallback_channel_id: int):
    channel_id = await get_config(guild_id, "automod_alert_channel_id", None)
    return bot.get_channel(int(channel_id)) if channel_id else bot.get_channel(fallback_channel_id)


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


async def _trigger_escalation(
    bot_user_id: int,
    channel: discord.abc.Messageable,
    guild: discord.Guild,
    user: discord.Member,
    total_points: int,
) -> None:
    ladder = await _get_ladder(guild.id)
    tier = await _consume_tier(guild.id, user.id)
    action = ladder[min(tier, len(ladder) - 1)]
    reason = f"Automatische Eskalation Stufe {tier + 1} ({total_points} Warn-Punkte)"

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
        bot_user_id,
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


async def _apply_warning(
    bot_user_id: int,
    guild: discord.Guild,
    user_id: int,
    mod_id: int,
    reason: str,
    points: int,
    channel: discord.abc.Messageable,
) -> tuple[int, int]:
    """Traegt eine Verwarnung ein, prueft die Schwelle und eskaliert bei
    Bedarf - gemeinsame Logik fuer /warn UND die AutoMod-Integration.
    Gibt (total_points, threshold) zurueck."""
    await ensure_guild(guild.id, guild.name)
    await ensure_user(user_id)

    async with get_db_session() as db:
        db.add(Warning(guild_id=guild.id, user_id=user_id, mod_id=mod_id, reason=reason, points=points))
        await db.commit()
        result = await db.execute(
            select(func.sum(Warning.points)).where(
                Warning.guild_id == guild.id, Warning.user_id == user_id, Warning.expired.is_(False)
            )
        )
        total_points = result.scalar_one() or 0

    member = guild.get_member(user_id)
    if member is not None:
        await _dm(
            member,
            f"Du wurdest in **{guild.name}** verwarnt.\n"
            f"Grund: {reason}\nPunkte: {points} (Gesamt: {total_points})",
        )

    threshold = int(await get_config(guild.id, "warn_threshold", "3"))
    if total_points >= threshold and member is not None:
        await _trigger_escalation(bot_user_id, channel, guild, member, total_points)

    return total_points, threshold


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

        self.warn_decay.start()

    async def cog_unload(self) -> None:
        self.warn_decay.cancel()

    @tasks.loop(hours=1)
    async def warn_decay(self) -> None:
        await _decay_warnings()

    @warn_decay.before_loop
    async def _before_warn_decay(self) -> None:
        await self.bot.wait_until_ready()

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

        total_points, threshold = await _apply_warning(
            self.bot.user.id,
            interaction.guild,
            user.id,
            interaction.user.id,
            reason,
            points,
            interaction.channel,
        )

        if total_points < threshold:
            await interaction.followup.send(
                f"{user.mention} verwarnt ({total_points}/{threshold} Punkten). Grund: {reason}"
            )
            return

        await interaction.followup.send(
            f"{user.mention} hat die Warn-Schwelle erreicht ({total_points}/{threshold})."
        )

    @commands.Cog.listener("on_automod_action")
    async def on_automod_action(self, execution: discord.AutoModAction) -> None:
        if execution.action.type != discord.AutoModRuleActionType.block_message:
            return  # Vermeidet Doppelzaehlung bei Regeln mit mehreren Aktionen

        if await get_config(execution.guild_id, "automod_warn_enabled", "false") != "true":
            return

        guild = self.bot.get_guild(execution.guild_id)
        if guild is None:
            return

        points = await _automod_points_for(execution.guild_id, execution.rule_trigger_type.name)
        reason = _build_automod_reason(execution.rule_trigger_type.name, execution.matched_keyword)
        channel = await _resolve_automod_channel(self.bot, execution.guild_id, execution.channel_id)
        if channel is None:
            return

        await _apply_warning(
            self.bot.user.id, guild, execution.user_id, self.bot.user.id, reason, points, channel
        )

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

    @modconfig_group.command(
        name="ladder", description="Setzt die Eskalations-Leiter (Reihenfolge der Aktionen)"
    )
    @app_commands.describe(actions="Kommagetrennt, z.B. 'timeout,kick,ban' (erlaubt: timeout/kick/ban)")
    @require_role(Level.OWNER)
    async def modconfig_ladder(self, interaction: discord.Interaction, actions: str) -> None:
        tokens = [token.strip().lower() for token in actions.split(",") if token.strip()]
        invalid = [token for token in tokens if token not in ALLOWED_LADDER_ACTIONS]
        if not tokens or invalid:
            await interaction.response.send_message(
                f"Ungueltig: `{', '.join(invalid) or actions}`. Erlaubt sind nur timeout/kick/ban.",
                ephemeral=True,
            )
            return

        await set_config(interaction.guild_id, "warn_ladder", json.dumps(tokens), interaction.guild.name)
        await interaction.response.send_message(
            f"Eskalations-Leiter auf `{' -> '.join(tokens)}` gesetzt.", ephemeral=True, delete_after=20
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

    @modconfig_group.command(
        name="decay_days", description="Setzt, nach wie vielen Tagen Warn-Punkte automatisch verfallen"
    )
    @app_commands.describe(days="Anzahl Tage")
    @require_role(Level.OWNER)
    async def modconfig_decay_days(
        self, interaction: discord.Interaction, days: app_commands.Range[int, 1, 3650]
    ) -> None:
        await set_config(interaction.guild_id, "warn_decay_days", str(days), interaction.guild.name)
        await interaction.response.send_message(
            f"Warn-Punkte verfallen jetzt nach {days} Tagen.", ephemeral=True, delete_after=20
        )

    @modconfig_group.command(
        name="automod", description="Aktiviert/deaktiviert automatische Warnungen aus Discords AutoMod"
    )
    @app_commands.describe(enabled="An oder aus")
    @require_role(Level.OWNER)
    async def modconfig_automod(self, interaction: discord.Interaction, enabled: bool) -> None:
        await set_config(
            interaction.guild_id, "automod_warn_enabled", "true" if enabled else "false", interaction.guild.name
        )
        state = "aktiviert" if enabled else "deaktiviert"
        await interaction.response.send_message(
            f"AutoMod-Integration {state}.", ephemeral=True, delete_after=20
        )

    @modconfig_group.command(
        name="automod_channel", description="Setzt den Kanal fuer AutoMod-Eskalations-Meldungen"
    )
    @app_commands.describe(channel="Zielkanal")
    @require_role(Level.OWNER)
    async def modconfig_automod_channel(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        await set_config(
            interaction.guild_id, "automod_alert_channel_id", str(channel.id), interaction.guild.name
        )
        await interaction.response.send_message(
            f"AutoMod-Eskalations-Kanal auf {channel.mention} gesetzt.", ephemeral=True, delete_after=20
        )

    @modconfig_group.command(
        name="automod_points", description="Setzt die Warn-Punkte fuer einen AutoMod-Regeltyp"
    )
    @app_commands.describe(trigger_type="AutoMod-Regeltyp", points="Punkte")
    @app_commands.choices(
        trigger_type=[Choice(name=key, value=key) for key in DEFAULT_AUTOMOD_POINTS]
    )
    @require_role(Level.OWNER)
    async def modconfig_automod_points(
        self,
        interaction: discord.Interaction,
        trigger_type: Choice[str],
        points: app_commands.Range[int, 0, 100],
    ) -> None:
        weights = json.loads(
            await get_config(interaction.guild_id, "automod_warn_points", json.dumps(DEFAULT_AUTOMOD_POINTS))
        )
        weights[trigger_type.value] = points
        await set_config(interaction.guild_id, "automod_warn_points", json.dumps(weights), interaction.guild.name)
        await interaction.response.send_message(
            f"AutoMod-Punkte fuer `{trigger_type.value}` auf {points} gesetzt.",
            ephemeral=True,
            delete_after=20,
        )

    @app_commands.command(
        name="reset_escalation", description="Setzt die Eskalationsstufe eines Mitglieds zurueck"
    )
    @app_commands.describe(user="Mitglied")
    @require_role(Level.MOD)
    async def reset_escalation_cmd(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await reset_escalation_tier(interaction.guild_id, user.id)
        await interaction.response.send_message(
            f"Eskalationsstufe von {user.mention} zurueckgesetzt.", ephemeral=True, delete_after=20
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
