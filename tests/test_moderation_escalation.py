import json
from datetime import datetime, timedelta, timezone

from bot.cogs.moderation.cog import (
    DEFAULT_LADDER,
    _consume_tier,
    _decay_warnings,
    _get_ladder,
    reset_escalation_tier,
)
from bot.core.guild_config import set_config
from db.models.guild import Guild
from db.models.modlog import Warning, WarnEscalationState
from db.models.user import User


async def _seed_guild_and_user(db_session, *, guild_id: int = 1, user_id: int = 200):
    db_session.add(Guild(id=guild_id, name="Wikinger"))
    db_session.add(User(id=user_id, username="Bösewicht"))
    await db_session.commit()


async def test_get_ladder_returns_default_when_unset(db_session):
    await _seed_guild_and_user(db_session)

    ladder = await _get_ladder(1)

    assert ladder == DEFAULT_LADDER


async def test_get_ladder_returns_configured_value(db_session):
    await _seed_guild_and_user(db_session)
    await set_config(1, "warn_ladder", json.dumps(["ban", "kick"]))

    ladder = await _get_ladder(1)

    assert ladder == ["ban", "kick"]


async def test_consume_tier_increments_on_each_call(db_session):
    await _seed_guild_and_user(db_session)

    first = await _consume_tier(1, 200)
    second = await _consume_tier(1, 200)
    third = await _consume_tier(1, 200)

    assert (first, second, third) == (0, 1, 2)


async def test_consume_tier_is_scoped_per_guild_and_user(db_session):
    await _seed_guild_and_user(db_session, guild_id=1, user_id=200)
    db_session.add(User(id=201, username="Zweiter"))
    db_session.add(Guild(id=2, name="Andere Guild"))
    await db_session.commit()

    await _consume_tier(1, 200)
    await _consume_tier(1, 200)

    assert await _consume_tier(1, 201) == 0
    assert await _consume_tier(2, 200) == 0


async def test_reset_escalation_tier_sets_back_to_zero(db_session):
    await _seed_guild_and_user(db_session)
    db_session.add(WarnEscalationState(guild_id=1, user_id=200, tier=2))
    await db_session.commit()

    await reset_escalation_tier(1, 200)

    state = await db_session.get(WarnEscalationState, (1, 200))
    assert state.tier == 0


async def test_reset_escalation_tier_is_noop_when_no_state_exists(db_session):
    await _seed_guild_and_user(db_session)

    await reset_escalation_tier(1, 200)  # darf nicht werfen


async def test_decay_warnings_expires_old_and_keeps_recent(db_session):
    await _seed_guild_and_user(db_session)
    await set_config(1, "warn_decay_days", "30")

    old = Warning(
        guild_id=1,
        user_id=200,
        mod_id=100,
        reason="alt",
        points=1,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=31),
    )
    recent = Warning(
        guild_id=1,
        user_id=200,
        mod_id=100,
        reason="neu",
        points=1,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
    )
    db_session.add_all([old, recent])
    await db_session.commit()
    await db_session.refresh(old)
    await db_session.refresh(recent)

    await _decay_warnings()

    await db_session.refresh(old)
    await db_session.refresh(recent)
    assert old.expired is True
    assert recent.expired is False


async def test_decay_warnings_uses_per_guild_decay_days(db_session):
    await _seed_guild_and_user(db_session, guild_id=1, user_id=200)
    db_session.add(Guild(id=2, name="Andere Guild"))
    await db_session.commit()
    await set_config(1, "warn_decay_days", "7")
    await set_config(2, "warn_decay_days", "365")

    ten_days_old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=10)
    warning_guild_1 = Warning(
        guild_id=1, user_id=200, mod_id=100, reason="a", points=1, created_at=ten_days_old
    )
    warning_guild_2 = Warning(
        guild_id=2, user_id=200, mod_id=100, reason="b", points=1, created_at=ten_days_old
    )
    db_session.add_all([warning_guild_1, warning_guild_2])
    await db_session.commit()

    await _decay_warnings()

    await db_session.refresh(warning_guild_1)
    await db_session.refresh(warning_guild_2)
    assert warning_guild_1.expired is True  # 10 Tage alt, decay_days=7 -> verfallen
    assert warning_guild_2.expired is False  # 10 Tage alt, decay_days=365 -> noch aktiv
