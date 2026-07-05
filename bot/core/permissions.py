from typing import Iterable

import discord
from discord import Interaction, app_commands
from sqlalchemy import select

from db.models.role import GuildRole, Level, highest_level, level_at_least
from db.session import get_db_session

__all__ = ["Level", "resolve_level", "require_role", "InsufficientPermissions"]


class InsufficientPermissions(app_commands.CheckFailure):
    def __init__(self, required: Level, actual: Level) -> None:
        self.required = required
        self.actual = actual
        super().__init__(
            f"Erfordert mindestens Level '{required.value}', "
            f"aktuelles Level ist '{actual.value}'."
        )


async def resolve_level(guild_id: int, member_role_ids: Iterable[int]) -> Level:
    """Ermittelt das hoechste Berechtigungslevel anhand der Discord-Rollen-IDs eines Members."""
    role_ids = list(member_role_ids)
    if not role_ids:
        return Level.MEMBER

    async with get_db_session() as db:
        result = await db.execute(
            select(GuildRole.level).where(
                GuildRole.guild_id == guild_id,
                GuildRole.discord_role_id.in_(role_ids),
            )
        )
        return highest_level(row[0] for row in result.all())


def require_role(minimum: Level):
    """Decorator fuer App-Commands: erfordert mindestens das angegebene Level.

    Verwendung:
        @discord.app_commands.command()
        @require_role(Level.MOD)
        async def kick(self, interaction, user: discord.Member, reason: str):
            ...
    """

    async def predicate(interaction: Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return False

        if interaction.user.guild_permissions.administrator:
            return True

        role_ids = [role.id for role in interaction.user.roles]
        actual = await resolve_level(interaction.guild.id, role_ids)
        if level_at_least(actual, minimum):
            return True
        raise InsufficientPermissions(minimum, actual)

    return app_commands.check(predicate)
