"""Rollen von Servern mit eingeschalteter Whitelist gibt es nur per Freigabe
(whitelist-Cog), nicht ueber Selbstwahl-Knoepfe oder als Autorole (roles-Cog).
Im Kern, damit roles nicht vom whitelist-Cog abhaengt."""

from sqlalchemy import select

from db.models.server import Server
from db.session import get_db_session


async def gated_roles(guild_id: int) -> dict[int, list[str]]:
    """Rolle -> Server mit eingeschalteter Whitelist, die diese Rolle vergeben."""
    async with get_db_session() as db:
        rows = (
            await db.execute(
                select(Server.discord_role_id, Server.display_name).where(
                    Server.guild_id == guild_id, Server.whitelist_enabled.is_(True), Server.discord_role_id.is_not(None)
                )
            )
        ).all()
    gated: dict[int, list[str]] = {}
    for role_id, name in rows:
        gated.setdefault(role_id, []).append(name)
    return gated


def gated_reason(role_name: str, servers: list[str]) -> str:
    return (
        f"Für {', '.join(servers)} läuft der Zugang über die Whitelist – "
        f"bitte `/whitelist request` nutzen, die Rolle {role_name} kommt mit der Freigabe."
    )
