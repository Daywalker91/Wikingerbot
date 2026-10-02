"""Verknuepfung Discord-Konto <-> Konto auf der Community-Seite.

Das Mitglied erzeugt auf der Seite (Einstellungen -> Discord) einen Code, der
15 Minuten gilt, und gibt in Discord /verknuepfen CODE ein.
"""

from dataclasses import dataclass

from sqlalchemy import delete, func, select, update

from bot.community.db import discord_link_codes, roles, session, users

CODE_ALPHABET = set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


class LinkError(Exception):
    """Meldung, die so an das Mitglied gehen kann."""


@dataclass
class SiteUser:
    id: int
    username: str
    role_name: str
    role_slug: str
    discord_id: int | None


def normalize_code(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


def _user_query():
    return select(
        users.c.id, users.c.username, users.c.discord_id, roles.c.name, roles.c.slug
    ).select_from(users.join(roles, roles.c.id == users.c.role_id))


def _to_user(row) -> SiteUser:
    return SiteUser(id=row[0], username=row[1], discord_id=row[2], role_name=row[3], role_slug=row[4])


async def user_for_discord(discord_id: int, *, include_banned: bool = False) -> SiteUser | None:
    """Verknuepftes Konto. Auf der Seite gesperrte Konten zaehlen fuer Aktionen
    (Tickets, Zusagen, ...) als nicht verknuepft - nur Anzeigen (include_banned)."""
    query = _user_query().where(users.c.discord_id == discord_id, users.c.deleted_at.is_(None))
    if not include_banned:
        query = query.where(users.c.is_banned == 0)
    async with session() as db:
        row = (await db.execute(query)).first()
    return _to_user(row) if row else None


async def link_with_code(code: str, discord_id: int, discord_name: str) -> SiteUser:
    code = normalize_code(code)
    if len(code) != 8 or not set(code) <= CODE_ALPHABET:
        raise LinkError("Das ist kein gültiger Code – er hat 8 Zeichen und steht auf der Seite unter Einstellungen → Discord.")

    async with session() as db:
        async with db.begin():
            row = (
                await db.execute(
                    select(discord_link_codes.c.user_id).where(
                        discord_link_codes.c.code == code, discord_link_codes.c.expires_at > func.now()
                    )
                )
            ).first()
            if row is None:
                raise LinkError("Der Code ist ungültig oder abgelaufen (er gilt 15 Minuten). Erzeug auf der Seite einfach einen neuen.")
            user_id = row[0]

            target = (
                await db.execute(
                    select(users.c.username, users.c.is_banned, users.c.deleted_at, users.c.discord_id).where(users.c.id == user_id)
                )
            ).first()
            if target is None or target.deleted_at is not None:
                raise LinkError("Dieses Konto gibt es nicht mehr.")
            if target.is_banned:
                raise LinkError("Dieses Konto ist auf der Seite gesperrt.")

            other = (
                await db.execute(
                    select(users.c.username).where(users.c.discord_id == discord_id, users.c.id != user_id)
                )
            ).first()
            if other is not None:
                raise LinkError(
                    f"Dein Discord-Konto ist schon mit **{other[0]}** verknüpft. "
                    "Löse die Verknüpfung zuerst (/verknuepfung_loesen oder auf der Seite)."
                )

            await db.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(discord_id=discord_id, discord_name=discord_name[:100], discord_linked_at=func.now())
            )
            await db.execute(delete(discord_link_codes).where(discord_link_codes.c.user_id == user_id))

        row = (await db.execute(_user_query().where(users.c.id == user_id))).first()
    return _to_user(row)


async def unlink_discord(discord_id: int) -> SiteUser | None:
    """Loest die Verknuepfung von Discord aus. Gibt das bisher verknuepfte Konto zurueck."""
    user = await user_for_discord(discord_id, include_banned=True)
    if user is None:
        return None
    async with session() as db:
        await db.execute(
            update(users)
            .where(users.c.id == user.id)
            .values(discord_id=None, discord_name=None, discord_linked_at=None)
        )
        await db.commit()
    return user


async def linked_count() -> int:
    async with session() as db:
        return int((await db.execute(select(func.count()).where(users.c.discord_id.is_not(None)))).scalar_one())
