"""Server-Statistiken: Beitritte/Austritte, Nachrichten, Voice-Zeit, aktivste
Mitglieder, optional ein Zaehler-Kanal ("👥 Mitglieder: 42").

Gezaehlt wird nur, wie viel - nie, was geschrieben wurde. Werte pro Mitglied
werden nach stats_retention_days (Standard 90) geloescht.
"""

import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.cogs.stats.collector import (
    StatsBuffer,
    flush,
    format_duration,
    member_summary,
    now,
    purge_member_rows,
    server_summary,
    today,
)
from bot.core.base_cog import BaseCog
from bot.core.guild_config import get_config, set_config
from bot.core.permissions import Level, require_role

log = logging.getLogger(__name__)

DEFAULT_COUNTER_FORMAT = "👥 Mitglieder: {count}"
DEFAULT_RETENTION_DAYS = 90


def counter_name(template: str, guild: discord.Guild) -> str:
    humans = sum(1 for m in guild.members if not m.bot)
    return template.replace("{count}", str(humans)).replace("{all}", str(guild.member_count or 0))[:100]


class StatsCog(BaseCog):
    """Aktivitaet zaehlen und auswerten."""

    __cog_name__ = "stats"
    __version__ = "1.0.0"
    __description__ = "Server-Statistiken und Aktivitaet"
    __author__ = "Daywalker91"

    stats_group = app_commands.Group(name="stats", description="Server-Statistiken")

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self.buffer = StatsBuffer()
        self.voice_started: dict[tuple[int, int], datetime] = {}

    async def cog_load(self) -> None:
        self.flush_loop.start()
        self.counter_loop.start()
        self.purge_loop.start()

    async def cog_unload(self) -> None:
        self.flush_loop.cancel()
        self.counter_loop.cancel()
        self.purge_loop.cancel()
        # laufende Voice-Sitzungen bis jetzt verbuchen
        end = now()
        for (guild_id, user_id), start in self.voice_started.items():
            self.buffer.voice(guild_id, user_id, start, end)
        self.voice_started.clear()
        await flush(self.buffer)

    # --- Zaehlen --------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Wer beim Start schon im Voice sitzt, zaehlt ab jetzt
        for guild in self.bot.guilds:
            self.buffer.guild_names[guild.id] = guild.name
            for channel in guild.voice_channels + guild.stage_channels:
                if channel == guild.afk_channel:
                    continue
                for member in channel.members:
                    if not member.bot:
                        self.voice_started.setdefault((guild.id, member.id), now())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.author.bot:
            return
        self.buffer.guild_names[message.guild.id] = message.guild.name
        self.buffer.message(message.guild.id, message.author.id, today())

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            self.buffer.join(member.guild.id, today())

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if not member.bot:
            self.buffer.leave(member.guild.id, today())

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.bot:
            return
        afk = member.guild.afk_channel
        was_in = before.channel is not None and before.channel != afk
        is_in = after.channel is not None and after.channel != afk
        key = (member.guild.id, member.id)
        if was_in and not is_in:
            start = self.voice_started.pop(key, None)
            if start is not None:
                self.buffer.voice(member.guild.id, member.id, start, now())
        elif is_in and not was_in:
            self.voice_started[key] = now()

    # --- Hintergrund ----------------------------------------------------------------

    @tasks.loop(minutes=1)
    async def flush_loop(self) -> None:
        try:
            await flush(self.buffer)
        except Exception as error:
            log.warning("Statistik konnte nicht gespeichert werden: %s", error)

    @tasks.loop(minutes=10)
    async def counter_loop(self) -> None:
        """Discord erlaubt nur 2 Umbenennungen pro 10 Minuten und Kanal - daher dieser Takt."""
        for guild in self.bot.guilds:
            channel_id = await get_config(guild.id, "stats_counter_channel_id")
            if not channel_id:
                continue
            channel = guild.get_channel(int(channel_id))
            if channel is None:
                continue
            name = counter_name(await get_config(guild.id, "stats_counter_format", DEFAULT_COUNTER_FORMAT), guild)
            if channel.name != name:
                try:
                    await channel.edit(name=name, reason="Mitgliederzaehler")
                except discord.HTTPException as error:
                    log.warning("Zaehler-Kanal in %s nicht umbenannt: %s", guild.name, error)

    @tasks.loop(hours=24)
    async def purge_loop(self) -> None:
        days = DEFAULT_RETENTION_DAYS
        for guild in self.bot.guilds:
            days = max(days, int(await get_config(guild.id, "stats_retention_days", str(DEFAULT_RETENTION_DAYS))))
        removed = await purge_member_rows(days)
        if removed:
            log.info("Statistik: %d alte Eintraege pro Mitglied geloescht", removed)

    @flush_loop.before_loop
    @counter_loop.before_loop
    @purge_loop.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    # --- Befehle --------------------------------------------------------------------

    def _name(self, guild: discord.Guild, user_id: int) -> str:
        member = guild.get_member(user_id)
        return member.display_name if member else f"(ehemals {user_id})"

    @stats_group.command(name="server", description="Aktivitaet des Servers")
    @app_commands.describe(tage="Zeitraum in Tagen (Standard 7)")
    async def stats_server(self, interaction: discord.Interaction, tage: app_commands.Range[int, 1, 365] = 7) -> None:
        await flush(self.buffer)
        guild = interaction.guild
        data = await server_summary(guild.id, tage)
        humans = sum(1 for m in guild.members if not m.bot)
        embed = discord.Embed(title=f"📊 {guild.name} – letzte {tage} Tage", color=0x8B5A2B)
        embed.add_field(name="Mitglieder", value=f"{humans} (+{len(guild.members) - humans} Bots)")
        embed.add_field(name="Beitritte / Austritte", value=f"+{data['joins']} / −{data['leaves']}")
        embed.add_field(name="Nachrichten", value=str(data["messages"]))
        embed.add_field(name="Voice-Zeit", value=format_duration(data["voice_seconds"]))
        if data["busiest_day"]:
            day, count = data["busiest_day"]
            embed.add_field(name="Aktivster Tag", value=f"{day:%d.%m.} ({count} Nachrichten)")
        if data["top_messages"]:
            embed.add_field(
                name="Meiste Nachrichten",
                value="\n".join(f"{i}. {self._name(guild, u)} – {v}" for i, (u, v) in enumerate(data["top_messages"], 1)),
                inline=False,
            )
        if data["top_voice"]:
            embed.add_field(
                name="Meiste Voice-Zeit",
                value="\n".join(
                    f"{i}. {self._name(guild, u)} – {format_duration(v)}" for i, (u, v) in enumerate(data["top_voice"], 1)
                ),
                inline=False,
            )
        embed.set_footer(text="Gezählt wird nur die Anzahl, nie der Inhalt.")
        await interaction.response.send_message(embed=embed)

    @stats_group.command(name="mitglied", description="Aktivitaet eines Mitglieds (ohne Angabe: deine)")
    @app_commands.describe(mitglied="Wen", tage="Zeitraum in Tagen (Standard 30)")
    async def stats_member(
        self,
        interaction: discord.Interaction,
        mitglied: discord.Member | None = None,
        tage: app_commands.Range[int, 1, 365] = 30,
    ) -> None:
        await flush(self.buffer)
        member = mitglied or interaction.user
        data = await member_summary(interaction.guild_id, member.id, tage)
        voice = data["voice_seconds"]
        start = self.voice_started.get((interaction.guild_id, member.id))
        if start is not None:
            voice += int((now() - start).total_seconds())  # laufende Sitzung mitzaehlen
        rank = f" – Platz {data['rank']}" if data["rank"] else ""
        await interaction.response.send_message(
            f"**{member.display_name}**, letzte {tage} Tage: {data['messages']} Nachrichten{rank}, "
            f"{format_duration(voice)} im Voice.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @stats_group.command(name="zaehler", description="Kanal, dessen Name die Mitgliederzahl zeigt (ohne Kanal: aus)")
    @app_commands.describe(
        kanal="Am besten ein Voice-Kanal, den niemand betreten darf",
        format="Name mit {count} (Mitglieder ohne Bots) oder {all}",
    )
    @require_role(Level.ADMIN)
    async def stats_counter(
        self,
        interaction: discord.Interaction,
        kanal: discord.VoiceChannel | None = None,
        format: str = DEFAULT_COUNTER_FORMAT,
    ) -> None:
        guild = interaction.guild
        await set_config(guild.id, "stats_counter_channel_id", str(kanal.id) if kanal else "", guild.name)
        await set_config(guild.id, "stats_counter_format", format, guild.name)
        if kanal is None:
            await interaction.response.send_message("Zähler-Kanal ist aus.", ephemeral=True, delete_after=20)
            return
        try:
            await kanal.edit(name=counter_name(format, guild), reason="Mitgliederzaehler")
            text = f"{kanal.mention} zeigt jetzt die Mitgliederzahl (aktualisiert alle 10 Minuten)."
        except discord.HTTPException:
            text = "Gespeichert, aber ich darf den Kanal nicht umbenennen – mir fehlt dort „Kanäle verwalten“."
        await interaction.response.send_message(text, ephemeral=True, delete_after=30)

    @stats_group.command(name="aufbewahrung", description="Wie lange Werte pro Mitglied gespeichert bleiben")
    @require_role(Level.ADMIN)
    async def stats_retention(self, interaction: discord.Interaction, tage: app_commands.Range[int, 7, 730]) -> None:
        await set_config(interaction.guild_id, "stats_retention_days", str(tage), interaction.guild.name)
        await interaction.response.send_message(
            f"Werte pro Mitglied werden nach {tage} Tagen gelöscht.", ephemeral=True, delete_after=20
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
