import asyncio
import io
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands, tasks
from PIL import Image
from sqlalchemy import func, select

from bot.core.amp_client import amp_client
from bot.cogs.banner.embed import build_embed, build_group_embed, image_card
from bot.cogs.banner.image import _status_color, extract_players, render_banner, render_banner_group
from bot.cogs.banner.themes import BANNER_THEMES, BLUR_LEVELS, PRESET_COLORS
from bot.core.base_cog import BaseCog
from bot.core.capabilities import require_capability
from bot.core.discord_utils import send_temp_followup as _followup_temp
from bot.core.entities import ensure_guild
from bot.core.permissions import Level, check_level_interaction, require_role
from bot.core.server_address import connect_address
from bot.core.steam_art import fetch_header_image
from db.models.banner_group import BannerGroup, BannerGroupLayout
from db.models.server import BannerType, Server
from db.models.user import User
from db.models.whitelist import WhitelistRequest, WhitelistStatus
from db.session import get_db_session

BACKGROUND_DIR = Path("data/banner_backgrounds")
log = logging.getLogger("wikingerbot.banner")
RECHECK_SECONDS = 600


def _digest(content, embeds, files) -> str:
    """Fingerabdruck eines Banners - ohne Zeitstempel des Embeds, mit den Bildbytes."""
    import hashlib
    import json as _json

    h = hashlib.sha256(str(content or "").encode())
    for embed in embeds:
        if embed is not None:
            data = embed.to_dict()
            data.pop("timestamp", None)
            h.update(_json.dumps(data, sort_keys=True, default=str).encode())
    for file in files:
        if file is not None and hasattr(file.fp, "getvalue"):
            h.update(file.fp.getvalue())
    return h.hexdigest()
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_GROUP_MEMBERS = 6
# Schutz gegen wiederholtes Anrennen gegen ein haengendes Rate-Limit: nach jedem
# Fehlschlag verdoppelt sich die Pause fuer dieses Ziel, bis zur Obergrenze.
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 1800
TYPE_CHOICES = [Choice(name="Embed", value="embed"), Choice(name="Bild", value="image")]
THEME_CHOICES = [Choice(name=key.capitalize(), value=key) for key in BANNER_THEMES]
LAYOUT_CHOICES = [
    Choice(name="Kombiniert (ein gestapeltes Bild/Embed)", value="combined"),
    Choice(name="Einzeln (ein Bild/Embed pro Server, eigenes Artwork)", value="separate"),
]

# Fuer Vorschauen im Customize-Editor - kein echter AMP-Aufruf noetig.
_PREVIEW_STATUS = SimpleNamespace(
    State=SimpleNamespace(name="Ready"),
    Uptime="1h 23m",
    Metrics={"Active Users": SimpleNamespace(RawValue=3, MaxValue=10)},
)
_OFFLINE_STATUS_FACTORY = lambda: SimpleNamespace(  # noqa: E731
    State=SimpleNamespace(name="Nicht erreichbar"), Uptime="", Metrics={}
)


async def _get_server(guild_id: int, name: str) -> Server | None:
    async with get_db_session() as db:
        result = await db.execute(
            select(Server).where(Server.guild_id == guild_id, Server.instance_name == name)
        )
        return result.scalar_one_or_none()


async def _get_group(guild_id: int, name: str) -> BannerGroup | None:
    async with get_db_session() as db:
        result = await db.execute(
            select(BannerGroup).where(BannerGroup.guild_id == guild_id, BannerGroup.name == name)
        )
        return result.scalar_one_or_none()


async def _autocomplete_instance_name(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with get_db_session() as db:
        result = await db.execute(
            select(Server.instance_name, Server.display_name).where(
                Server.guild_id == interaction.guild_id
            )
        )
        rows = result.all()

    current_lower = current.lower()
    return [
        app_commands.Choice(name=f"{display_name} ({instance_name})", value=instance_name)
        for instance_name, display_name in rows
        if current_lower in instance_name.lower() or current_lower in display_name.lower()
    ][:25]


async def _autocomplete_group_name(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    async with get_db_session() as db:
        result = await db.execute(
            select(BannerGroup.name).where(BannerGroup.guild_id == interaction.guild_id)
        )
        names = [row[0] for row in result.all()]

    current_lower = current.lower()
    return [Choice(name=n, value=n) for n in names if current_lower in n.lower()][:25]


def _convert_to_png(data: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(data)) as source:
        source.convert("RGB").save(path, format="PNG")


async def _save_background(data: bytes, path: Path) -> None:
    """Normalisiert ein hochgeladenes Bild auf PNG, unabhaengig vom Quellformat - in einem
    eigenen Thread, damit grosse Bilder den Bot nicht kurz anhalten."""
    await asyncio.to_thread(_convert_to_png, data, path)


class _ColorSelect(discord.ui.Select):
    def __init__(self, placeholder: str, attr: str) -> None:
        self.attr = attr
        options = [discord.SelectOption(label=name, value=hex_) for name, hex_ in PRESET_COLORS.items()]
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "BannerCustomizeView" = self.view
        if not await check_level_interaction(interaction, view.guild_id, Level.OWNER):
            return
        setattr(view, self.attr, self.values[0])
        await view.update_preview(interaction)


class _BlurSelect(discord.ui.Select):
    def __init__(self) -> None:
        options = [discord.SelectOption(label=name, value=str(radius)) for name, radius in BLUR_LEVELS.items()]
        super().__init__(placeholder="Unschaerfe waehlen", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: "BannerCustomizeView" = self.view
        if not await check_level_interaction(interaction, view.guild_id, Level.OWNER):
            return
        view.blur = int(self.values[0])
        await view.update_preview(interaction)


class BannerCustomizeView(discord.ui.View):
    """Interaktiver Editor mit Live-Vorschau.

    Zwei Modi, je nachdem ob ein Hintergrundbild (eigener Upload oder Steam-Artwork)
    aktiv ist: dann waeren Start-/Endfarbe wirkungslos (das Bild hat Vorrang vor einem
    Verlauf), daher wird stattdessen eine Schriftfarbe angeboten. Ohne Hintergrundbild
    bestimmen Start-/Endfarbe den Verlauf wie gehabt.
    """

    def __init__(
        self,
        *,
        guild_id: int,
        target_kind: str,
        target_id: int,
        color_start: str | None,
        color_end: str | None,
        text_color: str | None,
        blur: int,
        background_path: str | None,
        has_background_image: bool,
        preview_name: str,
        preview_host: str,
    ) -> None:
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.target_kind = target_kind
        self.target_id = target_id
        self.color_start = color_start
        self.color_end = color_end
        self.text_color = text_color
        self.blur = blur
        self.background_path = background_path
        self.has_background_image = has_background_image
        self.preview_name = preview_name
        self.preview_host = preview_host
        if has_background_image:
            self.add_item(_ColorSelect("Schriftfarbe waehlen", "text_color"))
        else:
            self.add_item(_ColorSelect("Startfarbe waehlen", "color_start"))
            self.add_item(_ColorSelect("Endfarbe waehlen", "color_end"))
        self.add_item(_BlurSelect())

    def _render_preview(self) -> io.BytesIO:
        return render_banner(
            self.preview_name,
            self.preview_host,
            _PREVIEW_STATUS,
            (3, 10),
            background_path=self.background_path,
            color_start=self.color_start,
            color_end=self.color_end,
            text_color=self.text_color,
            blur=self.blur,
        )

    async def update_preview(self, interaction: discord.Interaction) -> None:
        buffer = self._render_preview()
        file = discord.File(buffer, filename="preview.png")
        await interaction.response.edit_message(attachments=[file], view=self)

    @discord.ui.button(label="Vorschau", style=discord.ButtonStyle.secondary, row=3)
    async def preview_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await check_level_interaction(interaction, self.guild_id, Level.OWNER):
            return
        await self.update_preview(interaction)

    @discord.ui.button(label="Uebernehmen", style=discord.ButtonStyle.success, row=3)
    async def apply_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await check_level_interaction(interaction, self.guild_id, Level.OWNER):
            return

        async with get_db_session() as db:
            model = Server if self.target_kind == "server" else BannerGroup
            obj = await db.get(model, self.target_id)
            obj.banner_blur = self.blur
            if self.has_background_image:
                obj.banner_text_color = self.text_color
            else:
                obj.banner_color_start = self.color_start
                obj.banner_color_end = self.color_end
                obj.banner_theme = None
            await db.commit()

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Uebernommen - der Banner wird beim naechsten Update aktualisiert.",
            attachments=[],
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.danger, row=3)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await check_level_interaction(interaction, self.guild_id, Level.OWNER):
            return

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Abgebrochen - keine Aenderungen gespeichert.",
            attachments=[],
            view=self,
        )
        self.stop()


class BannerCog(BaseCog):
    """Automatisch aktualisierter Status-Banner pro Server oder Banner-Gruppe."""

    __cog_name__ = "banner"
    __version__ = "1.0.0"
    __description__ = "Server-Status-Banner (Embed/Bild), Banner-Gruppen, Steam-Artwork"
    __author__ = "Daywalker91"

    banner_group = app_commands.Group(name="banner", description="Banner fuer einen einzelnen Server")
    bannergroup_group = app_commands.Group(
        name="bannergroup", description="Banner-Gruppen (mehrere Server in einem Kanal)"
    )

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self._failures: dict[tuple[str, int], int] = {}
        # Fingerabdruck des zuletzt gesendeten Banners + wann zuletzt geprueft: unveraenderte
        # Banner nicht jede Minute neu bearbeiten (sonst bremst Discord mit Rate-Limits)
        self._digests: dict[tuple[str, int], tuple[str, float]] = {}
        self._backoff_until: dict[tuple[str, int], float] = {}

    async def cog_load(self) -> None:
        self.banner_loop.start()

    async def cog_unload(self) -> None:
        self.banner_loop.cancel()

    # --- Backoff bei wiederholten Fehlschlägen (z.B. haengendes Rate-Limit) --------

    def _should_skip(self, key: tuple[str, int]) -> bool:
        return time.monotonic() < self._backoff_until.get(key, 0.0)

    def _record_success(self, key: tuple[str, int]) -> None:
        self._failures.pop(key, None)
        self._backoff_until.pop(key, None)

    def _record_failure(self, key: tuple[str, int]) -> None:
        failures = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        backoff = min(BACKOFF_BASE_SECONDS * (2 ** (failures - 1)), BACKOFF_MAX_SECONDS)
        self._backoff_until[key] = time.monotonic() + backoff

    # --- Badge-Datenermittlung -------------------------------------------------

    async def _whitelist_badge(self, server_id: int) -> tuple[int, bool]:
        async with get_db_session() as db:
            count_result = await db.execute(
                select(func.count(WhitelistRequest.id)).where(
                    WhitelistRequest.server_id == server_id,
                    WhitelistRequest.status == WhitelistStatus.APPROVED,
                )
            )
            count = count_result.scalar_one()

            donator_result = await db.execute(
                select(func.count(User.id))
                .join(WhitelistRequest, WhitelistRequest.user_id == User.id)
                .where(
                    WhitelistRequest.server_id == server_id,
                    WhitelistRequest.status == WhitelistStatus.APPROVED,
                    User.is_donator.is_(True),
                )
            )
            has_donator = donator_result.scalar_one() > 0

        return count, has_donator

    # --- Rendering + Posting -----------------------------------------------------

    async def _resolve_background(self, server: Server) -> str | None:
        if server.banner_background_path:
            return server.banner_background_path
        if server.steam_app_id and server.banner_steam_art:
            cached = await fetch_header_image(server.steam_app_id)
            if cached is not None:
                return str(cached)
        return None

    async def _build_server_payload(
        self, server: Server
    ) -> tuple[discord.Embed | None, discord.File | None, str | None]:
        try:
            status = await amp_client.get_status(server.amp_instance_id)
        except Exception:
            status = _OFFLINE_STATUS_FACTORY()

        players = extract_players(status)
        whitelist_count, has_donator = await self._whitelist_badge(server.id)

        # Jeder Banner ist eine Karte (Embed): Verbinden-Adresse kopierbar oben, darunter
        # Status bzw. das Bild - so gehoert die Adresse sichtbar zum richtigen Server, auch
        # wenn mehrere Banner untereinander oder in einer Gruppe stehen. Kein Nachrichtentext.
        address = await connect_address(server)
        content = None

        if server.banner_type == BannerType.EMBED:
            embed = build_embed(
                server.display_name,
                address,
                status,
                players,
                whitelist_count=whitelist_count,
                has_donator=has_donator,
            )
            return embed, None, content

        background_path = await self._resolve_background(server)
        buffer = render_banner(
            server.display_name,
            address,
            status,
            players,
            theme=server.banner_theme,
            background_path=background_path,
            color_start=server.banner_color_start,
            color_end=server.banner_color_end,
            text_color=server.banner_text_color,
            blur=server.banner_blur,
            whitelist_count=whitelist_count,
            has_donator=has_donator,
        )
        # eindeutiger Dateiname: in einer Gruppe stehen mehrere Bilder in einer Nachricht
        filename = f"banner_{server.id}.png"
        card = image_card(address, filename, _status_color(status.State.name))
        return card, discord.File(buffer, filename=filename), content

    async def _post_or_refresh_server(self, server_id: int) -> None:
        async with get_db_session() as db:
            server = await db.get(Server, server_id)
        if server is None or not server.banner_enabled or server.banner_group_id is not None:
            return

        channel = self.bot.get_channel(server.banner_channel)
        if channel is None:
            return

        embed, file, content = await self._build_server_payload(server)
        key, digest = ("server", server_id), _digest(content, [embed], [file])
        if server.banner_message_id and self._unchanged(key, digest):
            return

        message = None
        if server.banner_message_id:
            try:
                message = await channel.fetch_message(server.banner_message_id)
            except discord.NotFound:
                message = None  # wirklich geloescht -> neu posten
            except discord.HTTPException as error:
                # Discord hakt gerade (Ausfall, Rate-Limit ...) - NICHT neu posten, sonst bleibt die
                # alte Nachricht stehen und es gibt zwei Banner; naechster Durchlauf versucht es wieder
                log.warning("Banner-Nachricht gerade nicht abrufbar (%s) - naechster Versuch", error)
                return

        if message is not None:
            await message.edit(content=content, embed=embed, attachments=[file] if file is not None else [])
            self._digests[key] = (digest, time.monotonic())
            return

        message = await channel.send(content=content, embed=embed, file=file)
        self._digests[key] = (digest, time.monotonic())
        async with get_db_session() as db:
            db_server = await db.get(Server, server_id)
            db_server.banner_message_id = message.id
            await db.commit()

    async def _build_group_payload(
        self, group: BannerGroup
    ) -> tuple[list[discord.Embed], list[discord.File], str | None]:
        async with get_db_session() as db:
            result = await db.execute(select(Server).where(Server.banner_group_id == group.id))
            members = result.scalars().all()

        if not members:
            return [], [], None

        if group.layout == BannerGroupLayout.SEPARATE:
            return await self._build_group_payload_separate(group, members)
        return await self._build_group_payload_combined(group, members)

    async def _build_group_payload_combined(
        self, group: BannerGroup, members: list[Server]
    ) -> tuple[list[discord.Embed], list[discord.File], str | None]:
        """Ein gestapeltes Bild/Embed mit gemeinsamem Hintergrund/Theme fuer die ganze Gruppe."""
        entries = []
        for member in members:
            try:
                status = await amp_client.get_status(member.amp_instance_id)
            except Exception:
                status = _OFFLINE_STATUS_FACTORY()
            players = extract_players(status)
            whitelist_count, has_donator = await self._whitelist_badge(member.id)
            entries.append((member.display_name, await connect_address(member), status, players, whitelist_count, has_donator))

        # Adressen stehen einheitlich als eigener Text ueber der Nachricht, nicht
        # nochmal im Embed/Bild dupliziert.
        content = "\n".join(f"{name}: `{host}`" for name, host, *_ in entries if host) or None

        if group.banner_type == BannerType.EMBED:
            return [build_group_embed(group.name, entries)], [], content

        buffer = render_banner_group(
            entries,
            background_path=group.banner_background_path,
            color_start=group.banner_color_start,
            color_end=group.banner_color_end,
            text_color=group.banner_text_color,
            theme=group.banner_theme,
            blur=group.banner_blur,
        )
        return [], [discord.File(buffer, filename="banner_group.png")], content

    async def _build_group_payload_separate(
        self, group: BannerGroup, members: list[Server]
    ) -> tuple[list[discord.Embed], list[discord.File], str | None]:
        """Ein eigenes Bild/Embed pro Mitglied, jeweils mit dessen eigenem Artwork/Theme
        (wie ein einzelner Server-Banner) - alle zusammen in einer Nachricht."""
        embeds: list[discord.Embed] = []
        files: list[discord.File] = []
        content_lines: list[str] = []

        # Discord erlaubt 10 Karten pro Nachricht
        for member in members[:10]:
            embed, file, member_content = await self._build_server_payload(member)
            if embed is not None:
                embeds.append(embed)
            if file is not None:
                files.append(file)
            if member_content:
                content_lines.append(member_content)

        content = "\n".join(content_lines) if content_lines else None
        return embeds, files, content

    async def _post_or_refresh_group(self, group_id: int) -> None:
        async with get_db_session() as db:
            group = await db.get(BannerGroup, group_id)
        if group is None:
            return

        channel = self.bot.get_channel(group.channel)
        if channel is None:
            return

        embeds, files, content = await self._build_group_payload(group)
        if not embeds and not files:
            return
        key, digest = ("group", group_id), _digest(content, embeds, files)
        if group.message_id and self._unchanged(key, digest):
            return

        message = None
        if group.message_id:
            try:
                message = await channel.fetch_message(group.message_id)
            except discord.NotFound:
                message = None  # wirklich geloescht -> neu posten
            except discord.HTTPException as error:
                # Discord hakt gerade (Ausfall, Rate-Limit ...) - NICHT neu posten, sonst bleibt die
                # alte Nachricht stehen und es gibt zwei Banner; naechster Durchlauf versucht es wieder
                log.warning("Banner-Nachricht gerade nicht abrufbar (%s) - naechster Versuch", error)
                return

        if message is not None:
            await message.edit(content=content, embeds=embeds, attachments=files)
            self._digests[key] = (digest, time.monotonic())
            return

        message = await channel.send(content=content, embeds=embeds, files=files)
        self._digests[key] = (digest, time.monotonic())
        async with get_db_session() as db:
            db_group = await db.get(BannerGroup, group_id)
            db_group.message_id = message.id
            await db.commit()

    def _unchanged(self, key: tuple[str, int], digest: str) -> bool:
        """Gleicher Banner wie zuletzt gesendet - und hoechstens 10 Minuten her (dann wird die
        Nachricht trotzdem abgerufen, um eine in Discord geloeschte neu zu posten)."""
        last = self._digests.get(key)
        return last is not None and last[0] == digest and time.monotonic() - last[1] < RECHECK_SECONDS

    @tasks.loop(seconds=60)
    async def banner_loop(self) -> None:
        async with get_db_session() as db:
            server_result = await db.execute(
                select(Server.id).where(Server.banner_enabled.is_(True), Server.banner_group_id.is_(None))
            )
            server_ids = [row[0] for row in server_result.all()]
            group_result = await db.execute(select(BannerGroup.id))
            group_ids = [row[0] for row in group_result.all()]

        for server_id in server_ids:
            key = ("server", server_id)
            if self._should_skip(key):
                continue
            try:
                await self._post_or_refresh_server(server_id)
            except Exception:
                # ein einzelner Server-Fehler darf die Loop nicht abbrechen - aber
                # wiederholte Fehlschlaege (z.B. haengendes Rate-Limit) fuehren zu
                # steigenden Pausen statt stur jede Minute erneut anzurennen.
                self._record_failure(key)
            else:
                self._record_success(key)

        for group_id in group_ids:
            key = ("group", group_id)
            if self._should_skip(key):
                continue
            try:
                await self._post_or_refresh_group(group_id)
            except Exception:
                self._record_failure(key)
            else:
                self._record_success(key)

    @banner_loop.before_loop
    async def before_banner_loop(self) -> None:
        await self.bot.wait_until_ready()

    # --- /banner (pro Server) -----------------------------------------------------

    @banner_group.command(name="enable", description="Aktiviert den Banner fuer einen Server")
    @app_commands.describe(name="Interner Servername (instance_name)", channel="Zielkanal", type="Darstellung")
    @app_commands.choices(type=TYPE_CHOICES)
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def banner_enable(
        self, interaction: discord.Interaction, name: str, channel: discord.TextChannel, type: Choice[str]
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return
        if server.banner_group_id is not None:
            await _followup_temp(
                interaction,
                f"`{server.display_name}` gehoert zu einer Banner-Gruppe - erst mit "
                "`/bannergroup remove` entfernen.",
            )
            return

        async with get_db_session() as db:
            db_server = await db.get(Server, server.id)
            db_server.banner_enabled = True
            db_server.banner_channel = channel.id
            db_server.banner_type = BannerType(type.value)
            await db.commit()

        await self._post_or_refresh_server(server.id)
        await _followup_temp(interaction, f"Banner fuer `{server.display_name}` aktiviert in {channel.mention}.")

    @banner_group.command(name="disable", description="Deaktiviert den Banner eines Servers")
    @app_commands.describe(name="Interner Servername (instance_name)")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def banner_disable(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        async with get_db_session() as db:
            db_server = await db.get(Server, server.id)
            db_server.banner_enabled = False
            message_id, channel_id = db_server.banner_message_id, db_server.banner_channel
            db_server.banner_message_id = None
            await db.commit()

        await _delete_message(self.bot, channel_id, message_id)
        await _followup_temp(interaction, f"Banner fuer `{server.display_name}` deaktiviert.")

    @banner_group.command(name="type", description="Wechselt zwischen Embed- und Bild-Darstellung")
    @app_commands.describe(name="Interner Servername (instance_name)", type="Darstellung")
    @app_commands.choices(type=TYPE_CHOICES)
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def banner_type_cmd(self, interaction: discord.Interaction, name: str, type: Choice[str]) -> None:
        await interaction.response.defer(ephemeral=True)
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        async with get_db_session() as db:
            db_server = await db.get(Server, server.id)
            old_channel_id, old_message_id = db_server.banner_channel, db_server.banner_message_id
            db_server.banner_type = BannerType(type.value)
            db_server.banner_message_id = None
            await db.commit()

        await _delete_message(self.bot, old_channel_id, old_message_id)
        if server.banner_enabled:
            await self._post_or_refresh_server(server.id)
        await _followup_temp(interaction, f"Darstellung fuer `{server.display_name}` auf `{type.name}` gesetzt.")

    @banner_group.command(name="theme", description="Setzt ein eingebautes Verlaufs-Theme")
    @app_commands.describe(name="Interner Servername (instance_name)", theme="Theme")
    @app_commands.choices(theme=THEME_CHOICES)
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def banner_theme(self, interaction: discord.Interaction, name: str, theme: Choice[str]) -> None:
        await interaction.response.defer(ephemeral=True)
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        async with get_db_session() as db:
            db_server = await db.get(Server, server.id)
            db_server.banner_theme = theme.value
            db_server.banner_background_path = None
            db_server.banner_color_start = None
            db_server.banner_color_end = None
            db_server.banner_steam_art = False  # sonst gewinnt das Steam-Artwork
            await db.commit()

        await _followup_temp(interaction, f"Theme `{theme.name}` fuer `{server.display_name}` gesetzt.")

    @banner_group.command(name="background", description="Laedt ein eigenes Hintergrundbild hoch")
    @app_commands.describe(
        name="Interner Servername (instance_name)",
        image="Hintergrundbild (PNG/JPEG/WebP, max. 8 MB)",
    )
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def banner_background(
        self, interaction: discord.Interaction, name: str, image: discord.Attachment
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        error = _validate_upload(image)
        if error is not None:
            await _followup_temp(interaction, error)
            return

        path = BACKGROUND_DIR / f"server_{server.id}.png"
        await _save_background(await image.read(), path)

        async with get_db_session() as db:
            db_server = await db.get(Server, server.id)
            db_server.banner_background_path = str(path)
            db_server.banner_theme = None
            db_server.banner_color_start = None
            db_server.banner_color_end = None
            await db.commit()

        await _followup_temp(interaction, f"Eigenes Hintergrundbild fuer `{server.display_name}` gespeichert.")

    @banner_group.command(name="customize", description="Interaktiver Editor fuer Verlaufsfarben und Unschaerfe")
    @app_commands.describe(name="Interner Servername (instance_name)")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def banner_customize(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        server = await _get_server(interaction.guild_id, name)
        if server is None:
            await _followup_temp(interaction, f"Server `{name}` nicht gefunden.")
            return

        # Aufgeloester Hintergrund (eigenes Bild ODER Steam-Artwork), nicht nur das rohe
        # DB-Feld - sonst zeigt die Vorschau bei Steam-Art faelschlich nur den Verlauf.
        background_path = await self._resolve_background(server)
        has_background_image = background_path is not None

        view = BannerCustomizeView(
            guild_id=interaction.guild_id,
            target_kind="server",
            target_id=server.id,
            color_start=server.banner_color_start,
            color_end=server.banner_color_end,
            text_color=server.banner_text_color,
            blur=server.banner_blur,
            background_path=background_path,
            has_background_image=has_background_image,
            preview_name=server.display_name,
            preview_host=await connect_address(server),
        )
        buffer = view._render_preview()
        file = discord.File(buffer, filename="preview.png")
        hint = (
            "Ein Hintergrundbild ist aktiv (Farben wirken hier nicht) - waehle stattdessen "
            "eine **Schriftfarbe** und Unschaerfe."
            if has_background_image
            else "Waehle Start-/Endfarbe und Unschaerfe."
        )
        await interaction.followup.send(
            f"{hint} Dann **Vorschau** oder direkt **Uebernehmen**.",
            file=file,
            view=view,
            ephemeral=True,
        )

    @banner_group.command(name="refresh", description="Aktualisiert den Banner sofort")
    @app_commands.describe(name="Interner Servername (instance_name)")
    @app_commands.autocomplete(name=_autocomplete_instance_name)
    @require_capability("banner.refresh")
    async def banner_refresh(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        server = await _get_server(interaction.guild_id, name)
        if server is None or not server.banner_enabled:
            await _followup_temp(interaction, f"Kein aktiver Banner fuer `{name}`.")
            return

        await self._post_or_refresh_server(server.id)
        await _followup_temp(interaction, f"Banner fuer `{server.display_name}` aktualisiert.")

    # --- /bannergroup (mehrere Server in einem Kanal) ------------------------------

    @bannergroup_group.command(name="create", description="Erstellt eine neue Banner-Gruppe")
    @app_commands.describe(
        name="Name der Gruppe", channel="Zielkanal", type="Darstellung", layout="Layout (Standard: Kombiniert)"
    )
    @app_commands.choices(type=TYPE_CHOICES, layout=LAYOUT_CHOICES)
    @require_role(Level.OWNER)
    async def bannergroup_create(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel,
        type: Choice[str],
        layout: Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await ensure_guild(interaction.guild_id, interaction.guild.name)

        if await _get_group(interaction.guild_id, name) is not None:
            await _followup_temp(interaction, f"Gruppe `{name}` existiert bereits.")
            return

        async with get_db_session() as db:
            db.add(
                BannerGroup(
                    guild_id=interaction.guild_id,
                    name=name,
                    channel=channel.id,
                    banner_type=BannerType(type.value),
                    layout=BannerGroupLayout(layout.value) if layout is not None else BannerGroupLayout.COMBINED,
                )
            )
            await db.commit()

        await _followup_temp(
            interaction,
            f"Banner-Gruppe `{name}` erstellt in {channel.mention}. Fuege Server mit `/bannergroup add` hinzu.",
        )

    @bannergroup_group.command(name="layout", description="Wechselt zwischen kombiniertem und einzelnem Layout")
    @app_commands.describe(group="Gruppenname", layout="Layout")
    @app_commands.choices(layout=LAYOUT_CHOICES)
    @app_commands.autocomplete(group=_autocomplete_group_name)
    @require_role(Level.OWNER)
    async def bannergroup_layout(self, interaction: discord.Interaction, group: str, layout: Choice[str]) -> None:
        await interaction.response.defer(ephemeral=True)
        group_row = await _get_group(interaction.guild_id, group)
        if group_row is None:
            await _followup_temp(interaction, f"Gruppe `{group}` nicht gefunden.")
            return

        async with get_db_session() as db:
            db_group = await db.get(BannerGroup, group_row.id)
            old_channel_id, old_message_id = db_group.channel, db_group.message_id
            db_group.layout = BannerGroupLayout(layout.value)
            db_group.message_id = None
            await db.commit()

        await _delete_message(self.bot, old_channel_id, old_message_id)
        await self._post_or_refresh_group(group_row.id)
        await _followup_temp(interaction, f"Layout fuer Gruppe `{group}` auf `{layout.name}` gesetzt.")

    @bannergroup_group.command(name="add", description="Fuegt einen Server einer Banner-Gruppe hinzu")
    @app_commands.describe(group="Gruppenname", server="Interner Servername (instance_name)")
    @app_commands.autocomplete(group=_autocomplete_group_name, server=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def bannergroup_add(self, interaction: discord.Interaction, group: str, server: str) -> None:
        await interaction.response.defer(ephemeral=True)
        group_row = await _get_group(interaction.guild_id, group)
        if group_row is None:
            await _followup_temp(interaction, f"Gruppe `{group}` nicht gefunden.")
            return
        server_row = await _get_server(interaction.guild_id, server)
        if server_row is None:
            await _followup_temp(interaction, f"Server `{server}` nicht gefunden.")
            return

        async with get_db_session() as db:
            count_result = await db.execute(
                select(func.count(Server.id)).where(Server.banner_group_id == group_row.id)
            )
            member_count = count_result.scalar_one()
        if member_count >= MAX_GROUP_MEMBERS:
            await _followup_temp(
                interaction, f"Gruppe `{group}` hat bereits die maximale Anzahl von {MAX_GROUP_MEMBERS} Servern."
            )
            return

        was_enabled = server_row.banner_enabled
        async with get_db_session() as db:
            db_server = await db.get(Server, server_row.id)
            db_server.banner_group_id = group_row.id
            db_server.banner_enabled = False
            await db.commit()

        note = " (individueller Banner wurde deaktiviert)" if was_enabled else ""
        await _followup_temp(interaction, f"`{server_row.display_name}` zur Gruppe `{group}` hinzugefuegt{note}.")

    @bannergroup_group.command(name="remove", description="Entfernt einen Server aus einer Banner-Gruppe")
    @app_commands.describe(group="Gruppenname", server="Interner Servername (instance_name)")
    @app_commands.autocomplete(group=_autocomplete_group_name, server=_autocomplete_instance_name)
    @require_role(Level.OWNER)
    async def bannergroup_remove(self, interaction: discord.Interaction, group: str, server: str) -> None:
        await interaction.response.defer(ephemeral=True)
        server_row = await _get_server(interaction.guild_id, server)
        if server_row is None:
            await _followup_temp(interaction, f"Server `{server}` nicht gefunden.")
            return

        async with get_db_session() as db:
            db_server = await db.get(Server, server_row.id)
            db_server.banner_group_id = None
            await db.commit()

        await _followup_temp(interaction, f"`{server_row.display_name}` aus der Gruppe `{group}` entfernt.")

    @bannergroup_group.command(name="theme", description="Setzt ein eingebautes Verlaufs-Theme fuer eine Gruppe")
    @app_commands.describe(group="Gruppenname", theme="Theme")
    @app_commands.choices(theme=THEME_CHOICES)
    @app_commands.autocomplete(group=_autocomplete_group_name)
    @require_role(Level.OWNER)
    async def bannergroup_theme(self, interaction: discord.Interaction, group: str, theme: Choice[str]) -> None:
        await interaction.response.defer(ephemeral=True)
        group_row = await _get_group(interaction.guild_id, group)
        if group_row is None:
            await _followup_temp(interaction, f"Gruppe `{group}` nicht gefunden.")
            return

        async with get_db_session() as db:
            db_group = await db.get(BannerGroup, group_row.id)
            db_group.banner_theme = theme.value
            db_group.banner_background_path = None
            db_group.banner_color_start = None
            db_group.banner_color_end = None
            await db.commit()

        await _followup_temp(
            interaction, f"Theme `{theme.name}` fuer Gruppe `{group}` gesetzt.{_separate_layout_hint(group_row)}"
        )

    @bannergroup_group.command(name="background", description="Laedt ein eigenes Hintergrundbild fuer eine Gruppe hoch")
    @app_commands.describe(group="Gruppenname", image="Hintergrundbild (PNG/JPEG/WebP, max. 8 MB)")
    @app_commands.autocomplete(group=_autocomplete_group_name)
    @require_role(Level.OWNER)
    async def bannergroup_background(
        self, interaction: discord.Interaction, group: str, image: discord.Attachment
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        group_row = await _get_group(interaction.guild_id, group)
        if group_row is None:
            await _followup_temp(interaction, f"Gruppe `{group}` nicht gefunden.")
            return

        error = _validate_upload(image)
        if error is not None:
            await _followup_temp(interaction, error)
            return

        path = BACKGROUND_DIR / f"group_{group_row.id}.png"
        await _save_background(await image.read(), path)

        async with get_db_session() as db:
            db_group = await db.get(BannerGroup, group_row.id)
            db_group.banner_background_path = str(path)
            db_group.banner_theme = None
            db_group.banner_color_start = None
            db_group.banner_color_end = None
            await db.commit()

        await _followup_temp(
            interaction,
            f"Eigenes Hintergrundbild fuer Gruppe `{group}` gespeichert.{_separate_layout_hint(group_row)}",
        )

    @bannergroup_group.command(name="customize", description="Interaktiver Editor fuer eine Banner-Gruppe")
    @app_commands.describe(group="Gruppenname")
    @app_commands.autocomplete(group=_autocomplete_group_name)
    @require_role(Level.OWNER)
    async def bannergroup_customize(self, interaction: discord.Interaction, group: str) -> None:
        await interaction.response.defer(ephemeral=True)
        group_row = await _get_group(interaction.guild_id, group)
        if group_row is None:
            await _followup_temp(interaction, f"Gruppe `{group}` nicht gefunden.")
            return

        has_background_image = group_row.banner_background_path is not None

        view = BannerCustomizeView(
            guild_id=interaction.guild_id,
            target_kind="group",
            target_id=group_row.id,
            color_start=group_row.banner_color_start,
            color_end=group_row.banner_color_end,
            text_color=group_row.banner_text_color,
            blur=group_row.banner_blur,
            background_path=group_row.banner_background_path,
            has_background_image=has_background_image,
            preview_name=group_row.name,
            preview_host="example.com",
        )
        buffer = view._render_preview()
        file = discord.File(buffer, filename="preview.png")
        hint = (
            "Ein Hintergrundbild ist aktiv (Farben wirken hier nicht) - waehle stattdessen "
            "eine **Schriftfarbe** und Unschaerfe."
            if has_background_image
            else "Waehle Start-/Endfarbe und Unschaerfe."
        )
        await interaction.followup.send(
            f"{hint} Dann **Vorschau** oder direkt **Uebernehmen**.{_separate_layout_hint(group_row)}",
            file=file,
            view=view,
            ephemeral=True,
        )

    @bannergroup_group.command(name="refresh", description="Aktualisiert eine Banner-Gruppe sofort")
    @app_commands.describe(group="Gruppenname")
    @app_commands.autocomplete(group=_autocomplete_group_name)
    @require_capability("banner.refresh")
    async def bannergroup_refresh(self, interaction: discord.Interaction, group: str) -> None:
        await interaction.response.defer(ephemeral=True)
        group_row = await _get_group(interaction.guild_id, group)
        if group_row is None:
            await _followup_temp(interaction, f"Gruppe `{group}` nicht gefunden.")
            return

        await self._post_or_refresh_group(group_row.id)
        await _followup_temp(interaction, f"Banner-Gruppe `{group}` aktualisiert.")

    @bannergroup_group.command(name="disable", description="Loest eine Banner-Gruppe wieder auf")
    @app_commands.describe(group="Gruppenname")
    @app_commands.autocomplete(group=_autocomplete_group_name)
    @require_role(Level.OWNER)
    async def bannergroup_disable(self, interaction: discord.Interaction, group: str) -> None:
        await interaction.response.defer(ephemeral=True)
        group_row = await _get_group(interaction.guild_id, group)
        if group_row is None:
            await _followup_temp(interaction, f"Gruppe `{group}` nicht gefunden.")
            return

        async with get_db_session() as db:
            members_result = await db.execute(select(Server).where(Server.banner_group_id == group_row.id))
            for member in members_result.scalars().all():
                member.banner_group_id = None
            db_group = await db.get(BannerGroup, group_row.id)
            message_id, channel_id = db_group.message_id, db_group.channel
            await db.delete(db_group)
            await db.commit()

        await _delete_message(self.bot, channel_id, message_id)
        await _followup_temp(interaction, f"Banner-Gruppe `{group}` aufgeloest, Mitglieder freigegeben.")


def _separate_layout_hint(group: BannerGroup) -> str:
    if group.layout != BannerGroupLayout.SEPARATE:
        return ""
    return (
        "\n-# Hinweis: Layout ist `Einzeln` - jedes Mitglied behaelt sein eigenes "
        "Theme/Hintergrund/Farben, diese Gruppen-Einstellung wird dort nicht angezeigt."
    )


def _validate_upload(image: discord.Attachment) -> str | None:
    if image.content_type not in ALLOWED_CONTENT_TYPES:
        return "Nur PNG/JPEG/WebP-Bilder werden unterstuetzt."
    if image.size > MAX_UPLOAD_BYTES:
        return "Bild ist zu gross (max. 8 MB)."
    return None


async def _delete_message(bot: commands.Bot, channel_id: int | None, message_id: int | None) -> None:
    if not channel_id or not message_id:
        return
    channel = bot.get_channel(channel_id)
    if channel is None:
        return
    try:
        message = await channel.fetch_message(message_id)
        await message.delete()
    except discord.HTTPException:
        pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BannerCog(bot))
