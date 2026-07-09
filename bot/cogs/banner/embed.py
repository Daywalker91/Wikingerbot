"""Embed-Rendering fuer die Embed-Variante des Server-Banners."""

import discord

STATE_EMOJI = {
    "Ready": "\N{LARGE GREEN CIRCLE}",
    "Stopped": "\N{LARGE RED CIRCLE}",
    "Failed": "\N{LARGE RED CIRCLE}",
    "Suspended": "\N{LARGE RED CIRCLE}",
}
DEFAULT_STATE_EMOJI = "\N{LARGE YELLOW CIRCLE}"


def _whitelist_field(whitelist_count: int | None, has_donator: bool) -> str:
    text = f"\N{LOCK} {whitelist_count} freigeschaltet"
    if has_donator:
        text += " \N{WHITE MEDIUM STAR} Donator-Server"
    return text


def build_embed(
    display_name: str,
    host: str,
    status,
    players: tuple[int, int] | None,
    *,
    whitelist_count: int | None = None,
    has_donator: bool = False,
) -> discord.Embed:
    state_name = status.State.name
    emoji = STATE_EMOJI.get(state_name, DEFAULT_STATE_EMOJI)

    # Die Verbinden-Adresse steht bereits als eigener, kopierbarer Text ueber der
    # Nachricht (siehe BannerCog._build_server_payload) - hier nicht nochmal duplizieren.
    embed = discord.Embed(title=display_name)
    embed.add_field(name="Status", value=f"{emoji} {state_name}", inline=True)
    if players is not None:
        embed.add_field(name="Spieler", value=f"{players[0]}/{players[1]}", inline=True)
    if getattr(status, "Uptime", None):
        embed.add_field(name="Uptime", value=status.Uptime, inline=True)
    if whitelist_count is not None:
        embed.add_field(name="Whitelist", value=_whitelist_field(whitelist_count, has_donator), inline=False)
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_group_embed(
    group_name: str,
    entries: list[tuple[str, str, object, tuple[int, int] | None, int | None, bool]],
) -> discord.Embed:
    # Die Verbinden-Adressen stehen bereits als eigener Text ueber der Nachricht
    # (siehe BannerCog._build_group_payload_combined) - hier nicht nochmal duplizieren.
    embed = discord.Embed(title=group_name)
    for display_name, _host, status, players, whitelist_count, has_donator in entries:
        state_name = status.State.name
        emoji = STATE_EMOJI.get(state_name, DEFAULT_STATE_EMOJI)
        lines = [f"{emoji} {state_name}"]
        if players is not None:
            lines.append(f"Spieler: {players[0]}/{players[1]}")
        if whitelist_count is not None:
            lines.append(_whitelist_field(whitelist_count, has_donator))
        embed.add_field(name=display_name, value="\n".join(lines), inline=False)
    embed.timestamp = discord.utils.utcnow()
    return embed
