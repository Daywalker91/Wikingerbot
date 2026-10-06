"""Rollenanfragen der Community-Seite (Tabelle role_requests): laden, pruefen, entscheiden.

Die Seite legt Anfrage und Ticket an (Einstellungen -> Rolle beantragen). Entschieden
wird hier, ueber die Knoepfe des Bots:

- Zusatzrolle: der Koenig - oder wer ab Mod ist und die Rolle selbst hat, aber nur fuer
  Mitglieder bis zum eigenen Rang (der Rang bestimmt z.B. die AMP-Rolle eines Schmieds).
- Rang: der Koenig - oder wer ab Mod ist und ueber dem beantragten Rang steht.
- Nie die eigene Anfrage.

"Koenig" = Bot-Stufe Owner (bzw. Discord-Administrator) oder auf der Seite alle Rechte.
Genehmigt vergibt der Bot die Rolle auf der Seite; Rang-Sync und AMP-Konten ziehen nach.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import aliased

from bot.community import db as community_db
from db.models.role import Level, level_at_least

PENDING, APPROVED, DENIED, CANCELLED = "pending", "approved", "denied", "cancelled"  # cancelled: Ticket vom Mitglied geschlossen


@dataclass
class RoleRequest:
    id: int
    user_id: int
    username: str
    discord_id: int | None
    role_id: int
    role_name: str
    role_kind: str  # rank | extra
    role_level: int
    requester_rank_level: int
    requester_rank_name: str
    ticket_id: int | None
    reason: str
    status: str
    decided_by: int | None
    decided_name: str | None
    decision_note: str | None
    created_at: datetime | None


@dataclass
class Approver:
    site_user_id: int
    username: str
    rank_level: int
    extra_role_ids: set[int]
    site_king: bool  # auf der Seite alle Rechte ("*")
    bot_level: Level
    discord_admin: bool = False

    @property
    def is_king(self) -> bool:
        return self.site_king or self.discord_admin or level_at_least(self.bot_level, Level.OWNER)


def _query():
    q, u, r = community_db.role_requests, community_db.users, community_db.roles
    rank = aliased(r)
    decider = aliased(u)
    return (
        select(
            q.c.id, q.c.user_id, u.c.username, u.c.discord_id, q.c.role_id, r.c.name, r.c.kind, r.c.level,
            rank.c.level, rank.c.name, q.c.ticket_id, q.c.reason, q.c.status, q.c.decided_by, decider.c.username,
            q.c.decision_note, q.c.created_at,
        )
        .select_from(
            q.join(u, u.c.id == q.c.user_id)
            .join(r, r.c.id == q.c.role_id)
            .join(rank, rank.c.id == u.c.role_id)
            .outerjoin(decider, decider.c.id == q.c.decided_by)
        )
    )


def _to_request(row) -> RoleRequest:
    return RoleRequest(
        id=row[0], user_id=row[1], username=row[2], discord_id=row[3], role_id=row[4], role_name=row[5],
        role_kind=row[6] or "rank", role_level=int(row[7] or 0), requester_rank_level=int(row[8] or 0),
        requester_rank_name=row[9] or "", ticket_id=row[10], reason=row[11] or "", status=row[12],
        decided_by=row[13], decided_name=row[14], decision_note=row[15], created_at=row[16],
    )


async def load(request_id: int) -> RoleRequest | None:
    async with community_db.session() as db:
        row = (await db.execute(_query().where(community_db.role_requests.c.id == request_id))).first()
    return _to_request(row) if row else None


async def recent(limit: int = 50) -> list[RoleRequest]:
    async with community_db.session() as db:
        rows = (await db.execute(_query().order_by(community_db.role_requests.c.id.desc()).limit(limit))).all()
    return [_to_request(r) for r in rows]


# --- Anfrage aus Discord stellen (Panel-Knopf, /amp) -------------------------------------
# Gleiche Regeln wie das Formular der Seite (src/role_requests.php der Community-Seite):
# nur Zusatzrollen, die man noch nicht hat; nicht unter dem Standardrang; je Rolle eine
# offene Anfrage, eine pro Tag, vier pro Woche, nach Ablehnung sieben Tage Pause.
PER_DAY, PER_WEEK, DENIED_COOLDOWN_DAYS = 1, 4, 7


async def site_extra_for_role(guild_id: int, discord_role_id: int):
    """Zusatzrolle der Seite, die im Rang-Sync mit dieser Discord-Rolle verknuepft ist - oder None."""
    if not community_db.enabled():
        return None
    from bot.cogs.rangsync.sync import load_extra_mapping

    try:
        extras = await load_extra_mapping(guild_id)
    except Exception:  # Seite gerade nicht erreichbar / ohne Zusatzrollen
        return None
    return next((e for e in extras if e.role_id == discord_role_id), None)


async def create_site_request(site_user_id: int, role_id: int, reason: str = "") -> tuple[int | None, str]:
    """Legt Rollenanfrage + Ticket auf der Seite an. (Anfrage-ID oder None, Text fuer das Mitglied)."""
    q, r, u, x = community_db.role_requests, community_db.roles, community_db.users, community_db.user_extra_roles
    t, m = community_db.tickets, community_db.ticket_messages
    async with community_db.session() as db:
        role = (await db.execute(select(r.c.id, r.c.name, r.c.kind).where(r.c.id == role_id))).first()
        if role is None or role.kind != "extra":
            return None, "Diese Rolle kann man nicht beantragen."
        member = (
            await db.execute(
                select(u.c.id, u.c.is_banned, r.c.level).select_from(u.join(r, r.c.id == u.c.role_id)).where(u.c.id == site_user_id)
            )
        ).first()
        default_level = (
            await db.execute(select(r.c.level).where(r.c.kind == "rank", r.c.is_default == 1).order_by(r.c.level).limit(1))
        ).scalar_one_or_none()
        if member is None or member.is_banned:
            return None, "Dein Konto auf der Seite ist gesperrt."
        if default_level is not None and int(member.level or 0) < int(default_level):
            return None, "Mit deinem jetzigen Rang kannst du keine Rollen beantragen."
        if (await db.execute(select(x.c.role_id).where(x.c.user_id == site_user_id, x.c.role_id == role_id))).first():
            return None, f"Du hast **{role.name}** schon."
        mine = q.c.user_id == site_user_id
        now = func.now()
        db_now = _as_datetime((await db.execute(select(func.now()))).scalar_one())  # Uhr der Seiten-DB
        if (await db.execute(select(q.c.id).where(mine, q.c.role_id == role_id, q.c.status == PENDING).limit(1))).first():
            return None, f"Für **{role.name}** läuft schon eine Anfrage – das Team entscheidet."
        recent_denial = (
            await db.execute(
                select(q.c.id).where(
                    mine, q.c.role_id == role_id, q.c.status == DENIED,
                    q.c.decided_at > db_now - timedelta(days=DENIED_COOLDOWN_DAYS),
                ).limit(1)
            )
        ).first()
        if recent_denial:
            return None, f"**{role.name}** wurde vor Kurzem abgelehnt – eine neue Anfrage geht erst nach {DENIED_COOLDOWN_DAYS} Tagen."
        day = (await db.execute(select(func.count()).where(mine, q.c.created_at > db_now - timedelta(days=1)))).scalar_one()
        if day >= PER_DAY:
            return None, "Du kannst eine Rollenanfrage pro Tag stellen – versuch es morgen wieder."
        week = (await db.execute(select(func.count()).where(mine, q.c.created_at > db_now - timedelta(days=7)))).scalar_one()
        if week >= PER_WEEK:
            return None, f"Du hast diese Woche schon {PER_WEEK} Rollenanfragen gestellt – bitte warte ein paar Tage."

        body = f"Ich beantrage Zusatzrolle **{role.name}**.\n\n" + (f"Begründung: {reason}" if reason else "Ohne Begründung (aus Discord beantragt).")
        ticket = await db.execute(
            insert(t).values(
                user_id=site_user_id, subject=f"Rollenanfrage: {role.name}"[:150], category="rollenanfrage",
                status="open", priority="normal", created_at=now, updated_at=now,
            )
        )
        ticket_id = ticket.inserted_primary_key[0]
        await db.execute(insert(m).values(ticket_id=ticket_id, user_id=site_user_id, body=body, is_internal=0, created_at=now))
        created = await db.execute(
            insert(q).values(user_id=site_user_id, role_id=role_id, ticket_id=ticket_id, reason=reason[:1000], status=PENDING, created_at=now)
        )
        await db.commit()  # Ticket, Nachricht und Anfrage gemeinsam
    return created.inserted_primary_key[0], f"Anfrage für **{role.name}** gestellt – das Team entscheidet, du bekommst Bescheid per DM."


def _as_datetime(value) -> datetime:
    """NOW() der Datenbank - MariaDB liefert datetime, SQLite (Tests) einen Text."""
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


async def approver_for(site_user_id: int, username: str, bot_level: Level, discord_admin: bool = False) -> Approver:
    u, r, x = community_db.users, community_db.roles, community_db.user_extra_roles
    async with community_db.session() as db:
        rank_level = (
            await db.execute(select(r.c.level).select_from(u.join(r, r.c.id == u.c.role_id)).where(u.c.id == site_user_id))
        ).scalar_one_or_none()
        extras = {row[0] for row in (await db.execute(select(x.c.role_id).where(x.c.user_id == site_user_id))).all()}
    site_king = await community_db.has_permission(site_user_id, "*")
    return Approver(site_user_id, username, int(rank_level or 0), extras, site_king, bot_level, discord_admin)


def decision_error(request: RoleRequest, approver: Approver) -> str | None:
    """Warum dieser Mensch ueber diese Anfrage nicht entscheiden darf - oder None."""
    if request.status != PENDING:
        return "Über diese Anfrage ist schon entschieden."
    if approver.site_user_id == request.user_id:
        return "Über deine eigene Anfrage entscheidet jemand anderes."
    if approver.is_king:
        return None
    if not level_at_least(approver.bot_level, Level.MOD):
        return "Entscheiden dürfen nur der König und das Team ab Mod."
    if request.role_kind == "extra":
        if request.role_id not in approver.extra_role_ids:
            return f"Über „{request.role_name}“ entscheidet, wer die Rolle selbst hat – oder der König."
        if approver.rank_level < request.requester_rank_level:
            return f"{request.username} hat einen höheren Rang als du – darüber entscheidet jemand mit mindestens diesem Rang."
        return None
    if approver.rank_level <= request.role_level:
        return f"Den Rang „{request.role_name}“ vergibt nur, wer darüber steht – oder der König."
    return None


async def decide(request: RoleRequest, approver: Approver, approve: bool, note: str = "") -> bool:
    """Traegt die Entscheidung ein, vergibt bei Zustimmung die Rolle und schliesst das Ticket.
    False, wenn inzwischen schon jemand anderes entschieden hat."""
    q, u, x = community_db.role_requests, community_db.users, community_db.user_extra_roles
    t, m = community_db.tickets, community_db.ticket_messages
    note = note.strip()[:255]
    if approve:
        reply = f"✅ Zugestimmt – du hast jetzt {'die Zusatzrolle' if request.role_kind == 'extra' else 'den Rang'} **{request.role_name}**."
    else:
        reply = f"❌ Deine Anfrage für **{request.role_name}** wurde abgelehnt." + (f"\n\nGrund: {note}" if note else "")
    async with community_db.session() as db:
        async with db.begin():
            result = await db.execute(
                update(q)
                .where(q.c.id == request.id, q.c.status == PENDING)
                .values(
                    status=APPROVED if approve else DENIED, decided_by=approver.site_user_id,
                    decision_note=note or None, decided_at=func.now(),
                )
            )
            if result.rowcount != 1:
                return False
            if approve and request.role_kind == "extra":
                held = (
                    await db.execute(select(x.c.role_id).where(x.c.user_id == request.user_id, x.c.role_id == request.role_id))
                ).first()
                if held is None:
                    await db.execute(
                        insert(x).values(user_id=request.user_id, role_id=request.role_id, assigned_by=approver.site_user_id)
                    )
            elif approve:
                # nur befoerdern - wer inzwischen schon gleich hoch oder hoeher steht, bleibt
                r = community_db.roles
                current = (
                    await db.execute(select(r.c.level).select_from(u.join(r, r.c.id == u.c.role_id)).where(u.c.id == request.user_id))
                ).scalar_one_or_none()
                if current is None or int(current) < request.role_level:
                    await db.execute(update(u).where(u.c.id == request.user_id).values(role_id=request.role_id))
            if request.ticket_id:
                await db.execute(
                    insert(m).values(
                        ticket_id=request.ticket_id, user_id=approver.site_user_id, body=reply, is_internal=0, created_at=func.now()
                    )
                )
                await db.execute(
                    insert(m).values(
                        ticket_id=request.ticket_id, user_id=None, is_internal=0, created_at=func.now(),
                        body=f"{approver.username} hat das Ticket geschlossen.",
                    )
                )
                await db.execute(
                    update(t).where(t.c.id == request.ticket_id).values(status="closed", closed_at=func.now(), updated_at=func.now())
                )
    return True
