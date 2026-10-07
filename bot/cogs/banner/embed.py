"""Embed-Rendering fuer die Embed-Variante des Server-Banners."""

import re

import discord

STATE_EMOJI = {
    "Ready": "\N{LARGE GREEN CIRCLE}",
    "Stopped": "\N{LARGE RED CIRCLE}",
    "Failed": "\N{LARGE RED CIRCLE}",
    "Suspended": "\N{LARGE RED CIRCLE}",
}
DEFAULT_STATE_EMOJI = "\N{LARGE YELLOW CIRCLE}"


def coarse_uptime(value) -> str:
    """Laufzeit grob ("5 Std", "2 T 3 Std", "< 1 Std") - aendert sich hoechstens stuendlich,
    damit der Banner nicht jede Minute neu gezeichnet und bearbeitet werden muss.
    Versteht "1.02:03:04" / "02:03:04" (wie AMP) und "1d 2h 3m" / "1h 23m"."""
    text = str(value or "").strip()
    if not text:
        return ""
    hours = None
    match = re.fullmatch(r"(?:(\d+)[.:])?(\d+):(\d+):(\d+)(?:\.\d+)?", text)
    if match:
        hours = int(match[1] or 0) * 24 + int(match[2])
    else:
        parts = dict((unit, int(num)) for num, unit in re.findall(r"(\d+)\s*([dhm])", text.lower()))
        if parts:
            hours = parts.get("d", 0) * 24 + parts.get("h", 0)
    if hours is None:
        return text
    if hours < 1:
        return "< 1 Std"
    days, rest = divmod(hours, 24)
    return f"{days} T {rest} Std" if days else f"{rest} Std"


def address_line(host: str | None) -> str | None:
    """Kopierbare Verbinden-Zeile oben in der Banner-Karte."""
    return f"Verbinden: `{host}`" if host else None


def image_card(host: str | None, filename: str, color: tuple[int, int, int]) -> discord.Embed:
    """Karte fuer einen Bild-Banner: Adresse oben, Bild darunter, Rand in Statusfarbe.

    Als Karte statt als nackter Anhang, damit Adresse und Bild sichtbar zusammengehoeren -
    nackte Anhaenge zeigt Discord bei mehreren Bannern als zugeschnittene Galerie, und
    Nachrichtentext steht dort immer UEBER allen Bildern."""
    embed = discord.Embed(description=address_line(host), colour=discord.Colour.from_rgb(*color))
    embed.set_image(url=f"attachment://{filename}")
    return embed


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

    # Verbinden-Adresse kopierbar oben in der Karte
    embed = discord.Embed(title=display_name, description=address_line(host))
    embed.add_field(name="Status", value=f"{emoji} {state_name}", inline=True)
    if players is not None:
        embed.add_field(name="Spieler", value=f"{players[0]}/{players[1]}", inline=True)
    if getattr(status, "Uptime", None):
        embed.add_field(name="Läuft seit", value=coarse_uptime(status.Uptime), inline=True)
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
