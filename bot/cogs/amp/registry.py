"""Server-Eintraege anlegen - mit Uebernahme verwaister Eintraege.

Jede AMP-Instanz und jeder interne Name darf in der Datenbank nur einmal vorkommen.
Ist der Bot von einem Discord-Server entfernt worden (z.B. Umzug vom Test- auf den
echten Server), bleiben dessen Server-Eintraege liegen und wuerden die Instanzen
blockieren. Solche Eintraege gelten als verwaist: Sie zaehlen fuer discover und die
Vorschlaege nicht mehr, und /server add uebernimmt sie.

Bei der Uebernahme bleiben eigene Konsolenmuster, Filter und Whitelist-Verlauf
erhalten; alles, was auf Kanaele/Rollen/Nachrichten des alten Discord-Servers
zeigt, wird geleert.
"""

from dataclasses import dataclass

from sqlalchemy import delete, select

from db.models.console_pattern import ConsolePattern, ConsolePatternOverride
from db.models.server import Server
from db.models.whitelist import WhitelistRequest
from db.session import get_db_session

# Felder, die auf den alten Discord-Server zeigen
RESET_ON_TAKEOVER = {
    "console_channel": None,
    "chat_channel": None,
    "event_channel": None,
    "discord_role_id": None,
    "banner_enabled": False,
    "banner_channel": None,
    "banner_message_id": None,
    "banner_group_id": None,
    "hidden": False,
}


@dataclass
class AddResult:
    ok: bool
    message: str
    server_id: int | None = None


def _is_active(guild_id: int, active_guild_ids: set[int] | None) -> bool:
    # None = unbekannt (Bot laeuft nicht) -> vorsichtshalber alle als aktiv werten
    return active_guild_ids is None or guild_id in active_guild_ids


async def known_instance_ids(active_guild_ids: set[int] | None) -> set[str]:
    """AMP-Instanzen, die auf einem Discord-Server angelegt sind, auf dem der Bot noch ist."""
    async with get_db_session() as db:
        rows = (await db.execute(select(Server.amp_instance_id, Server.guild_id))).all()
    return {instance for instance, guild_id in rows if _is_active(guild_id, active_guild_ids)}


async def add_server(
    active_guild_ids: set[int] | None,
    guild_id: int,
    *,
    name: str,
    amp_instance_id: str,
    display_name: str,
    host: str,
    steam_app_id: int | None,
) -> AddResult:
    async with get_db_session() as db:
        by_instance = (await db.execute(select(Server).where(Server.amp_instance_id == amp_instance_id))).scalar_one_or_none()
        by_name = (await db.execute(select(Server).where(Server.instance_name == name))).scalar_one_or_none()

        if by_instance is not None and _is_active(by_instance.guild_id, active_guild_ids):
            if by_instance.guild_id == guild_id:
                return AddResult(False, f"Diese AMP-Instanz ist hier schon als `{by_instance.instance_name}` angelegt.")
            return AddResult(False, "Diese AMP-Instanz ist schon auf einem anderen Discord-Server angelegt, auf dem der Bot ist.")
        if by_name is not None and by_name is not by_instance:
            if _is_active(by_name.guild_id, active_guild_ids):
                return AddResult(False, f"Der Name `{name}` ist schon vergeben - bitte einen anderen waehlen.")
            # verwaister Eintrag einer anderen Instanz blockiert nur den Namen -> umbenennen
            by_name.instance_name = f"{name}-alt-{by_name.id}"[:100]
            await db.flush()

        fields = {"guild_id": guild_id, "instance_name": name, "display_name": display_name, "host": host}
        if by_instance is not None:
            for key, value in {**fields, **RESET_ON_TAKEOVER}.items():
                setattr(by_instance, key, value)
            if steam_app_id is not None:
                by_instance.steam_app_id = steam_app_id
            await db.commit()
            return AddResult(
                True,
                f"Server `{display_name}` angelegt - vom alten Discord-Server uebernommen (eigene Muster und "
                "Filter bleiben, Kanaele/Banner/Whitelist-Rolle bitte neu setzen).",
                by_instance.id,
            )

        server = Server(amp_instance_id=amp_instance_id, steam_app_id=steam_app_id, **fields)
        db.add(server)
        await db.commit()
        return AddResult(True, f"Server `{display_name}` angelegt.", server.id)


@dataclass
class RemovedServer:
    display_name: str
    banner_channel: int | None
    banner_message_id: int | None


async def remove_server(guild_id: int, server_id: int) -> RemovedServer | None:
    """Loescht einen Server-Eintrag dieses Discord-Servers samt eigener Muster,
    Filter-Ausnahmen und Whitelist-Anfragen. Die AMP-Instanz selbst bleibt unberuehrt.
    Gibt zurueck, wo ein eigener Banner stand (zum Aufraeumen in Discord)."""
    async with get_db_session() as db:
        server = await db.get(Server, server_id)
        if server is None or server.guild_id != guild_id:
            return None
        removed = RemovedServer(server.display_name, server.banner_channel, server.banner_message_id)
        for model in (ConsolePattern, ConsolePatternOverride, WhitelistRequest):
            await db.execute(delete(model).where(model.server_id == server_id))
        await db.delete(server)
        await db.commit()
        return removed


async def delete_banner_message(bot, removed: RemovedServer) -> None:
    """Eigenen Banner des entfernten Servers in Discord loeschen (falls noch da)."""
    if bot is None or not removed.banner_channel or not removed.banner_message_id:
        return
    channel = bot.get_channel(removed.banner_channel)
    if channel is None:
        return
    try:
        message = await channel.fetch_message(removed.banner_message_id)
        await message.delete()
    except Exception:  # schon weg oder keine Rechte - nicht schlimm
        pass
