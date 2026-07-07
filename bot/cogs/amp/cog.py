import asyncio
import re

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands, tasks
from sqlalchemy import select

from bot.core.amp_client import amp_client
from bot.core.base_cog import BaseCog
from bot.core.console_filters import (
    BUILTIN_EVENT_PATTERNS,
    BUILTIN_FILTER_PATTERNS,
    active_builtin_patterns,
    classify,
)
from bot.core.discord_utils import MESSAGE_TIMEOUT, send_temp_followup as _followup_temp
from bot.core.entities import ensure_guild
from bot.core.permissions import Level, require_role
from db.models.console_pattern import ConsolePattern, ConsolePatternKind, ConsolePatternOverride
from db.models.server import ConsoleFilterMode, Server
from db.session import get_db_session


async def _get_server(guild_id: int, name: str) -> Server | None:
    async with get_db_session() as db:
        result = await db.execute(
            select(Server).where(Server.guild_id == guild_id, Server.instance_name == name)
        )
        return result.scalar_one_or_none()


async def _autocomplete_instance_name(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Schlaegt bereits angelegte Server dieser Guild vor."""
    async with get_db_session() as db:
        result = await db.execute(
            select(Server.instance_name, Server.display_name).where(
                Server.guild_id == interaction.guild_id
            )
        )
        rows = result.all()

    current_lower = current.lower()
    choices = [
        app_commands.Choice(name=f"{display_name} ({instance_name})", value=instance_name)
        for instance_name, display_name in rows
        if current_lower in instance_name.lower() or current_lower in display_name.lower()
    ]
    return choices[:25]


async def _autocomplete_amp_instance_id(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Schlaegt am Controller bekannte, noch nicht angelegte AMP-Instanzen vor."""
    try:
        instances = await amp_client.list_instances()
    except Exception:
        return []

    async with get_db_session() as db:
        result = await db.execute(select(Server.amp_instance_id))
        known_ids = {row[0] for row in result.all()}

    current_lower = current.lower()
    choices = [
        app_commands.Choice(name=f"{i.friendly_name} ({i.module})", value=i.instance_id)
        for i in instances
        if i.instance_id not in known_ids
        and (current_lower in i.friendly_name.lower() or current_lower in i.instance_id.lower())
    ]
    return choices[:25]


async def _autocomplete_custom_pattern(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    """Schlaegt eigene Muster vor - eingeschraenkt auf den bereits gewaehlten Server, falls vorhanden."""
    server_name = getattr(interaction.namespace, "name", None)

    async with get_db_session() as db:
        query = (
            select(ConsolePattern.id, ConsolePattern.kind, ConsolePattern.pattern, Server.instance_name)
            .join(Server, Server.id == ConsolePattern.server_id)
            .where(Server.guild_id == interaction.guild_id)
        )
        if server_name:
            query = query.where(Server.instance_name == server_name)
        result = await db.execute(query)
        rows = result.all()

    current_lower = current.lower()
    choices = []
    for pattern_id, kind, pattern, instance_name in rows:
        label = f"#{pattern_id} [{kind.value}] {pattern} ({instance_name})"
        if current_lower in label.lower():
            choices.append(app_commands.Choice(name=label[:100], value=pattern_id))
    return choices[:25]


async def _autocomplete_builtin_key(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Schlaegt eingebaute Muster-Keys vor, passend zur bereits gewaehlten kind-Option."""
    kind_value = getattr(interaction.namespace, "kind", None)
    builtins = BUILTIN_EVENT_PATTERNS if kind_value == "event" else BUILTIN_FILTER_PATTERNS

    current_lower = current.lower()
    return [
        app_commands.Choice(name=f"{key} ({pattern})"[:100], value=key)
        for key, pattern in builtins.items()
        if current_lower in key.lower()
    ][:25]


class AMPCog(BaseCog):
    """Bindet AMP-Instanzen an Discord an: Start/Stop/Status, Konsolen- und Chat-Bridge."""

    __cog_name__ = "amp"
    __version__ = "1.0.0"
    __description__ = "AMP-Integration (Start/Stop/Status/Console/Chat-Bridge)"
    __author__ = "Daywalker91"

    # Als Klassen-Attribut (nicht Modul-Level!), damit discord.py es beim
    # Hinzufuegen des Cogs automatisch an die Instanz bindet (siehe Cog._inject).
    server_group = app_commands.Group(name="server", description="AMP-Serververwaltung")

    async def cog_load(self) -> None:
        self.console_bridge.start()

    async def cog_unload(self) -> None:
        self.console_bridge.cancel()

    async def _get_patterns(self, server_id: int) -> tuple[list[str], list[str], list[str], list[str]]:
        """Gibt (aktive eingebaute Filter, eigene Filter, aktive eingebaute Events, eigene Events) zurueck."""
        async with get_db_session() as db:
            override_result = await db.execute(
                select(ConsolePatternOverride.kind, ConsolePatternOverride.builtin_key).where(
                    ConsolePatternOverride.server_id == server_id,
                    ConsolePatternOverride.enabled.is_(False),
                )
            )
            disabled_filter_keys: set[str] = set()
            disabled_event_keys: set[str] = set()
            for kind, key in override_result.all():
                if kind == ConsolePatternKind.FILTER:
                    disabled_filter_keys.add(key)
                else:
                    disabled_event_keys.add(key)

            custom_result = await db.execute(
                select(ConsolePattern.kind, ConsolePattern.pattern).where(
                    ConsolePattern.server_id == server_id
                )
            )
            custom_filters: list[str] = []
            custom_events: list[str] = []
            for kind, pattern in custom_result.all():
                if kind == ConsolePatternKind.FILTER:
                    custom_filters.append(pattern)
                else:
                    custom_events.append(pattern)

        active_filters = active_builtin_patterns(BUILTIN_FILTER_PATTERNS, disabled_filter_keys)
        active_events = active_builtin_patterns(BUILTIN_EVENT_PATTERNS, disabled_event_keys)
        return active_filters, custom_filters, active_events, custom_events

    @tasks.loop(seconds=2)
    async def console_bridge(self) -> None:
        async with get_db_session() as db:
            result = await db.execute(select(Server).where(Server.console_channel.is_not(None)))
            servers = result.scalars().all()

        for server in servers:
            channel = self.bot.get_channel(server.console_channel)
            if channel is None:
                continue
            try:
                lines = await amp_client.poll_console(server.amp_instance_id)
            except Exception:
                continue
            if not lines:
                continue

            event_channel = (
                self.bot.get_channel(server.event_channel) if server.event_channel else None
            )
            active_filters, custom_filters, active_events, custom_events = await self._get_patterns(
                server.id
            )

            for line in lines:
                if not line.contents:
                    continue
                outcome = classify(
                    line.contents,
                    filter_mode=server.console_filter_mode.value,
                    active_builtin_filters=active_filters,
                    custom_filter_patterns=custom_filters,
                    active_builtin_events=active_events,
                    custom_event_patterns=custom_events,
                )
                if outcome == "suppress":
                    continue
                target = event_channel if outcome == "event" and event_channel is not None else channel
                await target.send(f"`[{line.source}]` {line.contents}"[:2000])

    @console_bridge.before_loop
    async def _before_console_bridge(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener("on_message")
    async def relay_chat_to_game(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        async with get_db_session() as db:
            result = await db.execute(
                select(Server).where(Server.chat_channel == message.channel.id)
            )
            server = result.scalar_one_or_none()

        if server is None:
            return

        await amp_client.send_console_message(
            server.amp_instance_id, f"say {message.author.display_name}: {message.content}"
        )

    @server_group.command(name="list", description="Listet alle konfigurierten Server")
    @require_role(Level.MEMBER)
    async def server_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        async with get_db_session() as db:
            result = await db.execute(
                select(Server).where(
                    Server.guild_id == interaction.guild_id, Server.hidden.is_(False)
                )
            )
            servers = result.scalars().all()

        if not servers:
            await _followup_temp(interaction, "Keine Server konfiguriert.")
            return

        async def _state(server: Server) -> str:
            try:
                status = await amp_client.get_status(server.amp_instance_id)
                return status.State.name
            except Exception:
                return "Nicht erreichbar (evtl. gestoppt)"

        states = await asyncio.gather(*(_state(server) for server in servers))
        lines = [
            f"**{server.display_name}** (`{server.instance_name}`) — {state}"
            for server, state in zip(servers, states)
        ]

        await _followup_temp(interaction, "\n".join(lines))

    @server_group.command(name="status", description="Detail-Status eines Servers")
    @app_commands.describe(name="Interner Servername (instance_name)")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.MEMBER)
    async def server_status(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)

        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        try:
            status = await amp_client.get_status(server.amp_instance_id)
        except Exception:
            await _followup_temp(
                interaction, f"`{server.display_name}` ist nicht erreichbar (evtl. gestoppt)."
            )
            return

        embed = discord.Embed(title=server.display_name)
        embed.add_field(name="Status", value=status.State.name)
        embed.add_field(name="Uptime", value=status.Uptime)
        embed.add_field(name="Verbinden unter", value=server.host, inline=False)
        await _followup_temp(interaction, embed=embed)

    @server_group.command(name="start", description="Startet einen Server")
    @app_commands.describe(name="Interner Servername (instance_name)")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.MOD)
    async def server_start(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)

        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        try:
            await amp_client.start(server.amp_instance_id)
        except Exception as exc:
            await _followup_temp(interaction, f"Start fehlgeschlagen: {exc}")
            return
        await _followup_temp(interaction, f"Starte `{server.display_name}` ...")

    @server_group.command(name="stop", description="Stoppt einen Server")
    @app_commands.describe(name="Interner Servername (instance_name)")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.MOD)
    async def server_stop(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)

        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        try:
            await amp_client.stop(server.amp_instance_id)
        except Exception as exc:
            await _followup_temp(interaction, f"Stop fehlgeschlagen: {exc}")
            return
        await _followup_temp(interaction, f"Stoppe `{server.display_name}` ...")

    @server_group.command(name="console", description="Sendet einen Konsolenbefehl")
    @app_commands.describe(name="Interner Servername (instance_name)", command="Konsolenbefehl")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.MOD)
    async def server_console(self, interaction: discord.Interaction, name: str, command: str) -> None:
        await interaction.response.defer(ephemeral=True)

        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        try:
            await amp_client.send_console_message(server.amp_instance_id, command)
        except Exception as exc:
            await _followup_temp(interaction, f"Befehl fehlgeschlagen: {exc}")
            return
        await _followup_temp(interaction, f"Befehl an `{server.display_name}` gesendet.")

    @server_group.command(name="discover", description="Listet AMP-Instanzen, die noch nicht angelegt sind")
    @require_role(Level.OWNER)
    async def server_discover(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        instances = await amp_client.list_instances()

        async with get_db_session() as db:
            result = await db.execute(select(Server.amp_instance_id))
            known_ids = {row[0] for row in result.all()}

        unknown = [i for i in instances if i.instance_id not in known_ids]
        if not unknown:
            await _followup_temp(interaction, "Alle bekannten AMP-Instanzen sind bereits angelegt.")
            return

        lines = [
            f"`{i.instance_id}` — {i.friendly_name} ({i.module}, {'laeuft' if i.running else 'gestoppt'})"
            for i in unknown
        ]
        await _followup_temp(interaction, "\n".join(lines))

    @server_group.command(name="add", description="Legt einen neuen Server-Eintrag an")
    @app_commands.describe(
        name="Interner Servername (instance_name)",
        amp_instance_id="AMP-Instanz-ID (siehe /server discover)",
        display_name="Anzeigename",
        host="Verbindungs-Adresse fuer Spieler",
    )
    @app_commands.autocomplete(amp_instance_id=_autocomplete_amp_instance_id)
    @require_role(Level.OWNER)
    async def server_add(
        self,
        interaction: discord.Interaction,
        name: str,
        amp_instance_id: str,
        display_name: str,
        host: str,
    ) -> None:
        await ensure_guild(interaction.guild_id, interaction.guild.name)

        async with get_db_session() as db:
            db.add(
                Server(
                    guild_id=interaction.guild_id,
                    instance_name=name,
                    amp_instance_id=amp_instance_id,
                    display_name=display_name,
                    host=host,
                )
            )
            await db.commit()

        await interaction.response.send_message(
            f"Server `{display_name}` angelegt.", ephemeral=True, delete_after=MESSAGE_TIMEOUT
        )

    async def _set_channel(
        self,
        interaction: discord.Interaction,
        name: str,
        field: str,
        label: str,
        channel: discord.TextChannel | None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        async with get_db_session() as db:
            db_server = await db.get(Server, server.id)
            setattr(db_server, field, channel.id if channel is not None else None)
            await db.commit()

        mention = channel.mention if channel is not None else "kein Kanal"
        await _followup_temp(
            interaction, f"{label} fuer `{server.display_name}` gesetzt auf {mention}."
        )

    @server_group.command(name="console_channel", description="Setzt den Konsolen-Kanal eines Servers")
    @app_commands.describe(name="Interner Servername (instance_name)", channel="Zielkanal (leer = deaktivieren)")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def server_console_channel(
        self, interaction: discord.Interaction, name: str, channel: discord.TextChannel | None = None
    ) -> None:
        await self._set_channel(interaction, name, "console_channel", "Konsolen-Kanal", channel)

    @server_group.command(name="chat_channel", description="Setzt den Chat-Bruecken-Kanal eines Servers")
    @app_commands.describe(name="Interner Servername (instance_name)", channel="Zielkanal (leer = deaktivieren)")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def server_chat_channel(
        self, interaction: discord.Interaction, name: str, channel: discord.TextChannel | None = None
    ) -> None:
        await self._set_channel(interaction, name, "chat_channel", "Chat-Kanal", channel)

    @server_group.command(name="event_channel", description="Setzt den Event-Kanal eines Servers")
    @app_commands.describe(name="Interner Servername (instance_name)", channel="Zielkanal (leer = deaktivieren)")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def server_event_channel(
        self, interaction: discord.Interaction, name: str, channel: discord.TextChannel | None = None
    ) -> None:
        await self._set_channel(interaction, name, "event_channel", "Event-Kanal", channel)

    @server_group.command(
        name="console_filter_mode", description="Setzt den Rauschfilter-Modus eines Servers"
    )
    @app_commands.describe(name="Interner Servername (instance_name)", mode="Filter-Modus")
    @app_commands.choices(
        mode=[
            Choice(name="Aus", value="off"),
            Choice(name="Blacklist (Standard-Rauschen ausblenden)", value="blacklist"),
            Choice(name="Whitelist (nur eigene Muster zeigen)", value="whitelist"),
        ]
    )
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def server_console_filter_mode(
        self, interaction: discord.Interaction, name: str, mode: Choice[str]
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        async with get_db_session() as db:
            db_server = await db.get(Server, server.id)
            db_server.console_filter_mode = ConsoleFilterMode(mode.value)
            await db.commit()

        await _followup_temp(
            interaction, f"Filter-Modus fuer `{server.display_name}` auf `{mode.name}` gesetzt."
        )

    @server_group.command(name="pattern_add", description="Fuegt ein eigenes Regex-Muster hinzu")
    @app_commands.describe(
        name="Interner Servername (instance_name)",
        kind="Filter (Rauschen) oder Event (Join/Leave)",
        pattern="Regex-Muster",
    )
    @app_commands.choices(
        kind=[
            Choice(name="Filter (Rauschen)", value="filter"),
            Choice(name="Event (Join/Leave)", value="event"),
        ]
    )
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def server_pattern_add(
        self, interaction: discord.Interaction, name: str, kind: Choice[str], pattern: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        try:
            re.compile(pattern)
        except re.error as exc:
            await _followup_temp(interaction, f"Ungueltiges Regex-Muster: {exc}")
            return

        async with get_db_session() as db:
            db.add(
                ConsolePattern(
                    server_id=server.id, kind=ConsolePatternKind(kind.value), pattern=pattern
                )
            )
            await db.commit()

        await _followup_temp(
            interaction, f"Muster `{pattern}` ({kind.name}) fuer `{server.display_name}` hinzugefuegt."
        )

    @server_group.command(name="pattern_remove", description="Entfernt ein eigenes Regex-Muster")
    @app_commands.describe(name="Interner Servername (instance_name)", pattern_id="Muster-ID")
    @app_commands.autocomplete(name=_autocomplete_instance_name, pattern_id=_autocomplete_custom_pattern)
    @require_role(Level.OWNER)
    async def server_pattern_remove(
        self, interaction: discord.Interaction, name: str, pattern_id: int
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        async with get_db_session() as db:
            pattern = await db.get(ConsolePattern, pattern_id)
            if pattern is None:
                await _followup_temp(interaction, f"Muster `#{pattern_id}` nicht gefunden.")
                return
            await db.delete(pattern)
            await db.commit()

        await _followup_temp(interaction, f"Muster `#{pattern_id}` entfernt.")

    @server_group.command(
        name="pattern_toggle", description="Aktiviert/deaktiviert ein eingebautes Muster fuer einen Server"
    )
    @app_commands.describe(
        name="Interner Servername (instance_name)",
        kind="Filter (Rauschen) oder Event (Join/Leave)",
        key="Eingebauter Muster-Key",
        enabled="Aktivieren oder deaktivieren",
    )
    @app_commands.choices(
        kind=[
            Choice(name="Filter (Rauschen)", value="filter"),
            Choice(name="Event (Join/Leave)", value="event"),
        ]
    )
    @app_commands.autocomplete(name=_autocomplete_instance_name, key=_autocomplete_builtin_key)
    @require_role(Level.OWNER)
    async def server_pattern_toggle(
        self, interaction: discord.Interaction, name: str, kind: Choice[str], key: str, enabled: bool
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        builtins = BUILTIN_EVENT_PATTERNS if kind.value == "event" else BUILTIN_FILTER_PATTERNS
        if key not in builtins:
            await _followup_temp(interaction, f"Unbekannter eingebauter Key `{key}`.")
            return

        kind_enum = ConsolePatternKind(kind.value)
        async with get_db_session() as db:
            result = await db.execute(
                select(ConsolePatternOverride).where(
                    ConsolePatternOverride.server_id == server.id,
                    ConsolePatternOverride.kind == kind_enum,
                    ConsolePatternOverride.builtin_key == key,
                )
            )
            override = result.scalar_one_or_none()

            if enabled:
                if override is not None:
                    await db.delete(override)
            elif override is None:
                db.add(
                    ConsolePatternOverride(
                        server_id=server.id, kind=kind_enum, builtin_key=key, enabled=False
                    )
                )
            else:
                override.enabled = False
            await db.commit()

        status = "aktiviert" if enabled else "deaktiviert"
        await _followup_temp(
            interaction, f"Eingebautes Muster `{key}` fuer `{server.display_name}` {status}."
        )

    @server_group.command(name="pattern_list", description="Listet Filter-/Event-Muster eines Servers")
    @app_commands.describe(
        name="Interner Servername (instance_name)", kind="Filter (Rauschen) oder Event (Join/Leave)"
    )
    @app_commands.choices(
        kind=[
            Choice(name="Filter (Rauschen)", value="filter"),
            Choice(name="Event (Join/Leave)", value="event"),
        ]
    )
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.MOD)
    async def server_pattern_list(
        self, interaction: discord.Interaction, name: str, kind: Choice[str]
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        kind_enum = ConsolePatternKind(kind.value)
        builtins = BUILTIN_EVENT_PATTERNS if kind.value == "event" else BUILTIN_FILTER_PATTERNS

        async with get_db_session() as db:
            override_result = await db.execute(
                select(ConsolePatternOverride.builtin_key).where(
                    ConsolePatternOverride.server_id == server.id,
                    ConsolePatternOverride.kind == kind_enum,
                    ConsolePatternOverride.enabled.is_(False),
                )
            )
            disabled_keys = {row[0] for row in override_result.all()}

            custom_result = await db.execute(
                select(ConsolePattern.id, ConsolePattern.pattern).where(
                    ConsolePattern.server_id == server.id, ConsolePattern.kind == kind_enum
                )
            )
            custom_rows = custom_result.all()

        builtin_lines = [
            f"{'🟢' if key not in disabled_keys else '⚪'} `{key}` — `{pattern}`"
            for key, pattern in builtins.items()
        ]
        custom_lines = [f"`#{pattern_id}` — `{pattern}`" for pattern_id, pattern in custom_rows]

        lines = ["**Eingebaut:**", *builtin_lines, "", "**Eigene:**", *(custom_lines or ["(keine)"])]
        await _followup_temp(interaction, "\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AMPCog(bot))
