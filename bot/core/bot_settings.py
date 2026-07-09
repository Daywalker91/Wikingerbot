from sqlalchemy import select

from db.models.bot_setting import BotSetting
from db.session import get_db_session

SYNC_ON_STARTUP_KEY = "sync_globally_on_startup"


async def get_bot_setting(key: str, default: str | None = None) -> str | None:
    async with get_db_session() as db:
        result = await db.execute(select(BotSetting.value).where(BotSetting.key == key))
        value = result.scalar_one_or_none()
        return value if value is not None else default


async def set_bot_setting(key: str, value: str) -> None:
    async with get_db_session() as db:
        db_setting = await db.get(BotSetting, key)
        if db_setting is None:
            db.add(BotSetting(key=key, value=value))
        else:
            db_setting.value = value
        await db.commit()
