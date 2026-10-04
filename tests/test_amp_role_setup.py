"""Gameserver-Rollen in AMP: Rechte anhand der Rechte-Liste finden und setzen."""

from bot.cogs.ampkonten.role_setup import DENY, controller_plan, instance_plan, leaves, run


def node(path, *children, name=None):
    return {"Node": path, "DisplayName": name or path.rsplit(".", 1)[-1], "Children": list(children)}


INSTANCE_SPEC = [
    node(
        "Core",
        node(
            "Core.AppManagement",
            node("Core.AppManagement.StartApplication"),
            node("Core.AppManagement.StopApplication"),
            node("Core.AppManagement.RestartApplication"),
            node("Core.AppManagement.UpdateApplication"),
        ),
        node("Core.Console", node("Core.Console.ViewConsole"), node("Core.Console.SendConsoleInput")),
        node("Core.Scheduler", node("Core.Scheduler.EditSchedule")),
        node("Core.UserManagement", node("Core.UserManagement.EditUsers")),
    ),
    node("FileManager", node("FileManager.FileManager.BrowseFiles"), node("FileManager.FileManager.TrashFiles")),
    node("Settings", node("Settings.Server.Port")),
    node("LocalFileBackup", node("LocalFileBackup.Backup.TakeBackup"), node("LocalFileBackup.Backup.DeleteBackup")),
]

CONTROLLER_SPEC = [
    node("ADS", node("ADS.Manage")),
    node(
        "Instances",
        node(
            "Instances.game-1",
            node("Instances.game-1.Manage"),
            node("Instances.game-1.Start"),
            node("Instances.game-1.Stop"),
            node("Instances.game-1.Delete"),
        ),
    ),
]


def test_leaves_and_instance_plan():
    assert ("Core.Console.ViewConsole", "ViewConsole") in leaves(INSTANCE_SPEC)
    plan = instance_plan(INSTANCE_SPEC)
    assert plan["helfer"]["allow"] == [
        "Core.AppManagement.RestartApplication",
        "Core.AppManagement.StartApplication",
        "Core.AppManagement.StopApplication",
        "Core.Console.ViewConsole",
    ]
    assert "Core.Console.SendConsoleInput" in plan["betreuer"]["allow"] and "Settings.Server.Port" not in plan["betreuer"]["allow"]
    assert "Settings.Server.Port" in plan["betreuer"]["neutral"]  # gehoert zur Admin-Stufe -> neutral
    admin = plan["admin"]["allow"]
    assert {"Settings.Server.Port", "FileManager.FileManager.TrashFiles", "LocalFileBackup.Backup.DeleteBackup"} <= set(admin)
    assert "Core.UserManagement.EditUsers" not in admin
    assert plan["betreuer"]["missing"] == ["Spieler kicken/bannen"]  # nicht im Beispiel-Modul


def test_controller_plan():
    plan = controller_plan(CONTROLLER_SPEC, {"game-1": "Vein", "game-2": "ARK"})
    assert plan["login"] == ["ADS.Manage"]
    # Manage + Instanz starten/stoppen, aber nie loeschen
    assert sorted(plan["instances"]["Vein"]) == ["Instances.game-1.Manage", "Instances.game-1.Start", "Instances.game-1.Stop"]
    assert plan["missing_instances"] == ["ARK"]


class FakeAMP:
    def __init__(self, instance_roles=True):
        self.controller_roles = {"r-super": "Super Admins"}
        self.instance_roles = instance_roles
        self.set = []  # (wo, Rolle, Knoten, Wert)

    async def controller(self, endpoint, args):
        if endpoint == "GetPermissionsSpec":
            return CONTROLLER_SPEC
        if endpoint == "GetRoleIds":
            return dict(self.controller_roles)
        if endpoint == "CreateRole":
            assert args["AsCommonRole"] is True
            self.controller_roles[f"r-{args['Name']}"] = args["Name"]
            return {"Status": True}
        if endpoint == "SetAMPRolePermission":
            self.set.append(("ads", args["RoleId"], args["PermissionNode"], args["Enabled"]))
            return {"Status": True}
        raise AssertionError(endpoint)

    async def instance(self, iid, endpoint, args):
        if endpoint == "GetPermissionsSpec":
            return INSTANCE_SPEC
        if endpoint == "GetRoleIds":
            return {rid: name for rid, name in self.controller_roles.items()} if self.instance_roles else {}
        if endpoint == "SetAMPRolePermission":
            self.set.append((iid, args["RoleId"], args["PermissionNode"], args["Enabled"]))
            return {"Status": True}
        raise AssertionError(endpoint)


async def test_check_changes_nothing():
    amp = FakeAMP()
    report = await run(amp.controller, amp.instance, {"game-1": "Vein"}, apply=False)
    assert not report.errors and amp.set == [] and report.created_roles == []
    assert report.instances["Vein"]["helfer"]["allow"]


async def test_apply_creates_roles_and_sets_permissions():
    amp = FakeAMP()
    report = await run(amp.controller, amp.instance, {"game-1": "Vein"}, apply=True)
    assert report.created_roles == ["Gameserver Helfer", "Gameserver Betreuer", "Gameserver Admin"]
    helfer_ads = {(n, v) for where, rid, n, v in amp.set if where == "ads" and rid == "r-Gameserver Helfer"}
    assert helfer_ads == {
        ("ADS.Manage", True),
        ("Instances.game-1.Manage", True),
        ("Instances.game-1.Start", True),
        ("Instances.game-1.Stop", True),
    }
    helfer = {(n, v) for where, rid, n, v in amp.set if where == "game-1" and rid == "r-Gameserver Helfer"}
    assert ("Core.AppManagement.StartApplication", True) in helfer
    assert ("Settings.Server.Port", None) in helfer  # Admin-Recht: neutral
    assert all((d, False) in helfer for d in DENY)
    assert ("Core.UserManagement.EditUsers", True) not in helfer

    # zweiter Lauf legt nichts doppelt an
    again = await run(amp.controller, amp.instance, {"game-1": "Vein"}, apply=True)
    assert again.created_roles == []


async def test_apply_reports_missing_role_in_instance_and_controller_errors():
    amp = FakeAMP(instance_roles=False)
    report = await run(amp.controller, amp.instance, {"game-1": "Vein"}, apply=True)
    assert "nicht vorhanden" in report.instances["Vein"]["helfer"]["error"]

    async def denied(endpoint, args):
        raise PermissionError("Unauthorized Access")

    failed = await run(denied, amp.instance, {"game-1": "Vein"}, apply=True)
    assert failed.errors and "Super Admins" in failed.errors[0]


async def test_api_uses_fresh_login_and_remembers_done_servers(db_session, monkeypatch):
    import httpx

    from api.main import app
    from api.middleware.auth import create_access_token
    from bot.core.amp_client import amp_client
    from db.models.guild import Guild
    from db.models.role import Level
    from db.models.server import Server

    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()
    db_session.add(Server(guild_id=1, instance_name="vein", amp_instance_id="game-1", display_name="Vein", host=""))
    await db_session.commit()
    amp = FakeAMP()
    logins = []
    monkeypatch.setattr(amp_client, "fresh_calls", lambda *login: logins.append(login) or (amp.controller, amp.instance))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set("session", create_access_token(100, 1, Level.OWNER))
        assert (await client.get("/ampkonten/roles/status")).json()["pending"] == ["Vein"]
        assert (await client.post("/ampkonten/roles/check")).status_code == 200 and amp.set == []
        applied = (
            await client.post("/ampkonten/roles/apply", json={"username": "daywalker", "password": "geheim-123", "token": "123456"})
        ).json()
        assert applied["changed"] > 0 and not applied["errors"]
        status = (await client.get("/ampkonten/roles/status")).json()
        assert status["done"] == ["Vein"] and status["pending"] == []
    assert logins == [("", "", ""), ("daywalker", "geheim-123", "123456")]  # jede Aktion frisch, Admin-Daten nur durchgereicht

    from sqlalchemy import select

    from db.models.bot_setting import BotSetting

    stored = " ".join(str(v) for (v,) in (await db_session.execute(select(BotSetting.value))).all())
    assert "geheim-123" not in stored  # Passwort nirgends gespeichert


def test_controller_plan_lists_other_nodes_for_diagnosis():
    plan = controller_plan(CONTROLLER_SPEC, {"game-1": "Vein"})
    assert plan["other_nodes"] == ["ADS.Manage = Manage"]
