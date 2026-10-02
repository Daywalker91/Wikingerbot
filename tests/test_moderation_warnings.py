"""Verwarnsystem des moderation-Cogs (wird auch vom automod-Cog genutzt)."""

from types import SimpleNamespace

from bot.cogs.moderation.cog import _apply_warning
from bot.core.guild_config import set_config
from db.models.guild import Guild
from db.models.modlog import Warning


async def _seed_guild(db_session, guild_id: int = 1):
    db_session.add(Guild(id=guild_id, name="Wikinger"))
    await db_session.commit()


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
