from db.models.guild import Guild
from db.models.user import User
from db.session import get_db_session


async def ensure_guild(guild_id: int, name: str) -> None:
    """Legt eine Guild-Zeile an, falls noch nicht vorhanden.

    Noetig bevor guild-scoped Tabellen (GuildConfig, ModLogEntry, Warning,
    Server, ...) darauf verweisen - auf MariaDB werden FK-Constraints
    durchgesetzt, im Gegensatz zu SQLite im Dev-Betrieb.
    """
    async with get_db_session() as db:
        guild = await db.get(Guild, guild_id)
        if guild is None:
            db.add(Guild(id=guild_id, name=name))
            await db.commit()


async def ensure_user(user_id: int, username: str | None = None) -> None:
    """Legt eine User-Zeile an, falls noch nicht vorhanden."""
    async with get_db_session() as db:
        user = await db.get(User, user_id)
        if user is None:
            db.add(User(id=user_id, username=username))
            await db.commit()
