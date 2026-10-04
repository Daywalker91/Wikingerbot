import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt

from bot.core.config import settings
from db.models.role import Level, level_at_least

SESSION_COOKIE = "session"


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


def create_state_token(guild_id: int) -> str:
    """Signierter, kurzlebiger State-Token fuer den OAuth2-Redirect (CSRF-Schutz)."""
    payload = {
        "guild_id": guild_id,
        "nonce": secrets.token_urlsafe(16),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        "type": "oauth_state",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_state_token(state: str) -> int:
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=400, detail="Ungueltiger oder abgelaufener state-Parameter") from exc
    if payload.get("type") != "oauth_state":
        raise HTTPException(status_code=400, detail="Ungueltiger state-Parameter")
    return int(payload["guild_id"])


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_current_user(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> CurrentUser:
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht eingeloggt")
    try:
        payload = jwt.decode(session, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session ungueltig") from exc
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session ungueltig")
    return CurrentUser(
        user_id=int(payload["sub"]),
        guild_id=int(payload["guild_id"]),
        level=Level(payload["level"]),
    )


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
