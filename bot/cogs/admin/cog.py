import discord
from discord import app_commands
from discord.ext import commands

from bot.core.base_cog import BaseCog
from bot.core.permissions import Level, require_role

bot_group = app_commands.Group(name="bot", description="Bot-Verwaltung")
cog_group = app_commands.Group(
    name="cog", description="Cog laden/entladen/neuladen/auflisten", parent=bot_group
)


class AdminCog(BaseCog):
    """Verwaltet das Laden/Entladen anderer Cogs zur Laufzeit."""

    __cog_name__ = "admin"
    __version__ = "1.0.0"
    __description__ = "Cog-Verwaltung ueber Discord-Commands"
    __author__ = "Daywalker91"

    async def cog_load(self) -> None:
        self.bot.tree.add_command(bot_group)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(bot_group.name)

    @cog_group.command(name="load", description="Laedt ein Cog")
    @app_commands.describe(name="Name des Cog-Verzeichnisses (z.B. moderation)")
    @require_role(Level.OWNER)
    async def cog_load_cmd(self, interaction: discord.Interaction, name: str) -> None:
        await self.bot.load_cog(name)
        await interaction.response.send_message(f"Cog `{name}` geladen.", ephemeral=True)

    @cog_group.command(name="unload", description="Entlaedt ein Cog")
    @app_commands.describe(name="Name des Cog-Verzeichnisses (z.B. moderation)")
    @require_role(Level.OWNER)
    async def cog_unload_cmd(self, interaction: discord.Interaction, name: str) -> None:
        await self.bot.unload_cog(name)
        await interaction.response.send_message(f"Cog `{name}` entladen.", ephemeral=True)

    @cog_group.command(name="reload", description="Laedt ein Cog neu")
    @app_commands.describe(name="Name des Cog-Verzeichnisses (z.B. moderation)")
    @require_role(Level.OWNER)
    async def cog_reload_cmd(self, interaction: discord.Interaction, name: str) -> None:
        await self.bot.reload_cog(name)
        await interaction.response.send_message(f"Cog `{name}` neu geladen.", ephemeral=True)

    @cog_group.command(name="list", description="Listet geladene und verfuegbare Cogs")
    @require_role(Level.OWNER)
    async def cog_list_cmd(self, interaction: discord.Interaction) -> None:
        loaded = set(self.bot.loaded_cogs())
        available = self.bot.discover_cogs()
        if not available:
            await interaction.response.send_message("Keine Cogs gefunden.", ephemeral=True)
            return
        lines = [f"{'🟢' if name in loaded else '⚪'} {name}" for name in available]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
