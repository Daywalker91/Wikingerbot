"""Begruessung neuer Mitglieder: Nachricht im Kanal, optional DM, optional Abschied.

Alles liegt in guild_config (kein eigenes Schema). Texte unterstuetzen
Platzhalter (siehe PLACEHOLDERS) und "\\n" fuer Zeilenumbrueche - Discords
Slash-Command-Eingabe kennt keine echten Zeilenumbrueche.
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.base_cog import BaseCog
from bot.core.guild_config import get_config, set_config
from bot.core.permissions import Level, require_role

log = logging.getLogger(__name__)

DEFAULT_WELCOME = "Willkommen {user} auf **{server}**! Du bist Mitglied Nummer {count}."
DEFAULT_GOODBYE = "**{name}** hat {server} verlassen."
PLACEHOLDERS = "`{user}` Erwähnung, `{name}` Anzeigename, `{server}` Servername, `{count}` Mitgliederzahl"

# Nur das neue Mitglied darf angepingt werden - ein Text mit @everyone oder
# Rollen-Erwaehnungen soll bei jedem Beitritt nicht den ganzen Server wecken.
ALLOWED_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True)

OFF_WORDS = {"aus", "off", "-", ""}


def render(template: str, *, mention: str, name: str, server: str, count: int) -> str:
    """Setzt die Platzhalter ein. Unbekannte {xyz} bleiben stehen statt einen
    Fehler zu werfen - ein Tippfehler im Text soll die Begruessung nicht verhindern."""
    values = {"user": mention, "name": name, "server": server, "count": str(count)}
    text = template.replace("\\n", "\n")
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text[:2000]


def render_for(template: str, member: discord.Member) -> str:
    return render(
        template,
        mention=member.mention,
        name=member.display_name,
        server=member.guild.name,
        count=member.guild.member_count or len(member.guild.members),
    )


def is_off(value: str | None) -> bool:
    return value is None or value.strip().lower() in OFF_WORDS


async def _text_channel(guild: discord.Guild, key: str) -> discord.abc.Messageable | None:
    channel_id = await get_config(guild.id, key)
    if not channel_id:
        return None
    channel = guild.get_channel(int(channel_id))
    return channel if isinstance(channel, (discord.TextChannel, discord.Thread)) else None


class WelcomeCog(BaseCog):
    """Begruessung, Willkommens-DM und Abschiedsmeldung."""

    __cog_name__ = "welcome"
    __version__ = "1.0.0"
    __description__ = "Willkommens- und Abschiedsnachrichten"
    __author__ = "Daywalker91"

    welcome_group = app_commands.Group(name="welcome", description="Begruessung neuer Mitglieder einstellen")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        # Mit Discords Mitgliedschaftspruefung (Regeln/Onboarding) erst nach dem Akzeptieren
        if not member.bot and not member.pending:
            await self._greet(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.pending and not after.pending and not after.bot:
            await self._greet(after)

    async def _greet(self, member: discord.Member) -> None:
        guild = member.guild

        channel = await _text_channel(guild, "welcome_channel_id")
        if channel is not None:
            template = await get_config(guild.id, "welcome_message", DEFAULT_WELCOME)
            try:
                await channel.send(render_for(template, member), allowed_mentions=ALLOWED_MENTIONS)
            except discord.HTTPException as error:
                log.warning("Begruessung in %s fehlgeschlagen: %s", guild.name, error)

        dm_template = await get_config(guild.id, "welcome_dm_message")
        if not is_off(dm_template):
            try:
                await member.send(render_for(dm_template, member))
            except discord.HTTPException:
                pass  # DMs zu - kein Fehler, viele haben das so eingestellt

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        if member.bot:
            return
        guild = member.guild
        if await get_config(guild.id, "goodbye_enabled", "false") != "true":
            return
        channel = await _text_channel(guild, "goodbye_channel_id") or await _text_channel(
            guild, "welcome_channel_id"
        )
        if channel is None:
            return
        template = await get_config(guild.id, "goodbye_message", DEFAULT_GOODBYE)
        try:
            await channel.send(render_for(template, member), allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as error:
            log.warning("Abschiedsmeldung in %s fehlgeschlagen: %s", guild.name, error)

    @welcome_group.command(name="kanal", description="Kanal fuer die Begruessung (ohne Angabe: Begruessung aus)")
    @app_commands.describe(kanal="Textkanal fuer Begruessungen - leer lassen zum Abschalten")
    @require_role(Level.ADMIN)
    async def welcome_channel(
        self, interaction: discord.Interaction, kanal: discord.TextChannel | None = None
    ) -> None:
        await set_config(interaction.guild_id, "welcome_channel_id", str(kanal.id) if kanal else "", interaction.guild.name)
        text = f"Begrüßungen gehen jetzt nach {kanal.mention}." if kanal else "Begrüßung im Kanal ist aus."
        await interaction.response.send_message(text, ephemeral=True, delete_after=20)

    @welcome_group.command(name="text", description="Text der Begruessung")
    @app_commands.describe(text="Platzhalter: {user} {name} {server} {count}, Zeilenumbruch mit \\n")
    @require_role(Level.ADMIN)
    async def welcome_text(self, interaction: discord.Interaction, text: str) -> None:
        await set_config(interaction.guild_id, "welcome_message", text, interaction.guild.name)
        preview = render_for(text, interaction.user)
        await interaction.response.send_message(
            f"Gespeichert. So sieht es aus:\n\n{preview}", ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )

    @welcome_group.command(name="dm", description="Zusaetzliche DM an neue Mitglieder (\"aus\" schaltet ab)")
    @app_commands.describe(text="Text der DM, z.B. Regeln und Link zur Seite - \"aus\" zum Abschalten")
    @require_role(Level.ADMIN)
    async def welcome_dm(self, interaction: discord.Interaction, text: str) -> None:
        off = is_off(text)
        await set_config(interaction.guild_id, "welcome_dm_message", "" if off else text, interaction.guild.name)
        if off:
            await interaction.response.send_message("Willkommens-DM ist aus.", ephemeral=True, delete_after=20)
            return
        await interaction.response.send_message(
            f"Gespeichert. So sieht die DM aus:\n\n{render_for(text, interaction.user)}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @welcome_group.command(name="abschied", description="Meldung, wenn jemand den Server verlaesst")
    @app_commands.describe(
        aktiv="Abschiedsmeldung an oder aus",
        text="Optional eigener Text, Platzhalter wie bei der Begruessung",
        kanal="Optional eigener Kanal (sonst der Begruessungs-Kanal)",
    )
    @require_role(Level.ADMIN)
    async def welcome_goodbye(
        self,
        interaction: discord.Interaction,
        aktiv: bool,
        text: str | None = None,
        kanal: discord.TextChannel | None = None,
    ) -> None:
        guild_id, guild_name = interaction.guild_id, interaction.guild.name
        await set_config(guild_id, "goodbye_enabled", "true" if aktiv else "false", guild_name)
        if text is not None:
            await set_config(guild_id, "goodbye_message", text, guild_name)
        if kanal is not None:
            await set_config(guild_id, "goodbye_channel_id", str(kanal.id), guild_name)
        await interaction.response.send_message(
            "Abschiedsmeldung ist an." if aktiv else "Abschiedsmeldung ist aus.", ephemeral=True, delete_after=20
        )

    @welcome_group.command(name="test", description="Zeigt Begruessung, DM und Abschied mit dir als Beispiel")
    @require_role(Level.ADMIN)
    async def welcome_test(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        member = interaction.user
        channel = await _text_channel(guild, "welcome_channel_id")
        welcome = await get_config(guild.id, "welcome_message", DEFAULT_WELCOME)
        dm = await get_config(guild.id, "welcome_dm_message")
        goodbye_on = await get_config(guild.id, "goodbye_enabled", "false") == "true"
        goodbye = await get_config(guild.id, "goodbye_message", DEFAULT_GOODBYE)
        goodbye_channel = await _text_channel(guild, "goodbye_channel_id") or channel

        lines = [
            f"**Begrüßung** ({channel.mention if channel else 'aus – kein Kanal'}):\n{render_for(welcome, member)}",
            f"**DM**: {'aus' if is_off(dm) else chr(10) + render_for(dm, member)}",
            f"**Abschied** ({goodbye_channel.mention if goodbye_on and goodbye_channel else 'aus'}):"
            + (f"\n{render_for(goodbye, member)}" if goodbye_on else ""),
            f"\nPlatzhalter: {PLACEHOLDERS}",
        ]
        await interaction.response.send_message(
            "\n\n".join(lines)[:2000], ephemeral=True, allowed_mentions=discord.AllowedMentions.none()
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
