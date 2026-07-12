import json
from types import SimpleNamespace

from bot.cogs.moderation.cog import (
    DEFAULT_AUTOMOD_POINTS,
    _apply_warning,
    _automod_points_for,
    _build_automod_reason,
    _resolve_automod_channel,
)
from bot.core.guild_config import set_config
from db.models.guild import Guild
from db.models.modlog import Warning


async def _seed_guild(db_session, guild_id: int = 1):
    db_session.add(Guild(id=guild_id, name="Wikinger"))
    await db_session.commit()


async def test_automod_points_for_returns_default_weight(db_session):
    await _seed_guild(db_session)

    assert await _automod_points_for(1, "keyword") == DEFAULT_AUTOMOD_POINTS["keyword"]
    assert await _automod_points_for(1, "spam") == DEFAULT_AUTOMOD_POINTS["spam"]


async def test_automod_points_for_unknown_trigger_falls_back_to_one(db_session):
    await _seed_guild(db_session)

    assert await _automod_points_for(1, "future_trigger_type") == 1


async def test_automod_points_for_uses_configured_override(db_session):
    await _seed_guild(db_session)
    weights = {**DEFAULT_AUTOMOD_POINTS, "keyword": 9}
    await set_config(1, "automod_warn_points", json.dumps(weights))

    assert await _automod_points_for(1, "keyword") == 9


def test_build_automod_reason_without_matched_keyword():
    assert _build_automod_reason("spam", None) == "AutoMod: spam"


def test_build_automod_reason_with_matched_keyword():
    reason = _build_automod_reason("keyword", "boese-woerter")
    assert reason == "AutoMod: keyword (Treffer: 'boese-woerter')"


async def test_resolve_automod_channel_prefers_configured_channel(db_session):
    await _seed_guild(db_session)
    await set_config(1, "automod_alert_channel_id", "999")
    bot = SimpleNamespace(get_channel=lambda cid: f"channel-{cid}")

    channel = await _resolve_automod_channel(bot, 1, fallback_channel_id=111)

    assert channel == "channel-999"


async def test_resolve_automod_channel_falls_back_when_unset(db_session):
    await _seed_guild(db_session)
    bot = SimpleNamespace(get_channel=lambda cid: f"channel-{cid}")

    channel = await _resolve_automod_channel(bot, 1, fallback_channel_id=111)

    assert channel == "channel-111"


async def test_apply_warning_sums_points_and_returns_threshold(db_session):
    await _seed_guild(db_session)
    await set_config(1, "warn_threshold", "5")
    guild = SimpleNamespace(id=1, name="Wikinger", get_member=lambda uid: None)

    total_points, threshold = await _apply_warning(
        bot_user_id=999,
        guild=guild,
        user_id=200,
        mod_id=999,
        reason="AutoMod: spam",
        points=2,
        channel=SimpleNamespace(),
    )

    assert total_points == 2
    assert threshold == 5

    result = await db_session.execute(Warning.__table__.select())
    [row] = result.fetchall()
    assert row.user_id == 200
    assert row.mod_id == 999
    assert row.points == 2


async def test_apply_warning_accumulates_across_calls(db_session):
    await _seed_guild(db_session)
    guild = SimpleNamespace(id=1, name="Wikinger", get_member=lambda uid: None)

    await _apply_warning(999, guild, 200, 999, "erster Verstoss", 1, SimpleNamespace())
    total_points, _threshold = await _apply_warning(
        999, guild, 200, 999, "zweiter Verstoss", 2, SimpleNamespace()
    )

    assert total_points == 3


async def test_apply_warning_skips_escalation_when_member_not_in_guild(db_session):
    await _seed_guild(db_session)
    await set_config(1, "warn_threshold", "1")
    guild = SimpleNamespace(id=1, name="Wikinger", get_member=lambda uid: None)

    # Darf nicht werfen, obwohl die Schwelle erreicht ist - ohne Member-Objekt
    # kann/darf nicht eskaliert werden (Nutzer nicht mehr auf dem Server).
    total_points, threshold = await _apply_warning(
        999, guild, 200, 999, "Verstoss", 5, SimpleNamespace()
    )

    assert total_points == 5
    assert threshold == 1
