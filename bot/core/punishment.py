"""Strafrolle: Mitglieder einschraenken, ohne sie zu kicken (z.B. eine Rolle
"Thrall", die nur noch lesen darf).

- Welche Discord-Rolle die Strafrolle ist, steht in guild_config "punish_role_id"
  (Tab Moderation). Die Rechte selbst regelt man in Discord: die Strafrolle darf
  weniger, die Autorole (z.B. "Member") bringt das normale Mitmachen mit.
- Strafen = Autoroles weg, Strafrolle dazu. Aufheben = umgekehrt.
- Der Bot merkt sich bestrafte Mitglieder (guild_config "punish_memory"): Wer mit
  Strafrolle den Server verlaesst und wiederkommt, bekommt wieder die Strafrolle
  statt der Autorole. Gemerkt wird, sobald jemand die Strafrolle bekommt - egal
  ob per Befehl, Eskalation, Rang-Sync oder von Hand -, vergessen, sobald sie
  wieder weg ist.

Geteilt von moderation (Befehle, Eskalation, Merken) und roles (Autorole beim
Beitritt) - darum im Kern statt in einem Cog.
"""

import json
import logging

import discord

from bot.core.guild_config import get_config, set_config

log = logging.getLogger(__name__)

ROLE_KEY = "punish_role_id"
MEMORY_KEY = "punish_memory"
AUTOROLE_KEY = "autorole_ids"  # gepflegt vom roles-Cog


async def punish_role(guild: discord.Guild) -> discord.Role | None:
    role_id = await get_config(guild.id, ROLE_KEY)
    return guild.get_role(int(role_id)) if role_id else None


async def autoroles(guild: discord.Guild) -> list[discord.Role]:
    try:
        ids = [int(r) for r in json.loads(await get_config(guild.id, AUTOROLE_KEY, "[]") or "[]")]
    except (ValueError, json.JSONDecodeError):
        ids = []
    return [role for role in (guild.get_role(i) for i in ids) if role is not None]


async def _memory(guild_id: int) -> list[int]:
    try:
        return [int(x) for x in json.loads(await get_config(guild_id, MEMORY_KEY, "[]") or "[]")]
    except (ValueError, json.JSONDecodeError):
        return []


async def is_remembered(guild_id: int, user_id: int) -> bool:
    return user_id in await _memory(guild_id)


async def remember(guild: discord.Guild, user_id: int) -> None:
    memory = await _memory(guild.id)
    if user_id not in memory:
        await set_config(guild.id, MEMORY_KEY, json.dumps([str(x) for x in [*memory, user_id]]), guild.name)


async def forget(guild: discord.Guild, user_id: int) -> None:
    memory = await _memory(guild.id)
    if user_id in memory:
        await set_config(guild.id, MEMORY_KEY, json.dumps([str(x) for x in memory if x != user_id]), guild.name)


async def apply(member: discord.Member, reason: str) -> str | None:
    """Strafrolle geben, Autoroles nehmen. Gibt eine Fehlermeldung zurueck oder None."""
    role = await punish_role(member.guild)
    if role is None:
        return "Es ist keine Strafrolle eingestellt (Tab Moderation)."
    if role in member.roles:
        return f"{member.mention} hat die Strafrolle schon."
    auto = await autoroles(member.guild)
    keep = [r for r in member.roles if not r.is_default() and r not in auto]
    try:
        await member.edit(roles=[*keep, role], reason=reason[:500])
    except discord.HTTPException as error:
        log.warning("Strafrolle fuer %s nicht gesetzt: %s", member, error)
        return "Discord hat abgelehnt – die Bot-Rolle muss über der Strafrolle und der Autorole stehen."
    await remember(member.guild, member.id)
    return None


async def lift(member: discord.Member, reason: str) -> str | None:
    """Strafrolle nehmen, Autoroles zurueckgeben."""
    role = await punish_role(member.guild)
    if role is None:
        return "Es ist keine Strafrolle eingestellt (Tab Moderation)."
    if role not in member.roles:
        await forget(member.guild, member.id)
        return f"{member.mention} hat die Strafrolle nicht."
    roles = [r for r in member.roles if r != role and not r.is_default()]
    roles += [r for r in await autoroles(member.guild) if r not in roles]
    try:
        await member.edit(roles=roles, reason=reason[:500])
    except discord.HTTPException as error:
        log.warning("Strafrolle von %s nicht entfernt: %s", member, error)
        return "Discord hat abgelehnt – die Bot-Rolle muss über der Strafrolle und der Autorole stehen."
    await forget(member.guild, member.id)
    return None
