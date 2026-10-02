"""Selbst-Einrichtung der AMP-Rolle (bot/core/amp_role.py) gegen ein nachgebautes AMP."""

from bot.core.amp_role import (
    DESIRED_PERMISSIONS,
    ROLE_NAME,
    SUPER_ADMIN_ROLE,
    ensure_bot_role,
    plan_permission_changes,
    role_name_to_id,
    unknown_nodes,
)

SUPER_ID = "role-super"
USER_ID = "user-bot"


class FakeAMP:
    """Haelt Rollen, Rechte und Mitgliedschaften wie der AMP-Controller und
    beantwortet die Core-Endpunkte, die ensure_bot_role aufruft."""

    def __init__(self, *, bot_is_super: bool, existing_role_perms: list[str] | None = None):
        self.roles = {SUPER_ID: SUPER_ADMIN_ROLE, "role-default": "Default"}
        self.perms: dict[str, dict[str, bool]] = {}
        self.members = {USER_ID: {"role-default"}}
        if bot_is_super:
            self.members[USER_ID].add(SUPER_ID)
        if existing_role_perms is not None:
            self.roles["role-bot"] = ROLE_NAME
            self.perms["role-bot"] = {}
            for entry in existing_role_perms:
                node, enabled = (entry[1:], False) if entry.startswith("-") else (entry, True)
                self.perms["role-bot"][node] = enabled
        self.calls: list[str] = []

    async def __call__(self, endpoint, args):
        self.calls.append(endpoint)
        if endpoint == "GetAMPUserInfo":
            return {"ID": USER_ID, "Roles": sorted(self.members[USER_ID])} if args["Username"] == "wikingerbot" else {}
        if endpoint == "GetRoleIds":
            return dict(self.roles)
        if endpoint == "GetPermissionsSpec":
            return [{"Node": "Core.Console.Send", "Children": [{"Node": "Instances.abc.Start", "Children": []}]}]
        if endpoint == "CreateRole":
            self.roles["role-bot"] = args["Name"]
            self.perms["role-bot"] = {}
            return {"Status": True}
        if endpoint == "GetAMPRolePermissions":
            return [("" if on else "-") + node for node, on in self.perms.get(args["RoleId"], {}).items()]
        if endpoint == "SetAMPRolePermission":
            self.perms[args["RoleId"]][args["PermissionNode"]] = args["Enabled"]
            return {"Status": True}
        if endpoint == "SetAMPUserRoleMembership":
            if args["IsMember"]:
                self.members[args["UserId"]].add(args["RoleId"])
            else:
                self.members[args["UserId"]].discard(args["RoleId"])
            return {"Status": True}
        raise AssertionError(f"unerwarteter Aufruf {endpoint}")


def desired_as_dict():
    return {(e[1:] if e.startswith("-") else e): not e.startswith("-") for e in DESIRED_PERMISSIONS}


async def test_first_start_with_super_admin_sets_everything_up_and_drops_super():
    amp = FakeAMP(bot_is_super=True)
    report = await ensure_bot_role(amp, "wikingerbot", keep_super_admin=False)

    assert report.created_role and report.joined_role and report.left_super_admin
    assert amp.perms["role-bot"] == desired_as_dict()
    assert amp.members[USER_ID] == {"role-default", "role-bot"}  # Super Admin abgegeben
    # Super Admin wird erst ganz am Ende abgegeben
    assert amp.calls[-1] == "SetAMPUserRoleMembership"


async def test_keep_super_admin_keeps_it():
    amp = FakeAMP(bot_is_super=True)
    report = await ensure_bot_role(amp, "wikingerbot", keep_super_admin=True)

    assert not report.left_super_admin
    assert SUPER_ID in amp.members[USER_ID]


async def test_second_start_without_super_admin_changes_nothing():
    amp = FakeAMP(bot_is_super=True)
    await ensure_bot_role(amp, "wikingerbot", keep_super_admin=False)
    amp.calls.clear()

    report = await ensure_bot_role(amp, "wikingerbot", keep_super_admin=False)

    assert report.missing_without_super_admin == []
    assert not any(c.startswith("Set") or c == "CreateRole" for c in amp.calls)


async def test_without_super_admin_and_without_role_only_reports():
    amp = FakeAMP(bot_is_super=False)
    report = await ensure_bot_role(amp, "wikingerbot", keep_super_admin=False)

    assert report.skipped_reason and SUPER_ADMIN_ROLE in report.skipped_reason
    assert "CreateRole" not in amp.calls


async def test_without_super_admin_reports_missing_permissions():
    amp = FakeAMP(bot_is_super=False, existing_role_perms=["Instances.*"])
    amp.members[USER_ID].add("role-bot")
    report = await ensure_bot_role(amp, "wikingerbot", keep_super_admin=False)

    assert "Core.*" in report.missing_without_super_admin
    assert not any(c.startswith("Set") for c in amp.calls)


async def test_existing_role_is_completed_and_extra_rights_stay():
    # Jemand hat in AMP "FileManager.*" bewusst ergaenzt - das bleibt unberuehrt
    amp = FakeAMP(bot_is_super=True, existing_role_perms=["Instances.*", "FileManager.*"])
    report = await ensure_bot_role(amp, "wikingerbot", keep_super_admin=True)

    assert not report.created_role
    assert "Instances.*" not in report.changed_permissions
    assert amp.perms["role-bot"]["FileManager.*"] is True


async def test_unknown_user_is_skipped():
    amp = FakeAMP(bot_is_super=True)
    report = await ensure_bot_role(amp, "gibtsnicht", keep_super_admin=False)
    assert report.skipped_reason and "nicht gefunden" in report.skipped_reason


async def test_without_user_management_rights_is_normal_and_quiet():
    async def amp(endpoint, args):
        raise RuntimeError(
            "Unauthorized Access: You do not have permission to use this method (GSMyAdmin.WebServer.GetAMPUserInfo) "
            "at this time. This method requires the Core.UserManagement.ViewUserInfo permission."
        )

    report = await ensure_bot_role(amp, "wikingerbot", keep_super_admin=False)
    assert report.no_admin_rights and not report.skipped_reason


async def test_other_errors_still_raise():
    async def amp(endpoint, args):
        raise TimeoutError("AMP hat nach 10s nicht geantwortet")

    try:
        await ensure_bot_role(amp, "wikingerbot", keep_super_admin=False)
    except TimeoutError:
        return
    raise AssertionError("TimeoutError erwartet")


def test_plan_permission_changes():
    assert plan_permission_changes(["A.*", "-B.C"], ["A.*", "-B.C"]) == []
    assert plan_permission_changes(["A.*"], ["-A.*"]) == [("A.*", False)]
    assert plan_permission_changes([], ["X.Y"]) == [("X.Y", True)]


def test_role_name_to_id_both_directions():
    assert role_name_to_id({"id1": SUPER_ADMIN_ROLE})[SUPER_ADMIN_ROLE] == "id1"
    assert role_name_to_id({SUPER_ADMIN_ROLE: "id1"})[SUPER_ADMIN_ROLE] == "id1"


def test_unknown_nodes():
    known = {"Core.Console.Send", "Instances.abc.Start"}
    assert unknown_nodes(["Core.*", "-Instances.*", "Foo.Bar", "-Foo.*"], known) == ["Foo.Bar", "Foo.*"]
    assert unknown_nodes(["Foo.Bar"], set()) == []  # ohne Spec keine Aussage
