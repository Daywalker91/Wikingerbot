from bot.core.bot_settings import get_bot_setting, set_bot_setting


async def test_get_bot_setting_returns_default_when_unset():
    value = await get_bot_setting("sync_globally_on_startup", default="true")

    assert value == "true"


async def test_set_then_get_bot_setting_roundtrips():
    await set_bot_setting("sync_globally_on_startup", "false")

    value = await get_bot_setting("sync_globally_on_startup", default="true")

    assert value == "false"


async def test_set_bot_setting_overwrites_existing_value():
    await set_bot_setting("sync_globally_on_startup", "false")
    await set_bot_setting("sync_globally_on_startup", "true")

    value = await get_bot_setting("sync_globally_on_startup")

    assert value == "true"
