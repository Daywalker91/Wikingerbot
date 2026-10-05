"""AMP-Rollen fuer Gameserver-Betreuer einrichten (Tab AMP-Konten, "Pruefen"/"Einrichten").

AMP hat zwei Ebenen: Am Controller entscheidet "Manage", ob man sich anmelden darf und
welche Instanzen man sieht. Alles Weitere (Starten, Konsole, Dateien, Einstellungen, ...)
wird in JEDER Instanz fuer die Rolle gesetzt. Die Rollen legt der Bot als globale
Rollen am Controller an: in allen Instanzen vorhanden, Rechte je Instanz eigen (keine
Vorlage-Rollen - deren Rechte gaelten ueberall gleich, auch im Controller selbst).

Die genauen Rechte-Namen unterscheiden sich je nach AMP-Version und Spiel-Modul. Der
Bot sucht sie deshalb in der Rechte-Liste des jeweiligen AMP (GetPermissionsSpec)
anhand von Merkmalen (FAEHIGKEITEN) und meldet, was er nicht findet. "Pruefen" zeigt
das ohne etwas zu aendern; "Einrichten" setzt es (braucht kurz Super Admins).

Gesetzt werden nur Blaetter des Rechte-Baums (keine Wildcards) - so erbt eine Rolle
nichts, was spaeter neu dazukommt. Was eine Stufe nicht haben soll, wird neutral (grau)
gesetzt; Benutzer-/Rollenverwaltung ausdruecklich verboten, Audit-Log ausser fuer Verwalter.
Super Admins (alles, auch Benutzer/Rollen und AMP-Einstellungen) vergibt der Bot nie.
"""

from dataclasses import dataclass, field
from typing import Awaitable, Callable

Call = Callable[[str, dict], Awaitable[object]]


@dataclass(frozen=True)
class Tier:
    key: str
    name: str  # Name der AMP-Rolle
    caps: tuple[str, ...]


# Merkmale: Rechte-Knoten (klein geschrieben) -> gehoert zur Faehigkeit?
def _app(n: str) -> bool:
    return n.startswith("core.appmanagement.")


CAPABILITIES: dict[str, tuple[str, Callable[[str], bool]]] = {
    "start": ("Server starten", lambda n: _app(n) and n.rsplit(".", 1)[-1].startswith("start")),
    "stop": ("Server stoppen", lambda n: _app(n) and n.rsplit(".", 1)[-1].startswith("stop")),
    "restart": ("Server neustarten", lambda n: _app(n) and "restart" in n),
    "console_view": ("Konsole lesen", lambda n: "console" in n and any(k in n for k in ("view", "read", "watch"))),
    "console_send": ("Konsole schreiben", lambda n: "console" in n and any(k in n for k in ("send", "write", "input", "command"))),
    "update": ("Spiel-Update", lambda n: _app(n) and "update" in n),
    "players": (
        "Spieler kicken/bannen",
        lambda n: any(k in n for k in ("kick", "ban")) and "usermanagement" not in n and "rolemanagement" not in n,
    ),
    "backup_use": ("Backups erstellen/wiederherstellen", lambda n: "backup" in n and any(k in n for k in ("take", "create", "restore"))),
    "backup_delete": ("Backups löschen", lambda n: "backup" in n and "delete" in n),
    "settings": ("Einstellungen", lambda n: n.startswith("settings.")),
    "files": ("Dateimanager", lambda n: n.startswith("filemanager.")),
    "scheduler": ("Zeitpläne", lambda n: n.startswith("core.scheduler.")),
    "audit": ("Audit-Log lesen", lambda n: n.startswith("core.auditlog.")),
}

TIERS: tuple[Tier, ...] = (
    Tier("helfer", "Gameserver Helfer", ("start", "stop", "restart", "console_view")),
    Tier("betreuer", "Gameserver Betreuer", ("start", "stop", "restart", "console_view", "console_send", "players", "backup_use", "update")),
    Tier(
        "admin",
        "Gameserver Admin",
        ("start", "stop", "restart", "console_view", "console_send", "players", "backup_use", "update", "settings", "files", "scheduler", "backup_delete"),
    ),
    Tier(
        "verwalter",
        "Gameserver Verwalter",
        ("start", "stop", "restart", "console_view", "console_send", "players", "backup_use", "update", "settings", "files", "scheduler", "backup_delete", "audit"),
    ),
)

# Stand der Rechte-Regeln - erhoehen, wenn sich TIERS/CAPABILITIES/DENY/Controller-Rechte
# aendern: dann gelten bereits eingerichtete Instanzen als veraltet und werden beim
# naechsten Einrichten wieder mitgenommen.
PLAN_VERSION = 2

# In jeder Instanz fuer alle Stufen ausdruecklich verboten (sonst koennte man sich selbst
# mehr Rechte geben); das Audit-Log nur fuer Stufen ohne "audit".
DENY = ("Core.UserManagement.*", "Core.RoleManagement.*")


def deny_for(tier: Tier) -> tuple[str, ...]:
    return DENY + (() if "audit" in tier.caps else ("Core.AuditLog.*",))


# --- Rechte-Baum ---------------------------------------------------------------------------


def leaves(spec) -> list[tuple[str, str]]:
    """(Knoten, Anzeigename) aller Blaetter des Baums aus GetPermissionsSpec."""
    found, stack = [], list(spec or [])
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        children = node.get("Children") or []
        if children:
            stack.extend(children)
        elif node.get("Node"):
            found.append((str(node["Node"]), str(node.get("DisplayName") or node.get("Name") or node["Node"])))
    return sorted(found)


def resolve_capabilities(spec) -> dict[str, list[str]]:
    """Faehigkeit -> passende Rechte-Knoten dieser Instanz."""
    nodes = leaves(spec)
    return {cap: [n for n, _ in nodes if test(n.lower())] for cap, (_, test) in CAPABILITIES.items()}


def instance_plan(spec) -> dict:
    """Pro Stufe: erlaubte Knoten, neutral zu setzende (gehoeren zu anderen Stufen), fehlende Faehigkeiten."""
    found = resolve_capabilities(spec)
    every = sorted({n for nodes in found.values() for n in nodes})
    plan = {}
    for tier in TIERS:
        allow = sorted({n for cap in tier.caps for n in found[cap]})
        plan[tier.key] = {
            "allow": allow,
            "neutral": [n for n in every if n not in allow],
            "missing": [CAPABILITIES[cap][0] for cap in tier.caps if not found[cap]],
        }
    return plan


# Je Spiel-Instanz am Controller: sehen/hineingehen und die Instanz selbst starten,
# stoppen, neustarten (eine gestoppte Instanz beantwortet sonst gar nichts).
INSTANCE_ACTIONS = ("manage", "start", "stop", "restart")

# Admins und Verwalter, am Controller: Instanzen anlegen, loeschen, umbauen und neu
# angelegte selbst verwalten (sonst koennte man die eigene neue Instanz nicht oeffnen).
ADMIN_CONTROLLER = ("createinstance", "deleteinstances", "reconfigure", "selfassigninstance")

# Nur Verwalter, am Controller zusaetzlich: AMP-Versionen der Instanzen hochziehen,
# Targets anbinden/entfernen/bearbeiten, Instanzen aussetzen, Konfiguration neu laden,
# Vorlagen und Store, Audit-Log. Fuer niemanden: Benutzer-/Rollenverwaltung, Einstellungen
# des Controllers, "beliebige Instanz starten/stoppen" (traefe auch die Instanz des Bots).
VERWALTER_CONTROLLER = (
    "upgradeinstances",
    "attachremoteadsinstance",
    "removeremoteadsinstance",
    "editremotetargets",
    "suspendinstances",
    "managesuspendedinstances",
    "refreshconfiguration",
    "refreshremoteconfigstores",
)
CONTROLLER_EXTRAS = {
    "admin": ("Instanzen anlegen, löschen und umbauen",),
    "verwalter": (
        "Instanzen anlegen, löschen und umbauen",
        "AMP-Versionen der Instanzen hochziehen",
        "Targets verwalten",
        "Instanzen aussetzen",
        "Vorlagen und Store",
    ),
}


def _verwalter_node(n: str) -> bool:
    n = n.lower()
    if n.startswith("ads.instancemanagement."):
        return n.rsplit(".", 1)[-1] in VERWALTER_CONTROLLER
    return n.startswith(("ads.templatemanagement.", "store.", "core.auditlog."))


def controller_plan(spec, instance_ids: dict[str, str], controller_ids: tuple[str, ...] = ()) -> dict:
    """Controller: Anmelden und je Spiel-Instanz Manage/Start/Stop/Restart.

    instance_ids: Instanz-ID -> Anzeigename."""
    nodes = [n for n, _ in leaves(spec)]
    # Anmelden am Panel = "Manage" auf der Instanz des Controllers selbst (ADS) - nur das,
    # nie dessen Start/Stop. Rueckfall: ein "...Manage" ausserhalb der Instanzen.
    login = [n for n in nodes if any(c.lower() in n.lower() for c in controller_ids) and n.lower().endswith(".manage")]
    if not login:
        login = [n for n in nodes if n.lower().endswith(".manage") and not n.lower().startswith("instances.")][:1]
    per_instance, missing = {}, []
    for iid, name in instance_ids.items():
        own = [n for n in nodes if n.lower().startswith("instances.") and iid.lower() in n.lower()]
        chosen = [n for n in own if n.rsplit(".", 1)[-1].lower() in INSTANCE_ACTIONS]
        if any(n.lower().endswith(".manage") for n in chosen):
            per_instance[name] = chosen
        else:
            missing.append(name)
    # Zur Fehlersuche: alle Controller-Rechte ausserhalb der Instanzen (Knoten = Anzeigename)
    other = [f"{n} = {name}" for n, name in leaves(spec) if not n.lower().startswith("instances.")]
    admin = [n for n in nodes if n.lower().startswith("ads.instancemanagement.") and n.rsplit(".", 1)[-1].lower() in ADMIN_CONTROLLER]
    verwalter = [n for n in nodes if _verwalter_node(n)]
    return {
        "login": login,
        "instances": per_instance,
        "missing_instances": missing,
        "admin": admin,
        "verwalter": verwalter,
        "other_nodes": other,
    }


# --- Ausfuehren ----------------------------------------------------------------------------


@dataclass
class SetupReport:
    controller: dict = field(default_factory=dict)
    instances: dict = field(default_factory=dict)  # Name -> Plan pro Stufe (oder Fehler)
    created_roles: list[str] = field(default_factory=list)
    changed: int = 0
    errors: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # schon eingerichtet, diesmal ausgelassen


def _short(error: Exception) -> str:
    """Erste Zeile der Fehlermeldung (AMP haengt sonst Stacktrace/"None" an)."""
    return (str(error).strip().splitlines() or [type(error).__name__])[0][:200]


def _role_ids(result) -> dict[str, str]:
    """GetRoleIds liefert {ID: Name} - umgedreht auf Name -> ID."""
    if isinstance(result, dict):
        return {str(name): str(rid) for rid, name in result.items()}
    return {}


async def run(
    controller_call: Call,
    instance_call: Callable[[str, str, dict], Awaitable[object]],
    instances: dict[str, str],
    *,
    apply: bool,
    controller_ids: tuple[str, ...] = (),
    only: set[str] | None = None,
) -> SetupReport:
    """Pruefen (apply=False) oder einrichten (apply=True).

    controller_call(endpoint, args) - Core-Endpunkt am Controller
    instance_call(instance_id, endpoint, args) - Core-Endpunkt in einer Instanz
    instances - Instanz-ID -> Anzeigename (nur Spiel-Instanzen)
    only - nur diese Instanz-IDs einrichten, am Controller wie in der Instanz (None = alle);
           angezeigt wird der Controller-Plan trotzdem fuer alle"""
    report = SetupReport()
    try:
        spec = await controller_call("GetPermissionsSpec", {})
    except Exception as error:
        report.errors.append(f"Rechte-Liste des Controllers nicht lesbar ({_short(error)}) – mit einem Super-Admin-Konto anmelden oder dem Bot kurz Super Admins geben.")
        return report
    report.controller = controller_plan(spec, instances, controller_ids)

    # Vorlage-Rollen ("Template Role" = AsCommonRole) haben in JEDER Instanz dieselben
    # Rechte, auch im ADS von Controller und Targets - Instanz-Rechte wie Dateimanager oder
    # Einstellungen landeten so auch dort. Die Rollen muessen globale Rollen sein (gleiche
    # Rolle ueberall, Rechte je Instanz eigen); eine Vorlage-Rolle laesst sich nicht umstellen.
    try:
        role_ids = _role_ids(await controller_call("GetRoleIds", {}))
        templates = []
        for tier in TIERS:
            if tier.name in role_ids:
                role = await controller_call("GetRole", {"RoleId": role_ids[tier.name]})
                if isinstance(role, dict) and role.get("IsCommonRole"):
                    templates.append(tier.name)
    except Exception as error:
        report.errors.append(f"Rollen des Controllers nicht lesbar ({_short(error)}) – fehlen Super-Admin-Rechte?")
        return report
    if templates:
        report.errors.append(
            f"{', '.join(templates)}: in AMP als Vorlage-Rolle (Template Role) angelegt – deren Rechte gelten überall "
            "gleich, auch im Controller. Bitte in AMP unter Configuration → Role Management löschen und dann erneut "
            "einrichten; der Bot legt sie als globale Rollen neu an."
        )
        return report

    if apply:
        try:
            for tier in TIERS:
                if tier.name not in role_ids:
                    await controller_call("CreateRole", {"Name": tier.name, "AsCommonRole": False})
                    report.created_roles.append(tier.name)
            if report.created_roles:
                role_ids = _role_ids(await controller_call("GetRoleIds", {}))
                only = None  # neue Rollen haben noch keine Rechte - alle Instanzen einrichten
            for tier in TIERS:
                rid = role_ids[tier.name]
                # am Controller auch nur die offenen Instanzen (Anmelden immer - ist nur ein Recht)
                todo = {name for iid, name in instances.items() if only is None or iid in only}
                nodes = report.controller["login"] + [
                    n for name, ns in report.controller["instances"].items() if name in todo for n in ns
                ]
                if tier.key in ("admin", "verwalter"):
                    nodes += report.controller["admin"]
                if tier.key == "verwalter":
                    nodes += report.controller["verwalter"]
                for node in nodes:
                    await controller_call("SetAMPRolePermission", {"RoleId": rid, "PermissionNode": node, "Enabled": True})
                    report.changed += 1
        except Exception as error:
            report.errors.append(f"Am Controller abgebrochen: {_short(error)} – fehlen Super-Admin-Rechte?")
            return report

    for iid, name in instances.items():
        if only is not None and iid not in only:
            report.skipped.append(name)
            continue
        try:
            plan = instance_plan(await instance_call(iid, "GetPermissionsSpec", {}))
        except Exception as error:
            if "Instance Unavailable" in str(error):
                report.instances[name] = {"error": "Instanz läuft nicht – starten und dann erneut einrichten"}
            else:
                report.instances[name] = {"error": f"Rechte-Liste nicht lesbar: {_short(error)}"}
            continue
        report.instances[name] = plan
        if not apply:
            continue
        try:
            local_ids = _role_ids(await instance_call(iid, "GetRoleIds", {}))
            for tier in TIERS:
                rid = local_ids.get(tier.name)
                if rid is None:
                    plan[tier.key]["error"] = "Rolle in dieser Instanz nicht vorhanden (Instanz neu starten und erneut einrichten)"
                    continue
                for node, enabled in (
                    [(n, True) for n in plan[tier.key]["allow"]]
                    + [(n, None) for n in plan[tier.key]["neutral"]]
                    + [(n, False) for n in deny_for(tier)]
                ):
                    await instance_call(iid, "SetAMPRolePermission", {"RoleId": rid, "PermissionNode": node, "Enabled": enabled})
                    report.changed += 1
        except Exception as error:
            report.instances[name]["error"] = f"abgebrochen: {_short(error)}"
    return report
