import asyncio
import logging
from pathlib import Path

import discord

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
    config.set_main_option("script_location", str(ROOT / "db" / "migrations"))
    command.upgrade(config, "head")


def setup_logging() -> None:
    # force=True: alembic.ini setzt per fileConfig eigene Handler/Level, die sonst
    # alle INFO-Ausgaben des Bots verschlucken wuerden.
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


async def main() -> None:
    if not settings.discord_token:
        log.error("Kein Discord-Token gesetzt (DISCORD_TOKEN) - in AMP unter Konfiguration eintragen.")
        raise SystemExit(1)
    bot = WikingerBot()
    async with bot:
        try:
            await bot.start(settings.discord_token)
        except discord.LoginFailure:
            log.error("Discord hat den Token abgelehnt (DISCORD_TOKEN ungueltig oder zurueckgesetzt).")
            raise SystemExit(1)


if __name__ == "__main__":
    setup_logging()
    if settings.auto_migrate:
        log.info("Datenbank-Migrationen werden ausgefuehrt ...")
        run_migrations()
        setup_logging()
        log.info("Datenbank ist aktuell.")
    asyncio.run(main())
