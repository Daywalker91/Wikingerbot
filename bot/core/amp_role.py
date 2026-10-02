"""Eigene AMP-Rolle "WikingerBot" - der Bot richtet sie beim Start selbst ein.

Idee wie bei GatekeeperV2 (eigene Umsetzung): Man gibt dem AMP-Benutzer des
Bots einmalig "Super Admins". Beim Start legt der Bot dann seine eigene Rolle
mit genau den Rechten an, die er braucht, nimmt sich selbst hinein und gibt
"Super Admins" wieder ab (ausser AMP_KEEP_SUPER_ADMIN ist gesetzt).

Ohne Super Admin prueft der Bot nur, ob seine Rolle vollstaendig ist, und
meldet fehlende Rechte im Log - dann einmal kurz wieder Super Admin geben, der
Bot ergaenzt beim naechsten Start selbst.

Rechte-Knoten: "Knoten" = erlaubt, "-Knoten" = ausdruecklich verboten. Die
Namen sind AMPs eigene Rechte-Bezeichnungen (Role Management in AMP).
"""

import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

log = logging.getLogger("wikingerbot.amp_role")

ROLE_NAME = "WikingerBot"
SUPER_ADMIN_ROLE = "Super Admins"

# Was der Bot braucht: Instanzen auflisten/starten/stoppen (Controller), in den
# Instanzen Status, Start/Stop der Anwendung und die Konsole. Alles Gefaehrliche
# (Benutzer, Rollen, Instanzen anlegen/loeschen, Updates, Dateien, Einstellungen,
# Backups) bleibt aus - "Settings.*", "FileManager.*" und "LocalFileBackup.*"
# werden gar nicht erst erlaubt.
DESIRED_PERMISSIONS: list[str] = [
    # Zugriff auf alle Instanzen (anmelden, starten, stoppen)
    "Instances.*",
    # Controller: Instanzen verwalten - ohne alles, was Instanzen anlegt,
    # loescht, umbaut oder Remote-Knoten aendert
    "ADS.InstanceManagement.*",
    "-ADS.InstanceManagement.RegisterToController",
    "-ADS.InstanceManagement.CreateInstance",
    "-ADS.InstanceManagement.SuspendInstances",
    "-ADS.InstanceManagement.UpgradeInstances",
    "-ADS.InstanceManagement.DeleteInstances",
    "-ADS.InstanceManagement.AttachRemoteADSInstance",
    "-ADS.InstanceManagement.RemoveRemoteADSInstance",
    "-ADS.InstanceManagement.EditRemoteTargets",
    "-ADS.InstanceManagement.Convert",
    "-ADS.InstanceManagement.Reconfigure",
    "-ADS.InstanceManagement.RefreshConfiguration",
    "-ADS.InstanceManagement.RefreshRemoteConfigStores",
    "-ADS.TemplateManagement.*",
    # In den Instanzen: Status, Anwendung starten/stoppen, Konsole - ohne
    # Benutzer-/Rollenverwaltung, Zeitplaene, Audit-Log, Sonderrechte, Updates
    "Core.*",
    "-Core.RoleManagement.*",
    "-Core.UserManagement.*",
    "-Core.Scheduler.*",
    "-Core.AuditLog.*",
    "-Core.Special.*",
    "-Core.AppManagement.UpdateApplication",
]


@dataclass
class RoleReport:
    """Was beim Abgleich passiert ist - wird geloggt und ist testbar."""

    created_role: bool = False
    changed_permissions: list[str] = field(default_factory=list)
    joined_role: bool = False
    left_super_admin: bool = False
    missing_without_super_admin: list[str] = field(default_factory=list)
    unknown_nodes: list[str] = field(default_factory=list)
    skipped_reason: str | None = None


def parse_node(entry: str) -> tuple[str, bool]:
    """'-Core.X' -> ('Core.X', False), 'Core.X' -> ('Core.X', True)."""
    return (entry[1:], False) if entry.startswith("-") else (entry, True)


def plan_permission_changes(current: list[str], desired: list[str]) -> list[tuple[str, bool]]:
    """Welche Knoten gesetzt werden muessen, damit die Rolle `desired` entspricht.
    Knoten, die die Rolle zusaetzlich hat, bleiben unberuehrt (falls jemand sie
    in AMP bewusst ergaenzt hat)."""
    have = dict(parse_node(entry) for entry in current)
    changes = []
    for entry in desired:
        node, enabled = parse_node(entry)
        if have.get(node) is not enabled:
            changes.append((node, enabled))
    return changes


def role_name_to_id(role_ids: dict) -> dict[str, str]:
    """Core/GetRoleIds liefert {RollenID: Name}. Zur Sicherheit wird auch die
    umgekehrte Richtung erkannt."""
    if SUPER_ADMIN_ROLE in role_ids:
        return {str(name): str(rid) for name, rid in role_ids.items()}
    return {str(name): str(rid) for rid, name in role_ids.items()}


def flatten_spec(nodes) -> set[str]:
    """Alle Knoten-Namen aus Core/GetPermissionsSpec (verschachtelter Baum)."""
    found: set[str] = set()
    stack = list(nodes or [])
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("Node"):
                found.add(str(node["Node"]))
            stack.extend(node.get("Children") or [])
    return found


def unknown_nodes(desired: list[str], known: set[str]) -> list[str]:
    """Gewuenschte Knoten, die AMP nicht kennt (Tippfehler / andere AMP-Version).
    Ein Wildcard-Knoten 'A.B.*' gilt als bekannt, wenn es irgendeinen Knoten
    unter 'A.B.' gibt."""
    if not known:
        return []
    missing = []
    for entry in desired:
        node, _ = parse_node(entry)
        if node.endswith(".*"):
            prefix = node[:-1]
            if not any(k.startswith(prefix) or k == node for k in known):
                missing.append(node)
        elif node not in known:
            missing.append(node)
    return missing


CoreCall = Callable[..., Awaitable]


async def ensure_bot_role(core_call: CoreCall, amp_user: str, *, keep_super_admin: bool) -> RoleReport:
    """Gleicht die AMP-Rolle des Bots ab. `core_call(endpoint, args)` ruft einen
    Core-Endpunkt am Controller auf (siehe AMPClient.core_call) - als Parameter,
    damit der Ablauf ohne echtes AMP testbar ist."""
    report = RoleReport()

    user = await core_call("GetAMPUserInfo", {"Username": amp_user})
    if not isinstance(user, dict) or not user.get("ID"):
        report.skipped_reason = f"AMP-Benutzer '{amp_user}' nicht gefunden"
        return report
    user_id = str(user["ID"])
    user_roles = {str(r) for r in (user.get("Roles") or [])}

    roles = role_name_to_id(await core_call("GetRoleIds", {}))
    super_id = roles.get(SUPER_ADMIN_ROLE)
    is_super = super_id is not None and super_id in user_roles
    role_id = roles.get(ROLE_NAME)

    # Ohne Super Admin: nur pruefen und melden
    if not is_super:
        if role_id is None:
            report.skipped_reason = (
                f"Die AMP-Rolle '{ROLE_NAME}' fehlt. Gib dem AMP-Benutzer '{amp_user}' einmalig "
                f"'{SUPER_ADMIN_ROLE}' - der Bot legt sie beim naechsten Start selbst an."
            )
            return report
        current = await core_call("GetAMPRolePermissions", {"RoleId": role_id}) or []
        report.missing_without_super_admin = [
            ("" if enabled else "-") + node for node, enabled in plan_permission_changes(current, DESIRED_PERMISSIONS)
        ]
        if role_id not in user_roles:
            report.missing_without_super_admin.append(f"Mitgliedschaft in '{ROLE_NAME}'")
        return report

    # Mit Super Admin: einrichten
    try:
        report.unknown_nodes = unknown_nodes(DESIRED_PERMISSIONS, flatten_spec(await core_call("GetPermissionsSpec", {})))
    except Exception as error:  # nur eine Plausibilitaetspruefung - darf den Abgleich nicht stoppen
        log.debug("Rechte-Liste von AMP nicht lesbar: %s", error)

    if role_id is None:
        await core_call("CreateRole", {"Name": ROLE_NAME, "AsCommonRole": False})
        roles = role_name_to_id(await core_call("GetRoleIds", {}))
        role_id = roles.get(ROLE_NAME)
        if role_id is None:
            report.skipped_reason = f"AMP-Rolle '{ROLE_NAME}' konnte nicht angelegt werden"
            return report
        report.created_role = True

    current = await core_call("GetAMPRolePermissions", {"RoleId": role_id}) or []
    for node, enabled in plan_permission_changes(current, DESIRED_PERMISSIONS):
        await core_call("SetAMPRolePermission", {"RoleId": role_id, "PermissionNode": node, "Enabled": enabled})
        report.changed_permissions.append(("" if enabled else "-") + node)

    if role_id not in user_roles:
        await core_call("SetAMPUserRoleMembership", {"UserId": user_id, "RoleId": role_id, "IsMember": True})
        report.joined_role = True

    # Super Admin erst abgeben, wenn Rolle, Rechte und Mitgliedschaft stehen
    if not keep_super_admin:
        await core_call("SetAMPUserRoleMembership", {"UserId": user_id, "RoleId": super_id, "IsMember": False})
        report.left_super_admin = True
    return report


def log_report(report: RoleReport, amp_user: str) -> None:
    if report.skipped_reason:
        log.warning("AMP-Rolle: %s", report.skipped_reason)
        return
    if report.created_role:
        log.info("AMP-Rolle '%s' angelegt.", ROLE_NAME)
    if report.changed_permissions:
        log.info("AMP-Rolle '%s': %d Rechte gesetzt: %s", ROLE_NAME, len(report.changed_permissions), ", ".join(report.changed_permissions))
    if report.joined_role:
        log.info("AMP-Benutzer '%s' in die Rolle '%s' aufgenommen.", amp_user, ROLE_NAME)
    if report.left_super_admin:
        log.warning("AMP-Benutzer '%s' hat '%s' abgegeben und arbeitet jetzt nur noch mit der Rolle '%s'.", amp_user, SUPER_ADMIN_ROLE, ROLE_NAME)
    if report.unknown_nodes:
        log.warning("AMP kennt diese Rechte nicht (andere AMP-Version?): %s", ", ".join(report.unknown_nodes))
    if report.missing_without_super_admin:
        log.warning(
            "AMP-Rolle '%s' ist unvollstaendig: %s. Gib '%s' einmalig '%s', der Bot ergaenzt beim naechsten Start selbst.",
            ROLE_NAME, ", ".join(report.missing_without_super_admin), amp_user, SUPER_ADMIN_ROLE,
        )
    if not any([report.created_role, report.changed_permissions, report.joined_role, report.left_super_admin, report.missing_without_super_admin]):
        log.info("AMP-Rolle '%s' ist vollstaendig.", ROLE_NAME)
