from discord.ext import commands

from bot.core.config import settings


class BaseCog(commands.Cog):
    """Basis-Klasse fuer alle WikingerBot Cogs."""

    __cog_name__: str
    __version__: str
    __description__: str
    __author__: str

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config = settings

    async def cog_load(self) -> None:
        """Wird beim Laden des Cogs aufgerufen."""

    async def cog_unload(self) -> None:
        """Wird beim Entladen des Cogs aufgerufen."""
