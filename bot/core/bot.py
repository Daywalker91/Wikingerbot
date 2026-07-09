from pathlib import Path

import discord
from discord.ext import commands

from bot.core.bot_settings import SYNC_ON_STARTUP_KEY, get_bot_setting

COGS_PACKAGE = "bot.cogs"
COGS_PATH = Path(__file__).resolve().parent.parent / "cogs"


class WikingerBot(commands.Bot):
    """Bot-Kernklasse mit dynamischem Cog-Manager."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        for name in self.discover_cogs():
            await self.load_cog(name)

        # Default "true": eine frische Installation kennt noch keine Commands, es gibt
        # also keinen Slash-Command, um den ersten Sync manuell anzustossen - das muss
        # automatisch passieren. Bewusst abschaltbar (z.B. waehrend Entwicklung, wenn
        # zusaetzlich guild-lokal gesynct wird und der globale Auto-Sync nur doppelte
        # Commands im Picker erzeugen wuerde), spaeter auch ueber die WebUI.
        sync_on_startup = await get_bot_setting(SYNC_ON_STARTUP_KEY, default="true")
        if sync_on_startup == "true":
            await self.tree.sync()

    def discover_cogs(self) -> list[str]:
        """Listet alle verfuegbaren Cog-Namen (Verzeichnisse unter bot/cogs/) auf."""
        if not COGS_PATH.exists():
            return []
        return sorted(
            path.name
            for path in COGS_PATH.iterdir()
            if path.is_dir() and not path.name.startswith("_") and (path / "cog.py").exists()
        )

    async def load_cog(self, name: str) -> None:
        await self.load_extension(f"{COGS_PACKAGE}.{name}.cog")

    async def unload_cog(self, name: str) -> None:
        await self.unload_extension(f"{COGS_PACKAGE}.{name}.cog")

    async def reload_cog(self, name: str) -> None:
        await self.reload_extension(f"{COGS_PACKAGE}.{name}.cog")

    def loaded_cogs(self) -> list[str]:
        prefix = f"{COGS_PACKAGE}."
        suffix = ".cog"
        return sorted(
            ext[len(prefix) : -len(suffix)]
            for ext in self.extensions
            if ext.startswith(prefix) and ext.endswith(suffix)
        )
