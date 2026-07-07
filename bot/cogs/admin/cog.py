import discord
from discord import app_commands
from discord.ext import commands

from bot.core.base_cog import BaseCog
from bot.core.permissions import Level, require_role


class AdminCog(BaseCog):
    """Verwaltet das Laden/Entladen anderer Cogs zur Laufzeit."""

    __cog_name__ = "admin"
    __version__ = "1.0.0"
    __description__ = "Cog-Verwaltung ueber Discord-Commands"
    __author__ = "Daywalker91"

    # Als Klassen-Attribute (nicht Modul-Level!), damit discord.py sie beim
    # Hinzufuegen des Cogs automatisch an die Instanz bindet (siehe Cog._inject).
    management_group = app_commands.Group(name="bot", description="Bot-Verwaltung")
    cogs_subgroup = app_commands.Group(
        name="cog", description="Cog laden/entladen/neuladen/auflisten", parent=management_group
    )

    @cogs_subgroup.command(name="load", description="Laedt ein Cog")
    @app_commands.describe(name="Name des Cog-Verzeichnisses (z.B. moderation)")
    @require_role(Level.OWNER)
    async def cog_load_cmd(self, interaction: discord.Interaction, name: str) -> None:
        await self.bot.load_cog(name)
        await interaction.response.send_message(
            f"Cog `{name}` geladen.", ephemeral=True, delete_after=20
        )

    @cogs_subgroup.command(name="unload", description="Entlaedt ein Cog")
    @app_commands.describe(name="Name des Cog-Verzeichnisses (z.B. moderation)")
    @require_role(Level.OWNER)
    async def cog_unload_cmd(self, interaction: discord.Interaction, name: str) -> None:
        await self.bot.unload_cog(name)
        await interaction.response.send_message(
            f"Cog `{name}` entladen.", ephemeral=True, delete_after=20
        )

    @cogs_subgroup.command(name="reload", description="Laedt ein Cog neu")
    @app_commands.describe(name="Name des Cog-Verzeichnisses (z.B. moderation)")
    @require_role(Level.OWNER)
    async def cog_reload_cmd(self, interaction: discord.Interaction, name: str) -> None:
        await self.bot.reload_cog(name)
        await interaction.response.send_message(
            f"Cog `{name}` neu geladen.", ephemeral=True, delete_after=20
        )

    @cogs_subgroup.command(name="list", description="Listet geladene und verfuegbare Cogs")
    @require_role(Level.OWNER)
    async def cog_list_cmd(self, interaction: discord.Interaction) -> None:
        loaded = set(self.bot.loaded_cogs())
        available = self.bot.discover_cogs()
        if not available:
            await interaction.response.send_message("Keine Cogs gefunden.", ephemeral=True)
            return
        lines = [f"{'🟢' if name in loaded else '⚪'} {name}" for name in available]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @management_group.command(name="sync", description="Synct die Slash-Commands (lokal oder global)")
    @app_commands.describe(
        local="True = nur dieser Server (sofort sichtbar), False = global (bis zu 1h Verzoegerung)",
        reset="Vorher alle Commands loeschen, bevor neu gesynct wird",
    )
    @require_role(Level.OWNER)
    async def sync_cmd(
        self, interaction: discord.Interaction, local: bool = True, reset: bool = False
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild if local else None
        scope = "lokal" if local else "global"

        if reset:
            self.bot.tree.clear_commands(guild=guild)
            synced = await self.bot.tree.sync(guild=guild)
            await interaction.followup.send(
                f"Commands zurueckgesetzt und {scope} neu gesynct ({len(synced)})."
            )
            return

        if local:
            self.bot.tree.copy_global_to(guild=guild)
        synced = await self.bot.tree.sync(guild=guild)
        await interaction.followup.send(f"{len(synced)} Commands {scope} gesynct.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
