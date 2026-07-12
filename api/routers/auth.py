from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse

from api.middleware.auth import (
    SESSION_COOKIE,
    CurrentUser,
    create_access_token,
    create_state_token,
    get_current_user,
    hash_refresh_token,
    verify_state_token,
)
from bot.core.config import settings
from bot.core.permissions import has_owner_level_bypass, resolve_level
from db.models.role import Level
from db.models.web_session import WebSession
from db.session import get_db_session

router = APIRouter(prefix="/auth", tags=["auth"])

DISCORD_API = "https://discord.com/api"


@router.get("/login")
async def login(guild_id: int = Query(...)) -> RedirectResponse:
    """Leitet zum Discord-Authorize-Screen fuer die angegebene Guild weiter."""
    state = create_state_token(guild_id)
    params = {
        "client_id": settings.discord_client_id,
        "redirect_uri": settings.discord_redirect_uri,
        "response_type": "code",
        "scope": "identify guilds.members.read",
        "state": state,
    }
    return RedirectResponse(f"{DISCORD_API}/oauth2/authorize?{urlencode(params)}")


@router.get("/callback")
async def callback(code: str, state: str) -> RedirectResponse:
    guild_id = verify_state_token(state)

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": settings.discord_client_id,
                "client_secret": settings.discord_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.discord_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Discord-Token-Austausch fehlgeschlagen")
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
    redirect = RedirectResponse(f"{settings.frontend_url}/dashboard")
    redirect.set_cookie(SESSION_COOKIE, access, httponly=True, samesite="lax")
    return redirect


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    """Session-Introspektion fuers Frontend - wer ist gerade eingeloggt, ohne Reload."""
    return {"user_id": user.user_id, "guild_id": user.guild_id, "level": user.level.value}
