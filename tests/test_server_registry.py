"""Server anlegen: verwaiste Eintraege (Bot nicht mehr auf dem Discord-Server)
werden uebernommen, aktive bleiben geschuetzt."""

from sqlalchemy import select

from bot.cogs.amp.registry import add_server, known_instance_ids
from db.models.console_pattern import ConsolePattern, ConsolePatternKind
from db.models.guild import Guild
from db.models.server import Server

OLD, NEW, OTHER = 1, 2, 3


async def seed(db_session):
    db_session.add_all([Guild(id=OLD, name="Test"), Guild(id=NEW, name="Echt"), Guild(id=OTHER, name="Andere")])
    await db_session.commit()
    server = Server(
        guild_id=OLD, instance_name="valheim", amp_instance_id="abc", display_name="Valheim", host="old.example",
        console_channel=11, chat_channel=12, banner_enabled=True, banner_channel=13, banner_message_id=14,
        discord_role_id=15, steam_app_id=892970,
    )
    db_session.add(server)
    await db_session.commit()
    db_session.add(ConsolePattern(server_id=server.id, kind=ConsolePatternKind.FILTER, pattern="noise"))
    await db_session.commit()
    return server.id


async def add(active, guild_id, name="valheim", instance="abc"):
    return await add_server(
        active, guild_id, name=name, amp_instance_id=instance, display_name="Valheim", host="play.example", steam_app_id=None
    )


async def test_orphaned_instances_are_free_again(db_session):
    await seed(db_session)
    assert await known_instance_ids({OLD, NEW}) == {"abc"}
    assert await known_instance_ids({NEW}) == set()  # Bot ist nicht mehr auf OLD
    assert await known_instance_ids(None) == {"abc"}  # Bot laeuft nicht -> vorsichtig


async def test_takeover_keeps_patterns_and_resets_discord_references(db_session):
    server_id = await seed(db_session)
    result = await add({NEW}, NEW)
    assert result.ok and "uebernommen" in result.message and result.server_id == server_id

    db_session.expire_all()
    server = await db_session.get(Server, server_id)
    assert (server.guild_id, server.host, server.steam_app_id) == (NEW, "play.example", 892970)
    assert server.console_channel is server.chat_channel is server.banner_channel is server.banner_message_id is None
    assert server.discord_role_id is None and server.banner_enabled is False
    patterns = (await db_session.execute(select(ConsolePattern.pattern).where(ConsolePattern.server_id == server_id))).all()
    assert patterns == [("noise",)]


async def test_active_entries_are_protected(db_session):
    await seed(db_session)
    same = await add({OLD}, OLD, name="anders")
    assert not same.ok and "schon als `valheim`" in same.message
    other = await add({OLD, NEW}, NEW, name="anders")
    assert not other.ok and "anderen Discord-Server" in other.message
    name = await add({OLD, NEW}, NEW, instance="xyz")
    assert not name.ok and "schon vergeben" in name.message


async def test_orphan_only_blocking_the_name_is_renamed(db_session):
    server_id = await seed(db_session)
    result = await add({NEW}, NEW, instance="xyz")  # neue Instanz, Name vom alten Eintrag belegt
    assert result.ok and result.server_id != server_id
    db_session.expire_all()
    assert (await db_session.get(Server, server_id)).instance_name == f"valheim-alt-{server_id}"
    assert (await db_session.get(Server, result.server_id)).instance_name == "valheim"
