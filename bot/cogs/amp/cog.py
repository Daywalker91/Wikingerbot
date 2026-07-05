import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import select

from bot.core.amp_client import amp_client
from bot.core.base_cog import BaseCog
from bot.core.permissions import Level, require_role
from db.models.server import Server
from db.session import get_db_session

server_group = app_commands.Group(name="server", description="AMP-Serververwaltung")


async def _get_server(guild_id: int, name: str) -> Server | None:
    async with get_db_session() as db:
        result = await db.execute(
            select(Server).where(Server.guild_id == guild_id, Server.instance_name == name)
        )
        return result.scalar_one_or_none()


class AMPCog(BaseCog):
    """Bindet AMP-Instanzen an Discord an: Start/Stop/Status, Konsolen- und Chat-Bridge."""

    __cog_name__ = "amp"
    __version__ = "1.0.0"
    __description__ = "AMP-Integration (Start/Stop/Status/Console/Chat-Bridge)"
    __author__ = "Daywalker91"

    async def cog_load(self) -> None:
        self.bot.tree.add_command(server_group)
        self.console_bridge.start()

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(server_group.name)
        self.console_bridge.cancel()

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
            for line in lines:
                if line.contents:
                    await channel.send(f"`[{line.source}]` {line.contents}"[:2000])

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
        async with get_db_session() as db:
            result = await db.execute(
                select(Server).where(
                    Server.guild_id == interaction.guild_id, Server.hidden.is_(False)
                )
            )
            servers = result.scalars().all()

        if not servers:
            await interaction.response.send_message("Keine Server konfiguriert.", ephemeral=True)
            return

        lines = []
        for server in servers:
            try:
                status = await amp_client.get_status(server.amp_instance_id)
                state = status.State.name
            except Exception:
                state = "Nicht erreichbar"
            lines.append(f"**{server.display_name}** (`{server.instance_name}`) — {state}")

        await interaction.response.send_message("\n".join(lines))

    @server_group.command(name="status", description="Detail-Status eines Servers")
    @app_commands.describe(name="Interner Servername (instance_name)")
    @require_role(Level.MEMBER)
    async def server_status(self, interaction: discord.Interaction, name: str) -> None:
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await interaction.response.send_message(f"Server `{name}` nicht gefunden.", ephemeral=True)
            return

        try:
            status = await amp_client.get_status(server.amp_instance_id)
        except Exception as exc:
            await interaction.response.send_message(f"AMP nicht erreichbar: {exc}", ephemeral=True)
            return

        embed = discord.Embed(title=server.display_name)
        embed.add_field(name="Status", value=status.State.name)
        embed.add_field(name="Uptime", value=status.Uptime)
        embed.add_field(name="Verbinden unter", value=server.host, inline=False)
        await interaction.response.send_message(embed=embed)

    @server_group.command(name="start", description="Startet einen Server")
    @app_commands.describe(name="Interner Servername (instance_name)")
    @require_role(Level.MOD)
    async def server_start(self, interaction: discord.Interaction, name: str) -> None:
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await interaction.response.send_message(f"Server `{name}` nicht gefunden.", ephemeral=True)
            return

        await amp_client.start(server.amp_instance_id)
        await interaction.response.send_message(f"Starte `{server.display_name}` ...")

    @server_group.command(name="stop", description="Stoppt einen Server")
    @app_commands.describe(name="Interner Servername (instance_name)")
    @require_role(Level.MOD)
    async def server_stop(self, interaction: discord.Interaction, name: str) -> None:
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await interaction.response.send_message(f"Server `{name}` nicht gefunden.", ephemeral=True)
            return

        await amp_client.stop(server.amp_instance_id)
        await interaction.response.send_message(f"Stoppe `{server.display_name}` ...")

    @server_group.command(name="console", description="Sendet einen Konsolenbefehl")
    @app_commands.describe(name="Interner Servername (instance_name)", command="Konsolenbefehl")
    @require_role(Level.MOD)
    async def server_console(self, interaction: discord.Interaction, name: str, command: str) -> None:
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await interaction.response.send_message(f"Server `{name}` nicht gefunden.", ephemeral=True)
            return

        await amp_client.send_console_message(server.amp_instance_id, command)
        await interaction.response.send_message(f"Befehl an `{server.display_name}` gesendet.", ephemeral=True)

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
            await interaction.followup.send("Alle bekannten AMP-Instanzen sind bereits angelegt.")
            return

        lines = [
            f"`{i.instance_id}` — {i.friendly_name} ({i.module}, {'laeuft' if i.running else 'gestoppt'})"
            for i in unknown
        ]
        await interaction.followup.send("\n".join(lines))

    @server_group.command(name="add", description="Legt einen neuen Server-Eintrag an")
    @app_commands.describe(
        name="Interner Servername (instance_name)",
        amp_instance_id="AMP-Instanz-ID (siehe /server discover)",
        display_name="Anzeigename",
        host="Verbindungs-Adresse fuer Spieler",
    )
    @require_role(Level.OWNER)
    async def server_add(
        self,
        interaction: discord.Interaction,
        name: str,
        amp_instance_id: str,
        display_name: str,
        host: str,
    ) -> None:
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

        await interaction.response.send_message(f"Server `{display_name}` angelegt.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AMPCog(bot))
