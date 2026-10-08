import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from jose import JWTError, jwt

from bot.core.config import settings
from db.models.role import Level, level_at_least

SESSION_COOKIE = "session"
OAUTH_NONCE_COOKIE = "oauth_nonce"
OAUTH_REMEMBER_COOKIE = "oauth_remember"  # Haken "Angemeldet bleiben" ueber den Discord-Umweg
REMEMBER_COOKIE = "remember"
REMEMBER_DAYS = 30


@dataclass
class CurrentUser:
    user_id: int
    guild_id: int
    level: Level


def create_access_token(user_id: int, guild_id: int, level: Level) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "guild_id": guild_id,
        "level": level.value,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_state_token(guild_id: int, nonce: str | None = None) -> str:
    """Signierter, kurzlebiger State-Token fuer den OAuth2-Redirect (CSRF-Schutz).
    nonce steht zusaetzlich in einem Cookie des Browsers (OAUTH_NONCE_COOKIE) - so gilt
    der Rueckweg nur fuer den Browser, der die Anmeldung begonnen hat."""
    payload = {
        "guild_id": guild_id,
        "nonce": nonce or secrets.token_urlsafe(16),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        "type": "oauth_state",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_state_token(state: str, nonce: str | None = None) -> int:
    """guild_id aus dem State. Mit nonce: muss zum Cookie des Browsers passen."""
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="Ungueltiger oder abgelaufener state-Parameter") from exc
    if payload.get("type") != "oauth_state":
        raise HTTPException(status_code=400, detail="Ungueltiger state-Parameter")
    if nonce is not None and not secrets.compare_digest(str(payload.get("nonce", "")), nonce):
        raise HTTPException(status_code=400, detail="Anmeldung wurde in einem anderen Browser begonnen")
    return int(payload["guild_id"])


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def cookie_secure(request: Request) -> bool:
    return (settings.frontend_url or str(request.url)).startswith("https://")


def set_session_cookie(response: Response, request: Request, access: str) -> None:
    response.set_cookie(SESSION_COOKIE, access, httponly=True, samesite="lax", secure=cookie_secure(request))


def set_remember_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        REMEMBER_COOKIE, token, max_age=REMEMBER_DAYS * 86400, httponly=True, samesite="lax", secure=cookie_secure(request)
    )


async def create_remember_token(user_id: int, guild_id: int, level: Level) -> str:
    """Neues "Angemeldet bleiben"-Token; in der Datenbank nur der Hash. Raeumt Abgelaufene weg."""
    from sqlalchemy import delete

    from db.models.web_session import RememberToken
    from db.session import get_db_session

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with get_db_session() as db:
        await db.execute(delete(RememberToken).where(RememberToken.expires_at < now))
        db.add(
            RememberToken(
                user_id=user_id, guild_id=guild_id, level=level.value, token_hash=hash_refresh_token(token),
                expires_at=now + timedelta(days=REMEMBER_DAYS),
            )
        )
        await db.commit()
    return token


async def forget_remember_token(token: str | None) -> None:
    if not token:
        return
    from sqlalchemy import delete

    from db.models.web_session import RememberToken
    from db.session import get_db_session

    async with get_db_session() as db:
        await db.execute(delete(RememberToken).where(RememberToken.token_hash == hash_refresh_token(token)))
        await db.commit()


async def _user_from_remember_token(token: str) -> CurrentUser | None:
    """Gueltiges Token -> Nutzer; verlaengert die Laufzeit (wer die Seite nutzt, bleibt angemeldet)."""
    from sqlalchemy import select

    from db.models.web_session import RememberToken
    from db.session import get_db_session

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with get_db_session() as db:
        row = (
            await db.execute(select(RememberToken).where(RememberToken.token_hash == hash_refresh_token(token)))
        ).scalar_one_or_none()
        if row is None or row.expires_at < now:
            return None
        row.expires_at = now + timedelta(days=REMEMBER_DAYS)
        await db.commit()
        return CurrentUser(user_id=row.user_id, guild_id=row.guild_id, level=Level(row.level))


def _user_from_session(session: str | None) -> CurrentUser | None:
    if not session:
        return None
    try:
        payload = jwt.decode(session, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    return CurrentUser(user_id=int(payload["sub"]), guild_id=int(payload["guild_id"]), level=Level(payload["level"]))


async def get_current_user(
    request: Request,
    response: Response,
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    remember: str | None = Cookie(default=None, alias=REMEMBER_COOKIE),
) -> CurrentUser:
    user = _user_from_session(session)
    if user is None and remember:
        # Sitzung abgelaufen, aber "Angemeldet bleiben": neue Sitzung ausstellen
        user = await _user_from_remember_token(remember)
        if user is not None:
            set_session_cookie(response, request, create_access_token(user.user_id, user.guild_id, user.level))
            set_remember_cookie(response, request, remember)
    if user is None:
        detail = "Session ungueltig" if session else "Nicht eingeloggt"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)
    return await _with_live_level(user)


async def _with_live_level(user: CurrentUser) -> CurrentUser:
    """Stufe bei jedem Aufruf frisch aus Discord statt der beim Login gemerkten: wer eine
    Rolle verliert oder den Server verlaesst, verliert die Rechte sofort - nicht erst,
    wenn die Sitzung ablaeuft. Ohne laufenden Bot (oder solange er die Mitglieder noch
    nicht kennt) gilt die Stufe aus dem Login."""
    from bot.core import runtime
    from bot.core.permissions import resolve_level

    get_guild = getattr(runtime.bot, "get_guild", None)
    guild = get_guild(user.guild_id) if get_guild else None
    if guild is None or not getattr(guild, "chunked", False):
        return user
    member = guild.get_member(user.user_id)
    if member is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht mehr auf dem Discord-Server")
    if member.guild_permissions.administrator:  # auch der Server-Owner
        level = Level.OWNER
    else:
        level = await resolve_level(guild.id, [role.id for role in member.roles])
    return CurrentUser(user_id=user.user_id, guild_id=user.guild_id, level=level)


def require_level(minimum: Level):
    """FastAPI-Dependency: erfordert mindestens das angegebene Level."""

    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not level_at_least(user.level, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Unzureichende Berechtigung"
            )
        return user

    return dependency


def member_role_ids(user: CurrentUser) -> list[int]:
    """Discord-Rollen des Eingeloggten - aus dem laufenden Bot (die API laeuft im Bot-Prozess)."""
    from bot.core import runtime

    guild = runtime.bot.get_guild(user.guild_id) if runtime.bot else None
    member = guild.get_member(user.user_id) if guild else None
    return [role.id for role in member.roles] if member else []


def require_capability(capability: str):
    """FastAPI-Dependency: Standard-Stufe der Faehigkeit ODER eine zugeordnete Discord-Rolle
    (bot/core/capabilities.py)."""

    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        from bot.core.capabilities import allowed

        if await allowed(user.guild_id, capability, user.level, member_role_ids(user)):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unzureichende Berechtigung")

    return dependency
