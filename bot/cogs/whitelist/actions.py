"""Whitelist-Aktionen, gemeinsam fuer Discord (Knoepfe, Befehle) und die Weboberflaeche.

- Freigeben: AMP-Whitelist (nur wo AMP eine kennt, z.B. Minecraft), Discord-Rolle des
  Servers, DM.
- Entziehen: Status "revoked", AMP-Eintrag weg, Rolle weg - ausser das Mitglied hat
  noch eine Freigabe fuer einen anderen Server mit derselben Rolle (z.B. ARK-Cluster).
- Gesperrte Rollen: siehe bot/core/whitelist_gate.py.
"""

import logging

import discord
from sqlalchemy import select

from bot.core.amp_client import amp_client
from db.models.server import Server
from db.models.whitelist import WhitelistRequest, WhitelistStatus
from db.session import get_db_session

log = logging.getLogger(__name__)


async def _dm(member: discord.Member | None, message: str) -> None:
    if member is None:
        return
    try:
        await member.send(message)
    except discord.HTTPException:
        pass


async def grant(guild: discord.Guild | None, request: WhitelistRequest, server: Server) -> list[str]:
    """Nach dem Freigeben: AMP-Whitelist, Rolle, DM. Gibt Ergebniszeilen fuers Protokoll zurueck."""
    lines = []
    try:
        await amp_client.add_whitelist(server.amp_instance_id, request.ign)
        lines.append("AMP-Whitelist: OK")
    except Exception as exc:
        lines.append(f"AMP-Whitelist nicht gesetzt (gibt es nur bei manchen Spielen, z.B. Minecraft): {str(exc)[:120]}")
    member = guild.get_member(request.user_id) if guild else None
    if server.discord_role_id and member is not None:
        role = guild.get_role(server.discord_role_id)
        if role is not None:
            try:
                await member.add_roles(role, reason="Whitelist freigegeben")
                lines.append(f"Rolle {role.name} vergeben")
            except discord.HTTPException:
                lines.append("Rollen-Vergabe fehlgeschlagen (Bot-Rolle zu niedrig?)")
    await _dm(member, f"Deine Whitelist-Anfrage für **{server.display_name}** wurde genehmigt.")
    return lines


async def revoke(guild: discord.Guild, user_id: int, server: Server, moderator_id: int, reason: str | None) -> tuple[bool, str]:
    """Freigabe entziehen. (False, Meldung), wenn es keine Freigabe gibt."""
    async with get_db_session() as db:
        approved = (
            await db.execute(
                select(WhitelistRequest).where(
                    WhitelistRequest.user_id == user_id,
                    WhitelistRequest.server_id == server.id,
                    WhitelistRequest.status == WhitelistStatus.APPROVED,
                )
            )
        ).scalars().all()
        if not approved:
            return False, f"Keine Freigabe für {server.display_name}."
        igns = {r.ign for r in approved}
        for request in approved:
            request.status = WhitelistStatus.REVOKED
            request.handled_by = moderator_id
        await db.commit()

        # dieselbe Rolle noch durch eine andere Freigabe gedeckt?
        still_covered = False
        if server.discord_role_id:
            still_covered = (
                await db.execute(
                    select(WhitelistRequest.id)
                    .join(Server, Server.id == WhitelistRequest.server_id)
                    .where(
                        WhitelistRequest.user_id == user_id,
                        WhitelistRequest.status == WhitelistStatus.APPROVED,
                        Server.discord_role_id == server.discord_role_id,
                        Server.id != server.id,
                    )
                    .limit(1)
                )
            ).first() is not None

    lines = []
    for ign in igns:
        try:
            await amp_client.remove_whitelist(server.amp_instance_id, ign)
            lines.append(f"AMP-Whitelist: {ign} entfernt")
        except Exception:
            pass  # Spiel ohne AMP-Whitelist - nichts zu tun
    member = guild.get_member(user_id)
    if server.discord_role_id and member is not None and not still_covered:
        role = guild.get_role(server.discord_role_id)
        if role is not None and role in member.roles:
            try:
                await member.remove_roles(role, reason="Whitelist entzogen")
                lines.append(f"Rolle {role.name} entfernt")
            except discord.HTTPException:
                lines.append("Rolle nicht entfernt (Bot-Rolle zu niedrig?)")
    elif still_covered:
        lines.append("Rolle bleibt (Freigabe für einen anderen Server mit derselben Rolle)")
    grund = f"\nGrund: {reason}" if reason else ""
    await _dm(member, f"Deine Whitelist-Freigabe für **{server.display_name}** wurde entzogen.{grund}")
    return True, "\n".join([f"Freigabe für {server.display_name} entzogen.", *lines])
