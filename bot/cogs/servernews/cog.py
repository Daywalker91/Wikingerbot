"""Server-News: Neustarts, Wartungen und Ausfaelle der Gameserver in Discord ankuendigen.

- Von Hand: /wartung neustart (der Bot startet zur Zeit neu), /wartung plane (Wartung:
  der Bot stoppt zur Zeit), /wartung liste, /wartung abbrechen, /wartung ende.
- Aus dem AMP-Zeitplan (abschaltbar, erst nach Pruefung der Vorschau im Tab): Zeit-
  Trigger mit Neustart/Update/Stopp werden vorher angekuendigt - ausgefuehrt von AMP.
- Vorlaufzeiten frei einstellbar (z.B. 30, 10, 1 Minuten); nur die erste Meldung pingt.
  Optional zusaetzlich ein Hinweis im Spiel (Konsolenbefehl je Server, z.B. "say {text}").
- Danach "laeuft wieder"; nicht angekuendigte Ausfaelle werden ohne Ping gemeldet.

Kanal, Ping-Rolle und alles Weitere im Tab "Server-News". Ankuendigen darf, wer
Gameserver starten/stoppen darf (Faehigkeit server.control).
"""

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from bot.cogs.servernews.notices import (
    announce_text,
    create_notice,
    due_lead,
    ingame_text,
    load_settings,
    local_now,
    local_to_utc,
    open_notices,
    parse_start,
    set_status,
    unix,
    utcnow,
)
from bot.cogs.servernews.schedule import planned_runs
from bot.core.amp_client import amp_client
from bot.core.base_cog import BaseCog
from bot.core.capabilities import require_capability
from bot.core.entities import ensure_guild
from bot.core.server_address import connect_address
from db.models.server import Server
from db.models.server_notice import ServerNotice
from db.session import get_db_session

log = logging.getLogger("wikingerbot.servernews")

AMP_SYNC_EVERY = 20  # Takte (je 30 s) = alle 10 Minuten den AMP-Zeitplan lesen


async def _server_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    async with get_db_session() as db:
        rows = (await db.execute(select(Server.instance_name, Server.display_name).where(Server.guild_id == interaction.guild_id))).all()
    current = current.lower()
    return [
        app_commands.Choice(name=f"{display} ({name})"[:100], value=name)
        for name, display in rows
        if current in name.lower() or current in (display or "").lower()
    ][:25]


async def _server(guild_id: int, name: str) -> Server | None:
    async with get_db_session() as db:
        return (await db.execute(select(Server).where(Server.guild_id == guild_id, Server.instance_name == name))).scalar_one_or_none()


async def _is_up(server: Server) -> bool | None:
    """True = laeuft, False = aus, None = unbekannt (z.B. AMP nicht erreichbar)."""
    try:
        status = await amp_client.get_status(server.amp_instance_id)
    except Exception as error:
        return False if "Instance Unavailable" in str(error) else None
    return status.State.name == "Ready"


class ServerNewsCog(BaseCog):
    """Neustarts, Wartungen und Ausfaelle ankuendigen."""

    __cog_name__ = "servernews"
    __version__ = "1.0.0"
    __description__ = "Neustarts, Wartungen und Ausfaelle der Gameserver ankuendigen"
    __author__ = "Daywalker91"

    wartung_group = app_commands.Group(name="wartung", description="Neustarts und Wartungen ankuendigen")

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self._up: dict[int, bool] = {}  # Server-ID -> lief beim letzten Blick
        self._outage: set[int] = set()  # unangekuendigt ausgefallen
        self._ticks = 0

    async def cog_load(self) -> None:
        self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    # --- Takt -------------------------------------------------------------------------

    @tasks.loop(seconds=30)
    async def tick(self) -> None:
        sync_amp = self._ticks % AMP_SYNC_EVERY == 0
        self._ticks += 1
        for guild in self.bot.guilds:
            try:
                await self.run_guild(guild, sync_amp=sync_amp)
            except Exception as error:
                log.warning("Server-News fuer %s: %s", guild.name, error)

    @tick.before_loop
    async def _before_tick(self) -> None:
        await self.bot.wait_until_ready()

    async def run_guild(self, guild: discord.Guild, *, sync_amp: bool = False) -> None:
        settings = await load_settings(guild.id)
        channel = guild.get_channel(settings.channel_id) if settings.channel_id else None
        if channel is None:
            return
        async with get_db_session() as db:
            servers = (await db.execute(select(Server).where(Server.guild_id == guild.id))).scalars().all()
        if sync_amp and settings.amp_schedule:
            await self.sync_amp_schedule(guild.id, servers, max(settings.leads))
        now = utcnow()
        notices = await open_notices(guild.id)
        for notice, server in notices:
            await self.handle_notice(guild, channel, settings, notice, server, now)
        # angekuendigt = gerade unten wegen Neustart/Wartung oder kurz davor/danach -> kein "Ausfall"
        planned = {
            s.id for n, s in await open_notices(guild.id)
            if n.status == "running" or abs((n.at - now).total_seconds()) <= 600
        }
        for server in servers:
            await self.watch_state(guild, channel, settings, server, planned)

    async def send(self, channel, text: str, settings, *, ping: bool) -> None:
        role = channel.guild.get_role(settings.ping_role_id) if ping and settings.ping_role_id else None
        content = f"{text}\n{role.mention}" if role else text
        try:
            await channel.send(content[:2000], allowed_mentions=discord.AllowedMentions(roles=[role] if role else False, everyone=False, users=False))
        except discord.HTTPException as error:
            log.warning("Server-News nicht gesendet: %s", error)

    async def ingame(self, settings, server: Server, text: str) -> None:
        template = settings.ingame.get(str(server.id))
        if not template:
            return
        try:
            await amp_client.send_console_message(server.amp_instance_id, template.replace("{text}", text))
        except Exception as error:
            log.info("Hinweis im Spiel fuer %s nicht gesendet: %s", server.display_name, error)

    async def handle_notice(self, guild, channel, settings, notice: ServerNotice, server: Server, now) -> None:
        name = server.display_name
        if notice.status == "pending":
            lead, sent = due_lead(notice, settings.leads, now)
            if lead is not None:
                first = notice.sent_leads in ("", "[]")
                await self.send(channel, announce_text(notice, name, reminder=not first), settings, ping=first)
                await self.ingame(settings, server, ingame_text(notice, max(0, round((notice.at - now).total_seconds() / 60))))
                await set_status(notice.id, "pending", sent)
            if now >= notice.at:
                await self.ingame(settings, server, ingame_text(notice, 0))
                if notice.origin == "manual":
                    await self.execute(notice, server)
                icon = "🔧" if notice.kind == "maintenance" else "🔄"
                text = f"{icon} Wartung an **{name}** hat begonnen" if notice.kind == "maintenance" else f"{icon} **{name}** startet jetzt neu"
                if notice.kind == "stop":
                    text = f"⏹️ **{name}** wird jetzt gestoppt"
                await self.send(channel, text, settings, ping=False)
                await set_status(notice.id, "running")
                self._up[server.id] = False
            return
        # running: zu Ende, sobald der Server wieder laeuft (Wartung/Stopp: wenn ihn jemand startet)
        if now - notice.at < timedelta(minutes=1):
            return
        if await _is_up(server):
            address = await connect_address(server)
            await self.send(channel, f"✅ **{name}** läuft wieder" + (f" – `{address}`" if address else ""), settings, ping=False)
            await set_status(notice.id, "done")
            self._up[server.id] = True
        elif notice.kind in ("restart", "update") and now - notice.at > timedelta(hours=2):
            await set_status(notice.id, "done")  # haengt - nicht ewig offen lassen

    async def execute(self, notice: ServerNotice, server: Server) -> None:
        try:
            if notice.kind == "maintenance" or notice.kind == "stop":
                await amp_client.stop(server.amp_instance_id)
            else:
                await amp_client.instance_core_call(server.amp_instance_id, "RestartApplication", {})
        except Exception as error:
            log.warning("Angekuendigte Aktion fuer %s fehlgeschlagen: %s", server.display_name, error)

    async def watch_state(self, guild, channel, settings, server: Server, planned: set[int]) -> None:
        up = await _is_up(server)
        if up is None:
            return
        before = self._up.get(server.id)
        self._up[server.id] = up
        if before is None or before == up or server.id in planned:
            return
        if not up and settings.outages:
            self._outage.add(server.id)
            await self.send(channel, f"⚠️ **{server.display_name}** ist offline (nicht angekündigt)", settings, ping=False)
        elif up and server.id in self._outage:
            self._outage.discard(server.id)
            address = await connect_address(server)
            await self.send(channel, f"✅ **{server.display_name}** läuft wieder" + (f" – `{address}`" if address else ""), settings, ping=False)

    async def sync_amp_schedule(self, guild_id: int, servers, max_lead: int) -> None:
        """Naechste geplante Laeufe aus AMP als Ankuendigungen anlegen (je Lauf einmal)."""
        now_local = local_now()
        horizon = now_local + timedelta(minutes=max_lead + 15)
        for server in servers:
            try:
                runs = await planned_runs(amp_client.instance_core_call, server.amp_instance_id, now_local)
            except Exception:
                continue  # Instanz aus oder Recht fehlt - Vorschau im Tab zeigt den Grund
            for run in runs:
                if run.at > horizon:
                    continue
                await create_notice(
                    guild_id, server.id, run.kind, local_to_utc(run.at), origin="amp",
                    amp_key=f"{server.id}:{run.trigger_id}:{run.at:%Y%m%d%H%M}"[:80],
                )

    # --- Befehle ----------------------------------------------------------------------

    @wartung_group.command(name="neustart", description="Neustart ankuendigen - der Bot startet den Server zur Zeit neu")
    @app_commands.describe(name="Server", start="Minuten ab jetzt (z.B. 15) oder Uhrzeit (z.B. 20:00)", grund="Grund, z.B. Mod-Update")
    @app_commands.autocomplete(name=_server_choices)
    @require_capability("server.control")
    async def restart_cmd(self, interaction: discord.Interaction, name: str, start: str, grund: str | None = None) -> None:
        await self._plan(interaction, name, "restart", start, None, grund)

    @wartung_group.command(name="plane", description="Wartung ankuendigen - der Bot stoppt den Server zur Zeit")
    @app_commands.describe(
        name="Server", start="Minuten ab jetzt (z.B. 30) oder Uhrzeit (z.B. 20:00)", dauer="ungefaehre Dauer in Minuten", grund="Grund"
    )
    @app_commands.autocomplete(name=_server_choices)
    @require_capability("server.control")
    async def maintenance_cmd(
        self, interaction: discord.Interaction, name: str, start: str, dauer: app_commands.Range[int, 1, 1440] | None = None, grund: str | None = None
    ) -> None:
        await self._plan(interaction, name, "maintenance", start, dauer, grund)

    async def _plan(self, interaction, name, kind, start, duration, reason) -> None:
        await interaction.response.defer(ephemeral=True)
        server = await _server(interaction.guild_id, name)
        at = parse_start(start)
        if server is None:
            await interaction.followup.send(f"Server `{name}` nicht gefunden.", ephemeral=True)
            return
        if at is None:
            await interaction.followup.send("Startzeit bitte als Minuten (z.B. `15`) oder Uhrzeit (z.B. `20:00`).", ephemeral=True)
            return
        await ensure_guild(interaction.guild_id, interaction.guild.name)
        notice = await create_notice(interaction.guild_id, server.id, kind, at, duration_min=duration, reason=grund_or(reason), created_by=interaction.user.id)
        settings = await load_settings(interaction.guild_id)
        hint = "" if settings.channel_id else " Achtung: Im Tab Server-News ist noch kein Kanal eingestellt."
        await interaction.followup.send(
            f"Angekündigt (Nr. {notice.id}): {server.display_name} <t:{unix(at)}:t>. Die erste Meldung geht gleich raus.{hint}", ephemeral=True
        )
        await self.run_guild(interaction.guild)

    @wartung_group.command(name="liste", description="Angekuendigte Neustarts und Wartungen")
    @require_capability("server.control")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        rows = await open_notices(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("Nichts angekündigt.", ephemeral=True)
            return
        lines = [
            f"`{n.id}` <t:{unix(n.at)}:f> · **{s.display_name}** · {n.kind}{' (AMP)' if n.origin == 'amp' else ''}"
            + (" · läuft" if n.status == "running" else "") + (f" · {n.reason}" if n.reason else "")
            for n, s in rows
        ]
        await interaction.response.send_message("\n".join(lines)[:2000], ephemeral=True)

    @wartung_group.command(name="abbrechen", description="Angekuendigten Neustart / angekuendigte Wartung absagen")
    @app_commands.describe(nummer="Nummer aus /wartung liste")
    @require_capability("server.control")
    async def cancel_cmd(self, interaction: discord.Interaction, nummer: int) -> None:
        await interaction.response.send_message(await self.cancel(interaction.guild, nummer), ephemeral=True)

    @wartung_group.command(name="ende", description="Wartung beenden (startet den Server, meldet 'laeuft wieder')")
    @app_commands.autocomplete(name=_server_choices)
    @require_capability("server.control")
    async def end_cmd(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        server = await _server(interaction.guild_id, name)
        if server is None:
            await interaction.followup.send(f"Server `{name}` nicht gefunden.", ephemeral=True)
            return
        try:
            await amp_client.start(server.amp_instance_id)
        except Exception as error:
            await interaction.followup.send(f"Start fehlgeschlagen: {error}", ephemeral=True)
            return
        await interaction.followup.send(f"{server.display_name} startet – sobald er läuft, kommt „läuft wieder“.", ephemeral=True)

    async def cancel(self, guild: discord.Guild, notice_id: int) -> str:
        async with get_db_session() as db:
            notice = await db.get(ServerNotice, notice_id)
            server = await db.get(Server, notice.server_id) if notice else None
        if notice is None or notice.guild_id != guild.id or notice.status not in ("pending", "running"):
            return "Diese Ankündigung gibt es nicht (mehr)."
        await set_status(notice.id, "cancelled")
        settings = await load_settings(guild.id)
        channel = guild.get_channel(settings.channel_id) if settings.channel_id else None
        if channel is not None and notice.sent_leads not in ("", "[]") and notice.status == "pending":
            await self.send(channel, f"❎ Abgesagt: {server.display_name if server else '?'} – <t:{unix(notice.at)}:t> findet nicht statt", settings, ping=False)
        return "Abgesagt."


def grund_or(reason: str | None) -> str | None:
    return reason.strip()[:200] if reason and reason.strip() else None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerNewsCog(bot))
