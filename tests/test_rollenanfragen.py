"""Rollenanfragen: wer entscheiden darf, und was Zustimmen/Ablehnen auf der Seite aendert."""

from sqlalchemy import insert, select

from bot.cogs.rollenanfragen.requests import Approver, approver_for, decide, decision_error, load
from bot.community import db as community_db
from db.models.role import Level
from tests.test_community import site  # noqa: F401

KARL, HUSKARL, JARL, KONIG, SCHMIED = 2, 5, 8, 10, 20


async def setup_site():
    """Ragnar (1) Karl, Lagertha (2) Huskarl mit Schmied, Bjorn (4) Jarl ohne Schmied, Ivar (5) Koenig."""
    r, u, x, p = community_db.roles, community_db.users, community_db.user_extra_roles, community_db.role_permissions
    async with community_db.session() as db:
        await db.execute(
            insert(r),
            [
                {"id": HUSKARL, "slug": "huskarl", "name": "Huskarl", "level": 50, "kind": "rank", "color": "#fff"},
                {"id": JARL, "slug": "jarl", "name": "Jarl", "level": 80, "kind": "rank", "color": "#fff"},
                {"id": KONIG, "slug": "konig", "name": "König", "level": 100, "kind": "rank", "color": "#fff"},
                {"id": SCHMIED, "slug": "schmied", "name": "Schmied", "level": 60, "kind": "extra", "color": "#fff"},
            ],
        )
        await db.execute(insert(p).values(role_id=KONIG, permission="*"))
        await db.execute(community_db.users.update().where(u.c.id == 2).values(role_id=HUSKARL))
        await db.execute(
            insert(u),
            [
                {"id": 4, "username": "Bjorn", "role_id": JARL, "is_banned": 0},
                {"id": 5, "username": "Ivar", "role_id": KONIG, "is_banned": 0},
            ],
        )
        await db.execute(insert(x).values(user_id=2, role_id=SCHMIED))
        await db.execute(
            insert(community_db.tickets).values(id=7, user_id=1, subject="Rollenanfrage: Schmied", category="rollenanfrage", status="open")
        )
        await db.execute(
            insert(community_db.role_requests),
            [
                {"id": 1, "user_id": 1, "role_id": SCHMIED, "ticket_id": 7, "reason": "Ich kenne mich mit Servern aus", "status": "pending"},
                {"id": 2, "user_id": 1, "role_id": HUSKARL, "ticket_id": None, "reason": "", "status": "pending"},
                {"id": 3, "user_id": 2, "role_id": JARL, "ticket_id": None, "reason": "", "status": "pending"},
            ],
        )
        await db.commit()


async def who(site_user_id: int, name: str, level: Level) -> Approver:
    return await approver_for(site_user_id, name, level)


async def test_extra_role_needs_the_role_itself(site):  # noqa: F811
    await setup_site()
    request = await load(1)
    assert (request.role_name, request.role_kind, request.requester_rank_name) == ("Schmied", "extra", "Karl")
    assert decision_error(request, await who(2, "Lagertha", Level.MOD)) is None  # Huskarl mit Schmied
    assert "selbst hat" in decision_error(request, await who(4, "Bjorn", Level.ADMIN))  # Jarl ohne Schmied
    assert decision_error(request, await who(5, "Ivar", Level.MEMBER)) is None  # Koenig auf der Seite
    assert decision_error(request, await who(4, "Bjorn", Level.OWNER)) is None  # Owner im Bot
    assert "eigene" in decision_error(request, await who(1, "Ragnar", Level.OWNER))


async def test_extra_role_only_up_to_own_rank(site):  # noqa: F811
    await setup_site()
    async with community_db.session() as db:  # Bjorn (Jarl) beantragt Schmied - Lagertha (Huskarl) darf nicht
        await db.execute(insert(community_db.role_requests).values(id=4, user_id=4, role_id=SCHMIED, reason="", status="pending"))
        await db.commit()
    assert "höheren Rang" in decision_error(await load(4), await who(2, "Lagertha", Level.MOD))


async def test_rank_needs_someone_above(site):  # noqa: F811
    await setup_site()
    to_huskarl, to_jarl = await load(2), await load(3)
    assert "darüber" in decision_error(to_huskarl, await who(2, "Lagertha", Level.MOD))  # Huskarl -> Huskarl: nein
    assert decision_error(to_huskarl, await who(4, "Bjorn", Level.ADMIN)) is None  # Jarl -> Huskarl: ja
    assert "darüber" in decision_error(to_jarl, await who(4, "Bjorn", Level.ADMIN))  # Jarl -> Jarl: nur Koenig
    assert decision_error(to_jarl, await who(5, "Ivar", Level.MEMBER)) is None
    assert "ab Mod" in decision_error(to_huskarl, await who(4, "Bjorn", Level.MEMBER))  # ohne Bot-Stufe Mod: nein


async def test_approve_extra_role_closes_ticket(site):  # noqa: F811
    await setup_site()
    request, lagertha = await load(1), await who(2, "Lagertha", Level.MOD)
    assert await decide(request, lagertha, True)
    assert not await decide(request, lagertha, True)  # schon entschieden
    after = await load(1)
    assert (after.status, after.decided_name) == ("approved", "Lagertha")
    assert "schon entschieden" in decision_error(after, lagertha)
    async with community_db.session() as db:
        extras = (await db.execute(select(community_db.user_extra_roles.c.role_id).where(community_db.user_extra_roles.c.user_id == 1))).all()
        ticket = (await db.execute(select(community_db.tickets.c.status).where(community_db.tickets.c.id == 7))).scalar_one()
        bodies = [b for (b,) in (await db.execute(select(community_db.ticket_messages.c.body))).all()]
    assert extras == [(SCHMIED,)] and ticket == "closed"
    assert any("Zugestimmt" in b for b in bodies) and any("geschlossen" in b for b in bodies)


async def test_approve_rank_promotes_deny_keeps_rank(site):  # noqa: F811
    await setup_site()
    bjorn = await who(4, "Bjorn", Level.ADMIN)
    assert await decide(await load(2), bjorn, True)
    async with community_db.session() as db:
        rank = (await db.execute(select(community_db.users.c.role_id).where(community_db.users.c.id == 1))).scalar_one()
    assert rank == HUSKARL

    ivar = await who(5, "Ivar", Level.OWNER)
    assert await decide(await load(3), ivar, False, "Noch zu früh")
    denied = await load(3)
    assert (denied.status, denied.decision_note) == ("denied", "Noch zu früh")
    async with community_db.session() as db:
        rank = (await db.execute(select(community_db.users.c.role_id).where(community_db.users.c.id == 2))).scalar_one()
    assert rank == HUSKARL  # abgelehnt: bleibt Huskarl


async def test_cancelled_request_shows_state_without_buttons(site):  # noqa: F811
    """Mitglied hat sein Ticket geschlossen: Anfrage zurueckgezogen, keine Knoepfe, niemand entscheidet mehr."""
    from bot.cogs.rollenanfragen.cog import request_embed, request_view

    await setup_site()
    async with community_db.session() as db:
        await db.execute(community_db.role_requests.update().where(community_db.role_requests.c.id == 1).values(status="cancelled"))
        await db.commit()
    request = await load(1)
    assert request_view(request) is None
    assert any("zurückgezogen" in f.value for f in request_embed(request).fields)
    assert "schon entschieden" in decision_error(request, await who(5, "Ivar", Level.OWNER))


async def test_request_from_discord_creates_site_request_with_rules(site):  # noqa: F811
    """Aus Discord (Panel/amp): gleiche Regeln wie das Formular der Seite, Ticket inklusive."""
    from bot.cogs.rollenanfragen.requests import create_site_request

    await setup_site()
    async with community_db.session() as db:
        await db.execute(community_db.role_requests.delete())  # frisch: keine Anfragen
        await db.execute(community_db.roles.update().where(community_db.roles.c.id == KARL).values(is_default=1))
        await db.commit()

    assert (await create_site_request(2, SCHMIED))[1].startswith("Du hast")  # Lagertha hat Schmied schon
    assert (await create_site_request(1, HUSKARL))[0] is None  # Raenge nicht aus Discord

    request_id, message = await create_site_request(1, SCHMIED, "Ich kenne mich aus")
    assert request_id and "gestellt" in message
    request = await load(request_id)
    assert (request.status, request.role_name, request.reason) == ("pending", "Schmied", "Ich kenne mich aus")
    async with community_db.session() as db:
        ticket = (await db.execute(select(community_db.tickets.c.category, community_db.tickets.c.subject).where(
            community_db.tickets.c.id == request.ticket_id))).first()
    assert ticket == ("rollenanfrage", "Rollenanfrage: Schmied")

    assert "läuft schon" in (await create_site_request(1, SCHMIED))[1]  # eine offene je Rolle
    async with community_db.session() as db:  # Thrall (unter dem Standardrang) beantragt nichts
        await db.execute(insert(community_db.roles).values(id=1, slug="thrall", name="Thrall", level=10, kind="rank", color="#fff"))
        await db.execute(community_db.users.update().where(community_db.users.c.id == 4).values(role_id=1))
        await db.commit()
    assert "Rang" in (await create_site_request(4, SCHMIED))[1]


async def test_site_extra_for_role_uses_rangsync_mapping(site, db_session):  # noqa: F811
    import json

    from bot.cogs.rangsync.sync import EXTRA_CONFIG_KEY
    from bot.cogs.rollenanfragen.requests import site_extra_for_role
    from bot.core.guild_config import set_config
    from db.models.guild import Guild

    await setup_site()
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    await set_config(1, EXTRA_CONFIG_KEY, json.dumps({"schmied": {"role_id": "555", "direction": "to_discord"}}), "Wikinger")
    extra = await site_extra_for_role(1, 555)
    assert extra is not None and extra.id == SCHMIED
    assert await site_extra_for_role(1, 999) is None
