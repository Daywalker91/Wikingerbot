from bot.core.permissions import resolve_level
from db.models.guild import Guild
from db.models.role import GuildRole, Level, highest_level, level_at_least


def test_level_at_least_hierarchy():
    assert level_at_least(Level.OWNER, Level.MEMBER)
    assert level_at_least(Level.ADMIN, Level.MOD)
    assert not level_at_least(Level.MOD, Level.ADMIN)
    assert level_at_least(Level.MEMBER, Level.MEMBER)


def test_highest_level_picks_max():
    assert highest_level([Level.MOD, Level.MEMBER]) == Level.MOD
    assert highest_level([]) == Level.MEMBER


async def test_resolve_level_no_roles_is_member():
    assert await resolve_level(guild_id=1, member_role_ids=[]) == Level.MEMBER


async def test_resolve_level_looks_up_db(db_session):
    db_session.add(Guild(id=1, name="Test Guild"))
    db_session.add(GuildRole(guild_id=1, discord_role_id=42, level=Level.ADMIN))
    await db_session.commit()

    level = await resolve_level(guild_id=1, member_role_ids=[42, 999])
    assert level == Level.ADMIN
