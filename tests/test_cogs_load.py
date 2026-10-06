"""Laedt jeden Cog EINZELN in einen eigenen Bot ohne Discord-Verbindung (keine anderen
Cogs, keine Community-Seite) und entlaedt ihn wieder - so faellt auf, wenn ein Cog
einen anderen voraussetzt oder Fehler in den Slash-Command-Definitionen (Parametertypen,
Gruppen, Namen) hat, die sonst erst beim Start in AMP auffallen wuerden."""

import discord
import pytest
from discord.ext import commands

from bot.core.bot import discover_cog_names

# Cogs ohne eigene Slash-Commands (arbeiten ueber Auftraege der Seite, Knoepfe oder den Tab)
WITHOUT_COMMANDS = {"rangsync", "rollenanfragen"}


@pytest.mark.parametrize("name", discover_cog_names())
async def test_cog_runs_alone(name):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())
    await bot.load_extension(f"bot.cogs.{name}.cog")
    assert len(bot.cogs) == 1, f"{name} bringt weitere Cogs mit: {list(bot.cogs)}"
    commands_ = bot.tree.get_commands()
    if name not in WITHOUT_COMMANDS:
        assert commands_, f"{name} registriert keine Slash-Commands"
    for command in commands_:
        # to_dict() validiert Namen, Beschreibungen und Parameter wie beim Sync
        command.to_dict(bot.tree)
    await bot.unload_extension(f"bot.cogs.{name}.cog")
    assert not bot.cogs
    await bot.close()


def test_every_cog_is_covered():
    names = discover_cog_names()
    assert len(names) >= 18 and "admin" in names and "rollenanfragen" in names
