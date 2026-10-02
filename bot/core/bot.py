import asyncio
import json
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.bot_settings import SYNC_ON_STARTUP_KEY, get_bot_setting, set_bot_setting
from bot.core.config import settings
from bot.core.permissions import InsufficientPermissions

COGS_PACKAGE = "bot.cogs"
COGS_PATH = Path(__file__).resolve().parent.parent / "cogs"

# Bot-Setting-Key, unter dem der Bot seine aktuell geladenen Cogs als JSON-Liste
# ablegt - der API-Prozess hat keinen Zugriff auf self.extensions (anderer
# Prozess, kein IPC), liest diese Liste stattdessen aus der DB (siehe
# bot/cogs/admin/api.py:list_cogs).
LOADED_COGS_KEY = "loaded_cogs"

log = logging.getLogger("wikingerbot")


def discover_cog_names() -> list[str]:
    """Listet alle verfuegbaren Cog-Namen (Verzeichnisse unter bot/cogs/) auf.

    Modul-Level statt Methode, damit auch der API-Prozess (kein Zugriff auf
    eine lebende WikingerBot-Instanz) dieselbe Verzeichnis-Scan-Logik nutzen
    kann (siehe bot/cogs/admin/api.py:list_cogs).
    """
    if not COGS_PATH.exists():
        return []
    return sorted(
        path.name
        for path in COGS_PATH.iterdir()
        if path.is_dir() and not path.name.startswith("_") and (path / "cog.py").exists()
    )


class WikingerBot(commands.Bot):
    """Bot-Kernklasse mit dynamischem Cog-Manager."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        self.tree.on_error = self._on_app_command_error
        for name in self.discover_cogs():
            await self.load_cog(name)
        await self._sync_loaded_cogs_to_db()

        # Default "true": eine frische Installation kennt noch keine Commands, es gibt
        # also keinen Slash-Command, um den ersten Sync manuell anzustossen - das muss
        # automatisch passieren. Bewusst abschaltbar (z.B. waehrend Entwicklung, wenn
        # zusaetzlich guild-lokal gesynct wird und der globale Auto-Sync nur doppelte
        # Commands im Picker erzeugen wuerde), spaeter auch ueber die WebUI.
        sync_on_startup = await get_bot_setting(SYNC_ON_STARTUP_KEY, default="true")
        if sync_on_startup == "true":
            await self.tree.sync()

        # Eigene AMP-Rolle einrichten/pruefen - im Hintergrund, damit ein nicht
        # erreichbares AMP den Discord-Login nicht aufhaelt.
        if settings.amp_manage_role and settings.amp_user:
            self._amp_role_task = asyncio.create_task(self._ensure_amp_role())

    async def _ensure_amp_role(self) -> None:
        from bot.core.amp_client import amp_client
        from bot.core.amp_role import ensure_bot_role, log_report

        try:
            report = await ensure_bot_role(
                amp_client.core_call, settings.amp_user, keep_super_admin=settings.amp_keep_super_admin
            )
            log_report(report, settings.amp_user)
        except Exception as error:
            first_line = str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
            log.warning("AMP-Rolle konnte nicht geprueft werden (AMP nicht erreichbar?): %s", first_line)

    async def _on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        """Ohne diesen Handler sieht der Aufrufer bei jedem Fehler - auch bei
        fehlender Berechtigung - nur "Die Interaktion ist fehlgeschlagen"."""
        if isinstance(error, InsufficientPermissions):
            message = f"Dafür fehlt dir die Berechtigung (mindestens {error.required.value})."
        elif isinstance(error, app_commands.CheckFailure):
            message = "Das geht hier nicht."
        else:
            command = interaction.command.qualified_name if interaction.command else "?"
            log.error("Fehler in /%s", command, exc_info=error)
            message = "Da ist etwas schiefgelaufen. Details stehen im Log des Bots."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True, delete_after=20)
        except discord.HTTPException:
            pass

    async def on_ready(self) -> None:
        # Feste Log-Zeile: AMP erkennt daran, dass der Bot laeuft (Console.AppReadyRegex
        # in der AMP-Vorlage). Wortlaut nur zusammen mit der Vorlage aendern!
        log.info("WikingerBot bereit: angemeldet als %s (ID %s) auf %d Server(n)", self.user, self.user.id, len(self.guilds))

    def discover_cogs(self) -> list[str]:
        return discover_cog_names()

    async def load_cog(self, name: str) -> None:
        await self.load_extension(f"{COGS_PACKAGE}.{name}.cog")
        await self._sync_loaded_cogs_to_db()

    async def unload_cog(self, name: str) -> None:
        await self.unload_extension(f"{COGS_PACKAGE}.{name}.cog")
        await self._sync_loaded_cogs_to_db()

    async def reload_cog(self, name: str) -> None:
        await self.reload_extension(f"{COGS_PACKAGE}.{name}.cog")
        await self._sync_loaded_cogs_to_db()

    def loaded_cogs(self) -> list[str]:
        prefix = f"{COGS_PACKAGE}."
        suffix = ".cog"
        return sorted(
            ext[len(prefix) : -len(suffix)]
            for ext in self.extensions
            if ext.startswith(prefix) and ext.endswith(suffix)
        )

    async def _sync_loaded_cogs_to_db(self) -> None:
        await set_bot_setting(LOADED_COGS_KEY, json.dumps(self.loaded_cogs()))
