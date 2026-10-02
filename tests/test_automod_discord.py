"""automod-Cog: Warn-Punkte aus Discords eigenem AutoMod (frueher im moderation-Cog)."""

import json
from types import SimpleNamespace

import httpx

from api.main import app
from api.middleware.auth import create_access_token
from bot.cogs.automod.cog import (
    DEFAULT_AUTOMOD_POINTS,
    automod_points,
    automod_points_for,
    build_automod_reason,
    resolve_alert_channel,
)
from bot.cogs.moderation.cog import _modlog_channel
from bot.core import runtime
from bot.core.guild_config import get_config, set_config
from db.models.guild import Guild
from db.models.role import Level


async def _seed_guild(db_session, guild_id: int = 1):
    db_session.add(Guild(id=guild_id, name="Wikinger"))
    await db_session.commit()


async def test_points_default_unknown_and_override(db_session):
    await _seed_guild(db_session)
    assert await automod_points_for(1, "keyword") == DEFAULT_AUTOMOD_POINTS["keyword"]
    assert await automod_points_for(1, "future_trigger_type") == 1
    # bisher gespeicherte Werte (aus der Zeit im moderation-Cog) gelten weiter
    await set_config(1, "automod_warn_points", json.dumps({"keyword": 9}))
    assert await automod_points_for(1, "keyword") == 9
    assert (await automod_points(1))["spam"] == DEFAULT_AUTOMOD_POINTS["spam"]


def test_build_reason():
    assert build_automod_reason("spam", None) == "AutoMod: spam"
    assert build_automod_reason("keyword", "boese") == "AutoMod: keyword (Treffer: 'boese')"


async def test_alert_channel_prefers_configured(db_session):
    await _seed_guild(db_session)
    bot = SimpleNamespace(get_channel=lambda cid: f"channel-{cid}")
    assert await resolve_alert_channel(bot, 1, fallback_channel_id=111) == "channel-111"
    await set_config(1, "automod_alert_channel_id", "999")
    assert await resolve_alert_channel(bot, 1, fallback_channel_id=111) == "channel-999"


async def test_modlog_takes_over_old_shared_channel_once(db_session):
    """Frueher nutzte die Moderation ohne eigenen Log-Kanal den AutoMod-Kanal mit.
    Der wird einmal uebernommen - danach sind beide unabhaengig."""
    await _seed_guild(db_session)
    await set_config(1, "automod_alert_channel_id", "777")
    bot = SimpleNamespace(get_channel=lambda cid: f"channel-{cid}")

    assert await _modlog_channel(bot, 1) == "channel-777"
    assert await get_config(1, "modlog_channel_id") == "777"

    await set_config(1, "automod_alert_channel_id", "888")  # AutoMod-Kanal aendern ...
    assert await _modlog_channel(bot, 1) == "channel-777"  # ... Moderation bleibt


async def test_modlog_explicitly_off_does_not_take_over(db_session):
    await _seed_guild(db_session)
    await set_config(1, "modlog_channel_id", "")
    await set_config(1, "automod_alert_channel_id", "777")
    assert await _modlog_channel(SimpleNamespace(get_channel=lambda cid: cid), 1) is None


async def _client(level):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client.cookies.set("session", create_access_token(100, 1, level))
    return client


async def test_automod_api_roundtrip(db_session, monkeypatch):
    await _seed_guild(db_session)
    monkeypatch.setattr(runtime, "bot", None)

    async with await _client(Level.MOD) as client:
        assert (await client.get("/automod/config")).status_code == 403

    async with await _client(Level.ADMIN) as client:
        data = (await client.get("/automod/config")).json()
        config = data["config"]
        assert config["discord"]["enabled"] is False and config["rules"]["enabled"] is False
        assert data["trigger_labels"]["spam"] == "Spam"

        config["discord"] = {"enabled": True, "points": {**config["discord"]["points"], "spam": 4, "erfunden": 7}}
        config["rules"]["enabled"] = True
        config["rules"]["flood"]["messages"] = 10
        config["rules"]["links"] = {"mode": "allowlist", "allow": ["WWW.YouTube.com", " ", "youtube.com"]}
        config["rules"]["exempt_channels"] = ["1523404561895784448"]
        config["alert_channel_id"] = "1523404561895784449"
        assert (await client.put("/automod/config", json=config)).status_code == 200

        bad = json.loads(json.dumps(config))
        bad["rules"]["flood"]["messages"] = 500
        assert (await client.put("/automod/config", json=bad)).status_code == 422

        saved = (await client.get("/automod/config")).json()["config"]

    assert saved["discord"]["enabled"] is True and saved["discord"]["points"]["spam"] == 4
    assert "erfunden" not in saved["discord"]["points"]
    assert saved["rules"]["flood"]["messages"] == 10
    assert saved["rules"]["links"]["allow"] == ["youtube.com"]
    assert saved["rules"]["exempt_channels"] == ["1523404561895784448"]  # exakt, nicht gerundet
    assert saved["alert_channel_id"] == "1523404561895784449"
    # Moderation sieht davon nichts mehr
    assert await get_config(1, "modlog_channel_id") is None
