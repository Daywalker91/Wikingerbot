"""Eigene AutoMod-Regeln (Flut, Wiederholung, Grossbuchstaben, Emojis, Links,
neue Konten) - Ergaenzung zu Discords eingebautem AutoMod, nicht Ersatz.

Bei einem Verstoss: Nachricht loeschen, optional Warn-Punkte (ueber den
moderation-Cog, falls geladen) und Timeout, Meldung im AutoMod-Alarmkanal
(derselbe wie fuer Discords AutoMod: guild_config "automod_alert_channel_id").
Mods und hoeher sowie Administratoren sind ausgenommen.
"""

import json
import logging
import time
from datetime import timedelta
from typing import Literal

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
        """Ueber das Verwarnsystem des moderation-Cogs - nur wenn der geladen ist."""
        if self.bot.get_cog("ModerationCog") is None:
            return False
        from bot.cogs.moderation.cog import _apply_warning

        try:
            await _apply_warning(self.bot.user.id, message.guild, message.author.id, self.bot.user.id, reason, points, message.channel)
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
        lines = [
            f"**Bot-AutoMod {'an' if c['enabled'] else 'AUS'}**",
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

    @automod_group.command(name="aktiv", description="Bot-AutoMod an- oder abschalten")
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

    @automod_group.command(name="alarmkanal", description="Kanal fuer AutoMod-Meldungen (gilt auch fuer Discords AutoMod)")
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
