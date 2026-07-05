import asyncio
import logging

from bot.core.bot import WikingerBot
from bot.core.config import settings


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    bot = WikingerBot()
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
