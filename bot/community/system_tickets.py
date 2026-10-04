"""Tickets, die der Bot selbst eroeffnet (z.B. Rang-Konflikt beim Verknuepfen,
Discord-Bann eines verknuepften Mitglieds) - "ein Mensch entscheidet".

Bewusst ohne die Pruefungen fuer Mitglieder (Rang, Laenge, Haeufigkeit). Ist der
tickets-Cog geladen, legt er gleich den Staff-Thread an; sonst sieht der Support
das Ticket auf der Seite.
"""

import logging

from sqlalchemy import func, insert, select

from bot.community import db as community_db

log = logging.getLogger("wikingerbot.community")


async def default_owner_id() -> int | None:
    """Fallback-Ersteller fuer System-Tickets: das erste Konto mit allen Rechten (*)."""
    u = community_db.users
    rows = await community_db.query_permissions(
        lambda up: select(u.c.id)
        .select_from(u.join(up, up.c.user_id == u.c.id))
        .where(up.c.permission == "*", u.c.deleted_at.is_(None))
        .order_by(u.c.id)
        .limit(1)
    )
    return rows[0][0] if rows else None


async def open_system_ticket(bot, owner_id: int, subject: str, body: str, category: str = "konto") -> int:
    t, m = community_db.tickets, community_db.ticket_messages
    async with community_db.session() as db:
        async with db.begin():
            result = await db.execute(
                insert(t).values(
                    user_id=owner_id, subject=subject[:150], category=category, status="open", priority="normal",
                    created_at=func.now(), updated_at=func.now(),
                )
            )
            ticket_id = result.inserted_primary_key[0]
            await db.execute(insert(m).values(ticket_id=ticket_id, user_id=None, body=body, is_internal=0, created_at=func.now()))
    log.info("System-Ticket #%s: %s", ticket_id, subject)
    cog = bot.get_cog("TicketsCog") if bot else None
    if cog is not None:
        try:
            await cog.sync_ticket(ticket_id)
        except Exception as error:
            log.warning("Staff-Thread fuer Ticket #%s nicht angelegt: %s", ticket_id, error)
    return ticket_id
