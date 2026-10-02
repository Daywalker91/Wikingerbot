"""Verweis auf den laufenden Bot fuer die API, wenn beide im selben Prozess laufen
(bot/main.py mit Web-Oberflaeche). Laeuft die API getrennt (lokale Entwicklung),
bleibt er None - die Aufrufer muessen damit umgehen."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.core.bot import WikingerBot

bot: "WikingerBot | None" = None
