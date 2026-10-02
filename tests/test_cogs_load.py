"""Laedt Cogs in einen Bot ohne Discord-Verbindung - faengt Fehler in den
Slash-Command-Definitionen (Parametertypen, Gruppen, Namen) ab, die sonst erst
beim Start in AMP auffallen wuerden."""

import discord
import pytest
from discord.ext import commands

NEW_COGS = ["welcome", "roles", "stats", "automod", "music", "news", "events"]


def _existing(names):
    from pathlib import Path

    cogs = Path(__file__).resolve().parent.parent / "bot" / "cogs"
    return [n for n in names if (cogs / n / "cog.py").exists()]


@pytest.mark.parametrize("name", _existing(NEW_COGS))
async def test_cog_loads_and_registers_commands(name):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    await bot.load_extension(f"bot.cogs.{name}.cog")
    commands_ = bot.tree.get_commands()
    assert commands_, f"{name} registriert keine Slash-Commands"
    for command in commands_:
        # to_dict() validiert Namen, Beschreibungen und Parameter wie beim Sync
        command.to_dict(bot.tree)
    await bot.close()
