"""AMP-Konten fuer Mitglieder der Community-Seite (ohne Discord-Abhaengigkeit, testbar).

Ablauf: Antrag auf der Seite (amp.request) -> Konto anlegen, Startpasswort (muss
beim ersten Login geaendert werden), Rolle nach Rang. Rang geaendert -> Rolle
anpassen; Rang ohne AMP-Zugang -> Konto sperren (nie loeschen).

Grenzen, fest eingebaut:
- Der Bot fasst nur Konten an, die er selbst angelegt hat (Tabelle amp_accounts).
- Super Admins und die eigene Rolle des Bots werden nie vergeben.
- Das Passwort steht nur in der DM - nie im Log, nie in der Datenbank.

`core_call(endpoint, args)` ist AMPClient.core_call - als Parameter, damit testbar.
"""

import json
import logging
import re
import secrets
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import func, select, update

from bot.community import db as community_db
from bot.core.amp_role import ROLE_NAME, SUPER_ADMIN_ROLE, is_permission_error, role_name_to_id
from bot.core.bot_settings import get_bot_setting, set_bot_setting
from db.models.amp_account import AmpAccount
from db.session import get_db_session

log = logging.getLogger("wikingerbot.ampkonten")

CoreCall = Callable[[str, dict], Awaitable[object]]
MAP_KEY = "ampkonten_map"  # {Rang-Slug: AMP-Rollen-ID}
URL_KEY = "ampkonten_url"  # oeffentliche Adresse des Panels fuer die DM
# Optional: Zusatzrolle der Seite (Slug), ohne die es keinen Zugang gibt - z.B. eine
# Gameserver-Rolle. Mit ihr entscheidet weiter der Rang ueber die AMP-Rolle.
REQUIRES_KEY = "ampkonten_requires"
CACHE_KEY = "amp_roles_cache"  # {Name: ID}, gemerkt solange lesbar (bot/core/bot.py)
FORBIDDEN_ROLES = {SUPER_ADMIN_ROLE, ROLE_NAME}
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


class AmpError(Exception):
    """Meldung, die so in amp_note / die Oberflaeche kann."""


@dataclass
class SiteMember:
    id: int
    username: str
    rank_slug: str
    discord_id: int | None
    banned: bool
    deleted: bool
    extra_slugs: frozenset[str] = frozenset()


@dataclass
class Outcome:
    status: str  # active | denied | disabled
    note: str = ""
    amp_username: str | None = None
    password: str | None = None  # nur fuer die DM


def generate_password(length: int = 14) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def username_for(site_username: str, site_user_id: int) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]", "", site_username.replace(" ", "_"))[:24]
    return name if len(name) >= 3 else f"wikinger{site_user_id}"


def _ok(result) -> object:
    """AMP-ActionResult pruefen: {"Status": false, "Reason": ...} -> AmpError."""
    if isinstance(result, dict) and result.get("Status") is False:
        raise AmpError(result.get("Reason") or "AMP hat abgelehnt")
    return result.get("Result") if isinstance(result, dict) and "Result" in result else result


# --- Einstellungen --------------------------------------------------------------------


async def load_map() -> dict[str, str]:
    try:
        return {k: str(v) for k, v in json.loads(await get_bot_setting(MAP_KEY, "{}") or "{}").items() if v}
    except json.JSONDecodeError:
        return {}


async def load_requirement() -> str:
    return (await get_bot_setting(REQUIRES_KEY, "") or "").strip()


async def role_for(member: SiteMember) -> tuple[str | None, str | None]:
    """(AMP-Rolle, fehlende Zusatzrolle). Rolle None: kein Zugang - wegen der fehlenden
    Zusatzrolle (zweiter Wert = ihr Name) oder weil der Rang keinen hat (zweiter Wert None)."""
    required = await load_requirement()
    if required and required not in member.extra_slugs:
        return None, await _extra_role_name(required)
    return (await load_map()).get(member.rank_slug), None


async def _extra_role_name(slug: str) -> str:
    r = community_db.roles
    async with community_db.session() as db:
        name = (await db.execute(select(r.c.name).where(r.c.slug == slug))).scalar_one_or_none()
    return name or slug


async def available_roles(core_call: CoreCall | None) -> tuple[dict[str, str], bool]:
    """AMP-Rollen (Name -> ID) ohne Super Admins und die Bot-Rolle. Zweiter Wert:
    True = frisch aus AMP, False = gemerkte Liste (der Bot darf Rollen nicht mehr lesen)."""
    roles, fresh = {}, False
    if core_call is not None:
        try:
            roles = role_name_to_id(await core_call("GetRoleIds", {}))
            fresh = True
            await set_bot_setting(CACHE_KEY, json.dumps(roles))
        except Exception as error:
            if not is_permission_error(error):
                log.info("AMP-Rollen nicht lesbar: %s", error)
    if not roles:
        try:
            roles = json.loads(await get_bot_setting(CACHE_KEY, "{}") or "{}")
        except json.JSONDecodeError:
            roles = {}
    return {name: rid for name, rid in roles.items() if name not in FORBIDDEN_ROLES}, fresh


async def allowed_role_ids() -> set[str]:
    roles, _ = await available_roles(None)
    return set(roles.values())


# --- Seite ----------------------------------------------------------------------------


async def site_member(site_user_id: int) -> SiteMember | None:
    u, r = community_db.users, community_db.roles
    async with community_db.session() as db:
        row = (
            await db.execute(
                select(u.c.id, u.c.username, r.c.slug, u.c.discord_id, u.c.is_banned, u.c.deleted_at)
                .select_from(u.join(r, r.c.id == u.c.role_id))
                .where(u.c.id == site_user_id)
            )
        ).first()
    if row is None:
        return None
    extras: frozenset[str] = frozenset()
    if await community_db.extras_available():
        x = community_db.user_extra_roles
        async with community_db.session() as db:
            extras = frozenset(
                s for (s,) in (
                    await db.execute(select(r.c.slug).select_from(x.join(r, r.c.id == x.c.role_id)).where(x.c.user_id == site_user_id))
                ).all()
            )
    return SiteMember(row[0], row[1], row[2], row[3], bool(row[4]), row[5] is not None, extras)


async def write_site_status(site_user_id: int, outcome: Outcome) -> None:
    values = {"amp_status": outcome.status, "amp_note": outcome.note[:255] or None, "amp_updated_at": func.now()}
    if outcome.amp_username:
        values["amp_username"] = outcome.amp_username
    async with community_db.session() as db:
        await db.execute(update(community_db.users).where(community_db.users.c.id == site_user_id).values(**values))
        await db.commit()


# --- AMP ------------------------------------------------------------------------------


async def own_account(site_user_id: int) -> AmpAccount | None:
    async with get_db_session() as db:
        return await db.get(AmpAccount, site_user_id)


async def _save_account(account: AmpAccount) -> None:
    async with get_db_session() as db:
        await db.merge(account)
        await db.commit()


async def _set_password(core_call: CoreCall, username: str) -> str:
    password = generate_password()
    _ok(await core_call("ResetUserPassword", {"Username": username, "NewPassword": password}))
    _ok(
        await core_call(
            "UpdateUserInfo",
            {
                "Username": username, "Disabled": False, "PasswordExpires": False,
                "CannotChangePassword": False, "MustChangePassword": True, "EmailAddress": "",
            },
        )
    )
    return password


async def _set_disabled(core_call: CoreCall, username: str, disabled: bool) -> None:
    _ok(
        await core_call(
            "UpdateUserInfo",
            {
                "Username": username, "Disabled": disabled, "PasswordExpires": False,
                "CannotChangePassword": False, "MustChangePassword": False, "EmailAddress": "",
            },
        )
    )


async def _set_role(core_call: CoreCall, account: AmpAccount, role_id: str) -> None:
    """Genau die Rolle des Rangs - vom Bot frueher vergebene andere Rollen weg.
    Rollen, die jemand von Hand gegeben hat, bleiben unberuehrt."""
    if role_id not in await allowed_role_ids():
        raise AmpError("Diese AMP-Rolle darf der Bot nicht vergeben.")
    given = set(json.loads(account.role_ids or "[]"))
    for old in given - {role_id}:
        _ok(await core_call("SetAMPUserRoleMembership", {"UserId": account.amp_user_id, "RoleId": old, "IsMember": False}))
    if role_id not in given:
        _ok(await core_call("SetAMPUserRoleMembership", {"UserId": account.amp_user_id, "RoleId": role_id, "IsMember": True}))
    account.role_ids = json.dumps([role_id])


async def _user_exists(core_call: CoreCall, username: str) -> bool:
    info = await core_call("GetAMPUserInfo", {"Username": username})
    return isinstance(info, dict) and bool(info.get("ID"))


async def handle_request(core_call: CoreCall, site_user_id: int) -> Outcome:
    member = await site_member(site_user_id)
    if member is None or member.deleted:
        return Outcome("denied", "Konto nicht gefunden.")
    if member.banned:
        return Outcome("denied", "Dein Konto ist gesperrt.")
    if not member.discord_id:
        return Outcome("denied", "Verknüpfe zuerst Discord – dorthin kommen die Zugangsdaten.")
    role_id, missing = await role_for(member)
    if missing:
        return Outcome("denied", f"Für einen AMP-Zugang brauchst du die Zusatzrolle „{missing}“.")
    if not role_id:
        return Outcome("denied", "Dein Rang hat (noch) keinen AMP-Zugang.")

    account = await own_account(site_user_id)
    if account is None:
        username = username_for(member.username, member.id)
        if await _user_exists(core_call, username):
            username = f"{username[:20]}-{member.id}"
            if await _user_exists(core_call, username):
                raise AmpError(f"Der AMP-Name {username} ist schon vergeben – bitte ein Ticket schreiben.")
        _ok(await core_call("CreateUser", {"Username": username}))
        info = await core_call("GetAMPUserInfo", {"Username": username})
        if not isinstance(info, dict) or not info.get("ID"):
            raise AmpError("AMP hat das Konto nicht angelegt.")
        account = AmpAccount(site_user_id=site_user_id, amp_user_id=str(info["ID"]), amp_username=username, disabled=False, role_ids="[]")
        log.info("AMP-Konto %s fuer %s angelegt", username, member.username)
    password = await _set_password(core_call, account.amp_username)  # setzt auch Disabled=False
    account.disabled = False
    await _set_role(core_call, account, role_id)
    await _save_account(account)
    return Outcome("active", "", account.amp_username, password)


async def handle_reset(core_call: CoreCall, site_user_id: int) -> Outcome:
    account = await own_account(site_user_id)
    if account is None or account.disabled:
        return Outcome("denied", "Kein aktives AMP-Konto – bitte neu beantragen.")
    password = await _set_password(core_call, account.amp_username)
    return Outcome("active", "", account.amp_username, password)


async def handle_disable(core_call: CoreCall, site_user_id: int, note: str = "Konto gelöscht.") -> Outcome | None:
    account = await own_account(site_user_id)
    if account is None or account.disabled:
        return None
    await _set_disabled(core_call, account.amp_username, True)
    account.disabled = True
    await _save_account(account)
    log.info("AMP-Konto %s gesperrt (%s)", account.amp_username, note)
    return Outcome("disabled", note, account.amp_username)


async def apply_rank(core_call: CoreCall, site_user_id: int) -> Outcome | None:
    """Rang oder Zusatzrollen geaendert: Rolle anpassen oder sperren. None = kein eigenes Konto, nichts zu tun."""
    account = await own_account(site_user_id)
    member = await site_member(site_user_id)
    if account is None or member is None:
        return None
    role_id, missing = await role_for(member)
    if not role_id or member.banned or member.deleted:
        note = f"Ohne die Zusatzrolle „{missing}“ gibt es keinen AMP-Zugang mehr." if missing else "Dein Rang hat keinen AMP-Zugang mehr."
        return await handle_disable(core_call, site_user_id, note)
    if account.disabled:
        await _set_disabled(core_call, account.amp_username, False)
        account.disabled = False
    await _set_role(core_call, account, role_id)
    await _save_account(account)
    return Outcome("active", "", account.amp_username)


async def accounts_overview() -> list[dict]:
    async with get_db_session() as db:
        rows = (await db.execute(select(AmpAccount).order_by(AmpAccount.amp_username))).scalars().all()
    return [
        {"site_user_id": a.site_user_id, "amp_username": a.amp_username, "disabled": a.disabled, "role_ids": json.loads(a.role_ids or "[]")}
        for a in rows
    ]
