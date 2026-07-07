from sqlalchemy import select

from bot.core.entities import ensure_guild
from db.models.config import GuildConfig
from db.session import get_db_session


async def get_config(guild_id: int, key: str, default: str | None = None) -> str | None:
    async with get_db_session() as db:
        result = await db.execute(
            select(GuildConfig.value).where(
                GuildConfig.guild_id == guild_id, GuildConfig.key == key
            )
        )
        value = result.scalar_one_or_none()
        return value if value is not None else default


async def set_config(guild_id: int, key: str, value: str, guild_name: str | None = None) -> None:
    if guild_name is not None:
        await ensure_guild(guild_id, guild_name)

    async with get_db_session() as db:
        db_config = await db.get(GuildConfig, (guild_id, key))
        if db_config is None:
            db.add(GuildConfig(guild_id=guild_id, key=key, value=value))
        else:
            db_config.value = value
        await db.commit()
