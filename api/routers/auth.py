import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse

from api.middleware.auth import (
    OAUTH_NONCE_COOKIE,
    SESSION_COOKIE,
    CurrentUser,
    create_access_token,
    create_state_token,
    get_current_user,
    hash_refresh_token,
    verify_state_token,
)
from bot.core import runtime
from bot.core.config import settings
from bot.core.permissions import has_owner_level_bypass, resolve_level
from db.models.role import Level
from db.models.web_session import WebSession
from db.session import get_db_session

router = APIRouter(prefix="/auth", tags=["auth"])

DISCORD_API = "https://discord.com/api"


def redirect_uri(request: Request) -> str:
    """Discord-Redirect: fest eingestellt - oder (Web-Oberflaeche im Bot ohne
    PUBLIC_URL) die Adresse, unter der der Browser die API gerade aufruft.
    Login und Callback laufen ueber denselben Host, der Wert ist also beide
    Male gleich - so wie Discord es verlangt."""
    if settings.discord_redirect_uri:
        return settings.discord_redirect_uri
    # Pfad aus der aufgerufenen URL statt base_url: so bleibt das Praefix /api
    # erhalten, unter dem die API in der Web-Oberflaeche eingehaengt ist.
    path = request.url.path
    prefix = path[: path.rfind("/auth/")]
    return f"{request.url.scheme}://{request.url.netloc}{prefix}/auth/callback"


def client_id() -> str:
    """OAuth2-Client-ID = Application-ID des Bots - laeuft der Bot im selben
    Prozess, muss sie also nicht extra eingetragen werden."""
    if settings.discord_client_id:
        return settings.discord_client_id
    if runtime.bot is not None and runtime.bot.application_id:
        return str(runtime.bot.application_id)
    return ""


def missing_oauth_settings() -> list[str]:
    missing = []
    if not client_id():
        missing.append("Discord Client ID")
    if not settings.discord_client_secret:
        missing.append("Discord Client Secret")
    return missing


@router.get("/guilds")
async def guilds() -> list[dict]:
    """Discord-Server, an denen man sich anmelden kann (fuer die Login-Seite):
    alle, auf denen der laufende Bot ist - oder DISCORD_GUILD_ID, wenn die API
    ohne Bot laeuft. IDs als String, JavaScript kann 64-Bit-Zahlen nicht exakt."""
    if runtime.bot is not None and runtime.bot.guilds:
        return [{"id": str(g.id), "name": g.name} for g in runtime.bot.guilds]
    if settings.discord_guild_id:
        return [{"id": str(settings.discord_guild_id), "name": "Discord-Server"}]
    return []


@router.get("/login")
async def login(request: Request, guild_id: int = Query(...)):
    """Leitet zum Discord-Authorize-Screen fuer die angegebene Guild weiter."""
    missing = missing_oauth_settings()
    if missing:
        return PlainTextResponse(
            f"Anmeldung noch nicht eingerichtet: {' und '.join(missing)} fehlt.\n\n"
            "In AMP unter Konfiguration -> Web-Oberflaeche eintragen (Discord Developer Portal, "
            "Seite OAuth2) und den Bot neu starten.",
            status_code=503,
        )
    nonce = secrets.token_urlsafe(16)
    state = create_state_token(guild_id, nonce)
    params = {
        "client_id": client_id(),
        "redirect_uri": redirect_uri(request),
        "response_type": "code",
        "scope": "identify guilds.members.read",
        "state": state,
    }
    response = RedirectResponse(f"{DISCORD_API}/oauth2/authorize?{urlencode(params)}")
    # Bindet die Anmeldung an diesen Browser (Lax: kommt beim Ruecksprung von Discord mit)
    response.set_cookie(
        OAUTH_NONCE_COOKIE, nonce, max_age=600, httponly=True, samesite="lax",
        secure=(settings.frontend_url or str(request.url)).startswith("https://"),
    )
    return response


def login_error(reason: str) -> RedirectResponse:
    """Zurueck zur Login-Seite mit verstaendlichem Hinweis statt einer Fehlerseite."""
    return RedirectResponse(f"{settings.frontend_url}/login?error={reason}")


@router.get("/callback")
async def callback(request: Request, state: str = "", code: str = "", error: str = "") -> RedirectResponse:
    if error or not code:  # z.B. bei Discord auf "Abbrechen" getippt
        return login_error("denied")
    try:
        guild_id = verify_state_token(state, request.cookies.get(OAUTH_NONCE_COOKIE, ""))
    except HTTPException:  # abgelaufen oder in einem anderen Browser begonnen
        return login_error("failed")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": client_id(),
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(request),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            return login_error("failed")
        tokens = token_resp.json()
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]
        expires_in = tokens["expires_in"]

        auth_header = {"Authorization": f"Bearer {access_token}"}

        user_resp = await client.get(f"{DISCORD_API}/users/@me", headers=auth_header)
        user_resp.raise_for_status()
        user_id = int(user_resp.json()["id"])

        member_resp = await client.get(
            f"{DISCORD_API}/users/@me/guilds/{guild_id}/member", headers=auth_header
        )
        if member_resp.status_code in (403, 404):  # nicht auf diesem Discord-Server
            return login_error("not_member")
        member_resp.raise_for_status()
        member = member_resp.json()

        role_ids = [int(role_id) for role_id in member.get("roles", [])]
        has_bypass = await has_owner_level_bypass(client, guild_id, user_id, role_ids)

    level = Level.OWNER if has_bypass else await resolve_level(guild_id, role_ids)

    async with get_db_session() as db:
        db.add(
            WebSession(
                user_id=user_id,
                refresh_token_hash=hash_refresh_token(refresh_token),
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            )
        )
        await db.commit()

    access = create_access_token(user_id, guild_id, level)
    # Leere frontend_url: Seite und API kommen vom selben Host (Web-Oberflaeche im Bot)
    redirect = RedirectResponse(f"{settings.frontend_url}/dashboard")
    redirect.set_cookie(
        SESSION_COOKIE,
        access,
        httponly=True,
        samesite="lax",
        secure=(settings.frontend_url or str(request.url)).startswith("https://"),
    )
    return redirect


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Session-Introspektion fuers Frontend - wer ist gerade eingeloggt, ohne Reload."""
    from api.middleware.auth import member_role_ids
    from bot.core.capabilities import member_capabilities

    # IDs als Text - siehe api/types.py
    return {
        "user_id": str(user.user_id),
        "guild_id": str(user.guild_id),
        "level": user.level.value,
        # Faehigkeiten (z.B. server.control) - Stufe oder zugeordnete Discord-Rolle
        "capabilities": await member_capabilities(user.guild_id, user.level, member_role_ids(user)),
    }
