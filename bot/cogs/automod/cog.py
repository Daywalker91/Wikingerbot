"""Alles zu AutoMod an einer Stelle (eigener Tab in der Oberflaeche):

1. Discords eingebauter AutoMod: blockiert er eine Nachricht, gibt es Warn-Punkte
   je Regeltyp (frueher Teil des moderation-Cogs, gleiche Einstellungen).
2. Eigene Regeln, die Discord nicht kann: Flut, Wiederholung, Grossbuchstaben,
   Emojis, Links, Hinweis bei jungen Konten. Folgen: loeschen, optional Warn-Punkte
   und Timeout. Mods und hoeher sowie Administratoren sind ausgenommen.

Warn-Punkte laufen ueber das Verwarnsystem des moderation-Cogs (mit Eskalation) -
nur wenn der geladen ist; sonst wird nur geloescht und gemeldet. Meldungen gehen
in den eigenen AutoMod-Alarmkanal (guild_config "automod_alert_channel_id").
"""

import json
import logging
import time
from datetime import timedelta
from typing import Literal

from discord.app_commands import Choice

import discord
from discord import app_commands
from discord.ext import commands

from bot.cogs.automod.rules import MessageHistory, check_message, merged_config
from bot.core.base_cog import BaseCog
from bot.core.guild_config import get_config, set_config
from bot.core.permissions import Level, level_at_least, require_role, resolve_level

log = logging.getLogger(__name__)

CONFIG_KEY = "automod_rules"
CONFIG_CACHE_SECONDS = 60
PUNISH_COOLDOWN_SECONDS = 30  # waehrend einer Flut nur einmal verwarnen, Rest nur loeschen

# Warn-Punkte je Regeltyp von Discords AutoMod (guild_config "automod_warn_points")
DEFAULT_AUTOMOD_POINTS = {
    "spam": 1,
    "keyword": 2,
    "keyword_preset": 2,
    "mention_spam": 2,
    "harmful_link": 3,
    "member_profile": 1,
}
AUTOMOD_TRIGGER_LABELS = {
    "spam": "Spam",
    "keyword": "Eigene Stichwörter",
    "keyword_preset": "Discord-Stichwortlisten",
    "mention_spam": "Erwähnungs-Spam",
    "harmful_link": "Schädliche Links",
    "member_profile": "Mitgliederprofil",
}


async def automod_points(guild_id: int) -> dict[str, int]:
    try:
        stored = json.loads(await get_config(guild_id, "automod_warn_points", "{}") or "{}")
    except json.JSONDecodeError:
        stored = {}
    return {**DEFAULT_AUTOMOD_POINTS, **{k: int(v) for k, v in stored.items()}}


async def automod_points_for(guild_id: int, trigger_type: str) -> int:
    return (await automod_points(guild_id)).get(trigger_type, 1)


def build_automod_reason(trigger_type: str, matched_keyword: str | None) -> str:
    reason = f"AutoMod: {trigger_type}"
    if matched_keyword:
        reason += f" (Treffer: '{matched_keyword}')"
    return reason


async def resolve_alert_channel(bot: discord.Client, guild_id: int, fallback_channel_id: int | None = None):
    channel_id = await get_config(guild_id, "automod_alert_channel_id", None)
    if channel_id:
        return bot.get_channel(int(channel_id))
    return bot.get_channel(fallback_channel_id) if fallback_channel_id else None


class AutomodCog(BaseCog):
    """Regeln, die Discords AutoMod nicht kann."""

    __cog_name__ = "automod"
    __version__ = "1.0.0"
    __description__ = "Eigene AutoMod-Regeln: Flut, Wiederholung, Caps, Emojis, Links"
    __author__ = "Daywalker91"

    automod_group = app_commands.Group(name="automod", description="Eigene AutoMod-Regeln (zusaetzlich zu Discords AutoMod)")

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.history = MessageHistory()
        self._config_cache: dict[int, tuple[float, dict]] = {}
        self._last_punished: dict[tuple[int, int], float] = {}

    async def _config(self, guild_id: int) -> dict:
        cached = self._config_cache.get(guild_id)
        if cached and time.monotonic() - cached[0] < CONFIG_CACHE_SECONDS:
            return cached[1]
        try:
            stored = json.loads(await get_config(guild_id, CONFIG_KEY, "{}") or "{}")
        except json.JSONDecodeError:
            stored = {}
        config = merged_config(stored)
        self._config_cache[guild_id] = (time.monotonic(), config)
        return config

    async def _save(self, guild: discord.Guild, config: dict) -> None:
        await set_config(guild.id, CONFIG_KEY, json.dumps(config), guild.name)
        self._config_cache[guild.id] = (time.monotonic(), config)

    async def _exempt(self, message: discord.Message, config: dict) -> bool:
        member = message.author
        if not isinstance(member, discord.Member) or member.guild_permissions.administrator:
            return True
        if message.channel.id in config["exempt_channels"] or getattr(message.channel, "parent_id", None) in config["exempt_channels"]:
            return True
        role_ids = [r.id for r in member.roles]
        if any(r in config["exempt_roles"] for r in role_ids):
            return True
        return level_at_least(await resolve_level(message.guild.id, role_ids), Level.MOD)

    # --- Pruefen --------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot or not message.content:
            return
        config = await self._config(message.guild.id)
        if not config["enabled"] or await self._exempt(message, config):
            return
        at = time.monotonic()
        recent = self.history.add((message.guild.id, message.author.id), message.content, at)
        reason = check_message(config, message.content, recent, at)
        if reason:
            await self._act(message, config, reason)

    async def _act(self, message: discord.Message, config: dict, reason: str) -> None:
        action = config["action"]
        member = message.author
        key = (message.guild.id, member.id)
        if action["delete"]:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
        now = time.monotonic()
        if now - self._last_punished.get(key, 0) < PUNISH_COOLDOWN_SECONDS:
            return
        self._last_punished[key] = now

        try:
            await message.channel.send(f"{member.mention} {reason}.", delete_after=8)
        except discord.HTTPException:
            pass

        results = []
        if action["timeout_minutes"]:
            try:
                await member.timeout(timedelta(minutes=action["timeout_minutes"]), reason=f"AutoMod: {reason}")
                results.append(f"Timeout {action['timeout_minutes']} min")
            except discord.HTTPException as error:
                log.warning("AutoMod-Timeout fehlgeschlagen: %s", error)
        if action["points"]:
            if await self._warn(message, f"AutoMod: {reason}", action["points"]):
                results.append(f"{action['points']} Warn-Punkt(e)")

        await self._alert(message.guild, f"{member.mention} in {message.channel.mention}: **{reason}**", results, message.content)

    async def _warn(self, message: discord.Message, reason: str, points: int) -> bool:
        return await self._apply_points(message.guild, message.author.id, reason, points, message.channel)

    async def _apply_points(self, guild: discord.Guild, user_id: int, reason: str, points: int, channel) -> bool:
        """Ueber das Verwarnsystem des moderation-Cogs - nur wenn der geladen ist."""
        if self.bot.get_cog("ModerationCog") is None:
            return False
        from bot.cogs.moderation.cog import _apply_warning

        try:
            await _apply_warning(self.bot.user.id, guild, user_id, self.bot.user.id, reason, points, channel)
            return True
        except Exception as error:
            log.warning("AutoMod-Verwarnung fehlgeschlagen: %s", error)
            return False

    async def _alert(self, guild: discord.Guild, text: str, results: list[str], content: str | None = None) -> None:
        channel_id = await get_config(guild.id, "automod_alert_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(title="🛡️ AutoMod (Bot)", description=text, color=0xB03A2E)
        if content:
            embed.add_field(name="Nachricht", value=content[:1000], inline=False)
        if results:
            embed.add_field(name="Folgen", value=", ".join(results), inline=False)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as error:
            log.warning("AutoMod-Meldung fehlgeschlagen: %s", error)

    @commands.Cog.listener("on_automod_action")
    async def on_automod_action(self, execution: discord.AutoModAction) -> None:
        """Discords eigener AutoMod hat zugeschlagen -> Warn-Punkte je Regeltyp."""
        if execution.action.type != discord.AutoModRuleActionType.block_message:
            return  # nur einmal zaehlen, auch wenn eine Regel mehrere Aktionen hat
        if await get_config(execution.guild_id, "automod_warn_enabled", "false") != "true":
            return
        guild = self.bot.get_guild(execution.guild_id)
        if guild is None:
            return
        trigger = execution.rule_trigger_type.name
        points = await automod_points_for(execution.guild_id, trigger)
        channel = await resolve_alert_channel(self.bot, execution.guild_id, execution.channel_id)
        if channel is None or not points:
            return
        await self._apply_points(guild, execution.user_id, build_automod_reason(trigger, execution.matched_keyword), points, channel)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return
        config = await self._config(member.guild.id)
        days = config["new_accounts_days"]
        if not config["enabled"] or not days:
            return
        age = discord.utils.utcnow() - member.created_at
        if age < timedelta(days=days):
            hours = int(age.total_seconds() // 3600)
            alter = f"{hours} Stunden" if hours < 48 else f"{hours // 24} Tage"
            await self._alert(member.guild, f"Neues Konto beigetreten: {member.mention} – Konto ist erst {alter} alt.", [])

    # --- Einstellungen --------------------------------------------------------------

    async def _update(self, interaction: discord.Interaction, change, text: str) -> None:
        config = await self._config(interaction.guild_id)
        change(config)
        await self._save(interaction.guild, config)
        await interaction.response.send_message(text, ephemeral=True, delete_after=20)

    @automod_group.command(name="status", description="Zeigt alle Regeln und Einstellungen")
    @require_role(Level.MOD)
    async def status(self, interaction: discord.Interaction) -> None:
        c = await self._config(interaction.guild_id)
        on = lambda flag: "✅" if flag else "❌"  # noqa: E731
        links = {"off": "aus", "allowlist": "nur erlaubte Domains", "block": "alle gesperrt"}[c["links"]["mode"]]
        channel_id = await get_config(interaction.guild_id, "automod_alert_channel_id")
        discord_on = await get_config(interaction.guild_id, "automod_warn_enabled", "false") == "true"
        points = await automod_points(interaction.guild_id)
        lines = [
            f"**Discords AutoMod → Warn-Punkte: {'an' if discord_on else 'aus'}** "
            f"({', '.join(f'{AUTOMOD_TRIGGER_LABELS[k]} {v}' for k, v in points.items() if k in AUTOMOD_TRIGGER_LABELS)})",
            f"**Eigene Regeln {'an' if c['enabled'] else 'AUS'}**",
            f"{on(c['flood']['on'])} Flut: mehr als {c['flood']['messages']} Nachrichten in {c['flood']['seconds']} s",
            f"{on(c['duplicates']['on'])} Wiederholung: {c['duplicates']['count']}× gleich in {c['duplicates']['seconds']} s",
            f"{on(c['caps']['on'])} Großbuchstaben: ab {c['caps']['percent']} % (ab {c['caps']['min_length']} Buchstaben)",
            f"{on(c['emojis']['on'])} Emojis: mehr als {c['emojis']['max']}",
            f"🔗 Links: {links}" + (f" ({', '.join(c['links']['allow'])})" if c["links"]["mode"] == "allowlist" and c["links"]["allow"] else ""),
            f"🆕 Neue Konten: {'Hinweis unter ' + str(c['new_accounts_days']) + ' Tagen' if c['new_accounts_days'] else 'aus'}",
            f"⚖️ Folgen: {'löschen' if c['action']['delete'] else 'nicht löschen'}, {c['action']['points']} Warn-Punkte, "
            f"Timeout {c['action']['timeout_minutes']} min",
            f"📣 Alarmkanal: {f'<#{channel_id}>' if channel_id else 'keiner'}",
            "🙈 Ausnahmen: " + (", ".join([f"<#{i}>" for i in c["exempt_channels"]] + [f"<@&{i}>" for i in c["exempt_roles"]]) or "keine")
            + " (Mods und Admins immer)",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @automod_group.command(name="discord", description="Warn-Punkte, wenn Discords eigener AutoMod eine Nachricht blockiert")
    @require_role(Level.ADMIN)
    async def discord_toggle(self, interaction: discord.Interaction, an: bool) -> None:
        await set_config(interaction.guild_id, "automod_warn_enabled", "true" if an else "false", interaction.guild.name)
        await interaction.response.send_message(
            f"Warn-Punkte aus Discords AutoMod sind {'an' if an else 'aus'}.", ephemeral=True, delete_after=20
        )

    @automod_group.command(name="discord_punkte", description="Warn-Punkte je Regeltyp von Discords AutoMod")
    @app_commands.choices(typ=[Choice(name=label, value=key) for key, label in AUTOMOD_TRIGGER_LABELS.items()])
    @require_role(Level.ADMIN)
    async def discord_points(
        self, interaction: discord.Interaction, typ: Choice[str], punkte: app_commands.Range[int, 0, 100]
    ) -> None:
        weights = await automod_points(interaction.guild_id)
        weights[typ.value] = punkte
        await set_config(interaction.guild_id, "automod_warn_points", json.dumps(weights), interaction.guild.name)
        await interaction.response.send_message(f"{typ.name}: {punkte} Warn-Punkte.", ephemeral=True, delete_after=20)

    @automod_group.command(name="aktiv", description="Eigene Bot-Regeln an- oder abschalten")
    @require_role(Level.ADMIN)
    async def toggle(self, interaction: discord.Interaction, an: bool) -> None:
        await self._update(interaction, lambda c: c.update(enabled=an), f"Bot-AutoMod ist {'an' if an else 'aus'}.")

    @automod_group.command(name="flut", description="Zu viele Nachrichten in kurzer Zeit")
    @require_role(Level.ADMIN)
    async def flood(
        self,
        interaction: discord.Interaction,
        an: bool,
        nachrichten: app_commands.Range[int, 2, 50] = 6,
        sekunden: app_commands.Range[int, 2, 120] = 8,
    ) -> None:
        await self._update(
            interaction,
            lambda c: c["flood"].update(on=an, messages=nachrichten, seconds=sekunden),
            f"Flut-Regel {'an' if an else 'aus'}: mehr als {nachrichten} Nachrichten in {sekunden} s.",
        )

    @automod_group.command(name="wiederholung", description="Dieselbe Nachricht mehrfach")
    @require_role(Level.ADMIN)
    async def duplicates(
        self,
        interaction: discord.Interaction,
        an: bool,
        anzahl: app_commands.Range[int, 2, 20] = 3,
        sekunden: app_commands.Range[int, 5, 600] = 60,
    ) -> None:
        await self._update(
            interaction,
            lambda c: c["duplicates"].update(on=an, count=anzahl, seconds=sekunden),
            f"Wiederholungs-Regel {'an' if an else 'aus'}: {anzahl}× gleich in {sekunden} s.",
        )

    @automod_group.command(name="grossbuchstaben", description="Zu viel GROSSSCHRIFT")
    @require_role(Level.ADMIN)
    async def caps(
        self,
        interaction: discord.Interaction,
        an: bool,
        prozent: app_commands.Range[int, 50, 100] = 70,
        mindestlaenge: app_commands.Range[int, 5, 200] = 12,
    ) -> None:
        await self._update(
            interaction,
            lambda c: c["caps"].update(on=an, percent=prozent, min_length=mindestlaenge),
            f"Großbuchstaben-Regel {'an' if an else 'aus'}: ab {prozent} % bei mindestens {mindestlaenge} Buchstaben.",
        )

    @automod_group.command(name="emojis", description="Zu viele Emojis in einer Nachricht")
    @require_role(Level.ADMIN)
    async def emojis(self, interaction: discord.Interaction, an: bool, maximal: app_commands.Range[int, 1, 100] = 10) -> None:
        await self._update(
            interaction,
            lambda c: c["emojis"].update(on=an, max=maximal),
            f"Emoji-Regel {'an' if an else 'aus'}: mehr als {maximal} Emojis.",
        )

    @automod_group.command(name="links", description="Links: aus, nur erlaubte Domains oder alle sperren")
    @require_role(Level.ADMIN)
    async def links(self, interaction: discord.Interaction, modus: Literal["aus", "nur_erlaubte", "alle_sperren"]) -> None:
        mode = {"aus": "off", "nur_erlaubte": "allowlist", "alle_sperren": "block"}[modus]
        await self._update(interaction, lambda c: c["links"].update(mode=mode), f"Link-Regel: {modus.replace('_', ' ')}.")

    @automod_group.command(name="link_erlauben", description="Domain fuer 'nur erlaubte' freigeben (gilt mit Subdomains)")
    @require_role(Level.ADMIN)
    async def link_allow(self, interaction: discord.Interaction, domain: str) -> None:
        domain = domain.lower().strip().removeprefix("https://").removeprefix("http://").removeprefix("www.").split("/")[0]

        def change(c):
            if domain not in c["links"]["allow"]:
                c["links"]["allow"].append(domain)

        await self._update(interaction, change, f"`{domain}` ist erlaubt.")

    @automod_group.command(name="link_entfernen", description="Domain wieder von der Liste nehmen")
    @require_role(Level.ADMIN)
    async def link_remove(self, interaction: discord.Interaction, domain: str) -> None:
        domain = domain.lower().strip().removeprefix("www.")
        await self._update(
            interaction, lambda c: c["links"].update(allow=[d for d in c["links"]["allow"] if d != domain]), f"`{domain}` entfernt."
        )

    @automod_group.command(name="neue_konten", description="Hinweis im Alarmkanal, wenn ein junges Konto beitritt (0 = aus)")
    @require_role(Level.ADMIN)
    async def new_accounts(self, interaction: discord.Interaction, tage: app_commands.Range[int, 0, 365]) -> None:
        await self._update(
            interaction,
            lambda c: c.update(new_accounts_days=tage),
            f"Hinweis bei Konten jünger als {tage} Tage." if tage else "Hinweis bei neuen Konten ist aus.",
        )

    @automod_group.command(name="aktion", description="Was bei einem Verstoss passiert")
    @app_commands.describe(
        loeschen="Nachricht loeschen",
        punkte="Warn-Punkte ueber das Verwarnsystem (0 = keine; braucht den moderation-Cog)",
        timeout_minuten="Timeout in Minuten (0 = keiner)",
    )
    @require_role(Level.ADMIN)
    async def action(
        self,
        interaction: discord.Interaction,
        loeschen: bool = True,
        punkte: app_commands.Range[int, 0, 10] = 0,
        timeout_minuten: app_commands.Range[int, 0, 1440] = 0,
    ) -> None:
        await self._update(
            interaction,
            lambda c: c["action"].update(delete=loeschen, points=punkte, timeout_minutes=timeout_minuten),
            f"Bei Verstoß: {'löschen' if loeschen else 'nicht löschen'}, {punkte} Warn-Punkte, Timeout {timeout_minuten} min.",
        )

    @automod_group.command(name="alarmkanal", description="Kanal fuer alle AutoMod-Meldungen (eigene Regeln und Discords AutoMod)")
    @require_role(Level.ADMIN)
    async def alert_channel(self, interaction: discord.Interaction, kanal: discord.TextChannel) -> None:
        await set_config(interaction.guild_id, "automod_alert_channel_id", str(kanal.id), interaction.guild.name)
        await interaction.response.send_message(f"AutoMod-Meldungen gehen nach {kanal.mention}.", ephemeral=True, delete_after=20)

    @automod_group.command(name="ausnahme", description="Kanal oder Rolle von den Regeln ausnehmen (nochmal = wieder aufheben)")
    @require_role(Level.ADMIN)
    async def exempt(
        self, interaction: discord.Interaction, kanal: discord.TextChannel | None = None, rolle: discord.Role | None = None
    ) -> None:
        if kanal is None and rolle is None:
            await interaction.response.send_message("Bitte einen Kanal oder eine Rolle angeben.", ephemeral=True, delete_after=20)
            return
        notes = []

        def change(c):
            for item, key in ((kanal, "exempt_channels"), (rolle, "exempt_roles")):
                if item is None:
                    continue
                if item.id in c[key]:
                    c[key].remove(item.id)
                    notes.append(f"{item.mention} wieder geprüft")
                else:
                    c[key].append(item.id)
                    notes.append(f"{item.mention} ausgenommen")

        config = await self._config(interaction.guild_id)
        change(config)
        await self._save(interaction.guild, config)
        await interaction.response.send_message(
            ", ".join(notes) + ".", ephemeral=True, delete_after=20, allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutomodCog(bot))
