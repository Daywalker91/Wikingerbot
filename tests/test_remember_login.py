"""Web-Oberflaeche: "Angemeldet bleiben" - Token ersetzt die abgelaufene Sitzung, Abmelden loescht es."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select, update

from api.main import app
from api.middleware.auth import REMEMBER_COOKIE, create_remember_token, hash_refresh_token
from bot.core import runtime
from db.models.role import Level
from db.models.web_session import RememberToken
from db.session import get_db_session


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_remember_token_renews_session_and_logout_forgets_it(db_session, monkeypatch):
    monkeypatch.setattr(runtime, "bot", None)
    token = await create_remember_token(100, 1, Level.ADMIN)
    async with get_db_session() as db:
        row = (await db.execute(select(RememberToken))).scalar_one()
    assert row.token_hash == hash_refresh_token(token) and token not in row.token_hash  # nur der Hash

    async with _client() as client:
        assert (await client.get("/auth/me")).status_code == 401  # ohne alles
        client.cookies.set(REMEMBER_COOKIE, token)
        me = await client.get("/auth/me")
        assert me.status_code == 200 and me.json()["level"] == "admin"
        assert "session=" in me.headers.get("set-cookie", "")  # neue kurze Sitzung ausgestellt

        await client.post("/auth/logout")
    async with get_db_session() as db:
        assert (await db.execute(select(RememberToken))).scalar_one_or_none() is None

    async with _client() as client:
        client.cookies.set(REMEMBER_COOKIE, token)
        assert (await client.get("/auth/me")).status_code == 401  # nach dem Abmelden ungueltig


async def test_expired_or_unknown_remember_token_is_refused(db_session, monkeypatch):
    monkeypatch.setattr(runtime, "bot", None)
    token = await create_remember_token(100, 1, Level.MEMBER)
    async with get_db_session() as db:
        await db.execute(update(RememberToken).values(expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)))
        await db.commit()
    async with _client() as client:
        client.cookies.set(REMEMBER_COOKIE, token)
        assert (await client.get("/auth/me")).status_code == 401
        client.cookies.set(REMEMBER_COOKIE, "geraten")
        assert (await client.get("/auth/me")).status_code == 401
