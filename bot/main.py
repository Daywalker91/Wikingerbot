import asyncio
import logging
import signal
import sys
from pathlib import Path

import discord

from bot.core import runtime
from bot.core.bot import WikingerBot
from bot.core.config import settings

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("wikingerbot")


def run_migrations() -> None:
    """Bringt die Datenbank auf den neuesten Stand ("alembic upgrade head").

    Laeuft synchron VOR asyncio.run(), weil db/migrations/env.py selbst
    asyncio.run() aufruft. Pfade sind absolut, damit es unabhaengig vom
    Arbeitsverzeichnis funktioniert (z.B. in AMP)."""
    from alembic import command
    from alembic.config import Config

    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    config.set_main_option("script_location", str(ROOT / "db" / "migrations"))
    command.upgrade(config, "head")


def setup_logging() -> None:
    # force=True: alembic.ini setzt per fileConfig eigene Handler/Level, die sonst
    # alle INFO-Ausgaben des Bots verschlucken wuerden.
    # stdout statt stderr (Standard): AMP erkennt den Start an der Log-Zeile
    # "WikingerBot bereit: ..." in der Konsole - die muss sicher auf stdout landen.
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # Ruhiger Start: alembic meldet sonst bei jedem Start Plugins und Kontext -
    # nur tatsaechlich ausgefuehrte Migrationen ("Running upgrade ...") bleiben.
    logging.getLogger("alembic").setLevel(logging.WARNING)
    migration_log = logging.getLogger("alembic.runtime.migration")
    migration_log.setLevel(logging.INFO)
    migration_log.filters.clear()
    migration_log.addFilter(lambda r: r.levelno >= logging.WARNING or r.getMessage().startswith("Running "))
    # uvicorn meldet Start/Stopp ueber den Logger "uvicorn.error" - AMP faerbt das
    # rot, obwohl es keine Fehler sind. Die Port-Zeile kommt von api/server.py.
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    # "Invalid HTTP request received" (uvicorn.error) bleibt bewusst sichtbar: haeufen sich
    # die Meldungen, ist der Web-Port wahrscheinlich direkt aus dem Internet erreichbar.
    # Die Warnung "voice will NOT be supported" (PyNaCl/davey fehlen) bleibt sichtbar -
    # ohne die beiden Pakete spielt der music-Cog nichts.


async def main() -> None:
    if not settings.discord_token:
        log.error("Kein Discord-Token gesetzt (DISCORD_TOKEN) - in AMP unter Konfiguration eintragen.")
        raise SystemExit(1)
    bot = WikingerBot()
    runtime.bot = bot
    web = None
    if settings.web_enabled:
        from api.server import WebServer

        web = WebServer()
        await web.start()
    try:
        async with bot:
            try:
                await bot.start(settings.discord_token)
            except discord.LoginFailure:
                log.error("Discord hat den Token abgelehnt (DISCORD_TOKEN ungueltig oder zurueckgesetzt).")
                raise SystemExit(1)
    finally:
        if web is not None:
            await web.stop()


if __name__ == "__main__":
    setup_logging()
    if settings.auto_migrate:
        log.info("Datenbank-Migrationen werden ausgefuehrt ...")
        run_migrations()
        setup_logging()
        log.info("Datenbank ist aktuell.")
    # AMP stoppt den Bot mit Strg+C (App.ExitMethod=OS_CLOSE), Docker mit SIGTERM.
    # Beides beendet main() sauber (async with bot schliesst die Verbindung) -
    # nur der Traceback dazu wird hier unterdrueckt.
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("WikingerBot beendet.")
