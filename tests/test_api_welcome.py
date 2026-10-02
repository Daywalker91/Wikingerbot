"""Begruessungs-API: Lesen/Speichern, Rechte, exakte Kanal-IDs."""

import httpx

from api.main import app
from api.middleware.auth import create_access_token
from bot.core import runtime
from bot.core.guild_config import get_config
from db.models.guild import Guild
from db.models.role import Level


async def _client(level: Level) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client.cookies.set("session", create_access_token(100, 1, level))
    return client


async def test_welcome_roundtrip(db_session, monkeypatch):
    monkeypatch.setattr(runtime, "bot", None)
    db_session.add(Guild(id=1, name="Wikinger"))
    await db_session.commit()

    async with await _client(Level.MOD) as client:
        assert (await client.get("/welcome")).status_code == 403

    async with await _client(Level.ADMIN) as client:
        initial = (await client.get("/welcome")).json()
        assert initial["config"]["channel_id"] is None and "{user}" in initial["config"]["message"]

        body = {**initial["config"], "channel_id": "1523404561895784448", "dm_message": "Regeln: …", "goodbye_enabled": True}
        assert (await client.put("/welcome", json=body)).status_code == 200
        assert (await client.put("/welcome", json={**body, "channel_id": "abc"})).status_code == 422
        saved = (await client.get("/welcome")).json()["config"]

    assert saved["channel_id"] == "1523404561895784448"
    assert await get_config(1, "welcome_channel_id") == "1523404561895784448"
    assert saved["goodbye_enabled"] is True and saved["dm_message"] == "Regeln: …"
