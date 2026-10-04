"""AMP-Konten: gegen ein nachgebautes AMP und eine nachgebaute Seite."""

import json
from types import SimpleNamespace

from sqlalchemy import insert, select, update

from bot.cogs.ampkonten.accounts import (
    CACHE_KEY,
    MAP_KEY,
    apply_rank,
    available_roles,
    handle_request,
    handle_reset,
    username_for,
)
from bot.cogs.ampkonten.cog import AmpKontenCog
from bot.community import db as community_db
from bot.community import outbox
from bot.core.bot_settings import set_bot_setting
from db.models.amp_account import AmpAccount
from tests.test_community import site  # noqa: F401

ROLES = {"r-super": "Super Admins", "r-bot": "WikingerBot", "r-default": "Default", "r-mod": "Mod"}


class FakeAMP:
    def __init__(self, existing=()):
        self.users = {name: {"ID": f"u-{name}", "Disabled": False, "roles": set(), "password": None, "MustChangePassword": False} for name in existing}
        self.calls = []

    async def __call__(self, endpoint, args):
        self.calls.append(endpoint)
        if endpoint == "GetRoleIds":
            return dict(ROLES)
        if endpoint == "GetAMPUserInfo":
            user = self.users.get(args["Username"])
            return {"ID": user["ID"], "Disabled": user["Disabled"]} if user else {}
        if endpoint == "CreateUser":
            if args["Username"] in self.users:
                return {"Status": False, "Reason": "exists"}
            self.users[args["Username"]] = {"ID": f"u-{args['Username']}", "Disabled": False, "roles": set(), "password": None, "MustChangePassword": False}
            return {"Status": True, "Result": f"u-{args['Username']}"}
        if endpoint == "ResetUserPassword":
            self.users[args["Username"]]["password"] = args["NewPassword"]
            return {"Status": True}
        if endpoint == "UpdateUserInfo":
            self.users[args["Username"]].update(Disabled=args["Disabled"], MustChangePassword=args["MustChangePassword"])
            return {"Status": True}
        if endpoint == "SetAMPUserRoleMembership":
            user = next(u for u in self.users.values() if u["ID"] == args["UserId"])
            (user["roles"].add if args["IsMember"] else user["roles"].discard)(args["RoleId"])
            return {"Status": True}
        raise AssertionError(endpoint)


async def seed(mapping):
    async with community_db.session() as db:
        await db.execute(insert(community_db.roles).values(id=3, slug="huskarl", name="Huskarl", level=50, color="#000"))
        await db.execute(update(community_db.users).where(community_db.users.c.id == 1).values(discord_id=4242, role_id=3))
        await db.commit()
    await set_bot_setting(MAP_KEY, json.dumps(mapping))
    await set_bot_setting(CACHE_KEY, json.dumps({v: k for k, v in ROLES.items()}))


async def site_status(user_id=1):
    u = community_db.users
    async with community_db.session() as db:
        return (await db.execute(select(u.c.amp_username, u.c.amp_status, u.c.amp_note).where(u.c.id == user_id))).first()


def test_username_for():
    assert username_for("Ragnar Lothbrok", 1) == "Ragnar_Lothbrok"
    assert username_for("Ä!", 7) == "wikinger7"


async def test_roles_never_offer_super_admin_or_bot_role(site, db_session):  # noqa: F811
    roles, fresh = await available_roles(FakeAMP())
    assert fresh and set(roles) == {"Default", "Mod"}


async def test_request_creates_account_with_role_and_forced_password_change(site, db_session):  # noqa: F811
    await seed({"huskarl": "r-mod"})
    amp = FakeAMP()
    outcome = await handle_request(amp, 1)
    assert outcome.status == "active" and outcome.amp_username == "Ragnar" and outcome.password
    user = amp.users["Ragnar"]
    assert user["password"] == outcome.password and user["MustChangePassword"] and user["roles"] == {"r-mod"}

    async with db_session.bind.connect() as conn:  # Passwort nie in der Bot-Datenbank
        rows = (await conn.execute(select(AmpAccount.__table__))).mappings().all()
    assert outcome.password not in json.dumps([dict(r) for r in rows], default=str)

    # neues Passwort
    again = await handle_reset(amp, 1)
    assert again.password and again.password != outcome.password


async def test_rank_without_access_is_denied_and_super_admin_never_given(site, db_session):  # noqa: F811
    await seed({})
    assert (await handle_request(FakeAMP(), 1)).status == "denied"
    await set_bot_setting(MAP_KEY, json.dumps({"huskarl": "r-super"}))  # selbst wenn es jemand eintraegt
    amp = FakeAMP()
    try:
        await handle_request(amp, 1)
        raise AssertionError("haette abgelehnt werden muessen")
    except Exception as error:
        assert "nicht vergeben" in str(error)
    assert all("r-super" not in u["roles"] for u in amp.users.values())


async def test_existing_foreign_account_is_not_touched(site, db_session):  # noqa: F811
    await seed({"huskarl": "r-mod"})
    amp = FakeAMP(existing=["Ragnar"])
    outcome = await handle_request(amp, 1)
    assert outcome.amp_username == "Ragnar-1"
    assert amp.users["Ragnar"]["password"] is None and amp.users["Ragnar"]["roles"] == set()


async def test_rank_change_disables_and_reenables(site, db_session):  # noqa: F811
    await seed({"huskarl": "r-mod", "karl": "r-default"})
    amp = FakeAMP()
    await handle_request(amp, 1)
    async with community_db.session() as db:  # zum Thrall degradiert (Rang ohne Zugang)
        await db.execute(insert(community_db.roles).values(id=1, slug="thrall", name="Thrall", level=10, color="#000"))
        await db.execute(update(community_db.users).where(community_db.users.c.id == 1).values(role_id=1))
        await db.commit()
    assert (await apply_rank(amp, 1)).status == "disabled" and amp.users["Ragnar"]["Disabled"]

    async with community_db.session() as db:  # zum Karl -> wieder frei, andere Rolle
        await db.execute(update(community_db.users).where(community_db.users.c.id == 1).values(role_id=2))
        await db.commit()
    outcome = await apply_rank(amp, 1)
    assert outcome.status == "active" and not amp.users["Ragnar"]["Disabled"] and amp.users["Ragnar"]["roles"] == {"r-default"}
    assert await apply_rank(amp, 2) is None  # Lagertha hat kein eigenes Konto -> nichts tun


async def test_cog_dm_and_site_status(site, db_session):  # noqa: F811
    await seed({"huskarl": "r-mod"})
    sent = []

    class User:
        async def send(self, embed):
            sent.append(embed)

    bot = SimpleNamespace(get_user=lambda uid: User() if uid == 4242 else None)
    cog = AmpKontenCog(bot, core_call=FakeAMP())
    await cog._on_request({"user_id": 1})
    assert await site_status() == ("Ragnar", "active", None)
    fields = {f.name: f.value for f in sent[0].fields}
    assert fields["Benutzer"] == "`Ragnar`" and fields["Startpasswort"].startswith("||")


async def test_undeliverable_dm_leaves_hint(site, db_session):  # noqa: F811
    await seed({"huskarl": "r-mod"})

    async def no_user(uid):
        import discord

        raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "unknown")

    cog = AmpKontenCog(SimpleNamespace(get_user=lambda uid: None, fetch_user=no_user), core_call=FakeAMP())
    await cog._on_request({"user_id": 1})
    name, status, note = await site_status()
    assert status == "active" and "neues Passwort" in note


async def test_outbox_runs_all_handlers_of_a_kind():
    seen = []

    async def a(payload):
        seen.append("a")

    async def b(payload):
        seen.append("b")

    outbox.register("user.role", a)
    outbox.register("user.role", b)
    outbox.unregister("user.role", a)
    assert outbox.registered() == ["user.role"]
    outbox.unregister("user.role", b)
    assert outbox.registered() == []


async def test_required_extra_role_then_rank_decides(site, db_session):  # noqa: F811
    """Mit Voraussetzung (z.B. Gameserver-Zusatzrolle): ohne sie kein Zugang, mit ihr bestimmt der Rang."""
    from bot.cogs.ampkonten.accounts import REQUIRES_KEY

    await seed({"huskarl": "r-mod"})
    await set_bot_setting(REQUIRES_KEY, "schmied")
    async with community_db.session() as db:
        await db.execute(insert(community_db.roles).values(id=9, slug="schmied", name="Schmied", level=60, kind="extra", color="#000"))
        await db.commit()
    amp = FakeAMP()
    denied = await handle_request(amp, 1)
    assert denied.status == "denied" and "Schmied" in denied.note and not amp.users

    async with community_db.session() as db:
        await db.execute(insert(community_db.user_extra_roles).values(user_id=1, role_id=9))
        await db.commit()
    outcome = await handle_request(amp, 1)
    assert outcome.status == "active" and amp.users["Ragnar"]["roles"] == {"r-mod"}  # Rang Huskarl -> Mod

    async with community_db.session() as db:  # Zusatzrolle weg -> gesperrt
        await db.execute(community_db.user_extra_roles.delete())
        await db.commit()
    disabled = await apply_rank(amp, 1)
    assert disabled.status == "disabled" and "Schmied" in disabled.note and amp.users["Ragnar"]["Disabled"]
