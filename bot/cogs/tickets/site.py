"""Tickets auf der Community-Seite lesen und schreiben - mit denselben Regeln
wie die Seite (src/tickets.php, pages/tickets/view.php):

- Antwortet der Support (nicht der Ersteller, keine interne Notiz), wartet das
  Ticket auf das Mitglied ("waiting"); wer zuerst antwortet, uebernimmt es.
- Antwortet das Mitglied auf ein wartendes Ticket, ist es wieder offen.
- Geschlossene Tickets kann nur der Support beantworten.
- Statuswechsel landen als Systemmeldung (user_id NULL) im Verlauf.

Support = Rang mit dem Recht ticket.manage (oder *), wie auf der Seite.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, insert, select, update

from bot.community import db as community_db

CATEGORIES = {
    "allgemein": "Allgemeine Frage",
    "technik": "Technisches Problem",
    "server": "Gameserver",
    "melden": "Spieler melden",
    "konto": "Konto & Rollen",
    "sonstiges": "Sonstiges",
    "rollenanfrage": "Rollenanfrage",
}
SYSTEM_CATEGORIES = {"rollenanfrage"}  # legt nur die Seite an (Rolle beantragen) - nicht per /ticket waehlbar
STATUSES = {
    "open": ("⚪", "Offen"),
    "in_progress": ("🔨", "In Bearbeitung"),
    "waiting": ("⏳", "Wartet auf Antwort"),
    "closed": ("✅", "Geschlossen"),
}
PRIORITIES = {"low": "Niedrig", "normal": "Normal", "high": "Hoch"}
BODY_MAX = 10000


class TicketError(Exception):
    """Meldung, die so an den Discord-Nutzer gehen kann."""


@dataclass
class Ticket:
    id: int
    user_id: int
    author: str
    author_discord_id: int | None
    subject: str
    category: str
    status: str
    priority: str
    assigned_to: int | None
    assigned_name: str | None
    created_at: datetime | None


@dataclass
class TicketMessage:
    id: int
    ticket_id: int
    user_id: int | None
    author: str | None
    body: str
    internal: bool


async def has_permission(site_user_id: int, permission: str) -> bool:
    """Rang oder Zusatzrolle (z.B. Support) hat das Recht."""
    return await community_db.has_permission(site_user_id, permission)


async def is_staff(site_user_id: int) -> bool:
    return await has_permission(site_user_id, "ticket.manage")


async def fetch_ticket(ticket_id: int) -> Ticket | None:
    t, u = community_db.tickets, community_db.users
    a = u.alias("assignee")
    async with community_db.session() as db:
        row = (
            await db.execute(
                select(
                    t.c.id, t.c.user_id, u.c.username, u.c.discord_id, t.c.subject, t.c.category, t.c.status,
                    t.c.priority, t.c.assigned_to, a.c.username, t.c.created_at,
                )
                .select_from(t.join(u, u.c.id == t.c.user_id).outerjoin(a, a.c.id == t.c.assigned_to))
                .where(t.c.id == ticket_id)
            )
        ).first()
    return Ticket(*row) if row else None


async def messages_after(ticket_id: int, after_id: int) -> list[TicketMessage]:
    m, u = community_db.ticket_messages, community_db.users
    async with community_db.session() as db:
        rows = (
            await db.execute(
                select(m.c.id, m.c.ticket_id, m.c.user_id, u.c.username, m.c.body, m.c.is_internal)
                .select_from(m.outerjoin(u, u.c.id == m.c.user_id))
                .where(m.c.ticket_id == ticket_id, m.c.id > after_id)
                .order_by(m.c.id)
            )
        ).all()
    return [TicketMessage(r[0], r[1], r[2], r[3], r[4] or "", bool(r[5])) for r in rows]


async def open_tickets(limit: int = 30) -> list[Ticket]:
    t = community_db.tickets
    async with community_db.session() as db:
        ids = (
            await db.execute(select(t.c.id).where(t.c.status != "closed").order_by(t.c.updated_at.desc()).limit(limit))
        ).scalars().all()
    return [ticket for ticket in [await fetch_ticket(i) for i in ids] if ticket]


async def _log(db, ticket_id: int, text: str) -> int:
    result = await db.execute(
        insert(community_db.ticket_messages).values(ticket_id=ticket_id, user_id=None, body=text, is_internal=0, created_at=func.now())
    )
    return result.inserted_primary_key[0]


async def create_ticket(site_user_id: int, subject: str, category: str, body: str) -> int:
    subject, body = subject.strip(), body.strip()
    if not 5 <= len(subject) <= 150:
        raise TicketError("Der Betreff muss 5–150 Zeichen lang sein.")
    if category not in CATEGORIES or category in SYSTEM_CATEGORIES:
        raise TicketError("Unbekannte Kategorie.")
    if len(body) < 10:
        raise TicketError("Beschreib dein Anliegen bitte etwas genauer (mindestens 10 Zeichen).")
    if len(body) > BODY_MAX:
        raise TicketError("Deine Nachricht ist zu lang.")
    if not await has_permission(site_user_id, "ticket.create"):
        raise TicketError("Dein Rang darf keine Tickets erstellen.")
    t, m = community_db.tickets, community_db.ticket_messages
    async with community_db.session() as db:
        async with db.begin():
            result = await db.execute(
                insert(t).values(
                    user_id=site_user_id, subject=subject, category=category, status="open", priority="normal",
                    created_at=func.now(), updated_at=func.now(),
                )
            )
            ticket_id = result.inserted_primary_key[0]
            await db.execute(insert(m).values(ticket_id=ticket_id, user_id=site_user_id, body=body, is_internal=0, created_at=func.now()))
    return ticket_id


async def add_reply(ticket_id: int, site_user_id: int, body: str, internal: bool = False) -> int:
    """Antwort mit den Status-Regeln der Seite. Gibt die ID der neuen Nachricht zurueck."""
    body = body.strip()
    if len(body) < 2:
        raise TicketError("Die Nachricht ist zu kurz.")
    if len(body) > BODY_MAX:
        raise TicketError("Die Nachricht ist zu lang.")
    ticket = await fetch_ticket(ticket_id)
    if ticket is None:
        raise TicketError("Dieses Ticket gibt es nicht mehr.")
    staff = await is_staff(site_user_id)
    owner = ticket.user_id == site_user_id
    if not staff and not owner:
        raise TicketError("Dieses Ticket gehört dir nicht.")
    if internal and not staff:
        raise TicketError("Interne Notizen kann nur der Support schreiben.")
    if ticket.status == "closed" and not staff:
        raise TicketError("Das Ticket ist geschlossen. Öffne es auf der Seite wieder, um zu antworten.")

    status = ticket.status
    assigned = ticket.assigned_to
    if not internal:
        if staff and not owner:
            status = "closed" if status == "closed" else "waiting"
            assigned = assigned or site_user_id
        elif status == "waiting":
            status = "open"
    t, m = community_db.tickets, community_db.ticket_messages
    async with community_db.session() as db:
        async with db.begin():
            result = await db.execute(
                insert(m).values(ticket_id=ticket_id, user_id=site_user_id, body=body, is_internal=int(internal), created_at=func.now())
            )
            await db.execute(update(t).where(t.c.id == ticket_id).values(status=status, assigned_to=assigned, updated_at=func.now()))
    return result.inserted_primary_key[0]


async def change_status(ticket_id: int, site_user_id: int, username: str, action: str) -> None:
    """Knoepfe im Staff-Thread: claim (uebernehmen), close, reopen."""
    ticket = await fetch_ticket(ticket_id)
    if ticket is None:
        raise TicketError("Dieses Ticket gibt es nicht mehr.")
    staff = await is_staff(site_user_id)
    if not staff and not (action in ("close", "reopen") and ticket.user_id == site_user_id):
        raise TicketError("Das darf nur der Support.")
    t = community_db.tickets
    values, text = {"updated_at": func.now()}, None
    if action == "claim":
        if ticket.assigned_to == site_user_id:
            raise TicketError("Das Ticket ist schon deins.")
        values.update(assigned_to=site_user_id, status="in_progress" if ticket.status == "open" else ticket.status)
        text = f"{username}: zugewiesen an {username}"
    elif action == "close":
        if ticket.status == "closed":
            raise TicketError("Das Ticket ist schon geschlossen.")
        values.update(status="closed", closed_at=func.now())
        text = f"{username} hat das Ticket geschlossen."
    elif action == "reopen":
        if ticket.status != "closed":
            raise TicketError("Das Ticket ist nicht geschlossen.")
        values.update(status="open", closed_at=None)
        text = f"{username} hat das Ticket wieder geöffnet."
    else:
        raise ValueError(action)
    async with community_db.session() as db:
        async with db.begin():
            await db.execute(update(t).where(t.c.id == ticket_id).values(**values))
            await _log(db, ticket_id, text)
