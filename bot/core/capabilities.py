"""Faehigkeiten: einzelne Befehle zusaetzlich an Discord-Rollen binden.

Die Bot-Stufen sind gestaffelt (Member < Mod < Admin < Owner). Manche Aufgaben
passen aber nicht in diese Leiter - z.B. sollen Gameserver-Betreuer Server
starten duerfen, ohne Moderatoren zu sein. Eine Faehigkeit hat eine Standard-
Stufe (wer sie immer hat) und optional Discord-Rollen, die sie zusaetzlich geben.

Zuordnung pro Discord-Server in guild_config "capability_roles"
({"server.control": ["<rollen-id>", ...]}), einzustellen im Tab Einstellungen.
Geprueft wird in Slash-Befehlen (require_capability), Knoepfen
(check_capability_interaction) und der API (api/middleware/auth.require_capability).
"""

import json
from dataclasses import dataclass
from typing import Iterable

import discord
from discord import Interaction, app_commands

from bot.core.guild_config import get_config, set_config
from bot.core.permissions import InsufficientPermissions, resolve_level
from db.models.role import Level, level_at_least

CONFIG_KEY = "capability_roles"


@dataclass(frozen=True)
class Capability:
    label: str
    default: Level


CAPABILITIES: dict[str, Capability] = {
    "server.control": Capability("Gameserver starten/stoppen und Konsole", Level.MOD),
    "whitelist.review": Capability("Whitelist- und Gruppen-Anfragen ansehen, annehmen, ablehnen und entziehen", Level.MOD),
    "banner.refresh": Capability("Banner sofort aktualisieren", Level.MOD),
}


async def capability_roles(guild_id: int) -> dict[str, list[int]]:
    try:
        stored = json.loads(await get_config(guild_id, CONFIG_KEY, "{}") or "{}")
    except json.JSONDecodeError:
        stored = {}
    return {key: [int(r) for r in stored.get(key, [])] for key in CAPABILITIES}


async def save_capability_roles(guild_id: int, guild_name: str, mapping: dict[str, list[int]]) -> None:
    clean = {key: [str(r) for r in dict.fromkeys(mapping.get(key, []))] for key in CAPABILITIES}
    await set_config(guild_id, CONFIG_KEY, json.dumps(clean), guild_name)


async def allowed(guild_id: int, capability: str, level: Level, role_ids: Iterable[int]) -> bool:
    """Stufe reicht schon, oder eine der Rollen gibt die Faehigkeit."""
    if level_at_least(level, CAPABILITIES[capability].default):
        return True
    return bool(set(role_ids) & set((await capability_roles(guild_id))[capability]))


async def member_capabilities(guild_id: int, level: Level, role_ids: Iterable[int]) -> list[str]:
    role_ids = set(role_ids)
    return [key for key in CAPABILITIES if await allowed(guild_id, key, level, role_ids)]


async def _check(interaction: Interaction, guild_id: int, capability: str) -> tuple[bool, Level]:
    member = interaction.user
    if isinstance(member, discord.Member) and member.guild_permissions.administrator:
        return True, Level.OWNER
    role_ids = [role.id for role in member.roles] if isinstance(member, discord.Member) else []
    level = await resolve_level(guild_id, role_ids)
    return await allowed(guild_id, capability, level, role_ids), level


def require_capability(capability: str):
    """Wie require_role, aber mit Faehigkeit: Standard-Stufe ODER zugeordnete Rolle."""

    async def predicate(interaction: Interaction) -> bool:
        if interaction.guild is None:
            return False
        ok, level = await _check(interaction, interaction.guild.id, capability)
        if ok:
            return True
        raise InsufficientPermissions(CAPABILITIES[capability].default, level)

    return app_commands.check(predicate)


async def check_capability_interaction(interaction: Interaction, guild_id: int, capability: str) -> bool:
    """Fuer Knopf-Callbacks: meldet fehlende Berechtigung selbst und gibt False zurueck."""
    ok, _ = await _check(interaction, guild_id, capability)
    if not ok:
        await interaction.response.send_message("Dafuer fehlt dir die Berechtigung.", ephemeral=True)
    return ok
