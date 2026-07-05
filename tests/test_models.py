from datetime import datetime, timezone

from db.models.config import GuildConfig
from db.models.guild import Guild
from db.models.modlog import ModAction, ModLogEntry, Warning
from db.models.role import GuildRole, Level
from db.models.server import Server
from db.models.user import User
from db.models.web_session import WebSession
from db.models.whitelist import WhitelistRequest, WhitelistStatus


async def test_models_roundtrip(db_session):
    guild = Guild(id=1, name="Wikinger")
    user = User(id=100, username="Tester")
    db_session.add_all([guild, user])
    await db_session.flush()

    server = Server(
        guild_id=guild.id,
        instance_name="ark-01",
        amp_instance_id="11111111-1111-1111-1111-111111111111",
        display_name="ARK Server 1",
        host="ark01.example.com",
    )
    db_session.add(server)
    await db_session.flush()

    db_session.add(GuildRole(guild_id=guild.id, discord_role_id=1, level=Level.MOD))
    db_session.add(
        ModLogEntry(
            guild_id=guild.id, user_id=user.id, mod_id=1, action=ModAction.WARN, reason="Test"
        )
    )
    db_session.add(Warning(guild_id=guild.id, user_id=user.id, mod_id=1, reason="Test"))
    db_session.add(
        WhitelistRequest(
            user_id=user.id, server_id=server.id, ign="TesterIGN", status=WhitelistStatus.PENDING
        )
    )
    db_session.add(GuildConfig(guild_id=guild.id, key="prefix", value="!"))
    db_session.add(
        WebSession(
            user_id=user.id,
            refresh_token_hash="hash",
            expires_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    result = await db_session.get(User, user.id)
    assert result is not None
    assert result.username == "Tester"
