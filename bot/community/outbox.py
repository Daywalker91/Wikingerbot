"""Auftraege der Community-Seite (Tabelle bot_outbox) abholen und verteilen.

Jeder Community-Cog meldet beim Laden an, welche Auftragsarten er erledigt
(register), und beim Entladen wieder ab. Abgeholt werden nur Arten, fuer die
gerade jemand zustaendig ist - ist z.B. der tickets-Cog entladen, bleiben dessen
Auftraege liegen statt verloren zu gehen, und blockieren die anderen nicht.

Die Nutzlast enthaelt nur IDs; den aktuellen Stand liest der Handler selbst nach.
Schlaegt ein Handler fehl, wird es spaeter erneut versucht (hoechstens MAX_ATTEMPTS-mal,
der Fehler steht dann in last_error).
"""

import json
import logging
from typing import Awaitable, Callable

from sqlalchemy import func, select, update

from bot.community.db import bot_outbox, session

log = logging.getLogger("wikingerbot.community")

MAX_ATTEMPTS = 5
BATCH = 50

Handler = Callable[[dict], Awaitable[None]]
_handlers: dict[str, Handler] = {}


def register(kind: str, handler: Handler) -> None:
    _handlers[kind] = handler


def unregister(kind: str) -> None:
    _handlers.pop(kind, None)


def registered() -> list[str]:
    return sorted(_handlers)


async def process_pending() -> int:
    """Erledigt offene Auftraege der angemeldeten Arten. Gibt die Zahl erledigter zurueck."""
    if not _handlers:
        return 0
    async with session() as db:
        rows = (
            await db.execute(
                select(bot_outbox.c.id, bot_outbox.c.type, bot_outbox.c.payload)
                .where(
                    bot_outbox.c.processed_at.is_(None),
                    bot_outbox.c.attempts < MAX_ATTEMPTS,
                    bot_outbox.c.type.in_(list(_handlers)),
                )
                .order_by(bot_outbox.c.id)
                .limit(BATCH)
            )
        ).all()

    done = 0
    for row_id, kind, payload in rows:
        handler = _handlers.get(kind)
        if handler is None:  # zwischendurch entladen
            continue
        try:
            await handler(json.loads(payload or "{}"))
        except Exception as error:
            log.warning("Auftrag %s (%s) fehlgeschlagen: %s", row_id, kind, error)
            async with session() as db:
                await db.execute(
                    update(bot_outbox)
                    .where(bot_outbox.c.id == row_id)
                    .values(attempts=bot_outbox.c.attempts + 1, last_error=str(error)[:500])
                )
                await db.commit()
            continue
        async with session() as db:
            await db.execute(
                update(bot_outbox).where(bot_outbox.c.id == row_id).values(processed_at=func.now(), last_error=None)
            )
            await db.commit()
        done += 1
    return done


async def counts() -> dict[str, int]:
    """Fuer /community status: offen, endgueltig fehlgeschlagen."""
    async with session() as db:
        pending = (
            await db.execute(
                select(func.count()).where(bot_outbox.c.processed_at.is_(None), bot_outbox.c.attempts < MAX_ATTEMPTS)
            )
        ).scalar_one()
        failed = (
            await db.execute(
                select(func.count()).where(bot_outbox.c.processed_at.is_(None), bot_outbox.c.attempts >= MAX_ATTEMPTS)
            )
        ).scalar_one()
    return {"pending": int(pending), "failed": int(failed)}
